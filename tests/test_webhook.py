# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for the HTTP webhook listener (M6).

Each test builds a real `ThreadingHTTPServer` on an ephemeral port via
`create_webhook_server`, runs it on a thread, and drives it with
urllib — the webhook is a transport, so the interesting coverage is
auth, routing, the quit guard, and that dispatch lands on the same
state methods the TCP listener uses.
"""

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from clawd_buddy import webhook
from clawd_buddy.state import BuddyState


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def state():
    return BuddyState(theme_name="dark", sound_pack="off",
                      clock=FakeClock())


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server_factory(state):
    """Yield a factory that builds + runs a webhook server and returns
    its base URL. Every server is shut down at teardown so tests can't
    leak threads / sockets into each other."""
    servers = []

    def _make(token=None):
        port = _free_port()
        srv = webhook.create_webhook_server(state, port, token=token,
                                            tcp_port=44556)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return f"http://127.0.0.1:{port}"

    yield _make
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _post(url, payload, token=None, raw=None):
    """POST JSON (or raw bytes) and return (status_code, parsed_body)."""
    body = raw if raw is not None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _get(url, token=None):
    req = urllib.request.Request(url, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


# ── POST /signal ─────────────────────────────────────────────────────
class TestSignal:
    def test_wave_dispatches_to_state(self, server_factory, state):
        base = server_factory()
        code, body = _post(f"{base}/signal", {"action": "wave"})
        assert code == 200
        assert body == {"ok": True, "action": "wave"}
        assert state.waving

    def test_message_carries_payload(self, server_factory, state):
        base = server_factory()
        code, _ = _post(f"{base}/signal",
                        {"action": "message", "text": "ci green"})
        assert code == 200
        assert state.bubble_text == "ci green"

    def test_pomodoro_start_over_http(self, server_factory, state):
        # M6 features compose: the webhook can drive the pomodoro.
        base = server_factory()
        code, _ = _post(f"{base}/signal", {
            "action": "pomodoro_start",
            "work_seconds": 1500, "break_seconds": 300})
        assert code == 200
        assert state.pomodoro_phase == "work"

    def test_malformed_json_falls_back_to_celebrate(self, server_factory,
                                                    state):
        # Same backward-compat contract as the TCP listener: garbage
        # parses to the celebrate default, not an error.
        base = server_factory()
        code, body = _post(f"{base}/signal", None, raw=b"{not json")
        assert code == 200
        assert body["action"] == "celebrate"
        assert state.celebrating

    def test_empty_body_celebrates(self, server_factory, state):
        base = server_factory()
        code, body = _post(f"{base}/signal", None, raw=b"")
        assert code == 200
        assert body["action"] == "celebrate"

    def test_oversized_body_rejected(self, server_factory, state):
        base = server_factory()
        blob = b"x" * (webhook.MAX_BODY_BYTES + 1)
        code, body = _post(f"{base}/signal", None, raw=blob)
        assert code == 413
        assert state.mode == "idle"  # nothing dispatched


# ── GET /status ──────────────────────────────────────────────────────
class TestStatus:
    def test_status_returns_snapshot(self, server_factory, state):
        base = server_factory()
        state.set_message("ping")
        code, body = _get(f"{base}/status")
        assert code == 200
        assert body["bubble_text"] == "ping"
        assert body["port"] == 44556  # the TCP port, for parity with --status
        assert "pomodoro" in body
        assert "http" in body

    def test_status_does_not_change_mode(self, server_factory, state):
        base = server_factory()
        _get(f"{base}/status")
        assert state.mode == "idle"


# ── Routing ──────────────────────────────────────────────────────────
class TestRouting:
    def test_unknown_path_404(self, server_factory):
        base = server_factory()
        assert _get(f"{base}/nope")[0] == 404
        assert _post(f"{base}/nope", {"action": "wave"})[0] == 404

    def test_get_signal_is_404(self, server_factory):
        # /signal is POST-only; /status is GET-only.
        base = server_factory()
        assert _get(f"{base}/signal")[0] == 404
        assert _post(f"{base}/status", {})[0] == 404


# ── Token auth ───────────────────────────────────────────────────────
class TestAuth:
    def test_no_token_required_when_unconfigured(self, server_factory):
        base = server_factory(token=None)
        assert _post(f"{base}/signal", {"action": "wave"})[0] == 200

    def test_missing_token_rejected(self, server_factory, state):
        base = server_factory(token="s3cret")
        code, _ = _post(f"{base}/signal", {"action": "wave"})
        assert code == 401
        assert not state.waving

    def test_wrong_token_rejected(self, server_factory, state):
        base = server_factory(token="s3cret")
        code, _ = _post(f"{base}/signal", {"action": "wave"},
                        token="wrong")
        assert code == 401
        assert not state.waving

    def test_correct_token_accepted(self, server_factory, state):
        base = server_factory(token="s3cret")
        code, _ = _post(f"{base}/signal", {"action": "wave"},
                        token="s3cret")
        assert code == 200
        assert state.waving

    def test_status_also_gated_by_token(self, server_factory):
        base = server_factory(token="s3cret")
        assert _get(f"{base}/status")[0] == 401
        assert _get(f"{base}/status", token="s3cret")[0] == 200


# ── Quit guard ───────────────────────────────────────────────────────
class TestQuitGuard:
    def test_quit_without_token_403(self, server_factory, state):
        # An unauthenticated curl-able kill switch is a footgun — quit
        # over HTTP requires a configured token.
        base = server_factory(token=None)
        code, body = _post(f"{base}/signal", {"action": "quit"})
        assert code == 403
        assert state.should_quit is False

    def test_quit_with_token_dispatches(self, server_factory, state):
        base = server_factory(token="s3cret")
        code, _ = _post(f"{base}/signal", {"action": "quit"},
                        token="s3cret")
        assert code == 200
        assert state.should_quit is True


# ── Listener-level behaviour ─────────────────────────────────────────
class TestListener:
    def test_bind_failure_unmirrors_and_returns(self, state):
        # Take the port first, then ask webhook_listener to bind it —
        # it must print-and-return (not raise) and clear the mirror so
        # --status doesn't advertise a dead listener.
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = blocker.getsockname()[1]
        try:
            state.http_port = port  # app.py's optimistic mirror
            webhook.webhook_listener(state, port)  # returns immediately
            assert state.http_port is None
        finally:
            blocker.close()
