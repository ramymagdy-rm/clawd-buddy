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
