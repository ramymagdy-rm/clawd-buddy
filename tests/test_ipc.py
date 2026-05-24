# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for the IPC layer (socket protocol + dispatcher + client).

The dispatcher and parser are pure functions so most coverage is
in-process. A handful of end-to-end tests bind a real socket on an
ephemeral port to confirm the listener and `send_signal` interoperate.
"""

import json
import socket
import threading
import time

import pytest

from clawd_buddy import ipc
from clawd_buddy.state import BuddyState


# ── Test helpers ─────────────────────────────────────────────────────
class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def state(clock):
    return BuddyState(theme_name="dark", sound_pack="off", clock=clock)


def _free_port():
    """Grab an OS-assigned ephemeral port — avoids collisions with the
    default 44556 that a real buddy might be using on the dev machine."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── parse_message ────────────────────────────────────────────────────
class TestParseMessage:
    def test_valid_json_returns_action_and_payload(self):
        action, msg = ipc.parse_message(b'{"action": "wave"}')
        assert action == "wave"
        assert msg == {"action": "wave"}

    def test_payload_preserves_extra_keys(self):
        action, msg = ipc.parse_message(
            b'{"action": "prompt_start", "session_id": "abc"}'
        )
        assert action == "prompt_start"
        assert msg["session_id"] == "abc"

    def test_missing_action_defaults_to_celebrate(self):
        action, _ = ipc.parse_message(b'{}')
        assert action == "celebrate"

    def test_empty_input_defaults_to_celebrate(self):
        assert ipc.parse_message(b"")[0] == "celebrate"
        assert ipc.parse_message("")[0] == "celebrate"
        assert ipc.parse_message(None)[0] == "celebrate"

    def test_malformed_json_defaults_to_celebrate(self):
        action, msg = ipc.parse_message(b"{this is not json")
        assert action == "celebrate"
        assert msg == {}

    def test_non_dict_top_level_defaults_to_celebrate(self):
        # A user sending `["wave"]` should not become a wave.
        action, msg = ipc.parse_message(b'["wave"]')
        assert action == "celebrate"
        assert msg == {}

    def test_non_string_action_defaults_to_celebrate(self):
        action, _ = ipc.parse_message(b'{"action": 42}')
        assert action == "celebrate"

    def test_accepts_str_or_bytes(self):
        assert ipc.parse_message('{"action": "wave"}')[0] == "wave"
        assert ipc.parse_message(b'{"action": "wave"}')[0] == "wave"


# ── dispatch_action ──────────────────────────────────────────────────
class TestDispatch:
    def test_celebrate(self, state):
        ipc.dispatch_action(state, "celebrate")
        assert state.celebrating

    def test_wave(self, state):
        ipc.dispatch_action(state, "wave")
        assert state.waving

    def test_raise_sets_pending_raise(self, state):
        ipc.dispatch_action(state, "raise")
        assert state._raise_requested

    def test_quit_sets_should_quit(self, state):
        ipc.dispatch_action(state, "quit")
        assert state.should_quit

    def test_prompt_start_with_session_id(self, state):
        ipc.dispatch_action(
            state, "prompt_start", {"session_id": "abc-123"})
        assert state.greeting
        assert state.last_session_id == "abc-123"

    def test_greet_with_session_id(self, state):
        ipc.dispatch_action(state, "greet", {"session_id": "x"})
        assert state.greeting

    def test_thinking_start(self, state):
        ipc.dispatch_action(state, "thinking_start")
        assert state.thinking

    def test_thinking_end_from_thinking(self, state):
        state.start_thinking()
        ipc.dispatch_action(state, "thinking_end")
        assert state.mode == "idle"

    def test_unknown_action_falls_through_to_celebrate(self, state):
        ipc.dispatch_action(state, "no-such-action")
        assert state.celebrating

    def test_return_value_known_vs_unknown(self, state):
        assert ipc.dispatch_action(state, "wave") is True
        assert ipc.dispatch_action(state, "celebrate") is True
        assert ipc.dispatch_action(state, "frobnicate") is False

    def test_known_actions_set_is_complete(self):
        # Sanity: every action name dispatch_action specifically handles
        # must also be listed in KNOWN_ACTIONS so the True/False return
        # value matches reality.
        assert ipc.KNOWN_ACTIONS == {
            "celebrate", "wave", "raise", "quit",
            "prompt_start", "greet", "thinking_start", "thinking_end",
        }


# ── send_signal client ───────────────────────────────────────────────
class TestSendSignal:
    def test_connection_refused_returns_false(self):
        # No listener on this port → ConnectionRefusedError.
        port = _free_port()
        assert ipc.send_signal({"action": "wave"}, port=port) is False

    def test_round_trip_with_listener(self, state):
        """End-to-end: spin up the listener on a private port, send a
        signal, confirm the state changed."""
        port = _free_port()
        thread = threading.Thread(
            target=ipc.socket_listener,
            args=(state,),
            kwargs={"port": port},
            daemon=True,
        )
        thread.start()
        # Listener needs a moment to bind. We don't have a notification
        # hook; loop until accept is ready by trying a connect with a
        # short timeout.
        for _ in range(50):
            try:
                with socket.socket() as probe:
                    probe.settimeout(0.05)
                    probe.connect(("127.0.0.1", port))
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.02)
        ok = ipc.send_signal({"action": "wave"}, port=port)
        assert ok is True
        # Give the listener thread a moment to process the recv.
        for _ in range(50):
            if state.waving:
                break
            time.sleep(0.02)
        assert state.waving
