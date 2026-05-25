# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Smoke tests for the About-dialog and system-tray modules.

Both modules sit behind UI toolkits (tkinter / pystray) that we don't
want to actually drive in a unit test. The tests below cover the
testable surface: the procedurally-drawn icon, the tray log path,
and the import surface (no name has gone missing).
"""

import sys

import pytest

from clawd_buddy.config import (
    REMINDER_INTERVALS,
    REMINDER_INTERVAL_LABELS,
)
from clawd_buddy.ui import about, tray


# ── Buddy icon (shared between tray + About) ─────────────────────────
class TestBuddyIcon:
    def test_icon_returns_a_PIL_image(self):
        img = about._make_buddy_icon_image()
        # Don't import PIL here — duck-type on the attributes the icon
        # actually exposes to its consumers.
        assert img.size == (64, 64)
        assert img.mode == "RGBA"

    def test_icon_is_not_blank(self):
        img = about._make_buddy_icon_image()
        # If the procedural draw failed, every pixel would be fully
        # transparent. Sample a known body pixel — the body is the
        # rounded rect at (12,14)→(52,46), centre roughly (32, 30).
        px = img.getpixel((32, 30))
        assert px[3] > 0, "expected non-transparent body pixel"


# ── About dialog reentrancy guard ────────────────────────────────────
class TestAboutReentrancy:
    def test_show_about_does_not_spawn_a_second_thread(self, monkeypatch):
        # Force the open flag to True so the first guard kicks in. The
        # function should return without trying to spawn a thread.
        monkeypatch.setattr(about, "_ABOUT_DIALOG_OPEN", True)
        spawned = []

        class FakeThread:
            def __init__(self, *a, **kw):
                spawned.append((a, kw))

            def start(self):
                spawned.append("started")

        monkeypatch.setattr(about.threading, "Thread", FakeThread)
        about.show_about_dialog()
        assert spawned == []


# ── Tray log path ────────────────────────────────────────────────────
class TestTrayLogPath:
    def test_windows_uses_temp(self, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        monkeypatch.setenv("TEMP", r"C:\Tmp")
        monkeypatch.delenv("TMP", raising=False)
        assert tray._tray_log_path() == r"C:\Tmp\clawd-buddy-tray.log"

    def test_windows_falls_back_to_TMP(self, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        monkeypatch.delenv("TEMP", raising=False)
        monkeypatch.setenv("TMP", r"D:\AltTmp")
        assert tray._tray_log_path() == r"D:\AltTmp\clawd-buddy-tray.log"

    def test_windows_final_fallback_to_cwd(self, monkeypatch):
        monkeypatch.setattr(tray.sys, "platform", "win32")
        monkeypatch.delenv("TEMP", raising=False)
        monkeypatch.delenv("TMP", raising=False)
        # Should still produce a string with the expected filename.
        assert tray._tray_log_path().endswith("clawd-buddy-tray.log")

    def test_non_windows_uses_tmp(self, monkeypatch):
        # os.path.join on Windows still uses backslashes regardless of
        # the patched sys.platform, so test the components, not a
        # platform-specific literal string.
        monkeypatch.setattr(tray.sys, "platform", "linux")
        result = tray._tray_log_path()
        assert "/tmp" in result.replace("\\", "/")
        assert result.endswith("clawd-buddy-tray.log")


# ── Reminder interval combobox helpers ───────────────────────────────
class TestIntervalLabelHelpers:
    """The Reminders tab presents the interval as a Combobox now (same
    affordance as quiet hours). Two tiny pure helpers convert between
    the preset seconds value and the human label — round-trippable, with
    a documented fallback for off-preset input."""

    def test_label_for_every_preset_round_trips(self):
        # Every preset second value round-trips through the label
        # helpers. If this breaks, the combobox cannot reflect the
        # user's persisted selection on next launch.
        for sec in REMINDER_INTERVALS:
            label = about._interval_label_for(sec)
            assert about._interval_from_label(label) == sec

    def test_label_for_unknown_seconds_falls_back_to_one_hour(self):
        # A hand-edited config that drifted out of range still shows
        # *something* selected rather than rendering blank.
        assert (about._interval_label_for(12345)
                == REMINDER_INTERVAL_LABELS[60 * 60])

    def test_from_label_unknown_returns_none(self):
        # Garbage label ⇒ None, so the combobox handler snaps back to
        # the previous valid value rather than persisting it.
        assert about._interval_from_label("Every never") is None
        assert about._interval_from_label("") is None

    def test_interval_options_cover_every_preset_in_order(self):
        # The scroll list must match `REMINDER_INTERVALS` in build order
        # so the user scrolls from shortest to longest.
        assert about._INTERVAL_LABEL_OPTIONS == [
            REMINDER_INTERVAL_LABELS[s] for s in REMINDER_INTERVALS
        ]


# ── Pygame window icon surface ───────────────────────────────────────
class TestBuddyIconSurface:
    """`make_buddy_icon_surface` brands the pygame main-window taskbar
    icon with the buddy silhouette instead of the default Python
    feather. The surface is built from the same PIL icon — the test
    confirms shape parity and that it's not a blank surface."""

    def test_surface_is_64x64(self):
        try:
            import pygame
        except ImportError:
            pytest.skip("pygame not installed")
        pygame.init()
        try:
            surf = about.make_buddy_icon_surface()
            assert surf.get_size() == (64, 64)
        finally:
            pygame.quit()

    def test_surface_has_a_visible_body_pixel(self):
        try:
            import pygame
        except ImportError:
            pytest.skip("pygame not installed")
        pygame.init()
        try:
            surf = about.make_buddy_icon_surface()
            # The body is the rounded rect roughly centred at (32, 30);
            # if the procedural draw ever silently produced an empty
            # surface, every pixel would be fully transparent.
            r, g, b, a = surf.get_at((32, 30))
            assert a > 0, "expected non-transparent body pixel"
        finally:
            pygame.quit()


# ── Module surface stability ─────────────────────────────────────────
class TestExportSurface:
    @pytest.mark.parametrize("name", [
        "_make_buddy_icon_image",
        "make_buddy_icon_surface",
        "show_about_dialog",
        "_run_about_dialog",
        "_REPO_URL",
        "_interval_label_for",
        "_interval_from_label",
        "_INTERVAL_LABEL_OPTIONS",
    ])
    def test_about_module_exports(self, name):
        assert hasattr(about, name)

    @pytest.mark.parametrize("name", [
        "create_tray",
        "_create_tray_impl",
        "_tray_log_path",
    ])
    def test_tray_module_exports(self, name):
        assert hasattr(tray, name)
