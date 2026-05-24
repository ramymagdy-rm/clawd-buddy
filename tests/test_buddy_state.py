# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for BuddyState — the state machine driving the buddy's
animations.

These tests use a fake clock so they don't depend on real time elapsing.
Animation / rendering is intentionally out of scope; we test the queue,
mode transitions, session-greeting logic, and safety caps.

See .ai/decisions/2026-05-24-milestone-1-session-arc.md for the design
behind the behaviors covered here.
"""

import pytest

from clawd_buddy import state as buddy_state


# ── Test helpers ─────────────────────────────────────────────────────
class FakeClock:
    """Tiny monotonically-advanceable clock. Pass into BuddyState(clock=…)
    so update()'s elapsed-time arithmetic is fully deterministic."""

    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state(clock):
    # sound_pack="off" so transitions don't leave _pending_sound set —
    # easier to assert on pristine state.
    return buddy_state.BuddyState(theme_name="dark", sound_pack="off", clock=clock)


# ── Initial state ────────────────────────────────────────────────────
class TestInitialState:
    def test_starts_idle(self, state):
        assert state.mode == "idle"
        assert state.queue_depth == 0
        assert state.last_session_id is None

    def test_mode_properties_match_mode(self, state):
        # All convenience booleans should be False at rest.
        assert not state.celebrating
        assert not state.waving
        assert not state.greeting
        assert not state.thinking


# ── Basic mode transitions ───────────────────────────────────────────
class TestBasicTransitions:
    def test_trigger_enters_celebrating(self, state):
        state.trigger()
        assert state.mode == "celebrating"
        assert state.celebrating

    def test_wave_enters_waving(self, state):
        state.wave()
        assert state.mode == "waving"
        assert state.waving

    def test_greet_enters_greeting(self, state):
        state.greet()
        assert state.mode == "greeting"
        assert state.greeting

    def test_start_thinking_enters_thinking(self, state):
        state.start_thinking()
        assert state.mode == "thinking"
        assert state.thinking

    def test_end_thinking_returns_to_idle(self, state):
        state.start_thinking()
        state.end_thinking()
        assert state.mode == "idle"

    def test_end_thinking_when_not_thinking_is_noop(self, state):
        # End-thinking should not pull the buddy out of a celebrate.
        state.trigger()
        assert state.mode == "celebrating"
        state.end_thinking()
        assert state.mode == "celebrating"


# ── Preemption rules ─────────────────────────────────────────────────
class TestPreemption:
    def test_celebrate_preempts_thinking(self, state):
        state.start_thinking()
        state.trigger()
        assert state.mode == "celebrating"
        assert state.queue_depth == 0

    def test_wave_preempts_thinking(self, state):
        state.start_thinking()
        state.wave()
        assert state.mode == "waving"
        assert state.queue_depth == 0

    def test_greet_preempts_thinking(self, state):
        state.start_thinking()
        state.greet()
        assert state.mode == "greeting"
        assert state.queue_depth == 0


# ── Queueing behavior ────────────────────────────────────────────────
class TestQueue:
    def test_wave_during_celebrate_is_queued_not_dropped(self, state, clock):
        """Previously wave() was a no-op during celebrate — the whole
        point of the queued-reactions feature is that this no longer
        silently drops the wave."""
        state.trigger()
        state.wave()
        assert state.mode == "celebrating"
        assert state.queue_depth == 1
        clock.advance(state.cel_dur + 0.1)
        state.update()
        assert state.mode == "waving"
        assert state.queue_depth == 0

    def test_celebrate_during_wave_is_queued(self, state, clock):
        state.wave()
        state.trigger()
        assert state.mode == "waving"
        assert state.queue_depth == 1
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "celebrating"

    def test_queue_cap(self, state):
        state.trigger()
        for _ in range(10):
            state.wave()  # all but the first three should be dropped
        assert state.queue_depth == buddy_state.QUEUE_MAX

    def test_start_thinking_dedupes_against_tail(self, state):
        state.trigger()
        state.start_thinking()
        state.start_thinking()
        state.start_thinking()
        # Three calls; the queue should only hold one start_thinking.
        assert state.queue_depth == 1

    def test_thinking_resumes_after_queued_celebrate(self, state, clock):
        """start_thinking while a celebrate animates → queue → run after."""
        state.trigger()
        state.start_thinking()
        assert state.queue_depth == 1
        clock.advance(state.cel_dur + 0.1)
        state.update()
        assert state.mode == "thinking"

    def test_queue_unwinds_in_fifo_order(self, state, clock):
        state.trigger()
        state.wave()
        state.greet()
        assert state.queue_depth == 2

        clock.advance(state.cel_dur + 0.1)
        state.update()
        assert state.mode == "waving"

        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "greeting"

        clock.advance(state.greet_dur + 0.1)
        state.update()
        assert state.mode == "idle"


# ── Reactive mode expiration ─────────────────────────────────────────
class TestExpiration:
    def test_celebrate_falls_back_to_idle(self, state, clock):
        state.trigger()
        clock.advance(state.cel_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_wave_falls_back_to_idle(self, state, clock):
        state.wave()
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_greeting_falls_back_to_idle(self, state, clock):
        state.greet()
        clock.advance(state.greet_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_thinking_safety_cap(self, state, clock):
        """If Stop never arrives, thinking should eventually self-recover."""
        state.start_thinking()
        clock.advance(buddy_state.MAX_THINKING_SECONDS + 1)
        state.update()
        assert state.mode == "idle"

    def test_thinking_does_not_expire_before_cap(self, state, clock):
        state.start_thinking()
        clock.advance(buddy_state.MAX_THINKING_SECONDS - 1)
        state.update()
        assert state.mode == "thinking"


# ── Session-greeting logic ───────────────────────────────────────────
class TestPromptStart:
    def test_first_prompt_with_session_id_greets_and_thinks(self, state):
        state.prompt_start(session_id="abc")
        assert state.mode == "greeting"
        # start_thinking is queued for after the greet finishes.
        assert state.queue_depth == 1
        assert state.last_session_id == "abc"

    def test_repeat_session_id_skips_greet(self, state, clock):
        state.prompt_start(session_id="abc")
        # Let the greet animation finish + advance to idle.
        clock.advance(state.greet_dur + 0.1)
        state.update()  # transitions to thinking from queue
        clock.advance(0.1)
        state.end_thinking()
        # Second prompt of the same session — should only think, not greet.
        state.prompt_start(session_id="abc")
        assert state.mode == "thinking"
        assert state.queue_depth == 0

    def test_new_session_id_greets_again(self, state, clock):
        state.prompt_start(session_id="abc")
        clock.advance(state.greet_dur + 0.1)
        state.update()
        state.end_thinking()
        # A different id should trigger the greet again.
        state.prompt_start(session_id="xyz")
        assert state.mode == "greeting"
        assert state.last_session_id == "xyz"

    def test_no_session_id_first_call_greets(self, state):
        # Time-based fallback: never seen a prompt ⇒ greet.
        state.prompt_start()
        assert state.mode == "greeting"

    def test_no_session_id_recent_activity_skips_greet(self, state, clock):
        state.prompt_start()
        clock.advance(state.greet_dur + 0.1)
        state.update()
        state.end_thinking()
        # A second prompt soon after — should NOT greet again.
        clock.advance(5.0)
        state.prompt_start()
        assert state.mode == "thinking"

    def test_no_session_id_stale_activity_greets(self, state, clock):
        state.prompt_start()
        clock.advance(state.greet_dur + 0.1)
        state.update()
        state.end_thinking()
        # Long gap — looks like a brand-new session.
        clock.advance(buddy_state.NEW_SESSION_IDLE_SECONDS + 1.0)
        state.prompt_start()
        assert state.mode == "greeting"


# ── Sound pack interaction ───────────────────────────────────────────
class TestSoundIntegration:
    def test_celebrate_queues_sound_when_pack_enabled(self, clock):
        s = buddy_state.BuddyState(sound_pack="fanfare", clock=clock)
        s.trigger()
        assert s._pending_sound == "celebrate"

    def test_celebrate_no_sound_when_off(self, state):
        # state fixture uses sound_pack="off"
        state.trigger()
        assert state._pending_sound is None

    def test_greet_does_not_emit_sound(self, clock):
        # M1 decision: greet is silent in this milestone.
        s = buddy_state.BuddyState(sound_pack="fanfare", clock=clock)
        s.greet()
        assert s._pending_sound is None

    def test_thinking_does_not_emit_sound(self, clock):
        s = buddy_state.BuddyState(sound_pack="fanfare", clock=clock)
        s.start_thinking()
        assert s._pending_sound is None
