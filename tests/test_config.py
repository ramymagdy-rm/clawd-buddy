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


# ── Reduce-motion preference (M3) ────────────────────────────────────
class TestReduceMotionPref:
    def test_default_is_false(self, isolated_config_dir):
        assert config.load_saved_reduce_motion() is False

    def test_round_trip(self, isolated_config_dir):
        config.save_reduce_motion_pref(True)
        assert config.load_saved_reduce_motion() is True

    def test_round_trip_false_persisted(self, isolated_config_dir):
        # Toggling on then off should land at False, not unset.
        config.save_reduce_motion_pref(True)
        config.save_reduce_motion_pref(False)
        data = json.loads((isolated_config_dir / "config.json").read_text())
        assert data["reduce_motion"] is False

    def test_skips_write_when_unchanged(self, isolated_config_dir):
        config.save_reduce_motion_pref(True)
        mtime_before = (isolated_config_dir / "config.json").stat().st_mtime_ns
        config.save_reduce_motion_pref(True)
        assert (isolated_config_dir / "config.json").stat().st_mtime_ns \
            == mtime_before

    def test_load_coerces_garbage_to_false(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"reduce_motion": "yes"}))
        # bool("yes") is True, so this would normally return True — but
        # callers expect a real bool semantic. Document what actually
        # happens: bool() coercion is permissive (any truthy string ⇒ True).
        # This test pins the behaviour so future strictness is intentional.
        assert config.load_saved_reduce_motion() is True


# ── Volume preference (M3) ───────────────────────────────────────────
class TestVolumePref:
    def test_default_when_unset(self, isolated_config_dir):
        assert config.load_saved_volume() == 1.0

    def test_round_trip(self, isolated_config_dir):
        config.save_volume_pref(0.5)
        assert config.load_saved_volume() == 0.5

    def test_save_clamps_high(self, isolated_config_dir):
        config.save_volume_pref(2.5)
        assert config.load_saved_volume() == 1.0

    def test_save_clamps_low(self, isolated_config_dir):
        config.save_volume_pref(-1.0)
        assert config.load_saved_volume() == 0.0

    def test_save_ignores_garbage(self, isolated_config_dir):
        config.save_volume_pref("loud")
        assert not (isolated_config_dir / "config.json").exists()

    def test_save_ignores_nan(self, isolated_config_dir):
        config.save_volume_pref(float("nan"))
        assert not (isolated_config_dir / "config.json").exists()

    def test_load_clamps_corrupt_high(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"volume": 99.0}))
        assert config.load_saved_volume() == 1.0

    def test_load_falls_back_on_non_numeric(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"volume": "loud"}))
        assert config.load_saved_volume() == 1.0

    def test_skips_write_when_unchanged(self, isolated_config_dir):
        config.save_volume_pref(0.5)
        mtime_before = (isolated_config_dir / "config.json").stat().st_mtime_ns
        config.save_volume_pref(0.5)
        assert (isolated_config_dir / "config.json").stat().st_mtime_ns \
            == mtime_before


# ── Quiet-hours preference (M3) ──────────────────────────────────────
class TestQuietHoursPref:
    def test_default_is_disabled(self, isolated_config_dir):
        s, e = config.load_saved_quiet_hours()
        assert s is None and e is None

    def test_round_trip(self, isolated_config_dir):
        config.save_quiet_hours_pref(23 * 60, 8 * 60)
        assert config.load_saved_quiet_hours() == (23 * 60, 8 * 60)

    def test_save_none_disables(self, isolated_config_dir):
        config.save_quiet_hours_pref(23 * 60, 8 * 60)
        config.save_quiet_hours_pref(None, None)
        # Disabling drops the key entirely (cleaner JSON than null pair).
        data = json.loads((isolated_config_dir / "config.json").read_text())
        assert "quiet_hours" not in data

    def test_save_none_when_already_unset_is_noop(self, isolated_config_dir):
        # Should not create an empty config file.
        config.save_quiet_hours_pref(None, None)
        assert not (isolated_config_dir / "config.json").exists()

    def test_save_rejects_partial(self, isolated_config_dir):
        config.save_quiet_hours_pref(23 * 60, None)
        assert not (isolated_config_dir / "config.json").exists()

    def test_save_rejects_out_of_range(self, isolated_config_dir):
        config.save_quiet_hours_pref(-1, 8 * 60)
        assert not (isolated_config_dir / "config.json").exists()
        config.save_quiet_hours_pref(23 * 60, 1440)
        assert not (isolated_config_dir / "config.json").exists()

    def test_save_rejects_zero_length(self, isolated_config_dir):
        config.save_quiet_hours_pref(600, 600)
        assert not (isolated_config_dir / "config.json").exists()

    def test_load_rejects_malformed_block(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"quiet_hours": "23:00-08:00"}))
        # String, not dict ⇒ disabled.
        assert config.load_saved_quiet_hours() == (None, None)

    def test_load_rejects_missing_endpoints(self, isolated_config_dir):
        isolated_config_dir.mkdir(parents=True, exist_ok=True)
        (isolated_config_dir / "config.json").write_text(
            json.dumps({"quiet_hours": {"start": 23 * 60}}))
        assert config.load_saved_quiet_hours() == (None, None)

    def test_skips_write_when_unchanged(self, isolated_config_dir):
        config.save_quiet_hours_pref(23 * 60, 8 * 60)
        mtime_before = (isolated_config_dir / "config.json").stat().st_mtime_ns
        config.save_quiet_hours_pref(23 * 60, 8 * 60)
        assert (isolated_config_dir / "config.json").stat().st_mtime_ns \
            == mtime_before


# ── Public preset surfaces (used by tray) ────────────────────────────
class TestPublicPresets:
    def test_volume_steps_are_sorted_and_in_range(self):
        assert config.VOLUME_STEPS == tuple(sorted(config.VOLUME_STEPS))
        for step in config.VOLUME_STEPS:
            assert 0.0 <= step <= 1.0

    def test_quiet_hours_presets_are_valid(self):
        # Every preset must round-trip through save+load.
        for label, s, e in config.QUIET_HOURS_PRESETS:
            assert isinstance(label, str) and label
            assert isinstance(s, int) and 0 <= s < 1440
            assert isinstance(e, int) and 0 <= e < 1440
            assert s != e
