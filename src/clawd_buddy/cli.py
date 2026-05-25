# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""CLI argument parsing and Claude-Code hook stdin reader.

`parse_args` takes an optional `argv` so tests can drive it without
mucking with `sys.argv`. `read_hook_stdin` is the bridge between the
Claude Code hook environment (which pipes JSON on stdin) and our CLI —
isolated here so it can be mocked in tests.
"""

import argparse
import json
import sys

from . import __version__ as APP_VERSION
from .constants import SOCK_PORT
from .ui.themes import THEMES


def read_hook_stdin(stream=None):
    """Read Claude Code's hook payload from stdin, if any.

    Claude Code passes a JSON payload (with `session_id`,
    `transcript_path`, `hook_event_name`, …) on stdin to hook commands.
    When the buddy CLI is run from a terminal stdin is a TTY, so we
    skip reading to avoid blocking.

    `stream` defaults to `sys.stdin`; tests inject an io.StringIO so
    they can exercise the JSON parsing path without monkeypatching.

    Returns a dict (empty on missing / malformed input); never raises.
    """
    if stream is None:
        stream = sys.stdin
    if stream is None:
        return {}
    # isatty isn't defined on every file-like — bytewise streams or
    # io.StringIO in older Pythons may need a hasattr guard.
    is_tty = getattr(stream, "isatty", None)
    if callable(is_tty) and is_tty():
        return {}
    try:
        data = stream.read()
    except (OSError, ValueError):
        return {}
    if not data:
        return {}
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_parser():
    """Construct the argparse.ArgumentParser. Split from parse_args so
    tests can introspect the parser (e.g. dump help text without exiting)."""
    p = argparse.ArgumentParser(
        prog="clawd-buddy",
        description="Clawd Buddy — tiny terminal pet on your taskbar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  clawd-buddy                Start buddy on taskbar\n"
            "  clawd-buddy --test         Start with a celebration\n"
            "  clawd-buddy --send Done!   Signal a running buddy\n"
            "  clawd-buddy --wave         Wave for attention\n"
            "  clawd-buddy --message 'tests green'  Show a speech bubble\n"
            "  clawd-buddy --status       Print running buddy state as JSON\n"
            "  clawd-buddy --prompt-start Greet (if new session) + start thinking\n"
            "  clawd-buddy --top          Bring buddy to front (re-assert topmost)\n"
            "  clawd-buddy --quit         Ask the running buddy to exit cleanly\n"
            "  clawd-buddy --theme dracula   Use Dracula theme\n"
            "  clawd-buddy --theme nord      Use Nord theme\n"
            "  clawd-buddy --startup      Run at login/startup\n"
            "  clawd-buddy --no-startup   Remove from login/startup\n"
        ),
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {APP_VERSION}",
                   help="Show version and exit")
    p.add_argument("--port", type=int, default=SOCK_PORT,
                   help=f"TCP port (default: {SOCK_PORT})")
    p.add_argument("--no-topmost", action="store_true",
                   help="Don't stay always-on-top")
    p.add_argument("--test", action="store_true",
                   help="Celebrate on startup")
    p.add_argument("--send", metavar="MSG", type=str,
                   help="Send celebrate signal to running buddy and exit")
    p.add_argument("--wave", action="store_true",
                   help="Send wave/attention signal to running buddy and exit")
    p.add_argument("--top", action="store_true",
                   help="Tell running buddy to re-assert always-on-top and exit")
    p.add_argument("--quit", action="store_true",
                   help="Ask running buddy to exit cleanly and exit")
    p.add_argument("--message", metavar="TEXT", default=None,
                   help=("Show a speech bubble with TEXT above the running "
                         "buddy for ~3 seconds, then exit. Replaces any "
                         "bubble currently showing. Pass an empty string "
                         "to dismiss immediately."))
    p.add_argument("--status", action="store_true",
                   help=("Print the running buddy's state as JSON (version, "
                         "pid, port, mode, queue depth, theme, sound pack, "
                         "bubble text, last action) and exit. Exit code 1 "
                         "if no buddy is listening on the port."))
    p.add_argument("--prompt-start", dest="prompt_start", action="store_true",
                   help=("Signal the start of a Claude Code prompt "
                         "(UserPromptSubmit hook). Greets on the first prompt "
                         "of a new session and starts the thinking animation. "
                         "Reads session_id from piped JSON on stdin when "
                         "available."))
    p.add_argument("--session-id", dest="session_id", default=None,
                   metavar="ID",
                   help=("Session id to associate with --prompt-start. "
                         "Overrides any session_id read from stdin. Mostly "
                         "useful for testing."))
    p.add_argument("--theme", choices=list(THEMES.keys()), default=None,
                   metavar="THEME",
                   help=("Color theme. Choices: "
                         + ", ".join(THEMES.keys())
                         + ". If omitted, the last theme you picked is "
                         "remembered (falls back to 'dark' on first run). "
                         "Change at runtime via the tray Theme submenu."))
    p.add_argument("--startup", action="store_true",
                   help="Enable run at login/startup and exit")
    p.add_argument("--no-startup", action="store_true",
                   help="Disable run at login/startup and exit")
    p.add_argument("--fg", action="store_true",
                   help="Run in foreground (default auto-detaches)")
    # M4: external acknowledgment for the water-drinking reminder.
    # Mirrors `--wave` and `--send` (fire-and-forget; exits with 0 on
    # delivery, 1 if no buddy is listening). Useful for smart-bottle
    # integrations or "drank from the kitchen tap" wrist macros.
    p.add_argument("--drank", action="store_true",
                   help=("Tell the running buddy you drank water — clears "
                         "any active reminder alarm and resets the timer."))
    return p


def parse_args(argv=None):
    """Parse the CLI. `argv` is the list of arguments excluding the
    program name; defaults to sys.argv[1:] when None — matching
    argparse's own contract."""
    return build_parser().parse_args(argv)
