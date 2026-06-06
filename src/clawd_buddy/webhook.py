# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""HTTP webhook listener — the M6 generic integration surface.

A thin HTTP transport over the *existing* TCP protocol: `POST /signal`
routes its JSON body through the same `parse_message` →
`dispatch_action` pair the socket listener uses, and `GET /status`
returns the same `build_status_response` snapshot. No new action
semantics live here — anything the buddy learns to do via TCP is
instantly reachable over HTTP (GitHub Actions, n8n, IFTTT, curl).

Security posture (see the M6 design note):
  - Opt-in only — the listener exists only when `--http-port` is given.
  - Binds 127.0.0.1; this is a localhost convenience surface, not an
    internet-facing API. Users who reverse-proxy it are on their own.
  - Optional shared token (`--http-token`): when set, every request
    must carry `Authorization: Bearer <token>`.
  - The `quit` action is rejected over HTTP unless a token is
    configured — an unauthenticated curl-able kill switch is too easy
    a footgun, while the rest of the surface is merely cosmetic.

Designed to run on a daemon thread via `webhook_listener` (mirroring
`ipc.socket_listener`); tests build a server with
`create_webhook_server` so they can `shutdown()` it deterministically.
"""

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .constants import SOCK_PORT
from .ipc import (
    ACTION_QUIT,
    build_status_response,
    dispatch_action,
    parse_message,
)

# Refuse request bodies past this size. A signal payload is a small
# JSON object; anything bigger is a mistake or a memory-pressure abuse.
MAX_BODY_BYTES = 64 * 1024

WEBHOOK_HOST = "127.0.0.1"


class _WebhookServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the buddy context the handler needs.

    Attributes are set by `create_webhook_server` — the stdlib handler
    reaches them via `self.server`, which keeps the handler class free
    of globals and lets tests run several servers side by side.
    """

    # Don't linger on stuck clients when the daemon thread is told to die.
    daemon_threads = True

    state = None        # BuddyState
    token = None        # shared secret, or None
    tcp_port = SOCK_PORT  # reported in /status so it matches --status


class _WebhookHandler(BaseHTTPRequestHandler):
    # Default protocol is HTTP/1.0 which closes per request — fine for
    # fire-and-forget signals, and avoids keep-alive bookkeeping.

    def log_message(self, fmt, *args):
        # Quiet by default — the buddy's stdout is already chatty about
        # signals ("[buddy] Signal: …" from dispatch below); the stdlib
        # access-log line on top of that is noise.
        pass

    # ── helpers ─────────────────────────────────────────────────────
    def _send_json(self, code, obj):
        body = (json.dumps(obj) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        """True when no token is configured, or the request carries the
        right `Authorization: Bearer <token>` header. Constant-time
        comparison — a localhost timing oracle is a stretch, but
        compare_digest costs nothing."""
        token = self.server.token
        if token is None:
            return True
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {token}"
        return hmac.compare_digest(header, expected)

    # ── verbs ───────────────────────────────────────────────────────
    def do_GET(self):
        if self.path != "/status":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "missing or bad token"})
            return
        state = self.server.state
        resp = build_status_response(
            state, port=self.server.tcp_port, topmost=state.topmost)
        self._send_json(200, resp)

    def _read_body(self):
        """Read (and always fully drain) the request body.

        Responding before the body is consumed makes Windows abort the
        connection under the client's feet (WinError 10053) — so every
        POST reads its body up front, even on the 401/404 paths.
        Oversized bodies are drained in bounded chunks (memory stays
        capped), answered with 413, and reported as `None`.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        if length > MAX_BODY_BYTES:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self._send_json(413, {"error": "body too large"})
            return None
        return self.rfile.read(length) if length > 0 else b""

    def do_POST(self):
        raw = self._read_body()
        if raw is None:
            return  # 413 already sent
        if self.path != "/signal":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "missing or bad token"})
            return
        action, msg = parse_message(raw)
        if action == ACTION_QUIT and self.server.token is None:
            # No-token deployments get the cosmetic surface only.
            self._send_json(403, {
                "error": "quit over HTTP requires --http-token"})
            return
        print(f"[buddy] HTTP signal: {action}")
        dispatch_action(self.server.state, action, msg)
        self._send_json(200, {"ok": True, "action": action})


def create_webhook_server(state, http_port, token=None,
                          host=WEBHOOK_HOST, tcp_port=SOCK_PORT):
    """Build (but don't run) the webhook server. Raises OSError when
    the port is taken — callers decide whether that's fatal."""
    server = _WebhookServer((host, http_port), _WebhookHandler)
    server.state = state
    server.token = token
    server.tcp_port = tcp_port
    return server


def webhook_listener(state, http_port, token=None,
                     host=WEBHOOK_HOST, tcp_port=SOCK_PORT):
    """Run the webhook server forever. Designed for a daemon thread —
    mirrors `ipc.socket_listener`'s contract, including the print-and-
    return on a bind failure (an unusable webhook port must not take
    the buddy down with it)."""
    try:
        server = create_webhook_server(
            state, http_port, token=token, host=host, tcp_port=tcp_port)
    except OSError as e:
        print(f"[buddy] Cannot bind HTTP {host}:{http_port}: {e}")
        # Un-mirror so `--status` doesn't advertise a listener that
        # never came up (app.py sets the mirror optimistically before
        # spawning this thread).
        state.http_port = None
        return
    auth = "token required" if token else "no token"
    print(f"[buddy] HTTP listening on {host}:{http_port} ({auth})")
    server.serve_forever()
