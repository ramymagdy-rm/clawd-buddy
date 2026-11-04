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
from ..placement import area_at, clamp_into, overlaps_any
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
    the only consumers are `raise_window`, `center_window` and
    `resize_window`."""
    if sys.platform == "win32":
        return _impl._win_get_screen_size()
    if sys.platform == "linux":
        # Not pygame.display.Info(): once a window exists, its current_w
        # / current_h are the *window's* size, which sent every resize,
        # Center on Screen and Bring to Front to the top-left corner.
        try:
            sizes = pygame.display.get_desktop_sizes()
        except pygame.error:
            sizes = []
        if sizes:
            return sizes[0]
        info = pygame.display.Info()
        return info.current_w, info.current_h
    return 1920, 1080


def _screen_areas():
    """Rectangles the window should stay on: the window manager's work
    areas (one per monitor) when it publishes them, otherwise the
    primary screen."""
    areas = get_work_areas()
    if areas:
        return areas
    scr_w, scr_h = _get_screen_size()
    return [(0, 0, scr_w, scr_h)]


def get_work_areas():
    """Screen rectangles (x, y, w, h) the window manager keeps
    client-moved windows inside, or [] when it doesn't (Windows) or
    can't tell. Lets a drag predict where the window will really land.
    """
    if sys.platform == "linux":
        return _impl._linux_get_work_areas()
    return []


def set_input_region(handle, rects):
    """Make only `rects` (window pixels) of the window clickable, so the
    transparent area around the buddy doesn't block what's behind it.

    Linux uses the X SHAPE extension. Windows needs nothing: colour-keyed
    pixels of a layered window already let clicks through."""
    if sys.platform == "linux":
        return _impl._linux_set_input_region(handle, rects)
    return False


def raise_window(handle):
    """Force the window above other topmost peers, snapping it back
    on-screen if it has drifted off (e.g. monitor disconnected, dragged
    out of bounds)."""
    rect = get_window_rect(handle)
    if not overlaps_any(rect, _screen_areas()):
        nx, ny = get_initial_position()
        move_window(handle, nx, ny)

    if sys.platform == "win32":
        _impl._win_raise_topmost(handle)
    elif sys.platform == "linux":
        # Re-sending _NET_WM_STATE_ABOVE raises above other ABOVE windows
        _impl._linux_setup_window(handle, topmost=True)


def set_dpi_awareness():
    """Make the GUI process DPI-aware so screen and taskbar coordinates
    share a single physical pixel space.

    Windows-only; a no-op that returns None elsewhere. Call exactly once,
    before get_initial_position() and before any window is created — see
    `_windows._win_set_dpi_awareness` for the full rationale (issue #1:
    off-screen buddy on scaled Windows 11 displays)."""
    if sys.platform == "win32":
        return _impl._win_set_dpi_awareness()
    return None


def prepare_window_transparency():
    """Request a window that can carry per-pixel alpha.

    Linux-only; call once before the window is created. Returns a short
    description for the startup log, or None when per-pixel alpha isn't
    available (no compositor, no 32-bit visual, a non-X11 SDL driver, or
    Windows, which uses colour-key transparency instead). See
    `_linux._linux_prepare_argb_window` for why the Linux window used to
    show a black rectangle around the buddy."""
    if sys.platform == "linux":
        return _impl._linux_prepare_argb_window()
    return None


def window_has_alpha(screen):
    """True when the display surface really has an alpha channel, i.e.
    `prepare_window_transparency` worked and the frame should be painted
    on a transparent background instead of the theme's `bg_fill`.

    This checks the surface itself instead of trusting the request, so
    any SDL build or X server that ignores the request falls back to the
    old opaque background. Always False on Windows, which keeps its
    colour-key path."""
    if sys.platform != "linux":
        return False
    return screen.get_masks()[3] != 0


def _compute_taskbar_anchored_position(scr_w, scr_h, bar_top, bar_valid):
    """Pure geometry for the initial window placement — no ctypes, so it
    can be unit-tested against DPI-virtualized numbers (issue #1).

    Centers the window horizontally and sits it just above the taskbar
    (`bar_top` is the taskbar's top edge in screen pixels), then clamps
    the result fully on-screen. When no usable taskbar rect is available
    (`bar_valid` False — auto-hidden bar, shell API failure, exotic
    setup) it anchors to the screen bottom with a small margin instead.

    The clamp is a deliberate second line of defence: even if DPI
    awareness could not be applied and `bar_top` is a physical value that
    overshoots a virtualized `scr_h`, the window still stays visible.
    """
    x = scr_w // 2 - WIN_W // 2
    if bar_valid:
        y = bar_top - WIN_H + 28
    else:
        y = scr_h - WIN_H - 20
    # Never let the window drift off the top or bottom / left or right.
    y = max(0, min(y, scr_h - WIN_H))
    x = max(0, min(x, scr_w - WIN_W))
    return x, y


def center_window(handle):
    """Move the window to the center of the screen it's on (its work
    area, on Linux), or of the primary screen.

    Uses the window's *current* size (so it stays centered at whatever
    scale the user picked) and the same coordinate space as
    get_initial_position — after set_dpi_awareness that space is
    physical pixels, so the math lines up on scaled displays too. Kept
    at the area's top-left corner when the window is larger than it."""
    wx, wy, ww, wh = get_window_rect(handle)
    ax, ay, aw, ah = area_at(_screen_areas(), (wx + ww // 2, wy + wh // 2))
    x = ax + max(0, (aw - ww) // 2)
    y = ay + max(0, (ah - wh) // 2)
    move_window(handle, x, y)


def get_initial_position():
    """Return (win_x, win_y) for the buddy window."""
    if sys.platform == "win32":
        scr_w, scr_h = _impl._win_get_screen_size()
        _, tb_top, tb_w, tb_h = _impl._win_get_taskbar_rect()
        # SHAppBarMessage yields (0,0,0,0) when it fails; a zero-height or
        # top-aligned-at-0 rect isn't a usable "bottom taskbar" anchor.
        tb_valid = tb_w > 0 and tb_h > 0 and tb_top > 0
        return _compute_taskbar_anchored_position(
            scr_w, scr_h, tb_top, tb_valid)
    if sys.platform == "linux":
        # Need display init for screen info
        pygame.display.init()
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
        panel_h = _impl._linux_get_panel_height(scr_h)
        return _compute_taskbar_anchored_position(
            scr_w, scr_h, scr_h - panel_h, True)
    return 0, 0


def resize_window(handle, scale, topmost, anchor=(0.5, 1.0)):
    """Resize the pygame window, re-apply platform setup, and keep it on
    screen.

    The window grows or shrinks around `anchor`, a point given as
    fractions of the window's width and height (the buddy's feet, from
    the caller), so the buddy stays where it was instead of the window
    growing from its top-left corner."""
    new_w = int(WIN_W * scale)
    new_h = int(WIN_H * scale)
    wx, wy, ow, oh = get_window_rect(handle)
    ax, ay = wx + ow * anchor[0], wy + oh * anchor[1]
    screen = pygame.display.set_mode((new_w, new_h), pygame.NOFRAME)
    handle = get_window_handle()
    setup_window(handle, topmost)
    nx = int(round(ax - new_w * anchor[0]))
    ny = int(round(ay - new_h * anchor[1]))
    nx, ny = clamp_into((nx, ny, new_w, new_h), _screen_areas(),
                        (int(ax), int(ay)))
    move_window(handle, int(nx), int(ny))
    return screen, handle


def get_bg_fill(theme_name, transparent=False):
    """Background fill for the window surface each frame.

    Windows uses color-key transparency, so the background is painted
    in `TKEY` and becomes invisible. On Linux with an ARGB window
    (`transparent`, from `window_has_alpha`) the background is fully
    transparent. X11 has no colour-key, so without a compositor we paint
    the theme's `bg_fill` and hope it blends with the panel.
    """
    if sys.platform == "win32":
        return TKEY
    if transparent:
        return (0, 0, 0, 0)
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


def install_launcher():
    """Linux: install the per-user app launcher (.desktop file + icon),
    so the dock and Activities show "Clawd Buddy" with the buddy icon
    and the dock icon can be pinned. Best-effort; no-op elsewhere."""
    if sys.platform != "linux":
        return False
    try:
        import io
        from ..ui.about import _make_buddy_icon_image
        buf = io.BytesIO()
        _make_buddy_icon_image(256).save(buf, format="PNG")
        return _impl._linux_install_launcher(buf.getvalue())
    except Exception as e:  # read-only home, no Pillow, …
        print(f"[buddy] App launcher not installed: {e}")
        return False


def host_executable():
    """Windows: the `Clawd Buddy.exe` copy of the interpreter to run the
    detached buddy with, so Task Manager shows it by name and with its
    icon instead of as "Python" / pythonw.exe. Built on first use and
    after upgrades. None elsewhere, outside a venv, or if it can't be
    built — the caller then uses pythonw.exe as before."""
    if sys.platform != "win32":
        return None
    from . import _winhost
    return _winhost.ensure_host()


def startup_supported():
    """True where run-at-login is implemented (Windows, Linux)."""
    return sys.platform in ("win32", "linux")


def startup_enabled():
    """True when the buddy is set to run at login."""
    try:
        if sys.platform == "win32":
            return _impl._win_startup_enabled()
        if sys.platform == "linux":
            return _impl._linux_startup_enabled()
    except Exception:
        pass
    return False


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
