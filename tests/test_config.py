# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for persistent config.

Tests run against an isolated config directory per test (driven by
monkeypatched env vars) so they don't read or stomp on the user's real
config file at `%APPDATA%\\clawd-buddy\\` or `~/.config/clawd-buddy/`.
"""

import json
import os
import sys

import pytest

from clawd_buddy import config


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    """Point both Windows and Linux config-dir lookups at a tmp dir.

    The buddy resolves the config dir from `APPDATA` on Windows and
    `XDG_CONFIG_HOME` on Linux — patching both keeps tests platform-
    agnostic and survives running the same test on either OS.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "clawd-buddy"


# ── _config_dir / _config_path ───────────────────────────────────────
class TestPaths:
    def test_config_dir_points_inside_provided_root(self, isolated_config_dir):
        d = config._config_dir()
        assert d == str(isolated_config_dir)

    def test_config_path_is_inside_config_dir(self, isolated_config_dir):
        assert os.path.dirname(config._config_path()) == str(isolated_config_dir)
        assert os.path.basename(config._config_path()) == "config.json"

    def test_config_dir_falls_back_when_env_missing(self, monkeypatch, tmp_path):
        # No APPDATA / XDG_CONFIG_HOME — must still produce a path under
        # the user's home, not crash.
        monkeypatch.delenv("APPDATA", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        monkeypatch.setenv("HOME", str(tmp_path))
        d = config._config_dir()
        assert "clawd-buddy" in d


# ── load_config / save_config ────────────────────────────────────────
class TestLoadSave:
    def test_load_returns_empty_when_file_missing(self, isolated_config_dir):
        assert config.load_config() == {}

    def test_round_trip(self, isolated_config_dir):
        config.save_config({"theme": "dracula", "sound_pack": "chime"})
        assert config.load_config() == {
            "theme": "dracula",
            "sound_pack": "chime",
        }

    def test_load_returns_empty_on_malformed_json(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text("{not valid json")
        assert config.load_config() == {}

    def test_load_returns_empty_for_non_dict_top_level(self, isolated_config_dir):
        # A user could hand-edit and end up with a list — must not blow up.
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text("[1, 2, 3]")
        assert config.load_config() == {}

    def test_save_is_atomic_via_tmp_rename(self, isolated_config_dir):
        # We can't easily simulate a crash, but we can verify the .tmp
        # file doesn't persist after a successful save.
        config.save_config({"theme": "dark"})
        assert (isolated_config_dir / "config.json").exists()
        assert not (isolated_config_dir / "config.json.tmp").exists()

    def test_save_creates_parent_dir(self, isolated_config_dir):
        assert not isolated_config_dir.exists()
        config.save_config({"theme": "dark"})
        assert isolated_config_dir.is_dir()


# ── Theme preference ─────────────────────────────────────────────────
class TestThemePref:
    def test_load_returns_none_when_unset(self, isolated_config_dir):
        assert config.load_saved_theme() is None

    def test_load_returns_persisted_theme(self, isolated_config_dir):
        config.save_theme_pref("dracula")
        assert config.load_saved_theme() == "dracula"

    def test_load_rejects_unknown_theme(self, isolated_config_dir):
        config.save_config({"theme": "rainbow-glitter"})
        assert config.load_saved_theme() is None

    def test_save_ignores_unknown_theme(self, isolated_config_dir):
        config.save_theme_pref("rainbow-glitter")
        # File should not have been written.
        assert not (isolated_config_dir / "config.json").exists()

    def test_save_skips_write_when_unchanged(self, isolated_config_dir):
        # Detect by mtime — a no-op save should not touch the file.
        config.save_theme_pref("dracula")
        path = isolated_config_dir / "config.json"
        mtime_before = path.stat().st_mtime_ns
        # On fast filesystems mtime resolution can be coarse, so we
        # additionally check that a subsequent save with the same value
        # doesn't error and the data stays valid.
        config.save_theme_pref("dracula")
        assert path.stat().st_mtime_ns == mtime_before
        assert json.loads(path.read_text())["theme"] == "dracula"


# ── Sound-pack preference ────────────────────────────────────────────
class TestSoundPref:
    def test_default_when_unset(self, isolated_config_dir):
        assert config.load_saved_sound_pack() == "fanfare"

    def test_round_trip(self, isolated_config_dir):
        config.save_sound_pack_pref("retro")
        assert config.load_saved_sound_pack() == "retro"

    def test_save_ignores_unknown_pack(self, isolated_config_dir):
        config.save_sound_pack_pref("ultrasound")
        assert not (isolated_config_dir / "config.json").exists()

    def test_legacy_sound_false_migrates_to_off(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"sound": False}))
        assert config.load_saved_sound_pack() == "off"

    def test_legacy_sound_true_keeps_default(self, isolated_config_dir):
        # Old true → new fanfare. The reader doesn't write on its own;
        # the migration is finalised the next time `save_sound_pack_pref`
        # runs.
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"sound": True}))
        assert config.load_saved_sound_pack() == "fanfare"

    def test_new_key_wins_over_legacy(self, isolated_config_dir):
        # Both keys present (somehow) — new key takes precedence.
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"sound": False, "sound_pack": "retro"}))
        assert config.load_saved_sound_pack() == "retro"

    def test_save_strips_legacy_key(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"sound": False, "sound_pack": "chime"}))
        config.save_sound_pack_pref("retro")
        data = json.loads((isolated_config_dir / "config.json").read_text())
        assert "sound" not in data
        assert data["sound_pack"] == "retro"
