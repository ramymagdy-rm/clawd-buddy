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


class FakeNowMin:
    def __init__(self, minute=8 * 60):
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
    return FakeNowMin(minute=8 * 60)


@pytest.fixture
def state(clock, now_min):
    return BuddyState(theme_name="dark", sound_pack="off", clock=clock,
                      now_min_fn=now_min)


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
            "message", "status", "drank",
        }

    def test_message_sets_bubble_text(self, state):
        ipc.dispatch_action(state, "message", {"text": "hello"})
        assert state.bubble_text == "hello"

    def test_message_missing_text_clears_bubble(self, state):
        state.set_message("prior")
        ipc.dispatch_action(state, "message", {})
        assert state.bubble_text == ""

    def test_status_does_not_mutate_state(self, state):
        # The listener handles the response; dispatch_action is a no-op
        # on state for status — but it still records the action.
        state.trigger()  # something distinctive to confirm we don't reset
        mode_before = state.mode
        ipc.dispatch_action(state, "status")
        assert state.mode == mode_before

    def test_known_action_records_last_action(self, state):
        ipc.dispatch_action(state, "wave")
        assert state.last_action == "wave"

    def test_unknown_action_records_celebrate(self, state):
        # Unknown actions fall through to celebrate per dispatch_action's
        # backward-compat contract; last_action should reflect that, not
        # the misspelled token.
        ipc.dispatch_action(state, "frobnicate")
        assert state.last_action == "celebrate"


# ── build_status_response ────────────────────────────────────────────
class TestStatusResponse:
    def test_shape(self, state):
        resp = ipc.build_status_response(state, port=12345, topmost=True)
        # Spot-check every documented field — a field disappearing would
        # be a silent breaking change for any script consuming --status.
        for key in (
            "version", "pid", "port", "mode", "queue_depth",
            "last_session_id", "last_action", "last_action_ts",
            "theme", "sound_pack", "topmost", "bubble_text",
            "reduce_motion", "volume", "quiet_hours",
        ):
            assert key in resp, f"missing field: {key}"

    def test_port_is_passed_through(self, state):
        resp = ipc.build_status_response(state, port=44556)
        assert resp["port"] == 44556

    def test_topmost_is_passed_through(self, state):
        resp_on = ipc.build_status_response(state, topmost=True)
        resp_off = ipc.build_status_response(state, topmost=False)
        assert resp_on["topmost"] is True
        assert resp_off["topmost"] is False

    def test_reflects_state_mutations(self, state):
        state.trigger()
        state.set_message("ping")
        ipc.dispatch_action(state, "wave")  # so last_action != None
        resp = ipc.build_status_response(state)
        assert resp["mode"] in ("celebrating", "waving")  # depends on preempt
        assert resp["bubble_text"] == "ping"
        assert resp["last_action"] == "wave"
        assert resp["last_action_ts"] is not None

    def test_last_action_ts_is_none_when_no_action_yet(self, state):
        resp = ipc.build_status_response(state)
        assert resp["last_action"] is None
        assert resp["last_action_ts"] is None

    def test_response_is_json_serialisable(self, state):
        # If something non-JSON sneaks into the response (e.g. a set or
        # a tuple from a future addition), --status would crash the
        # client. Catch that here.
        resp = ipc.build_status_response(state)
        json.dumps(resp)  # raises if not serialisable

    # ── M3 fields ──────────────────────────────────────────────────
    def test_reduce_motion_default_false(self, state):
        resp = ipc.build_status_response(state)
        assert resp["reduce_motion"] is False

    def test_reduce_motion_reflects_state(self, state):
        state.set_reduce_motion(True)
        resp = ipc.build_status_response(state)
        assert resp["reduce_motion"] is True

    def test_volume_default_full(self, state):
        resp = ipc.build_status_response(state)
        assert resp["volume"] == 1.0

    def test_volume_reflects_state(self, state):
        state.set_volume(0.5)
        resp = ipc.build_status_response(state)
        assert resp["volume"] == 0.5

    def test_quiet_hours_default_null(self, state):
        resp = ipc.build_status_response(state)
        assert resp["quiet_hours"] is None

    def test_quiet_hours_formatted_as_hhmm(self, state):
        state.set_quiet_hours(23 * 60, 8 * 60)
        resp = ipc.build_status_response(state)
        assert resp["quiet_hours"] == {"start": "23:00", "end": "08:00"}

    def test_quiet_hours_handles_midnight(self, state):
        state.set_quiet_hours(0, 9 * 60)
        resp = ipc.build_status_response(state)
        assert resp["quiet_hours"] == {"start": "00:00", "end": "09:00"}


class TestFormatHHMM:
    """The minutes-to-HH:MM helper is small but used in every --status
    response — pin its boundary behaviour."""

    def test_basic(self):
        assert ipc._format_hhmm(0) == "00:00"
        assert ipc._format_hhmm(60) == "01:00"
        assert ipc._format_hhmm(23 * 60 + 59) == "23:59"

    def test_pads_single_digit(self):
        assert ipc._format_hhmm(8 * 60) == "08:00"
        assert ipc._format_hhmm(65) == "01:05"

    def test_rejects_out_of_range(self):
        assert ipc._format_hhmm(-1) is None
        assert ipc._format_hhmm(1440) is None

    def test_rejects_non_int(self):
        assert ipc._format_hhmm("23:00") is None
        assert ipc._format_hhmm(60.0) is None
        assert ipc._format_hhmm(None) is None


# ── Drank action + reminder status block (M4) ────────────────────────
class TestDrankAction:
    def test_drank_acknowledges_reminder(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        assert state.reminder_active is True
        ipc.dispatch_action(state, "drank")
        assert state.reminder_active is False

    def test_drank_does_not_shift_schedule(self, state, now_min):
        # M4.3: drinking ack only dismisses; the next slot still fires.
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        ipc.dispatch_action(state, "drank")
        # Countdown points at the next slot (10:00), not "interval from now".
        assert state.reminder_seconds_until_next() == 60 * 60

    def test_drank_records_last_action(self, state):
        ipc.dispatch_action(state, "drank")
        assert state.last_action == "drank"

    def test_drank_returns_true(self, state):
        assert ipc.dispatch_action(state, "drank") is True


class TestStatusReminderBlock:
    def test_reminder_block_shape(self, state):
        resp = ipc.build_status_response(state)
        assert "reminder" in resp
        block = resp["reminder"]
        # `anchor` joined the block in M4.3; `cups_today`, `today_date`,
        # `recent_days` in M4.1.
        for key in ("enabled", "interval_seconds", "anchor", "sound",
                    "quiet_hours", "active", "seconds_until_next",
                    "cups_today", "today_date", "recent_days"):
            assert key in block

    def test_reminder_block_disabled_defaults(self, state):
        resp = ipc.build_status_response(state)
        block = resp["reminder"]
        assert block["enabled"] is False
        assert block["interval_seconds"] == 60 * 60
        assert block["anchor"] == "08:00"  # M4.3 default
        assert block["sound"] == "water"
        # Default quiet hours are 23:00–08:00.
        assert block["quiet_hours"] == {"start": "23:00", "end": "08:00"}
        assert block["active"] is False
        assert block["seconds_until_next"] is None  # disabled ⇒ None

    def test_reminder_quiet_hours_null_when_disabled(self, state):
        state.set_reminder_quiet_hours(None, None)
        block = ipc.build_status_response(state)["reminder"]
        assert block["quiet_hours"] is None

    def test_reminder_block_when_enabled(self, state, clock):
        state.set_reminder_quiet_hours(None, None)
        state.set_reminder_enabled(True)
        block = ipc.build_status_response(state)["reminder"]
        assert block["enabled"] is True
        # Just-enabled: seconds-until-next ≈ full interval, definitely
        # not None.
        assert isinstance(block["seconds_until_next"], int)
        assert block["seconds_until_next"] > 0

    def test_reminder_block_when_active(self, state, now_min):
        state.set_reminder_quiet_hours(None, None)
        now_min.set(7 * 60 + 30)
        state.set_reminder_enabled(True)
        now_min.set(9 * 60)
        state.update()
        block = ipc.build_status_response(state)["reminder"]
        assert block["active"] is True
        assert block["seconds_until_next"] == 0

    def test_history_defaults_in_status(self, state):
        block = ipc.build_status_response(state)["reminder"]
        assert block["cups_today"] == 0
        assert block["today_date"] is None
        assert block["recent_days"] == []

    def test_history_reflects_drink_ack(self, state):
        state.drink_acknowledged()
        state.drink_acknowledged()
        block = ipc.build_status_response(state)["reminder"]
        assert block["cups_today"] == 2
        assert isinstance(block["today_date"], str)
        assert len(block["today_date"]) == 10  # YYYY-MM-DD

    def test_history_recent_days_in_status(self, state):
        state.recent_days = [{"date": "2026-05-24", "count": 6}]
        block = ipc.build_status_response(state)["reminder"]
        assert block["recent_days"] == [{"date": "2026-05-24", "count": 6}]

    def test_history_recent_days_is_defensive_copy(self, state):
        state.recent_days = [{"date": "2026-05-24", "count": 6}]
        block = ipc.build_status_response(state)["reminder"]
        block["recent_days"].append({"date": "BAD", "count": 99})
        assert state.recent_days == [{"date": "2026-05-24", "count": 6}]

    def test_status_response_with_reminder_is_json_serialisable(self, state):
        state.set_reminder_enabled(True)
        resp = ipc.build_status_response(state)
        json.dumps(resp)


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


# ── request_status client ────────────────────────────────────────────
class TestRequestStatus:
    def test_no_buddy_returns_none(self):
        port = _free_port()
        assert ipc.request_status(port=port, timeout=0.5) is None

    def test_round_trip_returns_status_dict(self, state):
        port = _free_port()
        thread = threading.Thread(
            target=ipc.socket_listener,
            args=(state,),
            kwargs={"port": port},
            daemon=True,
        )
        thread.start()
        # Wait for bind, same probe trick as test_round_trip_with_listener.
        for _ in range(50):
            try:
                with socket.socket() as probe:
                    probe.settimeout(0.05)
                    probe.connect(("127.0.0.1", port))
                break
            except (ConnectionRefusedError, OSError):
                time.sleep(0.02)
        # Put some recognisable state on the buddy first.
        state.set_message("ping")
        info = ipc.request_status(port=port, timeout=2.0)
        assert info is not None
        assert info["port"] == port
        assert info["bubble_text"] == "ping"
        assert info["mode"] in ("idle", "celebrating", "waving", "greeting",
                                "thinking")
