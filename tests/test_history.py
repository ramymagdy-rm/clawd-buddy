# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for the drinking-history persistence layer (M4.1).

`history.load_history` / `history.save_history` round-trip a tiny
schema to `~/.clawd-buddy/history.json`. Tests redirect the HOME
env var so the writer never touches the real user dir, and exercise
the validation + atomic-write contracts.
"""

import json
import os

import pytest

from clawd_buddy import history


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point HOME / USERPROFILE at a tmp dir so `os.path.expanduser`
    resolves there. Avoids stomping on the real ~/.clawd-buddy/."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    return tmp_path / ".clawd-buddy"


# ── Path resolution ──────────────────────────────────────────────────
class TestPaths:
    def test_history_dir_is_dot_clawd_buddy_under_home(self, isolated_home):
        d = history._history_dir()
        # Resolve both sides — the tmp_path comes back with a long-form
        # path on Windows that expanduser would also have normalised.
        assert os.path.normcase(os.path.realpath(d)) == \
            os.path.normcase(os.path.realpath(str(isolated_home)))

    def test_history_path_is_history_json(self, isolated_home):
        assert os.path.basename(history._history_path()) == "history.json"
        assert os.path.dirname(history._history_path()) == history._history_dir()


# ── load_history ─────────────────────────────────────────────────────
class TestLoad:
    def test_returns_none_today_empty_recent_when_file_missing(self, isolated_home):
        today, recent = history.load_history()
        assert today is None
        assert recent == []

    def test_round_trip_today_only(self, isolated_home):
        history.save_history({"date": "2026-05-25", "count": 3}, [])
        today, recent = history.load_history()
        assert today == {"date": "2026-05-25", "count": 3}
        assert recent == []

    def test_round_trip_with_recent(self, isolated_home):
        recent = [
            {"date": "2026-05-24", "count": 6},
            {"date": "2026-05-23", "count": 5},
        ]
        history.save_history({"date": "2026-05-25", "count": 3}, recent)
        today, loaded = history.load_history()
        assert today == {"date": "2026-05-25", "count": 3}
        assert loaded == recent

    def test_handles_missing_today_key(self, isolated_home):
        # User had no in-progress day — write only `recent`.
        history.save_history(None, [{"date": "2026-05-24", "count": 6}])
        today, recent = history.load_history()
        assert today is None
        assert recent == [{"date": "2026-05-24", "count": 6}]

    def test_corrupt_json_returns_defaults(self, isolated_home):
        isolated_home.mkdir(parents=True, exist_ok=True)
        (isolated_home / "history.json").write_text("{not valid json")
        today, recent = history.load_history()
        assert today is None
        assert recent == []

    def test_non_dict_top_level_returns_defaults(self, isolated_home):
        isolated_home.mkdir(parents=True, exist_ok=True)
        (isolated_home / "history.json").write_text("[1, 2, 3]")
        today, recent = history.load_history()
        assert today is None
        assert recent == []

    def test_drops_malformed_entries_from_recent(self, isolated_home):
        # Hand-craft a file with a mix of valid + garbage entries.
        isolated_home.mkdir(parents=True, exist_ok=True)
        (isolated_home / "history.json").write_text(json.dumps({
            "today": {"date": "2026-05-25", "count": 3},
            "recent": [
                {"date": "2026-05-24", "count": 6},          # valid
                {"date": "bogus", "count": 5},               # bad date
                {"date": "2026-05-23", "count": -1},         # negative
                "not an entry",                              # wrong type
                {"date": "2026-05-22", "count": 4},          # valid
                {"date": "2026-05-21"},                      # missing count
            ],
        }))
        _, recent = history.load_history()
        assert recent == [
            {"date": "2026-05-24", "count": 6},
            {"date": "2026-05-22", "count": 4},
        ]

    def test_drops_malformed_today(self, isolated_home):
        isolated_home.mkdir(parents=True, exist_ok=True)
        (isolated_home / "history.json").write_text(json.dumps({
            "today": {"date": "bogus", "count": 3},
            "recent": [],
        }))
        today, _ = history.load_history()
        assert today is None

    def test_trims_recent_to_cap_on_load(self, isolated_home):
        # File holds more than RECENT_DAYS_MAX entries (e.g. an older
        # build with a bigger cap, or hand-edit). Reader must trim.
        oversized = [{"date": f"2026-04-{d:02d}", "count": d}
                     for d in range(1, history.RECENT_DAYS_MAX + 5)]
        isolated_home.mkdir(parents=True, exist_ok=True)
        (isolated_home / "history.json").write_text(json.dumps({
            "today": None,
            "recent": oversized,
        }))
        _, recent = history.load_history()
        assert len(recent) == history.RECENT_DAYS_MAX


# ── save_history ─────────────────────────────────────────────────────
class TestSave:
    def test_creates_parent_dir_on_first_write(self, isolated_home):
        assert not isolated_home.exists()
        history.save_history({"date": "2026-05-25", "count": 1}, [])
        assert isolated_home.is_dir()
        assert (isolated_home / "history.json").exists()

    def test_atomic_via_tmp_rename(self, isolated_home):
        history.save_history({"date": "2026-05-25", "count": 1}, [])
        # No leftover .tmp after a successful save.
        assert not (isolated_home / "history.json.tmp").exists()

    def test_save_drops_malformed_recent_entries(self, isolated_home):
        history.save_history(
            {"date": "2026-05-25", "count": 3},
            [
                {"date": "2026-05-24", "count": 6},
                {"date": "bogus", "count": 5},       # dropped
                {"date": "2026-05-23", "count": 4},
            ],
        )
        _, recent = history.load_history()
        assert recent == [
            {"date": "2026-05-24", "count": 6},
            {"date": "2026-05-23", "count": 4},
        ]

    def test_save_omits_today_when_none(self, isolated_home):
        history.save_history(None, [{"date": "2026-05-24", "count": 6}])
        data = json.loads((isolated_home / "history.json").read_text())
        # `today` key should be absent (not stored as null).
        assert "today" not in data
        assert data["recent"] == [{"date": "2026-05-24", "count": 6}]

    def test_save_trims_recent_to_cap(self, isolated_home):
        oversized = [{"date": f"2026-04-{d:02d}", "count": d}
                     for d in range(1, history.RECENT_DAYS_MAX + 5)]
        history.save_history(None, oversized)
        data = json.loads((isolated_home / "history.json").read_text())
        assert len(data["recent"]) == history.RECENT_DAYS_MAX

    def test_save_drops_negative_today_count(self, isolated_home):
        # Garbage in (somehow): negative count must not be persisted.
        history.save_history({"date": "2026-05-25", "count": -3}, [])
        today, _ = history.load_history()
        assert today is None


# ── _validate_entry / _is_iso_date (pure helpers) ────────────────────
class TestValidator:
    def test_accepts_clean_entry(self):
        assert history._validate_entry({"date": "2026-05-25", "count": 3}) == \
            {"date": "2026-05-25", "count": 3}

    def test_rejects_non_dict(self):
        assert history._validate_entry("2026-05-25") is None
        assert history._validate_entry(None) is None
        assert history._validate_entry(42) is None

    def test_rejects_missing_keys(self):
        assert history._validate_entry({"date": "2026-05-25"}) is None
        assert history._validate_entry({"count": 3}) is None

    def test_rejects_bool_count(self):
        # `isinstance(True, int)` is True in Python; we explicitly
        # reject bool-as-count.
        assert history._validate_entry(
            {"date": "2026-05-25", "count": True}) is None

    def test_rejects_negative_count(self):
        assert history._validate_entry(
            {"date": "2026-05-25", "count": -1}) is None

    def test_rejects_float_count(self):
        assert history._validate_entry(
            {"date": "2026-05-25", "count": 3.0}) is None


class TestIsIsoDate:
    @pytest.mark.parametrize("ok", [
        "2026-05-25", "0000-01-01", "9999-12-31", "2024-02-29",
    ])
    def test_accepts_well_formed(self, ok):
        assert history._is_iso_date(ok) is True

    @pytest.mark.parametrize("bad", [
        "", "2026/05/25", "2026-5-25", "2026-13-01", "2026-00-01",
        "2026-05-32", "2026-05-00", "abcd-ef-gh", "26-05-25",
    ])
    def test_rejects_malformed(self, bad):
        assert history._is_iso_date(bad) is False
