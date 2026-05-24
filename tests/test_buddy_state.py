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


# ── Thinking resume after attention cue (M3 fix) ─────────────────────
class TestThinkingResumeAfterAttentionCue:
    """The bug: when an attention cue (wave / yellow border) interrupted
    thinking, the buddy fell back to idle after the cue cleared — even if
    Claude was still working. Expected behaviour is that thinking resumes
    until the next Stop event. Celebrate is the Stop event, so it should
    NOT trigger a resume (Stop ends thinking semantically).
    """

    def test_wave_during_thinking_resumes_thinking_after(self, state, clock):
        state.start_thinking()
        state.wave()
        assert state.mode == "waving"
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "thinking"

    def test_greet_during_thinking_resumes_thinking_after(self, state, clock):
        state.start_thinking()
        state.greet()
        assert state.mode == "greeting"
        clock.advance(state.greet_dur + 0.1)
        state.update()
        assert state.mode == "thinking"

    def test_celebrate_during_thinking_does_not_resume(self, state, clock):
        # Celebrate is the Stop event — it ends thinking.
        state.start_thinking()
        state.trigger()
        clock.advance(state.cel_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_end_thinking_after_wave_clears_resume(self, state, clock):
        state.start_thinking()
        state.wave()
        state.end_thinking()  # explicit "stop thinking" wins over resume
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_wave_then_celebrate_clears_resume(self, state, clock):
        # Wave preempts thinking → flag set. Celebrate queues behind wave.
        # Once celebrate pops, it clears the flag — final fallback is idle.
        state.start_thinking()
        state.wave()
        state.trigger()
        assert state.queue_depth == 1
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "celebrating"
        clock.advance(state.cel_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_chained_waves_during_thinking_still_resume(self, state, clock):
        # Wave preempts thinking → wave again queues. After both clear,
        # thinking should still resume (the flag survives chained reactives).
        state.start_thinking()
        state.wave()
        state.wave()
        assert state.queue_depth == 1
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "waving"
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "thinking"

    def test_wave_from_idle_does_not_resume(self, state, clock):
        # Wave entered from idle (not thinking) should fall back to idle —
        # no spurious thinking animation.
        state.wave()
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "idle"

    def test_start_thinking_clears_resume_flag(self, state, clock):
        state.start_thinking()
        state.wave()
        # Internal state: resume flag is set. Explicit start_thinking
        # should be idempotent and clear it (we're going to thinking
        # anyway when the wave ends, but the flag should match reality).
        state.start_thinking()  # queued behind wave
        assert state.queue_depth == 1
        clock.advance(state.wave_dur + 0.1)
        state.update()
        assert state.mode == "thinking"


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


# ── Speech bubble (M2: --message) ────────────────────────────────────
class TestSpeechBubble:
    def test_initial_bubble_is_empty(self, state):
        assert state.bubble_text == ""

    def test_set_message_stores_text(self, state):
        state.set_message("hello")
        assert state.bubble_text == "hello"

    def test_set_message_strips_whitespace(self, state):
        state.set_message("  spaced  ")
        assert state.bubble_text == "spaced"

    def test_set_message_empty_clears_bubble(self, state):
        state.set_message("hello")
        state.set_message("")
        assert state.bubble_text == ""

    def test_set_message_whitespace_clears_bubble(self, state):
        state.set_message("hello")
        state.set_message("   \t  ")
        assert state.bubble_text == ""

    def test_set_message_truncates_long_text(self, state):
        from clawd_buddy.state import MAX_BUBBLE_LEN

        long = "x" * (MAX_BUBBLE_LEN + 50)
        state.set_message(long)
        # Truncated at MAX_BUBBLE_LEN with a single ellipsis.
        assert len(state.bubble_text) == MAX_BUBBLE_LEN
        assert state.bubble_text.endswith("…")

    def test_set_message_ignores_non_string(self, state):
        state.set_message(42)
        assert state.bubble_text == ""

    def test_message_expires_after_duration(self, state, clock):
        state.set_message("hi", duration=1.0)
        assert state.bubble_text == "hi"
        clock.advance(1.5)
        state.update()
        assert state.bubble_text == ""

    def test_message_does_not_expire_before_duration(self, state, clock):
        state.set_message("hi", duration=2.0)
        clock.advance(1.0)
        state.update()
        assert state.bubble_text == "hi"

    def test_new_message_replaces_old(self, state):
        state.set_message("first")
        state.set_message("second")
        assert state.bubble_text == "second"

    def test_bubble_independent_of_mode(self, state):
        # A bubble must not preempt or queue against a celebrate — the
        # whole point of the overlay design is that they coexist.
        state.trigger()
        assert state.mode == "celebrating"
        state.set_message("done")
        assert state.mode == "celebrating"
        assert state.bubble_text == "done"


# ── record_action (M2: --status feeds last_action) ───────────────────
class TestRecordAction:
    def test_initial_last_action_is_none(self, state):
        assert state.last_action is None
        assert state.last_action_ts == 0.0

    def test_record_action_stores_token_and_ts(self, state, clock):
        clock.advance(123.0)
        state.record_action("wave")
        assert state.last_action == "wave"
        assert state.last_action_ts == clock.t

    def test_record_action_ignores_empty(self, state):
        state.record_action("")
        assert state.last_action is None

    def test_record_action_ignores_non_string(self, state):
        state.record_action(None)
        state.record_action(42)
        assert state.last_action is None


# ── topmost mirror (M2: --status reports it) ─────────────────────────
class TestTopmost:
    def test_default_topmost_true(self, state):
        assert state.topmost is True


# ── Reduce-motion (M3) ───────────────────────────────────────────────
class TestReduceMotion:
    def test_default_is_off(self, state):
        assert state.reduce_motion is False

    def test_constructor_param_respected(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   reduce_motion=True)
        assert s.reduce_motion is True

    def test_setter_coerces_to_bool(self, state):
        state.set_reduce_motion(1)
        assert state.reduce_motion is True
        state.set_reduce_motion(0)
        assert state.reduce_motion is False

    def test_celebrate_with_reduce_motion_skips_confetti(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   reduce_motion=True)
        s.trigger()
        assert s.mode == "celebrating"
        # Confetti is the most motion-heavy element — should be empty.
        assert s.confetti == []

    def test_celebrate_without_reduce_motion_spawns_confetti(self, state):
        state.trigger()
        # 40 particles per the spec.
        assert len(state.confetti) == 40

    def test_reduce_motion_does_not_block_sound(self, clock):
        # Roadmap: "border + sound only". Sound must still fire when
        # the pack is enabled.
        s = buddy_state.BuddyState(sound_pack="fanfare", clock=clock,
                                   reduce_motion=True)
        s.trigger()
        assert s._pending_sound == "celebrate"


# ── Volume (M3) ──────────────────────────────────────────────────────
class TestVolume:
    def test_default_is_full(self, state):
        assert state.volume == 1.0

    def test_constructor_clamps_out_of_range(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   volume=1.7)
        assert s.volume == 1.0
        s2 = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                    volume=-0.5)
        assert s2.volume == 0.0

    def test_constructor_falls_back_on_garbage(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   volume="loud")
        assert s.volume == 1.0  # safe fallback

    def test_setter_clamps_and_flags_dirty(self, state):
        assert state._volume_changed is False
        state.set_volume(0.5)
        assert state.volume == 0.5
        assert state._volume_changed is True

    def test_setter_no_op_when_unchanged(self, state):
        state.set_volume(0.5)
        state._volume_changed = False  # main loop would have cleared
        state.set_volume(0.5)
        # No-op write must not re-flag the main loop.
        assert state._volume_changed is False

    def test_setter_previews_on_change(self, clock):
        s = buddy_state.BuddyState(sound_pack="fanfare", clock=clock)
        s.set_volume(0.5)
        # Volume picker previews via the celebrate sound — same UX
        # affordance as the sound-pack submenu.
        assert s._pending_sound == "celebrate"

    def test_setter_no_preview_at_zero(self, clock):
        # Volume 0 means muted — no point playing a preview the user
        # can't hear.
        s = buddy_state.BuddyState(sound_pack="fanfare", clock=clock)
        s.set_volume(0.0)
        assert s._pending_sound is None

    def test_setter_no_preview_when_pack_off(self, state):
        # state fixture uses sound_pack="off" → no preview regardless.
        state.set_volume(0.5)
        assert state._pending_sound is None


# ── Quiet hours (M3) ─────────────────────────────────────────────────
class TestQuietHours:
    def test_default_is_disabled(self, state):
        assert state.quiet_start is None
        assert state.quiet_end is None
        assert state.is_quiet_now() is False

    def test_constructor_sets_window(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   quiet_start=23 * 60, quiet_end=8 * 60)
        assert s.quiet_start == 23 * 60
        assert s.quiet_end == 8 * 60

    def test_constructor_rejects_partial_window(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   quiet_start=23 * 60, quiet_end=None)
        # Mixed None+int ⇒ disabled (avoids partial-config foot-guns).
        assert s.quiet_start is None
        assert s.quiet_end is None

    def test_constructor_rejects_zero_length(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   quiet_start=600, quiet_end=600)
        assert s.quiet_start is None
        assert s.quiet_end is None

    def test_constructor_rejects_out_of_range(self, clock):
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   quiet_start=2000, quiet_end=8 * 60)
        assert s.quiet_start is None
        assert s.quiet_end is None

    def test_setter_normalizes(self, state):
        state.set_quiet_hours(23 * 60, 8 * 60)
        assert state.quiet_start == 23 * 60
        assert state.quiet_end == 8 * 60
        state.set_quiet_hours(None, None)
        assert state.quiet_start is None
        assert state.quiet_end is None

    def test_is_quiet_now_inside_normal_window(self, state):
        state.set_quiet_hours(60, 600)  # 01:00 – 10:00
        # Inject `now_min` rather than monkey-patching time.localtime.
        assert state.is_quiet_now(now_min=300) is True   # 05:00
        assert state.is_quiet_now(now_min=720) is False  # 12:00

    def test_is_quiet_now_handles_midnight_wraparound(self, state):
        state.set_quiet_hours(23 * 60, 8 * 60)  # 23:00 – 08:00
        # Inside (before midnight):
        assert state.is_quiet_now(now_min=23 * 60 + 30) is True   # 23:30
        # Inside (after midnight):
        assert state.is_quiet_now(now_min=3 * 60) is True         # 03:00
        # Outside:
        assert state.is_quiet_now(now_min=10 * 60) is False       # 10:00
        # Boundary: end is exclusive.
        assert state.is_quiet_now(now_min=8 * 60) is False        # 08:00
        # Boundary: start is inclusive.
        assert state.is_quiet_now(now_min=23 * 60) is True        # 23:00

    def test_is_quiet_now_disabled_returns_false(self, state):
        # No window set ⇒ never quiet.
        assert state.is_quiet_now(now_min=0) is False
        assert state.is_quiet_now(now_min=23 * 60) is False


class TestQuietHoursHelpers:
    """The pure helpers carry the trickiest logic — wraparound,
    range validation — so they get their own unit tests independent
    of BuddyState."""

    def test_in_window_normal(self):
        assert buddy_state._in_quiet_window(60, 600, 300) is True
        assert buddy_state._in_quiet_window(60, 600, 30) is False
        assert buddy_state._in_quiet_window(60, 600, 700) is False

    def test_in_window_wraparound(self):
        # 23:00 – 08:00 (start > end)
        assert buddy_state._in_quiet_window(23 * 60, 8 * 60, 0) is True
        assert buddy_state._in_quiet_window(23 * 60, 8 * 60, 7 * 60) is True
        assert buddy_state._in_quiet_window(23 * 60, 8 * 60, 8 * 60) is False
        assert buddy_state._in_quiet_window(
            23 * 60, 8 * 60, 23 * 60 + 30) is True
        assert buddy_state._in_quiet_window(
            23 * 60, 8 * 60, 22 * 60 + 59) is False

    def test_in_window_none_endpoints_disabled(self):
        assert buddy_state._in_quiet_window(None, 600, 300) is False
        assert buddy_state._in_quiet_window(60, None, 300) is False

    def test_clamp_volume_in_range(self):
        assert buddy_state._clamp_volume(0.5) == 0.5

    def test_clamp_volume_clamps_high(self):
        assert buddy_state._clamp_volume(1.5) == 1.0

    def test_clamp_volume_clamps_low(self):
        assert buddy_state._clamp_volume(-0.3) == 0.0

    def test_clamp_volume_garbage_defaults_to_one(self):
        assert buddy_state._clamp_volume("x") == 1.0
        assert buddy_state._clamp_volume(None) == 1.0

    def test_clamp_volume_rejects_nan(self):
        # NaN slipping through into pygame mixer would silently break
        # playback — coerce to the safe default instead.
        assert buddy_state._clamp_volume(float("nan")) == 1.0

    def test_normalize_quiet_passthrough(self):
        assert buddy_state._normalize_quiet(60, 600) == (60, 600)

    def test_normalize_quiet_mixed_none_disabled(self):
        assert buddy_state._normalize_quiet(60, None) == (None, None)
        assert buddy_state._normalize_quiet(None, 600) == (None, None)

    def test_normalize_quiet_rejects_non_int(self):
        assert buddy_state._normalize_quiet("23:00", 600) == (None, None)
        assert buddy_state._normalize_quiet(60, 1.5) == (None, None)

    def test_normalize_quiet_rejects_out_of_range(self):
        assert buddy_state._normalize_quiet(-1, 600) == (None, None)
        assert buddy_state._normalize_quiet(60, 1440) == (None, None)

    def test_normalize_quiet_rejects_zero_length(self):
        assert buddy_state._normalize_quiet(600, 600) == (None, None)


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
