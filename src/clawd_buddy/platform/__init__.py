# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Cross-platform facade for window manipulation and OS integration.

Selects the right backend (`_windows` on Win32, `_linux` on X11, or a
stub on anything else) at import time and exposes a small API the rest
of the codebase calls. Platform-specific names (`_win_*`, `_linux_*`)
stay encapsulated inside their respective modules.

Note: this package shadows the stdlib `platform` module. Code inside
this package must NOT do a bare `import platform` (use `sys.platform`
for OS detection instead). Code outside the package can safely
`from .platform import ...` thanks to absolute imports.
"""

import sys

import pygame

from ..constants import TKEY, WIN_H, WIN_W
from ..ui.themes import THEMES


# Conditional backend import — only the module matching the current OS
# is loaded, so Win32 ctypes setup never runs on Linux and vice versa.
if sys.platform == "win32":
    from . import _windows as _impl
elif sys.platform == "linux":
    from . import _linux as _impl
else:
    _impl = None


# ── Cross-platform window API ────────────────────────────────────────
def get_window_handle():
    if sys.platform == "win32":
        return _impl._win_get_hwnd()
    if sys.platform == "linux":
        return _impl._linux_get_window_id()
    return 0


def setup_window(handle, topmost, color_key=TKEY):
    """Apply transparency (Windows) and window properties."""
    if sys.platform == "win32":
        _impl._win_make_transparent(handle, color_key)
        if topmost:
            _impl._win_set_topmost(handle, True)
    elif sys.platform == "linux":
        _impl._linux_setup_window(handle, topmost)


def get_window_rect(handle):
    if sys.platform == "win32":
        return _impl._win_get_window_rect(handle)
    if sys.platform == "linux":
        return _impl._linux_get_window_rect(handle)
    return 0, 0, WIN_W, WIN_H


def move_window(handle, x, y):
    if sys.platform == "win32":
        _impl._win_move_window(handle, x, y)
    elif sys.platform == "linux":
        _impl._linux_move_window(handle, x, y)


def _get_screen_size():
    """Return (width, height) of the primary screen — kept private since
    the only consumers are `raise_window` and `resize_window`."""
    if sys.platform == "win32":
        return _impl._win_get_screen_size()
    if sys.platform == "linux":
        info = pygame.display.Info()
        return info.current_w, info.current_h
    return 1920, 1080


def raise_window(handle):
    """Force the window above other topmost peers, snapping it back
    on-screen if it has drifted off (e.g. monitor disconnected, dragged
    out of bounds)."""
    wx, wy, ww, wh = get_window_rect(handle)
    scr_w, scr_h = _get_screen_size()
    off_screen = (wx + ww <= 0 or wy + wh <= 0
                  or wx >= scr_w or wy >= scr_h)
    if off_screen:
        nx, ny = get_initial_position()
        move_window(handle, nx, ny)

    if sys.platform == "win32":
        _impl._win_raise_topmost(handle)
    elif sys.platform == "linux":
        # Re-sending _NET_WM_STATE_ABOVE raises above other ABOVE windows
        _impl._linux_setup_window(handle, topmost=True)


def get_initial_position():
    """Return (win_x, win_y) for the buddy window."""
    if sys.platform == "win32":
        scr_w, scr_h = _impl._win_get_screen_size()
        _, tb_y, _, _ = _impl._win_get_taskbar_rect()
        return scr_w // 2 - WIN_W // 2, tb_y - WIN_H + 28
    if sys.platform == "linux":
        # Need display init for screen info
        pygame.display.init()
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
        panel_h = _impl._linux_get_panel_height(scr_h)
        return scr_w // 2 - WIN_W // 2, scr_h - panel_h - WIN_H + 28
    return 0, 0


def resize_window(handle, scale, topmost):
    """Resize the pygame window, re-apply platform setup, and clamp
    to screen."""
    new_w = int(WIN_W * scale)
    new_h = int(WIN_H * scale)
    wx, wy, _, _ = get_window_rect(handle)
    screen = pygame.display.set_mode((new_w, new_h), pygame.NOFRAME)
    handle = get_window_handle()
    setup_window(handle, topmost)
    scr_w, scr_h = _get_screen_size()
    nx = max(0, min(wx, scr_w - new_w))
    ny = max(0, min(wy, scr_h - new_h))
    move_window(handle, nx, ny)
    return screen, handle


def get_bg_fill(theme_name):
    """Background fill for the window surface each frame.

    Windows uses color-key transparency, so the background is painted
    in `TKEY` and becomes invisible. X11 has no color-key, so we paint
    the theme's `bg_fill` to blend with the panel.
    """
    if sys.platform == "win32":
        return TKEY
    theme = THEMES.get(theme_name, THEMES["dark"])
    return theme.get("bg_fill", (1, 1, 1))


# ── Cross-platform startup / process API ─────────────────────────────
def enable_startup():
    if sys.platform == "win32":
        _impl._win_enable_startup()
    elif sys.platform == "linux":
        _impl._linux_enable_startup()
    else:
        print(f"[buddy] Startup not supported on {sys.platform}")


def disable_startup():
    if sys.platform == "win32":
        _impl._win_disable_startup()
    elif sys.platform == "linux":
        _impl._linux_disable_startup()
    else:
        print(f"[buddy] Startup not supported on {sys.platform}")


def auto_detach():
    """Daemonise the current process. No-op on platforms without a
    meaningful fork (Windows handles detach via a separate subprocess
    invocation in main())."""
    if sys.platform == "linux":
        _impl._linux_auto_detach()
