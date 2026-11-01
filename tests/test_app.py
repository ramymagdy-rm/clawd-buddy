# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""The hook fast path: Claude Code runs `clawd-buddy --send` /
`--wave` / `--prompt-start` on every prompt, so importing the app
module must not drag in the GUI stack (and pygame must never print its
banner into hook output)."""

import os
import pathlib
import subprocess
import sys

SRC = str(pathlib.Path(__file__).resolve().parents[1] / "src")


def _run(code):
    env = dict(os.environ, PYTHONPATH=SRC)
    env.pop("PYGAME_HIDE_SUPPORT_PROMPT", None)
    return subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=30)


def test_importing_app_skips_gui_modules():
    out = _run(
        "import sys, clawd_buddy.app\n"
        "heavy = ('pygame', 'PIL', 'pystray', 'http.server', 'jeepney')\n"
        "print(sorted(m for m in heavy if m in sys.modules))\n")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


def test_signal_to_missing_buddy_prints_no_pygame_banner():
    out = _run(
        "import sys\n"
        "sys.argv = ['clawd-buddy', '--send', 'done', '--port', '1']\n"
        "from clawd_buddy.app import main\n"
        "main()\n")
    assert "pygame" not in out.stdout
    assert "No buddy on port 1" in out.stdout


def _signal_with_hook_stdin(flags, hook):
    """Run `clawd-buddy <flags>` as a hook would (JSON on stdin) against
    a throwaway listener; return the payload it sent."""
    import json
    import socket
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(20)
    port = srv.getsockname()[1]
    got = {}

    def accept():
        conn, _ = srv.accept()
        with conn:
            got["payload"] = json.loads(conn.recv(4096))

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    env = dict(os.environ, PYTHONPATH=SRC)
    code = ("import sys\n"
            f"sys.argv = ['clawd-buddy', *{flags!r}, '--port', '{port}']\n"
            "from clawd_buddy.app import main\n"
            "main()\n")
    out = subprocess.run([sys.executable, "-c", code], env=env,
                         input=json.dumps(hook), capture_output=True,
                         text=True, timeout=30)
    t.join(20)
    srv.close()
    assert out.returncode == 0, out.stderr
    return got["payload"]


HOOK = {"session_id": "sess-1", "cwd": "/home/u/api",
        "hook_event_name": "Stop"}


def test_stop_hook_says_which_session_stopped():
    payload = _signal_with_hook_stdin(["--send", "done"], HOOK)
    assert payload == {"action": "celebrate", "session_id": "sess-1",
                       "workspace": "api"}


def test_permission_hook_carries_the_session():
    payload = _signal_with_hook_stdin(["--wave"], HOOK)
    assert payload["action"] == "wave"
    assert payload["session_id"] == "sess-1"


def test_explicit_session_id_wins():
    payload = _signal_with_hook_stdin(
        ["--prompt-start", "--session-id", "mine"], HOOK)
    assert payload["session_id"] == "mine"


def test_message_carries_no_session():
    payload = _signal_with_hook_stdin(["--message", "hi"], HOOK)
    assert "session_id" not in payload
