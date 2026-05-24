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


# ── Module surface stability ─────────────────────────────────────────
class TestExportSurface:
    @pytest.mark.parametrize("name", [
        "_make_buddy_icon_image",
        "show_about_dialog",
        "_run_about_dialog",
        "_REPO_URL",
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
