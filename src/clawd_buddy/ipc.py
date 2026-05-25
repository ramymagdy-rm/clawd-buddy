# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Inter-process communication for the running buddy.

The running buddy exposes a tiny JSON-over-TCP server on `SOCK_PORT`.
Clients (CLI invocations of `clawd-buddy --send` / `--wave` / etc.)
connect, send a single JSON payload, and disconnect. Each payload
maps to one method on the active `BuddyState`.

Protocol layout:

    {"action": "<name>", ...optional kwargs...}

Supported actions (and the BuddyState method they invoke):

    celebrate      → state.trigger()
    wave           → state.wave()
    raise          → state.bring_to_front()
    quit           → sets state.should_quit
    prompt_start   → state.prompt_start(session_id=…)
    greet          → state.greet(session_id=…)
    thinking_start → state.start_thinking()
    thinking_end   → state.end_thinking()
    message        → state.set_message(text=…)             (M2)
    status         → server replies with JSON status        (M2)
    <anything else> → state.trigger()   (defensive default for older clients)

`status` is the one request/response action — every other action is
fire-and-forget. See
.ai/decisions/2026-05-24-milestone-2-buddy-speaks.md for the rationale.

The dispatch logic lives in `dispatch_action` as a pure function so it
can be tested without a real socket. `socket_listener` is the network
shell that wraps the dispatch in an accept-loop.
"""

import json
import os
import socket

from . import __version__
from .constants import SOCK_HOST, SOCK_PORT


# Names every consumer can reference. Keeping them as constants rather
# than string literals scattered across the codebase makes typos cheaper
# to catch.
ACTION_CELEBRATE = "celebrate"
ACTION_WAVE = "wave"
ACTION_RAISE = "raise"
ACTION_QUIT = "quit"
ACTION_PROMPT_START = "prompt_start"
ACTION_GREET = "greet"
ACTION_THINKING_START = "thinking_start"
ACTION_THINKING_END = "thinking_end"
ACTION_MESSAGE = "message"
ACTION_STATUS = "status"
ACTION_DRANK = "drank"   # M4: water-reminder acknowledgment

KNOWN_ACTIONS = frozenset({
    ACTION_CELEBRATE,
    ACTION_WAVE,
    ACTION_RAISE,
    ACTION_QUIT,
    ACTION_PROMPT_START,
    ACTION_GREET,
    ACTION_THINKING_START,
    ACTION_THINKING_END,
    ACTION_MESSAGE,
    ACTION_STATUS,
    ACTION_DRANK,
})


def parse_message(raw):
    """Parse raw socket bytes/str into a (action, payload) tuple.

    Returns the literal action token as it appeared (or "celebrate" if
    the payload was unparseable / had no action key), plus the full
    decoded payload dict. The dispatcher uses the action to route and
    the payload to extract any kwargs (e.g. session_id).
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            raw = ""
    raw = (raw or "").strip()
    if not raw:
        return ACTION_CELEBRATE, {}
    msg = {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            msg = parsed
    except json.JSONDecodeError:
        pass
    action = msg.get("action") if isinstance(msg.get("action"), str) else ACTION_CELEBRATE
    return action, msg


def dispatch_action(state, action, payload=None):
    """Apply `action` to the given BuddyState.

    Returns True if the action was recognised (one of KNOWN_ACTIONS or
    falls through to celebrate). The return value is only used by tests
    today, but it makes the function's contract precise: callers can
    log unknown actions if they care.

    Note: `status` is a no-op here — the listener intercepts it before
    dispatch to send a response. We still register it in KNOWN_ACTIONS
    so the protocol surface is centralised in one place.
    """
    payload = payload or {}
    if action == ACTION_WAVE:
        state.wave()
    elif action == ACTION_RAISE:
        state.bring_to_front()
    elif action == ACTION_QUIT:
        state.should_quit = True
    elif action == ACTION_PROMPT_START:
        state.prompt_start(session_id=payload.get("session_id"))
    elif action == ACTION_GREET:
        state.greet(session_id=payload.get("session_id"))
    elif action == ACTION_THINKING_START:
        state.start_thinking()
    elif action == ACTION_THINKING_END:
        state.end_thinking()
    elif action == ACTION_MESSAGE:
        state.set_message(payload.get("text", ""))
    elif action == ACTION_STATUS:
        # Handled by the listener (request/response). Nothing to do on
        # the state side — but we still record the action below so
        # `--status` reports "status" as its own last_action.
        pass
    elif action == ACTION_DRANK:
        state.drink_acknowledged()
    else:
        # Defensive default: any unrecognised action celebrates. This
        # preserves backward-compat with older buddy clients that sent
        # the literal "done" or empty string for a Stop hook.
        state.trigger()
    state.record_action(action if action in KNOWN_ACTIONS else ACTION_CELEBRATE)
    return action in KNOWN_ACTIONS


def _format_hhmm(minutes):
    """Render `minutes`-from-midnight (0..1439) as "HH:MM". Returns None
    if the input isn't a usable int — used inside the quiet-hours
    block of the status response."""
    if not isinstance(minutes, int):
        return None
    if not (0 <= minutes < 1440):
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build_status_response(state, port=SOCK_PORT, topmost=True):
    """Snapshot the running buddy's state as a JSON-serialisable dict.

    `port` and `topmost` are passed in from the listener / app context —
    `BuddyState` deliberately doesn't know about either (state stays
    pygame-/socket-free for testability). `last_action_ts` is `None`
    until the first action lands; callers can use that to tell a fresh
    buddy from a long-running one.

    M3: `reduce_motion`, `volume`, and `quiet_hours` reflect the
    accessibility / comfort prefs. `quiet_hours` is `null` when
    disabled, or `{"start": "HH:MM", "end": "HH:MM"}` when set — the
    HH:MM strings are easier to eyeball than minutes-from-midnight in
    a CLI dump.
    """
    if state.quiet_start is None or state.quiet_end is None:
        quiet_block = None
    else:
        quiet_block = {
            "start": _format_hhmm(state.quiet_start),
            "end": _format_hhmm(state.quiet_end),
        }
    # M4: reminder block. Mirrors M3's quiet-hours shape (null when
    # the inner window is disabled; HH:MM strings when set).
    # `seconds_until_next` is rounded to whole seconds — sub-second
    # precision is meaningless for a feature whose minimum interval
    # is 30 minutes.
    if (state.reminder_quiet_start is None
            or state.reminder_quiet_end is None):
        reminder_quiet = None
    else:
        reminder_quiet = {
            "start": _format_hhmm(state.reminder_quiet_start),
            "end": _format_hhmm(state.reminder_quiet_end),
        }
    secs_until = state.reminder_seconds_until_next()
    reminder_block = {
        "enabled": bool(state.reminder_enabled),
        "interval_seconds": int(state.reminder_interval),
        "anchor": _format_hhmm(state.reminder_anchor_minute),
        "sound": state.reminder_sound,
        "quiet_hours": reminder_quiet,
        "active": bool(state.reminder_active),
        "seconds_until_next": (None if secs_until is None
                               else int(round(secs_until))),
    }
    return {
        "version": __version__,
        "pid": os.getpid(),
        "port": port,
        "mode": state.mode,
        "queue_depth": state.queue_depth,
        "last_session_id": state.last_session_id,
        "last_action": state.last_action,
        "last_action_ts": (state.last_action_ts
                           if state.last_action is not None else None),
        "theme": state.theme_name,
        "sound_pack": state.sound_pack,
        "topmost": bool(topmost),
        "bubble_text": state.bubble_text,
        "reduce_motion": bool(state.reduce_motion),
        "volume": round(float(state.volume), 3),
        "quiet_hours": quiet_block,
        "reminder": reminder_block,
    }


def socket_listener(state, port=SOCK_PORT, host=SOCK_HOST):
    """Run the accept-loop forever, routing each incoming message
    through `dispatch_action`. Designed to run on a daemon thread.

    `status` is the only action that elicits a response — the listener
    writes the JSON snapshot back on the same connection before closing.
    Every other action is fire-and-forget.
    """
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((host, port))
    except OSError as e:
        print(f"[buddy] Cannot bind {host}:{port}: {e}")
        return
    srv.listen(5)
    srv.settimeout(1.0)
    print(f"[buddy] Listening on {host}:{port}")

    while True:
        try:
            conn, _ = srv.accept()
            try:
                conn.settimeout(2.0)
                data = conn.recv(4096)
                if data:
                    action, msg = parse_message(data)
                    print(f"[buddy] Signal: {action}")
                    dispatch_action(state, action, msg)
                    if action == ACTION_STATUS:
                        resp = build_status_response(
                            state, port=port, topmost=state.topmost)
                        try:
                            conn.sendall(
                                (json.dumps(resp) + "\n").encode("utf-8"))
                        except OSError as e:
                            print(f"[buddy] Status reply failed: {e}")
            finally:
                conn.close()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[buddy] Socket error: {e}")


def send_signal(payload, port=SOCK_PORT, host=SOCK_HOST):
    """Connect to a running buddy and send a single JSON payload.

    Returns True on success, False if no buddy is listening (so callers
    can exit with an appropriate status without inlining socket logic).
    """
    data = json.dumps(payload).encode()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host, port))
        s.sendall(data)
        s.close()
        return True
    except ConnectionRefusedError:
        return False


def request_status(port=SOCK_PORT, host=SOCK_HOST, timeout=2.0):
    """Ask the running buddy for its current state. Returns the parsed
    JSON response dict, or None if no buddy is listening or the response
    was unreadable. Callers should treat None as "no buddy".
    """
    payload = json.dumps({"action": ACTION_STATUS}).encode("utf-8")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            s.sendall(payload)
            # Server writes the JSON response then closes — read to EOF.
            chunks = []
            while True:
                buf = s.recv(4096)
                if not buf:
                    break
                chunks.append(buf)
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if not raw:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except (ConnectionRefusedError, json.JSONDecodeError, OSError):
        return None
