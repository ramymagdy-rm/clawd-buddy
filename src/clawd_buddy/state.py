# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""BuddyState — the state machine driving every animation the buddy plays.

Split out of `app.py` so the state behaviour is independently importable
and testable (no pygame/window/socket dependencies). See
`.ai/decisions/2026-05-24-milestone-1-session-arc.md` for the design
behind the modes, the queue, and the session-greeting logic.
"""

import random
import time

from .constants import WIN_H, WIN_W
from .ui.sound import DEFAULT_SOUND_PACK, SOUND_PACK_CHOICES, SOUND_PACK_OFF
from .ui.themes import THEMES


# ── Mode taxonomy ────────────────────────────────────────────────────
# Ambient modes hold indefinitely and yield to any incoming signal.
# Reactive modes own the buddy for a fixed duration, then yield to the
# next queued signal (or fall back to idle).
AMBIENT_MODES = frozenset({"idle", "thinking"})
REACTIVE_MODES = frozenset({"celebrating", "waving", "greeting"})

# Reactive action → mode name. Used by the queue dispatcher to convert
# the queued action token into the matching mode string.
_ACTION_TO_MODE = {
    "celebrate": "celebrating",
    "wave": "waving",
    "greet": "greeting",
}

# Default per-mode durations (seconds). Read on BuddyState init so tests
# can override per-instance.
DEFAULT_CEL_DUR = 5.0
DEFAULT_WAVE_DUR = 5.0
DEFAULT_GREET_DUR = 1.8

# Thinking is ambient with a safety cap — if Stop never arrives
# (assistant crash, network loss) we don't want to stay in the thinking
# animation forever. Long enough for legitimate long runs, short enough
# that a stale state self-recovers within ~10 minutes.
MAX_THINKING_SECONDS = 600.0

# Without an explicit session id, treat any prompt arriving after this
# many idle seconds as the start of a new session (so we greet again).
NEW_SESSION_IDLE_SECONDS = 1800.0

# Cap on the reaction queue. Three is enough to absorb a normal burst
# (e.g. a wave during a celebrate during another celebrate) without
# letting a runaway producer build up minutes of animations no longer
# tied to their original event.
QUEUE_MAX = 3

# Default lifetime of a `--message` speech bubble, in seconds. Long
# enough to read a short status ping, short enough that a stale message
# clears itself before the next prompt cycle. See
# .ai/decisions/2026-05-24-milestone-2-buddy-speaks.md.
DEFAULT_BUBBLE_DUR = 3.0

# Hard cap on bubble text length. Anything longer is truncated with an
# ellipsis — the bubble is a status ping, not a notification panel.
MAX_BUBBLE_LEN = 120


# Confetti palette — shared across all themes so a celebrate animation
# is always rainbow-coloured regardless of which theme is active.
CONFETTI_COLORS = [
    (255, 107, 107), (78, 205, 196), (69, 183, 209),
    (255, 230, 109), (199, 128, 232), (255, 159, 67),
]


# ── M3 helpers (pure, testable without instantiating BuddyState) ─────
def _clamp_volume(v):
    """Coerce a volume value into [0.0, 1.0]. Non-numeric input ⇒ 1.0
    so a corrupt config doesn't end up muting the buddy permanently."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    if v != v:  # NaN
        return 1.0
    return max(0.0, min(1.0, v))


def _normalize_quiet(start, end):
    """Validate a (start, end) quiet-hours pair (minutes-from-midnight).

    Returns the pair unchanged when both are valid integers in
    [0, 1439]. Returns (None, None) — i.e. disabled — for any other
    input (mixed None, out-of-range, non-int, or start==end zero-length
    window). Treating malformed values as 'disabled' keeps the buddy
    chirping when a config gets corrupted rather than silently muting.
    """
    if start is None or end is None:
        return None, None
    if not (isinstance(start, int) and isinstance(end, int)):
        return None, None
    if not (0 <= start < 1440 and 0 <= end < 1440):
        return None, None
    if start == end:
        return None, None
    return start, end


def _in_quiet_window(start, end, now_min):
    """Return True if `now_min` (minutes-from-midnight) falls inside
    the [start, end) window. Handles wraparound: when start > end
    (e.g. 23:00 → 08:00), the window spans midnight."""
    if start is None or end is None:
        return False
    if start < end:
        return start <= now_min < end
    return now_min >= start or now_min < end


def _spawn_confetti(n):
    """Build n confetti particles for the celebrate animation.

    Particles are plain lists rather than namedtuples for cheap in-place
    mutation in the per-frame physics step.
    Particle layout: [x, y, vx, vy, color, size].
    """
    cx = WIN_W // 2
    return [
        [cx + random.randint(-30, 30), WIN_H // 2 - 40,
         random.uniform(-3, 3), random.uniform(-7, -2),
         random.choice(CONFETTI_COLORS), random.randint(3, 6)]
        for _ in range(n)
    ]


class BuddyState:
    SCALE_PRESETS = {1: 1.0, 2: 1.25, 3: 1.5, 4: 2.0}

    def __init__(self, theme_name="dark", sound_pack=None, clock=None,
                 reduce_motion=False, volume=1.0,
                 quiet_start=None, quiet_end=None):
        # `clock` indirection so unit tests can advance time without
        # actually sleeping. Defaults to time.time at runtime.
        self._clock = clock if clock is not None else time.time
        self.mode = "idle"
        self.mode_start = 0.0
        self.cel_dur = DEFAULT_CEL_DUR
        self.wave_dur = DEFAULT_WAVE_DUR
        self.greet_dur = DEFAULT_GREET_DUR
        self.confetti = []
        self.should_quit = False
        self.theme_name = theme_name
        self.theme = dict(THEMES[theme_name])
        self.scale = 1.0
        self._scale_changed = False
        self._raise_requested = False
        # Notification sound — queued from socket / tray / key threads and
        # consumed by the main loop so mixer.play() only runs on one thread.
        if sound_pack is None or sound_pack not in SOUND_PACK_CHOICES:
            sound_pack = DEFAULT_SOUND_PACK
        self.sound_pack = sound_pack
        self._pending_sound = None  # "celebrate" | "wave" | None

        # Reaction queue (FIFO of (action, kwargs)). See _request().
        self._queue = []

        # Session-greeting state. last_session_id is what we saw most
        # recently; last_activity_ts is the wall-clock of the last
        # prompt_start (used for the no-session-id fallback).
        self._last_session_id = None
        self._last_activity_ts = 0.0

        # M2: speech bubble overlay. Independent of `mode` so a bubble
        # can co-exist with any animation. Empty string = no bubble.
        self.bubble_text = ""
        self._bubble_expiry = 0.0

        # M2: last action token dispatched through the IPC layer, with
        # the wall-clock when it happened. Surfaced via `--status`.
        self.last_action = None
        self.last_action_ts = 0.0

        # M2: mirror of whether the window is currently kept on top.
        # The main loop owns the real pygame/Win32 state and writes it
        # here so `--status` can report it without the IPC layer reaching
        # into windowing code.
        self.topmost = True

        # M3: when wave/greet preempts thinking, remember to resume the
        # thinking animation after the cue clears (and any items behind
        # it in the queue drain). Cleared by celebrate — Stop semantically
        # ends thinking — or by explicit end_thinking. Without this flag
        # the buddy fell back to idle after an attention cue even though
        # Claude was still working.
        self._resume_thinking = False

        # M3: accessibility / comfort preferences.
        # `reduce_motion` strips bob, limb swings, confetti, and ambient
        # eye/mouth animation — keeps only the attention border and
        # sounds (the signaling minimum), so users with vestibular
        # sensitivities can still tell what's happening without motion.
        # `volume` is a 0.0–1.0 multiplier applied on top of each pack's
        # per-sound base level — surfaced as discrete steps in the tray
        # but stored as a float so future sliders can fill in.
        # `quiet_start` / `quiet_end` are minutes-from-midnight; when
        # both are set, sounds are muted within the window (handles the
        # 23:00–07:00 wraparound, see `is_quiet_now`).
        self.reduce_motion = bool(reduce_motion)
        self.volume = _clamp_volume(volume)
        self.quiet_start, self.quiet_end = _normalize_quiet(
            quiet_start, quiet_end)

        # Dirty flag — the audio mixer's per-sound volumes live in
        # pygame's Sound objects, owned by app.py. The state holds the
        # user preference and flips this so the main loop knows to
        # re-apply on the next frame. Same pattern as `_scale_changed`.
        self._volume_changed = False

    # ── Sound ────────────────────────────────────────────────────
    @property
    def sound_enabled(self):
        return self.sound_pack != SOUND_PACK_OFF

    def set_sound_pack(self, pack):
        """Switch the active sound pack and queue an immediate preview of
        the celebrate sound (unless 'off'). Called from the tray menu —
        previewing right after selection is the whole point of the submenu,
        per the feature spec.
        """
        if pack not in SOUND_PACK_CHOICES:
            return
        self.sound_pack = pack
        if pack != SOUND_PACK_OFF:
            self._pending_sound = "celebrate"

    def set_volume(self, v):
        """Set the user volume multiplier (0.0–1.0). Flags
        `_volume_changed` so the main loop re-applies it to every
        cached pygame Sound on the next frame. Also queues a celebrate
        preview at the new level when sound is enabled — picking a
        volume in the tray is most useful when you can hear it."""
        new_vol = _clamp_volume(v)
        if new_vol == self.volume:
            return
        self.volume = new_vol
        self._volume_changed = True
        if self.sound_enabled and new_vol > 0.0:
            self._pending_sound = "celebrate"

    def set_reduce_motion(self, enabled):
        """Toggle reduce-motion. When on, drawing suppresses bobbing,
        limb swings, confetti, and ambient pupil/mouth animation —
        keeps the attention border and sounds (the signaling minimum
        per the M3 design note)."""
        self.reduce_motion = bool(enabled)

    def set_quiet_hours(self, start, end):
        """Set the quiet-hours window. Pass (None, None) to disable.
        Both endpoints are minutes-from-midnight; the window wraps over
        midnight when start > end (typical 23:00–08:00 case)."""
        self.quiet_start, self.quiet_end = _normalize_quiet(start, end)

    def is_quiet_now(self, now_min=None):
        """True if quiet hours are configured AND the current local
        time falls inside the window. `now_min` (minutes-from-midnight)
        is the testing seam; production callers omit it and we read
        `time.localtime()` instead."""
        if self.quiet_start is None or self.quiet_end is None:
            return False
        if now_min is None:
            lt = time.localtime()
            now_min = lt.tm_hour * 60 + lt.tm_min
        return _in_quiet_window(self.quiet_start, self.quiet_end, now_min)

    # ── Mode introspection (used by drawing and tests) ───────────
    @property
    def celebrating(self):
        return self.mode == "celebrating"

    @property
    def waving(self):
        return self.mode == "waving"

    @property
    def greeting(self):
        return self.mode == "greeting"

    @property
    def thinking(self):
        return self.mode == "thinking"

    @property
    def queue_depth(self):
        return len(self._queue)

    @property
    def last_session_id(self):
        return self._last_session_id

    # ── Theme / window ───────────────────────────────────────────
    def set_theme(self, name):
        if name in THEMES:
            self.theme_name = name
            self.theme = dict(THEMES[name])

    def set_scale(self, preset):
        """Set scale from preset number (1-4)."""
        if preset in self.SCALE_PRESETS:
            self.scale = self.SCALE_PRESETS[preset]
            self._scale_changed = True

    def bring_to_front(self):
        self._raise_requested = True

    # ── Public action surface ────────────────────────────────────
    # Each of these is a thin wrapper around _request so callers don't
    # have to know about the queue / preemption rules.
    def trigger(self, _msg=""):
        """Celebrate — assistant finished. Preempts thinking/idle, queues
        behind another reactive mode."""
        self._request("celebrate")

    def wave(self):
        """Wave for attention. Same priority as celebrate; queues if
        another reactive mode is already animating."""
        self._request("wave")

    def greet(self, session_id=None):
        """Soft greeting animation for the start of a new session.
        Use prompt_start() instead unless you specifically want to bypass
        the new-session check."""
        self._request("greet", session_id=session_id)

    def start_thinking(self):
        """Enter the thinking animation. No-op if already thinking; queues
        behind a reactive mode so thinking resumes after a celebrate/wave
        clears."""
        self._request("start_thinking")

    def end_thinking(self):
        """Leave thinking. No-op if not currently thinking. Reactive modes
        already implicitly end thinking by preempting it, so callers
        rarely need this directly."""
        self._request("end_thinking")

    def set_message(self, text, duration=DEFAULT_BUBBLE_DUR):
        """Show `text` in a speech bubble above the buddy for `duration`
        seconds. Replaces any current message (single-slot, no queue).

        Empty / blank input clears the bubble immediately — that matches
        the user intent of `clawd-buddy --message ""` as a dismiss.
        Anything past MAX_BUBBLE_LEN is truncated with a single ellipsis;
        the bubble is a status ping, not a notification panel.
        """
        if not isinstance(text, str):
            return
        text = text.strip()
        if not text:
            self.bubble_text = ""
            self._bubble_expiry = 0.0
            return
        if len(text) > MAX_BUBBLE_LEN:
            text = text[:MAX_BUBBLE_LEN - 1].rstrip() + "…"
        self.bubble_text = text
        self._bubble_expiry = self._clock() + duration

    def record_action(self, action):
        """Record an IPC action token as the last dispatched action.
        Used by `--status` so callers can see what the buddy last
        reacted to without grepping the buddy's stdout."""
        if not isinstance(action, str) or not action:
            return
        self.last_action = action
        self.last_action_ts = self._clock()

    def prompt_start(self, session_id=None):
        """UserPromptSubmit handler — the wire-once Claude Code entry point.

        Decides whether this is the *first* prompt of a session and emits
        a greet + start_thinking accordingly. Greets when:
          - session_id is given and differs from the last one we saw, OR
          - no session_id is given and we've been idle longer than
            NEW_SESSION_IDLE_SECONDS (or never seen a prompt before).
        Always starts thinking afterwards.
        """
        now = self._clock()
        if session_id:
            is_new_session = session_id != self._last_session_id
            self._last_session_id = session_id
        else:
            is_new_session = (self._last_activity_ts == 0.0
                              or now - self._last_activity_ts
                              > NEW_SESSION_IDLE_SECONDS)
        self._last_activity_ts = now
        if is_new_session:
            self._request("greet")
        self._request("start_thinking")

    # ── Per-frame tick ───────────────────────────────────────────
    def update(self):
        """Called once per frame. Expires reactive modes, pulls the
        next queued action, enforces the thinking safety cap, and clears
        any expired speech bubble."""
        now = self._clock()
        elapsed = now - self.mode_start
        if self.mode == "celebrating" and elapsed > self.cel_dur:
            self._advance_from_reactive()
        elif self.mode == "waving" and elapsed > self.wave_dur:
            self._advance_from_reactive()
        elif self.mode == "greeting" and elapsed > self.greet_dur:
            self._advance_from_reactive()
        elif self.mode == "thinking" and elapsed > MAX_THINKING_SECONDS:
            self._enter("idle")

        if self.bubble_text and now > self._bubble_expiry:
            self.bubble_text = ""
            self._bubble_expiry = 0.0

    # ── Internal: dispatch / queue ───────────────────────────────
    def _request(self, action, **kwargs):
        """Single entry point for all mode transitions. Either applies
        the action immediately or enqueues it; see the decision doc."""
        if action == "end_thinking":
            self._resume_thinking = False
            if self.mode == "thinking":
                self._enter("idle")
            return

        if action == "start_thinking":
            if self.mode == "thinking":
                self._resume_thinking = False
                return  # already thinking
            if self.mode == "idle":
                self._resume_thinking = False
                self._enter("thinking")
                return
            self._enqueue(action, kwargs)
            return

        if action in ("celebrate", "wave", "greet"):
            if self.mode in REACTIVE_MODES:
                self._enqueue(action, kwargs)
                return
            # idle or thinking → apply now (celebrate/wave preempt
            # thinking; greet preempts thinking too — design doc rule).
            self._enter_reactive(action, kwargs)
            return

    def _enter(self, mode):
        self.mode = mode
        self.mode_start = self._clock()

    def _enter_reactive(self, action, kwargs):
        """Switch to the reactive mode for `action`, doing any per-action
        side effects (confetti spawn, pending sound).

        M3: maintain `_resume_thinking` so an attention cue (wave / greet)
        that interrupts thinking restores thinking when it clears.
        Celebrate is the Stop signal — semantically ends thinking, so it
        clears the flag. Only set the flag when transitioning *from*
        thinking (the initial preemption); chained reactives popped from
        the queue keep whatever value was set earlier.
        """
        if action == "celebrate":
            self._resume_thinking = False
        elif action in ("wave", "greet") and self.mode == "thinking":
            self._resume_thinking = True
        self.mode = _ACTION_TO_MODE[action]
        self.mode_start = self._clock()
        if action == "celebrate":
            # M3: reduce-motion skips the confetti particle physics
            # entirely (the swarm of falling rectangles is the most
            # motion-heavy element). Sound + border still fire so the
            # celebrate is still legible.
            if not self.reduce_motion:
                self.confetti = _spawn_confetti(40)
            if self.sound_enabled:
                self._pending_sound = "celebrate"
        elif action == "wave":
            if self.sound_enabled:
                self._pending_sound = "wave"
        # greet: silent in M1 — see decision doc §"Visual + audio"

    def _enqueue(self, action, kwargs):
        """Add to the FIFO. Suppresses consecutive `start_thinking`s
        (they would just resume the same ambient animation) and caps the
        queue at QUEUE_MAX to bound runaway producers."""
        if action == "start_thinking":
            if self._queue and self._queue[-1][0] == "start_thinking":
                return
        if len(self._queue) >= QUEUE_MAX:
            return
        self._queue.append((action, kwargs))

    def _advance_from_reactive(self):
        """A reactive mode just expired. Pop the next queued action and
        apply it; if the queue is empty, fall back to idle — or to
        thinking, if a prior wave/greet preempted it (see
        `_resume_thinking`)."""
        if not self._queue:
            if self._resume_thinking:
                self._resume_thinking = False
                self._enter("thinking")
            else:
                self._enter("idle")
            return
        action, kwargs = self._queue.pop(0)
        if action == "start_thinking":
            self._resume_thinking = False
            self._enter("thinking")
        elif action in ("celebrate", "wave", "greet"):
            self._enter_reactive(action, kwargs)
        else:
            # end_thinking or unknown — degrade to idle.
            self._resume_thinking = False
            self._enter("idle")
