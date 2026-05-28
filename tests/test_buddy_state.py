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


class FakeNowMin:
    """Mutable minute-of-day source for reminder-schedule tests.

    The M4.3 reminder schedule is wall-clock anchored — tests need to
    set the current minute-of-day independently of the unix-epoch
    `FakeClock`. Pass an instance as `now_min_fn=` to BuddyState and
    advance it with `.set(...)`."""

    def __init__(self, minute=0):
        self.minute = minute

    def __call__(self):
        return self.minute

    def set(self, minute):
        self.minute = minute


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def now_min():
    return FakeNowMin(minute=8 * 60)  # 08:00 default — matches anchor default


@pytest.fixture
def state(clock, now_min):
    # sound_pack="off" so transitions don't leave _pending_sound set —
    # easier to assert on pristine state. `now_min_fn` makes the M4.3
    # wall-clock schedule deterministic across timezones.
    return buddy_state.BuddyState(theme_name="dark", sound_pack="off",
                                  clock=clock, now_min_fn=now_min)


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


# ── Water reminder (M4) ──────────────────────────────────────────────
class TestReminderDefaults:
    def test_disabled_by_default(self, state):
        assert state.reminder_enabled is False

    def test_default_interval_is_one_hour(self, state):
        assert state.reminder_interval == 60 * 60

    def test_default_sound_is_water(self, state):
        assert state.reminder_sound == "water"

    def test_default_anchor_is_eight_am(self, state):
        # M4.3: schedule cycles from 08:00 by default.
        assert state.reminder_anchor_minute == 8 * 60

    def test_default_quiet_hours_are_23_to_8(self, state):
        assert state.reminder_quiet_start == 23 * 60
        assert state.reminder_quiet_end == 8 * 60

    def test_not_active_initially(self, state):
        assert state.reminder_active is False

    def test_seconds_until_next_is_none_when_disabled(self, state):
        assert state.reminder_seconds_until_next() is None


class TestReminderSetters:
    def test_set_enabled_rebases_slot_tracker(self, state, clock, now_min):
        # Default anchor 08:00, default interval 1h. now=09:15.
        # Enabling should mark the 09:00 slot as already fired so the
        # NEXT firing is 10:00 — not retroactive for 08:00 + 09:00.
        now_min.set(9 * 60 + 15)
        state.set_reminder_enabled(True)
        # _last_fired_slot_min should be 09:00 (the latest slot at or
        # before now), so the next slot the tick produces is 10:00.
        assert state._last_fired_slot_min == 9 * 60

    def test_set_enabled_countdown_targets_next_slot(self, state, now_min):
        # Default anchor 08:00 + 1h interval, now=08:30.
        # Next slot is 09:00 ⇒ countdown ≈ 30 min.
        now_min.set(8 * 60 + 30)
        state.set_reminder_enabled(True)
        secs = state.reminder_seconds_until_next()
        assert secs == 30 * 60

    def test_set_disabled_clears_active_alarm(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60)  # before anchor — disables retroactive firing
        state.set_reminder_enabled(True)
        # Cross into a scheduled slot and tick.
        now_min.set(9 * 60)
        state.update()
        assert state.reminder_active is True
        state.set_reminder_enabled(False)
        assert state.reminder_active is False

    def test_set_interval_only_accepts_presets(self, state):
        state.set_reminder_interval(30 * 60)
        assert state.reminder_interval == 30 * 60
        # Bogus value normalises to the DEFAULT (1h) — better than
        # silently honouring a 7-second reminder spam interval.
        state.set_reminder_interval(7)
        assert state.reminder_interval == 60 * 60
        # Non-numeric also normalises to the default.
        state.set_reminder_interval(90 * 60)
        state.set_reminder_interval("garbage")
        assert state.reminder_interval == 60 * 60

    def test_set_interval_rebases_slot_tracker(self, state, now_min):
        # Enable at 09:15 (anchor 08:00, interval 1h ⇒ last fired slot
        # = 09:00). Switching to 30min interval at 09:45 should rebase
        # to the latest 30-min slot ≤ 09:45 ⇒ 09:30. The 10:00 slot
        # (1h schedule) won't fire because the schedule changed.
        now_min.set(9 * 60 + 15)
        state.set_reminder_enabled(True)
        assert state._last_fired_slot_min == 9 * 60
        now_min.set(9 * 60 + 45)
        state.set_reminder_interval(30 * 60)
        assert state._last_fired_slot_min == 9 * 60 + 30

    def test_set_sound_validates(self, state):
        state.set_reminder_sound("chime")
        assert state.reminder_sound == "chime"
        state.set_reminder_sound("not-a-sound")
        assert state.reminder_sound == "chime"  # unchanged

    def test_set_sound_off(self, state):
        state.set_reminder_sound("off")
        assert state.reminder_sound == "off"

    def test_set_quiet_hours_round_trip(self, state):
        state.set_reminder_quiet_hours(22 * 60, 7 * 60)
        assert state.reminder_quiet_start == 22 * 60
        assert state.reminder_quiet_end == 7 * 60

    def test_set_quiet_hours_none_disables(self, state):
        state.set_reminder_quiet_hours(None, None)
        assert state.reminder_quiet_start is None
        assert state.reminder_quiet_end is None


class TestReminderQuietHours:
    def test_is_reminder_quiet_now_default_window(self, state):
        # Default 23:00–08:00.
        assert state.is_reminder_quiet_now(now_min=23 * 60 + 30) is True
        assert state.is_reminder_quiet_now(now_min=3 * 60) is True
        assert state.is_reminder_quiet_now(now_min=8 * 60) is False
        assert state.is_reminder_quiet_now(now_min=10 * 60) is False

    def test_is_reminder_quiet_independent_of_m3_quiet(self, state):
        # M3 quiet hours are off by default; M4 is on (23–08). Confirms
        # the two checks consult different fields.
        assert state.is_quiet_now(now_min=23 * 60 + 30) is False
        assert state.is_reminder_quiet_now(now_min=23 * 60 + 30) is True


class TestReminderTick:
    def test_disabled_never_fires(self, state, clock):
        # Default is disabled — even a year later, nothing fires.
        clock.advance(365 * 24 * 3600)
        state.update()
        assert state.reminder_active is False

    def test_fires_at_scheduled_slot(self, state, now_min):
        # Anchor 08:00, interval 1h, now=07:30 → enable. Advance to
        # 09:00: the 09:00 slot fires (08:00 is consumed by enable's
        # "rebase to latest past slot" rule).
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        assert state.reminder_active is True

    def test_does_not_refire_between_slots_after_ack(self, state, now_min):
        # Enable at 07:30 ⇒ catch-up fires at 08:00 once we cross it.
        # After ack, 08:30 (between 08:00 and 09:00) must not refire.
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(8 * 60)
        state.update()
        assert state.reminder_active is True
        state.drink_acknowledged()
        now_min.set(8 * 60 + 30)
        state.update()
        assert state.reminder_active is False

    def test_catches_up_missed_slot_when_buddy_is_late(self, state, now_min):
        # Enable at 07:30 (anchor 08:00). User wasn't paying attention
        # and we don't tick again until 08:30 — the 08:00 slot we
        # missed *does* fire on the next tick, not silently get
        # swallowed. (Behaviour matches the user's mental model of
        # "remind me AT 08:00, 09:00, …"; if a tick is late, fire as
        # soon as the buddy realises.)
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(8 * 60 + 30)
        state.update()
        assert state.reminder_active is True
        assert state._last_fired_slot_min == 8 * 60

    def test_active_alarm_sets_bubble_text(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        assert state.bubble_text == "Drink water!"

    def test_active_alarm_queues_sound_when_not_off(self, clock):
        nm = FakeNowMin(7 * 60 + 30)
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   now_min_fn=nm,
                                   reminder_enabled=True,
                                   reminder_sound="water",
                                   reminder_quiet_start=None,
                                   reminder_quiet_end=None)
        nm.set(9 * 60)
        s.update()
        assert s._pending_reminder_sound == "water"

    def test_active_alarm_silent_when_sound_off(self, clock):
        nm = FakeNowMin(7 * 60 + 30)
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   now_min_fn=nm,
                                   reminder_enabled=True,
                                   reminder_sound="off",
                                   reminder_quiet_start=None,
                                   reminder_quiet_end=None)
        nm.set(9 * 60)
        s.update()
        assert s._pending_reminder_sound is None
        # Visual cue still fires — only audio is muted.
        assert s.reminder_active is True
        assert s.bubble_text == "Drink water!"

    def test_fires_at_anchor_when_enabled_before_anchor(self, state, now_min):
        # User flips the reminder on at 06:00. Default anchor 08:00.
        # No slot fires immediately (anchor hasn't happened yet); the
        # 08:00 slot fires when we cross it.
        state.set_reminder_quiet_hours(None, None)
        now_min.set(6 * 60)
        state.set_reminder_enabled(True)
        # Still before anchor — no fire.
        now_min.set(7 * 60 + 59)
        state.update()
        assert state.reminder_active is False
        # Cross the anchor.
        now_min.set(8 * 60)
        state.update()
        assert state.reminder_active is True

    def test_each_slot_fires_at_most_once(self, state, now_min):
        # Two consecutive ticks at the same slot ⇒ alarm fires once,
        # not twice. (After ack, the slot is consumed; the next
        # firing is at the next slot.)
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        state.drink_acknowledged()
        # Same slot, another tick — must not refire.
        state.update()
        assert state.reminder_active is False


class TestReminderAcknowledge:
    def test_drink_clears_active_alarm(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        assert state.reminder_active is True
        state.drink_acknowledged()
        assert state.reminder_active is False

    def test_drink_does_not_shift_schedule(self, state, now_min):
        # M4.3: drinking ack only dismisses the current alarm; the
        # next scheduled slot still fires on time.
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()  # 09:00 fires
        state.drink_acknowledged()
        # Countdown reads the next slot (10:00), not "interval from now".
        secs = state.reminder_seconds_until_next()
        assert secs == 60 * 60  # 09:00 → 10:00

    def test_drink_clears_reminder_bubble_only(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        assert state.bubble_text == "Drink water!"
        state.drink_acknowledged()
        assert state.bubble_text == ""

    def test_drink_leaves_user_bubble_alone(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        # User sends a --message while reminder is active.
        state.set_message("deploy done")
        assert state.bubble_text == "deploy done"
        state.drink_acknowledged()
        # _dismiss_reminder must not nuke the user's bubble.
        assert state.bubble_text == "deploy done"

    def test_next_slot_fires_after_drink(self, state, now_min, clock):
        # Drink ack at 09:05; the 10:00 slot still fires when reached.
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        now_min.set(9 * 60 + 5)
        state.drink_acknowledged()
        # Advance to the next scheduled slot.
        now_min.set(10 * 60)
        state.update()
        assert state.reminder_active is True


class TestReminderInQuietHours:
    """When the reminder's quiet hours are active, the alarm must not
    fire and the timer must not accumulate — so the user wakes up to
    a fresh interval, not an instant 7am ping."""

    def test_does_not_fire_in_quiet(self, clock):
        # Build a state with quiet hours covering "now". Inject now_min
        # via the helper used by is_reminder_quiet_now... actually
        # _tick_reminder reads time.localtime(). Test through the
        # is_reminder_quiet_now path by spying on it.
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   reminder_enabled=True,
                                   reminder_quiet_start=0,
                                   reminder_quiet_end=1439)
        # 23:59 → 00:00 wraps but here is_reminder_quiet_now will return
        # True for almost any wall-clock minute. Confirm no alarm fires.
        clock.advance(s.reminder_interval * 10)
        s.update()
        assert s.reminder_active is False

    def test_slot_tracker_advances_silently_in_quiet(self, clock):
        # Quiet hours cover all-day in this test. Walk now_min across
        # several scheduled slots and confirm: no alarm ever fires,
        # and `_last_fired_slot_min` advances so the moment the user
        # exits quiet hours, only the *next* slot fires (not every
        # slot they were meant to sleep through).
        nm = FakeNowMin(7 * 60)
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   now_min_fn=nm,
                                   reminder_enabled=True,
                                   reminder_quiet_start=0,
                                   reminder_quiet_end=1439)
        # Tick through several slot-times during quiet hours.
        for hh in (9, 10, 11, 12):
            nm.set(hh * 60)
            s.update()
            assert s.reminder_active is False
        # The 12:00 slot was the last quiet-consumed one.
        assert s._last_fired_slot_min == 12 * 60


class TestReminderIntervalHelper:
    def test_known_intervals_pass_through(self):
        assert buddy_state._normalize_reminder_interval(30 * 60) == 30 * 60
        assert buddy_state._normalize_reminder_interval(60 * 60) == 60 * 60
        assert buddy_state._normalize_reminder_interval(240 * 60) == 240 * 60

    def test_unknown_value_falls_back_to_default(self):
        assert buddy_state._normalize_reminder_interval(7) == 60 * 60
        assert buddy_state._normalize_reminder_interval(99999) == 60 * 60

    def test_non_numeric_falls_back(self):
        assert buddy_state._normalize_reminder_interval("hourly") == 60 * 60
        assert buddy_state._normalize_reminder_interval(None) == 60 * 60


# ── Drinking history (M4.1) ──────────────────────────────────────────
class _RecordingHistorySave:
    """Tiny callable that records the args every time it's called, so
    tests can assert on what the state handed to the persistence layer."""

    def __init__(self):
        self.calls = []

    def __call__(self, today, recent):
        # Defensive copy — we want to observe what the state held at
        # the moment of save, not whatever it looked like later.
        self.calls.append((
            dict(today) if today is not None else None,
            [dict(e) for e in recent],
        ))


class TestHistoryDefaults:
    def test_starts_at_zero(self, state):
        assert state.cups_today == 0

    def test_recent_days_starts_empty(self, state):
        assert state.recent_days == []

    def test_today_date_starts_unset(self, state):
        assert state.cups_today_date is None


class TestHistorySeeding:
    """Constructor seeds the in-memory counter from a (today, recent)
    snapshot — that's how app.py restores the previous run on startup."""

    def test_seeds_from_constructor_args(self, clock):
        s = buddy_state.BuddyState(
            sound_pack="off", clock=clock,
            cups_today=4, cups_today_date="2026-05-25",
            recent_days=[
                {"date": "2026-05-24", "count": 6},
                {"date": "2026-05-23", "count": 5},
            ],
        )
        assert s.cups_today == 4
        assert s.cups_today_date == "2026-05-25"
        assert len(s.recent_days) == 2

    def test_rejects_negative_seed(self, clock):
        s = buddy_state.BuddyState(
            sound_pack="off", clock=clock,
            cups_today=-3, cups_today_date="2026-05-25",
        )
        assert s.cups_today == 0

    def test_rejects_non_int_seed(self, clock):
        s = buddy_state.BuddyState(
            sound_pack="off", clock=clock,
            cups_today="five", cups_today_date="2026-05-25",
        )
        assert s.cups_today == 0

    def test_rejects_malformed_date_seed(self, clock):
        s = buddy_state.BuddyState(
            sound_pack="off", clock=clock,
            cups_today=3, cups_today_date="bogus",
        )
        assert s.cups_today_date is None

    def test_drops_malformed_recent_entries(self, clock):
        s = buddy_state.BuddyState(
            sound_pack="off", clock=clock,
            recent_days=[
                {"date": "2026-05-24", "count": 6},          # ok
                {"date": "bogus", "count": 5},               # bad date
                {"date": "2026-05-23", "count": -1},         # negative
                "not a dict",                                # wrong type
                {"date": "2026-05-22", "count": 4},          # ok
            ],
        )
        assert s.recent_days == [
            {"date": "2026-05-24", "count": 6},
            {"date": "2026-05-22", "count": 4},
        ]

    def test_trims_seed_to_cap(self, clock):
        oversized = [{"date": f"2026-04-{d:02d}", "count": d}
                     for d in range(1, buddy_state.HISTORY_RECENT_DAYS_MAX + 5)]
        s = buddy_state.BuddyState(
            sound_pack="off", clock=clock, recent_days=oversized,
        )
        assert len(s.recent_days) == buddy_state.HISTORY_RECENT_DAYS_MAX


class TestHistoryAcknowledge:
    def test_drink_increments_cup_count(self, state):
        assert state.cups_today == 0
        state.drink_acknowledged()
        assert state.cups_today == 1
        state.drink_acknowledged()
        state.drink_acknowledged()
        assert state.cups_today == 3

    def test_drink_stamps_today_date_on_first_ack(self, state, clock):
        # Clock starts at fixed value — the date string is whatever
        # localtime gives for that timestamp. We don't care about the
        # exact value, only that it's set + iso-shaped.
        state.drink_acknowledged()
        assert state.cups_today_date is not None
        assert len(state.cups_today_date) == 10
        assert state.cups_today_date[4] == "-"
        assert state.cups_today_date[7] == "-"

    def test_drink_persists_via_history_save_fn(self, clock):
        save = _RecordingHistorySave()
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   history_save_fn=save)
        s.drink_acknowledged()
        assert len(save.calls) == 1
        today, recent = save.calls[0]
        assert today["count"] == 1
        assert recent == []

    def test_no_save_fn_means_no_disk_write(self, state):
        # Default fixture has no history_save_fn — drink_acknowledged
        # must not crash. The count still increments in memory.
        state.drink_acknowledged()
        assert state.cups_today == 1

    def test_save_fn_failure_is_non_fatal(self, clock):
        def boom(today, recent):
            raise OSError("disk on fire")
        s = buddy_state.BuddyState(sound_pack="off", clock=clock,
                                   history_save_fn=boom)
        # Must not propagate — drink_acknowledged is called from the
        # main render loop and crashing the buddy because a save
        # failed would be the wrong contract.
        s.drink_acknowledged()
        assert s.cups_today == 1


class TestHistoryDayRollover:
    """When the local calendar day changes, the in-progress count
    closes out into `recent_days` and `cups_today` resets to 0."""

    def test_same_day_no_rollover(self, state):
        # Calling _roll twice in the same tick must be idempotent.
        state.drink_acknowledged()
        state.drink_acknowledged()
        state._roll_history_day_if_needed()
        state._roll_history_day_if_needed()
        assert state.cups_today == 2
        assert state.recent_days == []

    def test_explicit_rollover_via_date_swap(self, state):
        # Force a rollover by mutating `cups_today_date` to yesterday
        # (the easiest way to drive _roll deterministically without
        # advancing the system clock).
        state.drink_acknowledged()
        state.drink_acknowledged()
        state.drink_acknowledged()
        state.cups_today_date = "2026-05-24"  # pretend yesterday
        state._roll_history_day_if_needed()
        assert state.cups_today == 0
        assert state.recent_days == [{"date": "2026-05-24", "count": 3}]

    def test_rollover_skips_zero_cup_day(self, state):
        # An idle day shouldn't pollute the recent list with a 0 row.
        state.cups_today_date = "2026-05-24"  # stamp yesterday, no drinks
        state._roll_history_day_if_needed()
        assert state.recent_days == []

    def test_rollover_trims_recent_to_cap(self, state):
        # Pre-load the recent list at the cap. Roll over one more day.
        state.recent_days = [
            {"date": f"2026-04-{d:02d}", "count": d}
            for d in range(1, buddy_state.HISTORY_RECENT_DAYS_MAX + 1)
        ]
        state.drink_acknowledged()
        state.cups_today_date = "2026-05-24"
        state._roll_history_day_if_needed()
        assert len(state.recent_days) == buddy_state.HISTORY_RECENT_DAYS_MAX
        # Newest entry is at the front.
        assert state.recent_days[0]["date"] == "2026-05-24"

    def test_first_call_stamps_date_without_close_out(self, state):
        # `cups_today_date` is None initially — first _roll should just
        # stamp today, not push a zero entry.
        assert state.cups_today_date is None
        state._roll_history_day_if_needed()
        assert state.cups_today_date is not None
        assert state.recent_days == []


class TestHistorySnapshot:
    def test_snapshot_returns_today_and_recent(self, state):
        state.drink_acknowledged()
        state.drink_acknowledged()
        today, recent = state.history_snapshot()
        assert today["count"] == 2
        assert recent == []

    def test_snapshot_today_none_when_no_drinks_yet(self, state):
        today, recent = state.history_snapshot()
        assert today is None
        assert recent == []

    def test_snapshot_recent_is_defensive_copy(self, state):
        state.recent_days = [{"date": "2026-05-24", "count": 6}]
        _, recent = state.history_snapshot()
        recent.append({"date": "BAD", "count": 99})  # mutate the copy
        assert state.recent_days == [{"date": "2026-05-24", "count": 6}]


class TestHistoryUpdateTick:
    def test_update_triggers_rollover(self, state):
        state.drink_acknowledged()
        state.cups_today_date = "2026-05-24"  # simulate cross-midnight
        state.update()
        assert state.cups_today == 0
        assert state.recent_days[0]["date"] == "2026-05-24"


class TestHistoryDateHelper:
    def test_today_iso_shape(self, state):
        s = state._today_iso()
        assert len(s) == 10 and s[4] == "-" and s[7] == "-"
        # All numeric parts.
        for part in s.split("-"):
            int(part)

    def test_is_iso_date_str_helper(self):
        assert buddy_state._is_iso_date_str("2026-05-25") is True
        assert buddy_state._is_iso_date_str("bogus") is False
        assert buddy_state._is_iso_date_str(None) is False
        assert buddy_state._is_iso_date_str("2026-13-01") is False


class TestReminderAnchorHelpers:
    """M4.3: the daily anchor + slot-arithmetic helpers."""

    def test_normalize_anchor_passthrough(self):
        assert buddy_state._normalize_anchor_minute(8 * 60) == 8 * 60
        assert buddy_state._normalize_anchor_minute(0) == 0
        assert buddy_state._normalize_anchor_minute(1439) == 1439

    def test_normalize_anchor_out_of_range_defaults(self):
        assert (buddy_state._normalize_anchor_minute(-1)
                == buddy_state.DEFAULT_REMINDER_ANCHOR_MINUTE)
        assert (buddy_state._normalize_anchor_minute(1440)
                == buddy_state.DEFAULT_REMINDER_ANCHOR_MINUTE)

    def test_normalize_anchor_non_numeric_defaults(self):
        assert (buddy_state._normalize_anchor_minute("09:00")
                == buddy_state.DEFAULT_REMINDER_ANCHOR_MINUTE)
        assert (buddy_state._normalize_anchor_minute(None)
                == buddy_state.DEFAULT_REMINDER_ANCHOR_MINUTE)

    def test_latest_slot_before_anchor_is_none(self):
        # now_min < anchor ⇒ no slot has fired today
        assert buddy_state._latest_slot_at_or_before(
            anchor_min=9 * 60, interval_min=60, now_min=7 * 60) is None

    def test_latest_slot_at_anchor_is_anchor(self):
        assert buddy_state._latest_slot_at_or_before(
            anchor_min=9 * 60, interval_min=60, now_min=9 * 60) == 9 * 60

    def test_latest_slot_between_slots(self):
        # 09:00 + 1h grid, now=10:30 ⇒ latest slot is 10:00
        assert buddy_state._latest_slot_at_or_before(
            anchor_min=9 * 60, interval_min=60,
            now_min=10 * 60 + 30) == 10 * 60

    def test_latest_slot_with_irregular_interval(self):
        # 08:00 + 90 min grid: 08:00, 09:30, 11:00, 12:30, …
        # At 11:45 the latest slot is 11:00.
        assert buddy_state._latest_slot_at_or_before(
            anchor_min=8 * 60, interval_min=90,
            now_min=11 * 60 + 45) == 11 * 60


class TestReminderAnchorSetter:
    def test_anchor_setter_updates_field(self, state):
        state.set_reminder_anchor_minute(13 * 60)
        assert state.reminder_anchor_minute == 13 * 60

    def test_anchor_setter_rejects_out_of_range(self, state):
        state.set_reminder_anchor_minute(2000)
        # Out-of-range ⇒ falls back to default; field is now 08:00.
        assert state.reminder_anchor_minute == 8 * 60

    def test_anchor_setter_resets_slot_tracker(self, state, now_min):
        # Enable at 09:15 ⇒ _last_fired_slot_min = 09:00. Change anchor
        # to 13:00 ⇒ tracker resets to None so the next future slot
        # (13:00 → 14:00 → …) fires when reached, not retroactively.
        now_min.set(9 * 60 + 15)
        state.set_reminder_enabled(True)
        assert state._last_fired_slot_min == 9 * 60
        state.set_reminder_anchor_minute(13 * 60)
        assert state._last_fired_slot_min is None


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
