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
        "center_window",
        "get_bg_fill",
        "set_dpi_awareness",
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


# ── Initial window position — the issue #1 off-screen fix ────────────
class TestInitialPositionMath:
    """`_compute_taskbar_anchored_position` is the pure geometry behind
    get_initial_position(). Testing it directly lets us feed the exact
    DPI-virtualized numbers that made the buddy vanish on scaled
    Windows 11 displays — no real display or ctypes required.
    """

    def test_normal_100pct_display_sits_above_taskbar(self):
        # 1920x1200 physical, 48px bottom taskbar (top at 1152). This is
        # the coordinate set observed on a real 100%-scaled Win11 machine.
        x, y = plat._compute_taskbar_anchored_position(
            1920, 1200, 1152, bar_valid=True)
        assert x == 1920 // 2 - WIN_W // 2
        # Just above the taskbar, overlapping it slightly (feet near bar).
        assert y == 1152 - WIN_H + 28
        # And fully on-screen.
        assert 0 <= y <= 1200 - WIN_H

    def test_dpi_virtualized_case_stays_on_screen(self):
        # The bug: a DPI-UNAWARE process on a 150%-scaled 1920x1200 panel
        # sees a virtualized 1280x800 screen but a PHYSICAL taskbar top of
        # 1152. The old formula (bar_top - WIN_H + 28 = 920) lands ~120px
        # below an 800px screen → invisible. The clamp must rescue it.
        scr_w, scr_h, phys_bar_top = 1280, 800, 1152

        old_formula_y = phys_bar_top - WIN_H + 28
        assert old_formula_y + WIN_H > scr_h  # demonstrates the regression

        x, y = plat._compute_taskbar_anchored_position(
            scr_w, scr_h, phys_bar_top, bar_valid=True)
        # Clamped fully on-screen despite the physical/logical mismatch.
        assert 0 <= y <= scr_h - WIN_H
        assert 0 <= x <= scr_w - WIN_W

    def test_invalid_taskbar_falls_back_to_screen_bottom(self):
        # SHAppBarMessage failure yields a zero rect → bar_valid False.
        x, y = plat._compute_taskbar_anchored_position(
            1920, 1080, 0, bar_valid=False)
        assert y == 1080 - WIN_H - 20
        assert 0 <= y <= 1080 - WIN_H

    def test_tiny_screen_never_goes_negative(self):
        # Absurdly short screen: clamp floors at 0 rather than off the top.
        x, y = plat._compute_taskbar_anchored_position(
            200, 100, 60, bar_valid=True)
        assert y == 0
        assert x == 0


class TestCenterWindow:
    """center_window composes get_window_rect + _get_screen_size +
    move_window. Patch those and capture the move to assert the geometry
    without touching a real display."""

    def _patch(self, monkeypatch, rect, screen):
        moved = {}
        monkeypatch.setattr(plat, "get_window_rect", lambda h: rect)
        monkeypatch.setattr(plat, "_get_screen_size", lambda: screen)
        monkeypatch.setattr(
            plat, "move_window", lambda h, x, y: moved.update(x=x, y=y))
        return moved

    def test_centers_on_screen(self, monkeypatch):
        # 200x260 window on a 1920x1200 screen → centered top-left corner.
        moved = self._patch(monkeypatch, (0, 0, WIN_W, WIN_H), (1920, 1200))
        plat.center_window(handle=1234)
        assert moved == {"x": (1920 - WIN_W) // 2, "y": (1200 - WIN_H) // 2}

    def test_uses_current_window_size_not_native(self, monkeypatch):
        # A scaled-up (Ctrl+4) window stays centered at its actual size.
        moved = self._patch(monkeypatch, (10, 10, 400, 520), (1920, 1200))
        plat.center_window(handle=1234)
        assert moved == {"x": (1920 - 400) // 2, "y": (1200 - 520) // 2}

    def test_never_negative_when_window_bigger_than_screen(self, monkeypatch):
        moved = self._patch(monkeypatch, (0, 0, 3000, 3000), (1920, 1200))
        plat.center_window(handle=1234)
        assert moved == {"x": 0, "y": 0}


class TestSetDpiAwareness:
    def test_noop_off_win32_and_linux(self, monkeypatch):
        # On unsupported platforms it must return None without raising.
        monkeypatch.setattr(plat.sys, "platform", "haiku")
        assert plat.set_dpi_awareness() is None

    def test_win32_returns_a_known_mode(self):
        if sys.platform != "win32":
            pytest.skip("Windows-only behaviour")
        # Idempotent/best-effort: either it applied one of the ladder
        # modes, or awareness was already locked in (SDL, a prior call)
        # and it returns None. Both are acceptable; it must not raise.
        result = plat.set_dpi_awareness()
        assert result in (None, "per-monitor-v2", "per-monitor", "system")

    def test_get_initial_position_on_win32_is_on_screen(self):
        if sys.platform != "win32":
            pytest.skip("Windows-only behaviour")
        # End-to-end against the real machine's metrics: whatever the
        # display scaling, the computed position must be on-screen.
        x, y = plat.get_initial_position()
        scr_w, scr_h = plat._get_screen_size()
        assert 0 <= x <= scr_w - WIN_W
        assert 0 <= y <= scr_h - WIN_H


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
