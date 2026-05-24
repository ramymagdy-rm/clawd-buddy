# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Tests for the cross-platform facade.

The platform-specific impls (`_windows.py`, `_linux.py`) wrap native APIs
that we can't easily exercise in unit tests. What we *can* test is the
facade's dispatch logic: that the right impl is selected, that the
fall-through cases produce safe defaults, and that the colour-key /
bg_fill behaviour matches the platform.
"""

import sys

import pytest

from clawd_buddy import platform as plat
from clawd_buddy.constants import TKEY, WIN_H, WIN_W


# ── Facade availability ──────────────────────────────────────────────
class TestFacadeExports:
    @pytest.mark.parametrize("name", [
        "get_window_handle",
        "setup_window",
        "get_window_rect",
        "move_window",
        "raise_window",
        "get_initial_position",
        "resize_window",
        "get_bg_fill",
        "enable_startup",
        "disable_startup",
        "auto_detach",
    ])
    def test_attribute_exists(self, name):
        # The whole point of the facade is a stable API across OSes; a
        # name disappearing on one platform would be a regression.
        assert hasattr(plat, name)
        assert callable(getattr(plat, name))


# ── Implementation selection ─────────────────────────────────────────
class TestBackendSelection:
    def test_impl_is_windows_module_on_win32(self):
        if sys.platform == "win32":
            assert plat._impl.__name__.endswith("_windows")

    def test_impl_is_linux_module_on_linux(self):
        if sys.platform == "linux":
            assert plat._impl.__name__.endswith("_linux")

    def test_impl_is_none_on_other_platforms(self):
        # Sanity: the dispatcher uses sys.platform comparisons. On the
        # current OS exactly one of these must be true.
        win = sys.platform == "win32"
        linux = sys.platform == "linux"
        other = not (win or linux)
        assert (plat._impl is None) == other


# ── get_bg_fill behaves per platform ─────────────────────────────────
class TestBgFill:
    def test_windows_always_returns_TKEY(self):
        if sys.platform != "win32":
            pytest.skip("Windows-only behaviour")
        assert plat.get_bg_fill("dark") == TKEY
        assert plat.get_bg_fill("dracula") == TKEY
        # Even an unknown theme is harmless on Windows.
        assert plat.get_bg_fill("unknown") == TKEY

    def test_linux_returns_theme_bg_fill(self):
        if sys.platform != "linux":
            pytest.skip("Linux-only behaviour")
        from clawd_buddy.ui.themes import THEMES

        for name, theme in THEMES.items():
            assert plat.get_bg_fill(name) == theme["bg_fill"]

    def test_linux_falls_back_for_unknown_theme(self):
        if sys.platform != "linux":
            pytest.skip("Linux-only behaviour")
        from clawd_buddy.ui.themes import THEMES

        # Unknown theme name falls back to "dark"'s bg_fill — matches
        # the facade's defensive default.
        assert plat.get_bg_fill("no-such-theme") == THEMES["dark"]["bg_fill"]


# ── Stub paths return safe defaults ──────────────────────────────────
class TestStubFallback:
    """When the impl is None (non-Win32, non-Linux), the facade should
    still return reasonable defaults rather than raise."""

    def test_get_window_handle_returns_zero_when_no_impl(self, monkeypatch):
        monkeypatch.setattr(plat, "_impl", None)
        # Force the sys.platform-detection branches to fall through by
        # pretending we're on something exotic.
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        assert plat.get_window_handle() == 0

    def test_get_window_rect_returns_default_size(self, monkeypatch):
        monkeypatch.setattr(plat, "_impl", None)
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        assert plat.get_window_rect(handle=0) == (0, 0, WIN_W, WIN_H)

    def test_get_screen_size_has_a_fallback(self, monkeypatch):
        # Private helper, but worth confirming the fallback exists.
        monkeypatch.setattr(plat, "_impl", None)
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        assert plat._get_screen_size() == (1920, 1080)


# ── Startup helpers print rather than crash on unknown platforms ─────
class TestStartupOnUnknownPlatform:
    def test_enable_startup_unknown_platform_does_not_raise(
        self, monkeypatch, capsys,
    ):
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        plat.enable_startup()
        out = capsys.readouterr().out
        assert "not supported" in out.lower()

    def test_disable_startup_unknown_platform_does_not_raise(
        self, monkeypatch, capsys,
    ):
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        plat.disable_startup()
        out = capsys.readouterr().out
        assert "not supported" in out.lower()

    def test_auto_detach_unknown_platform_is_noop(self, monkeypatch):
        # Returns None on platforms without a meaningful fork; must not
        # raise, must not exit.
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        result = plat.auto_detach()
        assert result is None
