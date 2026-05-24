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
    <anything else> → state.trigger()   (defensive default for older clients)

The dispatch logic lives in `dispatch_action` as a pure function so it
can be tested without a real socket. `socket_listener` is the network
shell that wraps the dispatch in an accept-loop.
"""

import json
import socket

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

KNOWN_ACTIONS = frozenset({
    ACTION_CELEBRATE,
    ACTION_WAVE,
    ACTION_RAISE,
    ACTION_QUIT,
    ACTION_PROMPT_START,
    ACTION_GREET,
    ACTION_THINKING_START,
    ACTION_THINKING_END,
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
    else:
        # Defensive default: any unrecognised action celebrates. This
        # preserves backward-compat with older buddy clients that sent
        # the literal "done" or empty string for a Stop hook.
        state.trigger()
    return action in KNOWN_ACTIONS


def socket_listener(state, port=SOCK_PORT, host=SOCK_HOST):
    """Run the accept-loop forever, routing each incoming message
    through `dispatch_action`. Designed to run on a daemon thread."""
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
            finally:
                conn.close()
            if data:
                action, msg = parse_message(data)
                print(f"[buddy] Signal: {action}")
                dispatch_action(state, action, msg)
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
