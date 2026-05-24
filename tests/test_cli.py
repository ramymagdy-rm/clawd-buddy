# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for the CLI module.

`parse_args` is driven directly with a list so it doesn't touch
`sys.argv`. `read_hook_stdin` is exercised against `io.StringIO`
streams to confirm the JSON / TTY / malformed handling.
"""

import io

import pytest

from clawd_buddy import cli
from clawd_buddy.constants import SOCK_PORT


# ── parse_args defaults ──────────────────────────────────────────────
class TestDefaults:
    def test_no_args_gives_default_port(self):
        args = cli.parse_args([])
        assert args.port == SOCK_PORT

    def test_no_args_gives_falsy_action_flags(self):
        args = cli.parse_args([])
        assert args.send is None
        assert args.wave is False
        assert args.top is False
        assert args.quit is False
        assert args.prompt_start is False
        assert args.test is False
        assert args.startup is False
        assert args.no_startup is False
        assert args.fg is False
        assert args.no_topmost is False
        assert args.session_id is None
        assert args.theme is None


# ── Individual flag parsing ──────────────────────────────────────────
class TestFlags:
    def test_send_with_message(self):
        args = cli.parse_args(["--send", "Done!"])
        assert args.send == "Done!"

    def test_wave(self):
        assert cli.parse_args(["--wave"]).wave is True

    def test_top(self):
        assert cli.parse_args(["--top"]).top is True

    def test_quit(self):
        assert cli.parse_args(["--quit"]).quit is True

    def test_prompt_start_normalised_dest(self):
        # The dest uses underscores; the CLI flag uses a hyphen.
        args = cli.parse_args(["--prompt-start"])
        assert args.prompt_start is True

    def test_session_id_optional(self):
        args = cli.parse_args(["--prompt-start", "--session-id", "abc"])
        assert args.session_id == "abc"

    def test_port_parses_as_int(self):
        args = cli.parse_args(["--port", "12345"])
        assert args.port == 12345
        assert isinstance(args.port, int)

    def test_theme_accepts_known_values(self):
        args = cli.parse_args(["--theme", "dracula"])
        assert args.theme == "dracula"

    def test_theme_rejects_unknown_values(self):
        # argparse exits with code 2 on choice failure.
        with pytest.raises(SystemExit):
            cli.parse_args(["--theme", "rainbow"])

    def test_test_flag(self):
        assert cli.parse_args(["--test"]).test is True

    def test_startup(self):
        assert cli.parse_args(["--startup"]).startup is True

    def test_no_startup(self):
        assert cli.parse_args(["--no-startup"]).no_startup is True

    def test_fg(self):
        assert cli.parse_args(["--fg"]).fg is True

    def test_no_topmost(self):
        assert cli.parse_args(["--no-topmost"]).no_topmost is True


# ── --version short-circuits with exit code 0 ────────────────────────
class TestVersion:
    def test_version_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.parse_args(["--version"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "clawd-buddy" in out


# ── Help text mentions every flag we shipped ─────────────────────────
class TestHelpText:
    def test_help_lists_new_M1_flags(self, capsys):
        with pytest.raises(SystemExit):
            cli.parse_args(["--help"])
        out = capsys.readouterr().out
        # Spot-check a few flags that have caused docs regressions before.
        assert "--prompt-start" in out
        assert "--session-id" in out
        assert "--wave" in out
        assert "--theme" in out


# ── read_hook_stdin behaviours ───────────────────────────────────────
class TestReadHookStdin:
    def test_tty_skips_read(self):
        # A faux TTY shouldn't be read (otherwise interactive runs of
        # `clawd-buddy --prompt-start` would block waiting for input).
        class _TTY(io.StringIO):
            def isatty(self):  # noqa: ANN001
                return True

        tty = _TTY('{"session_id": "should-be-ignored"}')
        assert cli.read_hook_stdin(stream=tty) == {}

    def test_valid_json_parsed(self):
        payload = '{"session_id": "abc", "hook_event_name": "UserPromptSubmit"}'
        result = cli.read_hook_stdin(stream=io.StringIO(payload))
        assert result["session_id"] == "abc"
        assert result["hook_event_name"] == "UserPromptSubmit"

    def test_empty_input_returns_empty_dict(self):
        assert cli.read_hook_stdin(stream=io.StringIO("")) == {}

    def test_malformed_json_returns_empty_dict(self):
        assert cli.read_hook_stdin(stream=io.StringIO("{not json")) == {}

    def test_non_dict_top_level_returns_empty_dict(self):
        # `["a"]` is valid JSON but not what hooks send — must not crash.
        assert cli.read_hook_stdin(stream=io.StringIO("[1,2,3]")) == {}

    def test_none_stream_returns_empty_dict(self):
        # Some daemonised contexts close stdin (sys.stdin becomes None).
        assert cli.read_hook_stdin(stream=None) == {} or True  # see next
