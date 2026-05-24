# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""
Clawd Buddy — A tiny animated terminal pet that sits on your taskbar.

Always visible. When your coding assistant finishes a response, it celebrates!

Usage:
  clawd-buddy [OPTIONS]

Options:
  --port PORT      TCP port to listen on (default: 44556)
  --no-topmost     Don't keep the window always-on-top
  --test           Trigger a test celebration on startup
  --send MESSAGE   Signal a running buddy (celebrate) and exit
  --wave           Signal buddy to wave (attention needed) and exit
  --prompt-start   Signal a Claude Code prompt start (greet if new
                   session, then enter the thinking animation) and exit.
                   Reads session_id from piped JSON on stdin when run as
                   a hook command.
  --session-id ID  Explicit session id for --prompt-start (overrides stdin)
  --top            Signal running buddy to re-assert always-on-top and exit
  --quit           Ask the running buddy to exit cleanly and exit
  --theme THEME    Color theme — one of: dark, light, dracula, monokai,
                   nord, gruvbox, solarized, sunset (default: dark)
  --help           Show this help and exit

Controls:
  Drag             Click and drag to reposition
  Space            Test celebration
  Ctrl+1/2/3/4     Resize: 100% / 125% / 150% / 200%
  Escape           Quit

Switch themes from the system-tray right-click menu (Theme submenu)
or with the --theme CLI flag at launch.
"""

import sys
import os
import math
import time
import json
import array
import random
import threading
import socket
import ctypes
import argparse
import shutil

from . import __version__ as APP_VERSION
from .constants import (
    CHAR_H, CHAR_W, FPS, SOCK_HOST, SOCK_PORT, TKEY, WIN_H, WIN_W,
)
from .state import (
    BuddyState,
    MAX_THINKING_SECONDS,
    NEW_SESSION_IDLE_SECONDS,
    QUEUE_MAX,
    _spawn_confetti,
)
from .ui.drawing import draw_buddy, rounded_rect
from .ui.sound import (
    DEFAULT_SOUND_PACK,
    SOUND_PACK_CHOICES,
    SOUND_PACK_NAMES,
    SOUND_PACK_OFF,
    SOUND_PACKS,
    SOUND_SAMPLE_RATE,
    init_sounds,
)
from .ui.themes import THEME_NAMES, THEMES

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Force X11 on Linux — Wayland restricts window positioning & always-on-top
if sys.platform == "linux":
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")

import pygame




# ── Platform: Windows ────────────────────────────────────────────────
if sys.platform == "win32":
    import ctypes.wintypes

    user32 = ctypes.windll.user32

    GWL_EXSTYLE      = -20
    WS_EX_LAYERED    = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080
    LWA_COLORKEY     = 0x00000001
    SWP_NOMOVE       = 0x0002
    SWP_NOSIZE       = 0x0001
    SWP_NOACTIVATE   = 0x0010
    SWP_SHOWWINDOW   = 0x0040
    HWND_TOPMOST     = -1
    HWND_NOTOPMOST   = -2
    SW_SHOWNOACTIVATE = 4

    # Explicit argtypes — without these, ctypes defaults to c_int (32-bit),
    # which truncates HWND_TOPMOST/HWND_NOTOPMOST on 64-bit Windows.
    user32.SetWindowPos.argtypes = [
        ctypes.wintypes.HWND, ctypes.wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = ctypes.wintypes.BOOL
    user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = ctypes.wintypes.BOOL
    user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
    user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
    user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]
    user32.BringWindowToTop.restype = ctypes.wintypes.BOOL
    user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [
        ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
    user32.AttachThreadInput.argtypes = [
        ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL,
    ]
    user32.AttachThreadInput.restype = ctypes.wintypes.BOOL
    kernel32 = ctypes.windll.kernel32
    kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

    class APPBARDATA(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.wintypes.DWORD),
            ("hWnd", ctypes.wintypes.HWND),
            ("uCallbackMessage", ctypes.c_uint),
            ("uEdge", ctypes.c_uint),
            ("rc", ctypes.wintypes.RECT),
            ("lParam", ctypes.wintypes.LPARAM),
        ]

    ABM_GETTASKBARPOS = 0x00000005

    def _win_get_hwnd():
        return pygame.display.get_wm_info().get("window", 0)

    def _win_make_transparent(hwnd, color_key):
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
        r, g, b = color_key
        user32.SetLayeredWindowAttributes(
            hwnd, r | (g << 8) | (b << 16), 0, LWA_COLORKEY)

    def _win_set_topmost(hwnd, topmost=True):
        flag = HWND_TOPMOST if topmost else HWND_NOTOPMOST
        user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)

    def _win_raise_topmost(hwnd):
        """Force the window above other topmost peers without stealing focus.

        SetWindowPos(HWND_TOPMOST) on an already-topmost window does NOT
        re-insert at the top of the z-order group — peers added after us
        sit above us. The reliable sequence is: drop to NOTOPMOST, re-assert
        TOPMOST (puts us at top of topmost group), then BringWindowToTop
        within the topmost z-group. AttachThreadInput briefly attaches to
        the foreground thread so BringWindowToTop is honored.
        """
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)

        r1 = user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        r2 = user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                 flags | SWP_SHOWWINDOW)

        # AttachThreadInput trick: BringWindowToTop is otherwise ignored when
        # the calling thread doesn't own the foreground window.
        fg = user32.GetForegroundWindow()
        my_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if fg_tid and fg_tid != my_tid:
            attached = bool(user32.AttachThreadInput(my_tid, fg_tid, True))
        r3 = user32.BringWindowToTop(hwnd)
        if attached:
            user32.AttachThreadInput(my_tid, fg_tid, False)

        print(f"[buddy] raise: NOTOPMOST={r1} TOPMOST={r2} BringToTop={r3}")

    def _win_get_window_rect(hwnd):
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top

    def _win_move_window(hwnd, x, y):
        _, _, w, h = _win_get_window_rect(hwnd)
        user32.MoveWindow(hwnd, x, y, w, h, True)

    def _win_get_taskbar_rect():
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        ctypes.windll.shell32.SHAppBarMessage(
            ABM_GETTASKBARPOS, ctypes.byref(abd))
        rc = abd.rc
        return rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top

    def _win_get_screen_size():
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    # Startup — HKCU Run registry key.
    #
    # Earlier versions dropped a .vbs launcher in the Startup folder so the
    # console-subsystem clawd-buddy.exe could be started without a console
    # window. Windows 11 Smart App Control blocks unsigned VBS scripts at
    # login (error 800711C7), so we use the Run key instead and point it at
    # the GUI-subsystem clawd-buddyw.exe (registered via [project.gui-scripts]
    # in pyproject.toml) which starts silently with no console flash.
    import winreg
    _WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _WIN_RUN_VALUE = "ClawdBuddy"
    _WIN_LEGACY_STARTUP_DIR = os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows",
        "Start Menu", "Programs", "Startup",
    )
    _WIN_LEGACY_VBS = "clawd-buddy-startup.vbs"

    def _win_resolve_startup_exe():
        # Prefer the GUI-subsystem launcher so no console flashes at login.
        for name in ("clawd-buddyw", "clawd-buddy"):
            found = shutil.which(name)
            if found:
                return found
            candidate = os.path.join(
                os.path.dirname(sys.executable), f"{name}.exe")
            if os.path.exists(candidate):
                return candidate
        return "clawd-buddy"

    def _win_remove_legacy_vbs():
        path = os.path.join(_WIN_LEGACY_STARTUP_DIR, _WIN_LEGACY_VBS)
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"[buddy] Removed legacy startup script")
                print(f"        {path}")
            except OSError as e:
                print(f"[buddy] Could not remove legacy {path}: {e}")

    def _win_enable_startup():
        exe = _win_resolve_startup_exe()
        # Quote the path so spaces in user folders are handled.
        command = f'"{exe}"'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _WIN_RUN_VALUE, 0, winreg.REG_SZ, command)
        _win_remove_legacy_vbs()
        print(f"[buddy] Enabled run at startup")
        print(f"        HKCU\\{_WIN_RUN_KEY}\\{_WIN_RUN_VALUE} = {command}")

    def _win_disable_startup():
        removed = False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY,
                                0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _WIN_RUN_VALUE)
            removed = True
            print(f"[buddy] Disabled run at startup")
            print(f"        Removed HKCU\\{_WIN_RUN_KEY}\\{_WIN_RUN_VALUE}")
        except FileNotFoundError:
            pass
        legacy = os.path.join(_WIN_LEGACY_STARTUP_DIR, _WIN_LEGACY_VBS)
        if os.path.exists(legacy):
            _win_remove_legacy_vbs()
            removed = True
        if not removed:
            print(f"[buddy] Not in startup (nothing to remove)")


# ── Platform: Linux (X11) ────────────────────────────────────────────
elif sys.platform == "linux":
    _x11 = None
    _x11_display = None

    class _XClientMessageData(ctypes.Union):
        _fields_ = [
            ("b", ctypes.c_char * 20),
            ("s", ctypes.c_short * 10),
            ("l", ctypes.c_long * 5),
        ]

    class _XClientMessageEvent(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.c_int),
            ("serial", ctypes.c_ulong),
            ("send_event", ctypes.c_int),
            ("display", ctypes.c_void_p),
            ("window", ctypes.c_ulong),
            ("message_type", ctypes.c_ulong),
            ("format", ctypes.c_int),
            ("data", _XClientMessageData),
        ]

    class _XEvent(ctypes.Union):
        """Padded to sizeof(XEvent) = 192 bytes on 64-bit."""
        _fields_ = [
            ("type", ctypes.c_int),
            ("xclient", _XClientMessageEvent),
            ("_pad", ctypes.c_long * 24),
        ]

    def _linux_init_x11():
        """Initialize X11 ctypes bindings (lazy, called once)."""
        global _x11, _x11_display
        if _x11 is not None:
            return _x11_display is not None
        try:
            _x11 = ctypes.cdll.LoadLibrary("libX11.so.6")

            _x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
            _x11.XOpenDisplay.restype = ctypes.c_void_p

            _x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
            _x11.XDefaultRootWindow.restype = ctypes.c_ulong

            _x11.XInternAtom.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            _x11.XInternAtom.restype = ctypes.c_ulong

            _x11.XMoveWindow.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int]
            _x11.XMoveWindow.restype = ctypes.c_int

            _x11.XFlush.argtypes = [ctypes.c_void_p]
            _x11.XFlush.restype = ctypes.c_int

            _x11.XGetGeometry.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.POINTER(ctypes.c_ulong),
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
            ]
            _x11.XGetGeometry.restype = ctypes.c_int

            _x11.XTranslateCoordinates.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_ulong),
            ]
            _x11.XTranslateCoordinates.restype = ctypes.c_int

            _x11.XSendEvent.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                ctypes.c_long, ctypes.c_void_p,
            ]
            _x11.XSendEvent.restype = ctypes.c_int

            _x11.XChangeProperty.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong,
                ctypes.c_ulong, ctypes.c_ulong,
                ctypes.c_int, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_int,
            ]
            _x11.XChangeProperty.restype = ctypes.c_int

            _x11_display = _x11.XOpenDisplay(None)
            if not _x11_display:
                _x11 = None
                return False
            return True
        except OSError:
            _x11 = None
            return False

    def _linux_get_window_id():
        return pygame.display.get_wm_info().get("window", 0)

    def _linux_get_panel_height(scr_h):
        """Detect panel/dock height via _NET_WORKAREA. Falls back to 48px."""
        try:
            import subprocess
            result = subprocess.run(
                ["xprop", "-root", "_NET_WORKAREA"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and "=" in result.stdout:
                parts = result.stdout.split("=", 1)[1].strip().split(",")
                if len(parts) >= 4:
                    work_y = int(parts[1].strip())
                    work_h = int(parts[3].strip())
                    bottom = scr_h - (work_y + work_h)
                    if bottom > 10:
                        return bottom
                    if work_y > 10:
                        return work_y
        except (FileNotFoundError, ValueError, IndexError, OSError):
            pass
        return 48

    def _linux_move_window(window_id, x, y):
        if not _linux_init_x11():
            return
        _x11.XMoveWindow(_x11_display, window_id, x, y)
        _x11.XFlush(_x11_display)

    def _linux_get_window_rect(window_id):
        if not _linux_init_x11():
            return 0, 0, WIN_W, WIN_H
        root_ret = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        w = ctypes.c_uint()
        h = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        _x11.XGetGeometry(
            _x11_display, window_id, ctypes.byref(root_ret),
            ctypes.byref(x), ctypes.byref(y),
            ctypes.byref(w), ctypes.byref(h),
            ctypes.byref(border), ctypes.byref(depth),
        )
        # Convert to screen coordinates
        root = _x11.XDefaultRootWindow(_x11_display)
        dest_x = ctypes.c_int()
        dest_y = ctypes.c_int()
        child = ctypes.c_ulong()
        _x11.XTranslateCoordinates(
            _x11_display, window_id, root, 0, 0,
            ctypes.byref(dest_x), ctypes.byref(dest_y),
            ctypes.byref(child),
        )
        return dest_x.value, dest_y.value, w.value, h.value

    def _linux_setup_window(window_id, topmost):
        """Set window type to UTILITY and optionally always-on-top."""
        if not _linux_init_x11():
            return
        display = _x11_display
        XA_ATOM = 4

        # Set _NET_WM_WINDOW_TYPE to UTILITY (no taskbar entry)
        wm_type = _x11.XInternAtom(display, b"_NET_WM_WINDOW_TYPE", 0)
        wm_utility = _x11.XInternAtom(
            display, b"_NET_WM_WINDOW_TYPE_UTILITY", 0)
        atom_data = (ctypes.c_ulong * 1)(wm_utility)
        _x11.XChangeProperty(
            display, window_id, wm_type, XA_ATOM, 32, 0,
            ctypes.cast(atom_data, ctypes.c_void_p), 1,
        )

        if topmost:
            # Send _NET_WM_STATE client message to set ABOVE
            wm_state = _x11.XInternAtom(display, b"_NET_WM_STATE", 0)
            above = _x11.XInternAtom(display, b"_NET_WM_STATE_ABOVE", 0)
            root = _x11.XDefaultRootWindow(display)

            ev = _XEvent()
            ev.xclient.type = 33  # ClientMessage
            ev.xclient.send_event = 1
            ev.xclient.display = display
            ev.xclient.window = window_id
            ev.xclient.message_type = wm_state
            ev.xclient.format = 32
            ev.xclient.data.l[0] = 1   # _NET_WM_STATE_ADD
            ev.xclient.data.l[1] = above
            ev.xclient.data.l[2] = 0
            ev.xclient.data.l[3] = 1   # source: application
            ev.xclient.data.l[4] = 0

            _x11.XSendEvent(
                display, root, 0,
                0x180000,  # SubstructureNotify | SubstructureRedirect
                ctypes.byref(ev),
            )

        _x11.XFlush(display)

    # Startup — .desktop file in XDG autostart
    _LINUX_AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
    _DESKTOP_NAME = "clawd-buddy.desktop"

    def _linux_enable_startup():
        exe = shutil.which("clawd-buddy") or "clawd-buddy"
        desktop = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Clawd Buddy\n"
            f"Exec={exe} --fg\n"
            "Comment=Animated terminal pet for coding assistants\n"
            "X-GNOME-Autostart-enabled=true\n"
            "StartupNotify=false\n"
        )
        path = os.path.join(_LINUX_AUTOSTART_DIR, _DESKTOP_NAME)
        os.makedirs(_LINUX_AUTOSTART_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(desktop)
        print(f"[buddy] Enabled run at login")
        print(f"        {path}")

    def _linux_disable_startup():
        path = os.path.join(_LINUX_AUTOSTART_DIR, _DESKTOP_NAME)
        if os.path.exists(path):
            os.remove(path)
            print(f"[buddy] Disabled run at login")
            print(f"        Removed {path}")
        else:
            print(f"[buddy] Not in autostart (nothing to remove)")

    def _linux_auto_detach():
        """Double-fork to daemonize. Returns only in the daemon process."""
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
        os.setsid()
        pid = os.fork()
        if pid > 0:
            sys.exit(0)
        # Redirect stdio to /dev/null
        devnull = os.open(os.devnull, os.O_RDWR)
        os.dup2(devnull, 0)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        if devnull > 2:
            os.close(devnull)


# ── Cross-platform wrappers ──────────────────────────────────────────
def get_window_handle():
    if sys.platform == "win32":
        return _win_get_hwnd()
    elif sys.platform == "linux":
        return _linux_get_window_id()
    return 0


def setup_window(handle, topmost, color_key=TKEY):
    """Apply transparency (Windows) and window properties."""
    if sys.platform == "win32":
        _win_make_transparent(handle, color_key)
        if topmost:
            _win_set_topmost(handle, True)
    elif sys.platform == "linux":
        _linux_setup_window(handle, topmost)


def get_window_rect(handle):
    if sys.platform == "win32":
        return _win_get_window_rect(handle)
    elif sys.platform == "linux":
        return _linux_get_window_rect(handle)
    return 0, 0, WIN_W, WIN_H


def move_window(handle, x, y):
    if sys.platform == "win32":
        _win_move_window(handle, x, y)
    elif sys.platform == "linux":
        _linux_move_window(handle, x, y)


def raise_window(handle):
    """Force the window above other topmost peers, snapping it back on-screen
    if it has drifted off (e.g. monitor disconnected, dragged out of bounds).
    """
    # Snap back on-screen if the window is outside the primary screen area.
    wx, wy, ww, wh = get_window_rect(handle)
    if sys.platform == "win32":
        scr_w, scr_h = _win_get_screen_size()
    elif sys.platform == "linux":
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
    else:
        scr_w, scr_h = 1920, 1080
    off_screen = (wx + ww <= 0 or wy + wh <= 0
                  or wx >= scr_w or wy >= scr_h)
    if off_screen:
        nx, ny = get_initial_position()
        move_window(handle, nx, ny)

    if sys.platform == "win32":
        _win_raise_topmost(handle)
    elif sys.platform == "linux":
        # Re-sending _NET_WM_STATE_ABOVE raises above other ABOVE windows
        _linux_setup_window(handle, topmost=True)


def get_initial_position():
    """Return (win_x, win_y) for the buddy window."""
    if sys.platform == "win32":
        scr_w, scr_h = _win_get_screen_size()
        _, tb_y, _, _ = _win_get_taskbar_rect()
        return scr_w // 2 - WIN_W // 2, tb_y - WIN_H + 28
    elif sys.platform == "linux":
        # Need display init for screen info
        pygame.display.init()
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
        panel_h = _linux_get_panel_height(scr_h)
        return scr_w // 2 - WIN_W // 2, scr_h - panel_h - WIN_H + 28
    return 0, 0


def enable_startup():
    if sys.platform == "win32":
        _win_enable_startup()
    elif sys.platform == "linux":
        _linux_enable_startup()
    else:
        print(f"[buddy] Startup not supported on {sys.platform}")


def disable_startup():
    if sys.platform == "win32":
        _win_disable_startup()
    elif sys.platform == "linux":
        _linux_disable_startup()
    else:
        print(f"[buddy] Startup not supported on {sys.platform}")


def resize_window(handle, scale, topmost):
    """Resize the pygame window, re-apply platform setup, and clamp to screen."""
    new_w = int(WIN_W * scale)
    new_h = int(WIN_H * scale)
    # Get current position before recreating the surface
    wx, wy, _, _ = get_window_rect(handle)
    screen = pygame.display.set_mode((new_w, new_h), pygame.NOFRAME)
    handle = get_window_handle()
    setup_window(handle, topmost)
    # Clamp so the window stays fully on screen
    if sys.platform == "win32":
        scr_w, scr_h = _win_get_screen_size()
    elif sys.platform == "linux":
        info = pygame.display.Info()
        scr_w, scr_h = info.current_w, info.current_h
    else:
        scr_w, scr_h = 1920, 1080
    nx = max(0, min(wx, scr_w - new_w))
    ny = max(0, min(wy, scr_h - new_h))
    move_window(handle, nx, ny)
    return screen, handle


def get_bg_fill(theme_name):
    """Background fill for the window surface each frame."""
    if sys.platform == "win32":
        return TKEY  # color-key transparency
    # Linux: no color-key transparency, use themed background
    theme = THEMES.get(theme_name, THEMES["dark"])
    return theme.get("bg_fill", (1, 1, 1))





# ── Socket listener ───────────────────────────────────────────────────
def socket_listener(state, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((SOCK_HOST, port))
    except OSError as e:
        print(f"[buddy] Cannot bind {SOCK_HOST}:{port}: {e}")
        return
    srv.listen(5)
    srv.settimeout(1.0)
    print(f"[buddy] Listening on {SOCK_HOST}:{port}")

    while True:
        try:
            conn, _ = srv.accept()
            try:
                conn.settimeout(2.0)
                data = conn.recv(4096).decode("utf-8", errors="replace").strip()
            finally:
                conn.close()
            if data:
                action = "celebrate"
                msg = {}
                try:
                    msg = json.loads(data)
                    action = msg.get("action", "celebrate")
                except (json.JSONDecodeError, AttributeError):
                    pass
                print(f"[buddy] Signal: {action}")
                if action == "wave":
                    state.wave()
                elif action == "raise":
                    state.bring_to_front()
                elif action == "quit":
                    state.should_quit = True
                elif action == "prompt_start":
                    state.prompt_start(session_id=msg.get("session_id"))
                elif action == "greet":
                    state.greet(session_id=msg.get("session_id"))
                elif action == "thinking_start":
                    state.start_thinking()
                elif action == "thinking_end":
                    state.end_thinking()
                else:
                    state.trigger()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[buddy] Socket error: {e}")


# ── Persistent config (remembered theme, etc.) ────────────────────────
def _config_dir():
    """Per-OS directory for clawd-buddy's user config."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser(
            "~\\AppData\\Roaming"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "clawd-buddy")


def _config_path():
    return os.path.join(_config_dir(), "config.json")


def load_config():
    """Read config.json. Returns an empty dict on any error."""
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def save_config(data):
    """Atomically write config.json. Non-fatal on failure."""
    path = _config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[buddy] Could not save config: {e}")


def load_saved_theme():
    """Return the last remembered theme name, or None if unknown / invalid."""
    name = load_config().get("theme")
    return name if name in THEMES else None


def save_theme_pref(name):
    """Persist the user's theme selection. Called on launch override and
    whenever the tray Theme submenu changes the active theme."""
    if name not in THEMES:
        return
    cfg = load_config()
    if cfg.get("theme") == name:
        return  # no-op write avoided
    cfg["theme"] = name
    save_config(cfg)


def load_saved_sound_pack():
    """Return the last remembered sound-pack name.

    Defaults to DEFAULT_SOUND_PACK on first run / corrupt config so the
    buddy still chirps out of the box. Also migrates the legacy
    `sound: bool` key written by an earlier iteration of this feature:
      sound=False ⇒ "off", sound=True ⇒ DEFAULT_SOUND_PACK.
    The new key takes precedence if both exist.
    """
    cfg = load_config()
    pack = cfg.get("sound_pack")
    if isinstance(pack, str) and pack in SOUND_PACK_CHOICES:
        return pack
    legacy = cfg.get("sound")
    if legacy is False:
        return SOUND_PACK_OFF
    return DEFAULT_SOUND_PACK


def save_sound_pack_pref(pack):
    """Persist the chosen sound pack. Called from the tray Sound submenu.

    Also strips the legacy `sound: bool` key on first new write so the
    config doesn't accumulate dead keys after migration.
    """
    if pack not in SOUND_PACK_CHOICES:
        return
    cfg = load_config()
    if cfg.get("sound_pack") == pack and "sound" not in cfg:
        return
    cfg["sound_pack"] = pack
    cfg.pop("sound", None)
    save_config(cfg)


# ── Buddy icon image (shared by tray + About dialog) ─────────────────
def _make_buddy_icon_image():
    """Procedurally draw a 64x64 RGBA PIL Image of the buddy's face.

    Used as both the system-tray icon and the About-dialog window icon so
    the buddy silhouette is the branding everywhere the app shows itself.
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([12, 14, 52, 46], radius=5, fill=(42, 42, 58))
    d.rounded_rectangle([12, 14, 52, 22], radius=5, fill=(70, 70, 92))
    d.ellipse([22, 28, 30, 36], fill=(230, 235, 255))
    d.ellipse([34, 28, 42, 36], fill=(230, 235, 255))
    d.line([(28, 40), (36, 40)], fill=(120, 130, 160), width=2)
    d.line([(24, 46), (22, 54)], fill=(35, 35, 48), width=3)
    d.line([(40, 46), (42, 54)], fill=(35, 35, 48), width=3)
    return img


# ── About dialog ──────────────────────────────────────────────────────
# Small tkinter Toplevel that pops up when the user clicks tray → About.
# tkinter is imported lazily inside the worker so the buddy still launches
# on stripped-down Python installs without _tkinter — the dialog just
# fails gracefully with a log line.
_REPO_URL = "https://github.com/ramymagdy-rm/clawd-buddy"
_ABOUT_DIALOG_OPEN = False


def show_about_dialog():
    """Open the About dialog. Reentrant clicks are debounced — at most one
    dialog at a time. Spawned on its own thread so it doesn't block the
    tray menu (pystray's callbacks are synchronous) or the pygame loop.
    """
    global _ABOUT_DIALOG_OPEN
    if _ABOUT_DIALOG_OPEN:
        return
    _ABOUT_DIALOG_OPEN = True
    threading.Thread(target=_run_about_dialog, daemon=True).start()


def _run_about_dialog():
    global _ABOUT_DIALOG_OPEN
    try:
        import tkinter as tk
        import webbrowser

        root = tk.Tk()
        root.title("About Clawd Buddy")
        root.resizable(False, False)

        # Replace the default tk feather icon with the buddy silhouette.
        # PhotoImage must be retained on `root` — tkinter doesn't keep its
        # own reference and the icon vanishes on GC otherwise.
        try:
            from PIL import ImageTk
            icon_photo = ImageTk.PhotoImage(_make_buddy_icon_image())
            root.iconphoto(True, icon_photo)
            root._buddy_icon_ref = icon_photo
        except Exception as ie:
            print(f"[buddy] About dialog icon failed: {ie}")

        frame = tk.Frame(root, padx=24, pady=20)
        frame.pack(expand=True, fill="both")

        tk.Label(frame, text="Clawd Buddy",
                 font=("Segoe UI", 16, "bold")).pack()
        tk.Label(frame, text=f"Version {APP_VERSION}",
                 font=("Segoe UI", 9)).pack(pady=(2, 10))

        tk.Label(frame, text="A tiny animated terminal pet that sits",
                 font=("Segoe UI", 9)).pack()
        tk.Label(frame, text="on your taskbar and reacts to",
                 font=("Segoe UI", 9)).pack()
        tk.Label(frame, text="coding-assistant events.",
                 font=("Segoe UI", 9)).pack(pady=(0, 12))

        tk.Label(frame, text="Author: Ramy Ezzat",
                 font=("Segoe UI", 9)).pack()
        tk.Label(frame, text="License: MIT",
                 font=("Segoe UI", 9)).pack(pady=(0, 8))

        link = tk.Label(frame, text=_REPO_URL,
                        fg="#3a7ad6", cursor="hand2",
                        font=("Segoe UI", 9, "underline"))
        link.pack()
        link.bind("<Button-1>", lambda _e: webbrowser.open(_REPO_URL))

        tk.Button(frame, text="Close", command=root.destroy,
                  padx=18).pack(pady=(14, 0))

        # Center on screen — tk needs a refresh before geometry is known.
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception as e:
        print(f"[buddy] About dialog failed: {e}")
    finally:
        _ABOUT_DIALOG_OPEN = False


# ── System tray ───────────────────────────────────────────────────────
def _tray_log_path():
    """Per-OS scratch path for tray startup errors."""
    if sys.platform == "win32":
        base = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    else:
        base = "/tmp"
    return os.path.join(base, "clawd-buddy-tray.log")


def create_tray(state):
    """Entry point for the tray daemon thread — swallow no exceptions silently.

    The tray is a daemon thread; an uncaught exception here used to kill the
    tray icon without any visible feedback (pythonw on Windows has no stderr).
    Log to a file so startup failures are diagnosable.
    """
    import traceback
    try:
        _create_tray_impl(state)
    except Exception:
        path = _tray_log_path()
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n=== clawd-buddy tray crash @ {time.ctime()} ===\n")
                traceback.print_exc(file=f)
        except OSError:
            pass
        # Also try stderr (visible when run with --fg)
        try:
            sys.stderr.write(
                f"[buddy] Tray thread crashed — see {path}\n"
            )
            traceback.print_exc()
        except Exception:
            pass


def _create_tray_impl(state):
    import pystray

    img = _make_buddy_icon_image()

    def on_celebrate(_icon, _item):
        state.trigger()

    def on_bring_to_front(_icon, _item):
        state.bring_to_front()

    def on_about(_icon, _item):
        show_about_dialog()

    def on_quit(icon, _item):
        state.should_quit = True
        icon.stop()

    # pystray's _assert_action rejects callables whose __code__.co_argcount
    # exceeds 2 — even when the extra parameter is a default. Build the
    # closures via factories so each closure has exactly the arg count
    # pystray expects (action: 2, checked: 1).
    def _make_action(name):
        def _action(_icon, _item):
            state.set_theme(name)
            save_theme_pref(name)
        return _action

    def _make_checker(name):
        def _checker(_item):
            return state.theme_name == name
        return _checker

    def _theme_item(name):
        return pystray.MenuItem(
            name.title(),
            _make_action(name),
            checked=_make_checker(name),
            radio=True,
        )

    theme_submenu = pystray.Menu(*[
        _theme_item(name) for name in THEME_NAMES
    ])

    # Sound submenu — same factory pattern as the theme submenu so pystray
    # sees closures with the exact arity its _assert_action expects.
    # Clicking a pack switches AND previews via state.set_sound_pack,
    # then persists the choice. "Off" mutes (no preview to play).
    def _make_pack_action(pack):
        def _action(_icon, _item):
            state.set_sound_pack(pack)
            save_sound_pack_pref(pack)
        return _action

    def _make_pack_checker(pack):
        def _checker(_item):
            return state.sound_pack == pack
        return _checker

    def _pack_item(pack, label):
        return pystray.MenuItem(
            label,
            _make_pack_action(pack),
            checked=_make_pack_checker(pack),
            radio=True,
        )

    sound_submenu = pystray.Menu(
        _pack_item(SOUND_PACK_OFF, "Off"),
        *[_pack_item(name, name.title()) for name in SOUND_PACK_NAMES],
    )

    menu = pystray.Menu(
        pystray.MenuItem("Test Celebration", on_celebrate),
        pystray.MenuItem("Bring to Front", on_bring_to_front),
        pystray.MenuItem("Theme", theme_submenu),
        pystray.MenuItem("Sound", sound_submenu),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Clawd Buddy v{APP_VERSION}", None, enabled=False),
        pystray.MenuItem("About", on_about),
        pystray.MenuItem("Quit", on_quit),
    )
    pystray.Icon("clawd-buddy", img, "Clawd Buddy", menu).run()


# ── CLI ───────────────────────────────────────────────────────────────
def _read_hook_stdin():
    """Read Claude Code's hook payload from stdin, if any.

    Claude Code passes a JSON payload (with `session_id`, `transcript_path`,
    `hook_event_name`, …) on stdin to hook commands. When the buddy CLI is
    run from a terminal stdin is a TTY, so we skip reading to avoid blocking.

    Returns a dict (empty on missing / malformed input); never raises.
    """
    if sys.stdin is None or sys.stdin.isatty():
        return {}
    try:
        data = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not data:
        return {}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_args():
    p = argparse.ArgumentParser(
        prog="clawd-buddy",
        description="Clawd Buddy — tiny terminal pet on your taskbar",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  clawd-buddy               Start buddy on taskbar\n"
            "  clawd-buddy --test         Start with a celebration\n"
            "  clawd-buddy --send Done!   Signal a running buddy\n"
            "  clawd-buddy --wave         Wave for attention\n"
            "  clawd-buddy --prompt-start Greet (if new session) + start thinking\n"
            "  clawd-buddy --top          Bring buddy to front (re-assert topmost)\n"
            "  clawd-buddy --quit         Ask the running buddy to exit cleanly\n"
            "  clawd-buddy --theme dracula   Use Dracula theme\n"
            "  clawd-buddy --theme nord      Use Nord theme\n"
            "  clawd-buddy --startup      Run at login/startup\n"
            "  clawd-buddy --no-startup   Remove from login/startup\n"
        ),
    )
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {APP_VERSION}",
                   help="Show version and exit")
    p.add_argument("--port", type=int, default=SOCK_PORT,
                   help=f"TCP port (default: {SOCK_PORT})")
    p.add_argument("--no-topmost", action="store_true",
                   help="Don't stay always-on-top")
    p.add_argument("--test", action="store_true",
                   help="Celebrate on startup")
    p.add_argument("--send", metavar="MSG", type=str,
                   help="Send celebrate signal to running buddy and exit")
    p.add_argument("--wave", action="store_true",
                   help="Send wave/attention signal to running buddy and exit")
    p.add_argument("--top", action="store_true",
                   help="Tell running buddy to re-assert always-on-top and exit")
    p.add_argument("--quit", action="store_true",
                   help="Ask running buddy to exit cleanly and exit")
    p.add_argument("--prompt-start", dest="prompt_start", action="store_true",
                   help=("Signal the start of a Claude Code prompt "
                         "(UserPromptSubmit hook). Greets on the first prompt "
                         "of a new session and starts the thinking animation. "
                         "Reads session_id from piped JSON on stdin when "
                         "available."))
    p.add_argument("--session-id", dest="session_id", default=None,
                   metavar="ID",
                   help=("Session id to associate with --prompt-start. "
                         "Overrides any session_id read from stdin. Mostly "
                         "useful for testing."))
    p.add_argument("--theme", choices=list(THEMES.keys()), default=None,
                   metavar="THEME",
                   help=("Color theme. Choices: "
                         + ", ".join(THEMES.keys())
                         + ". If omitted, the last theme you picked is "
                         "remembered (falls back to 'dark' on first run). "
                         "Change at runtime via the tray Theme submenu."))
    p.add_argument("--startup", action="store_true",
                   help="Enable run at login/startup and exit")
    p.add_argument("--no-startup", action="store_true",
                   help="Disable run at login/startup and exit")
    p.add_argument("--fg", action="store_true",
                   help="Run in foreground (default auto-detaches)")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────
def main():
    args = parse_args()
    port = args.port

    # Resolve the active theme:
    #   1. Explicit --theme on CLI wins (and is persisted as the new default).
    #   2. Otherwise load the last saved theme from config.json.
    #   3. Otherwise fall back to 'dark'.
    if args.theme is not None:
        save_theme_pref(args.theme)
        resolved_theme = args.theme
    else:
        resolved_theme = load_saved_theme() or "dark"
    args.theme = resolved_theme

    # --startup / --no-startup
    if args.startup:
        enable_startup()
        sys.exit(0)
    if args.no_startup:
        disable_startup()
        sys.exit(0)

    # --send / --wave / --top / --quit / --prompt-start
    # (any of these signals a running instance and exits)
    if (args.send is not None or args.wave or args.top or args.quit
            or args.prompt_start):
        payload_obj = {}
        if args.quit:
            payload_obj["action"] = "quit"
        elif args.top:
            payload_obj["action"] = "raise"
        elif args.wave:
            payload_obj["action"] = "wave"
        elif args.prompt_start:
            payload_obj["action"] = "prompt_start"
            # Claude Code passes hook metadata as JSON on stdin. Prefer an
            # explicit --session-id when given; otherwise fall back to the
            # piped JSON. When neither is available the running buddy uses
            # its time-based new-session heuristic.
            hook = _read_hook_stdin()
            session_id = args.session_id or hook.get("session_id")
            if session_id:
                payload_obj["session_id"] = session_id
        else:
            payload_obj["action"] = "celebrate"
        payload = json.dumps(payload_obj).encode()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SOCK_HOST, port))
            s.sendall(payload)
            s.close()
            print(f"[buddy] Sent: {payload_obj['action']}")
        except ConnectionRefusedError:
            print(f"[buddy] No buddy on port {port}")
            sys.exit(1)
        sys.exit(0)

    # Auto-detach: run in background
    if not args.fg:
        if sys.platform == "win32":
            import subprocess
            py_dir = os.path.dirname(sys.executable)
            pythonw = os.path.join(py_dir, "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = os.path.join(py_dir, "Scripts", "pythonw.exe")
            if not os.path.exists(pythonw):
                pythonw = sys.executable
            cmd = [pythonw, "-m", "clawd_buddy.app", "--fg",
                   "--theme", args.theme]
            if args.port != SOCK_PORT:
                cmd += ["--port", str(args.port)]
            if args.no_topmost:
                cmd.append("--no-topmost")
            if args.test:
                cmd.append("--test")
            subprocess.Popen(
                cmd,
                creationflags=(subprocess.DETACHED_PROCESS
                               | subprocess.CREATE_NO_WINDOW),
                close_fds=True,
            )
            sys.exit(0)
        elif sys.platform == "linux":
            _linux_auto_detach()
            # Daemon continues executing below

    # Single instance lock
    lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_sock.bind(("127.0.0.1", port + 1))
    except OSError:
        print("[buddy] Already running — sending signal.")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SOCK_HOST, port))
            s.sendall(b'{"message": "hello"}')
            s.close()
        except Exception:
            pass
        sys.exit(0)

    # Compute initial window position (may init display subsystem)
    win_x, win_y = get_initial_position()
    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{win_x},{win_y}"

    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.NOFRAME)
    pygame.display.set_caption("Clawd Buddy")
    clock = pygame.time.Clock()

    handle = get_window_handle()
    setup_window(handle, topmost=not args.no_topmost)

    topmost = not args.no_topmost
    state = BuddyState(theme_name=args.theme,
                       sound_pack=load_saved_sound_pack())

    # Audio is best-effort: init may fail on headless machines / containers /
    # missing audio device — we still run silently in that case. Every
    # pack's Sound objects are pre-built so tray previews are instant.
    sounds_by_pack = init_sounds()

    if args.test:
        state.trigger()

    # Base surface — always draw at native resolution, then scale to window
    base_surf = pygame.Surface((WIN_W, WIN_H))

    # Background threads
    threading.Thread(target=socket_listener, args=(state, port),
                     daemon=True).start()
    threading.Thread(target=create_tray, args=(state,),
                     daemon=True).start()

    # Drag state
    dragging = False
    drag_off = (0, 0)

    # Blink
    blink_timer = 0.0
    blink_interval = 3.5
    blink_dur = 0.12

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        t = time.time()

        if state.should_quit:
            break

        # Apply pending scale change
        if state._scale_changed:
            state._scale_changed = False
            screen, handle = resize_window(handle, state.scale, topmost)

        # Apply pending bring-to-front request
        if state._raise_requested:
            state._raise_requested = False
            topmost = True
            raise_window(handle)

        # Drain pending notification sound. Producers (socket listener,
        # tray callbacks, key handler) just set the flag; playback happens
        # on the main thread to keep mixer access single-threaded. We look
        # up the pair for the *current* sound pack so tray previews fire
        # immediately when the user picks a new pack from the submenu.
        if state._pending_sound is not None:
            snd_name = state._pending_sound
            state._pending_sound = None
            pair = sounds_by_pack.get(state.sound_pack)
            if pair is not None:
                snd = pair[0] if snd_name == "celebrate" else pair[1]
                try:
                    snd.play()
                except pygame.error as e:
                    print(f"[buddy] Sound play failed: {e}")

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_SPACE:
                    state.trigger()
                elif ev.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                    # Ctrl+1..4 resizes the buddy. Theme switching is now
                    # exclusively via the tray Theme submenu.
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_CTRL:
                        state.set_scale(ev.key - pygame.K_0)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                dragging = True
                drag_off = ev.pos
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                dragging = False
            elif ev.type == pygame.MOUSEMOTION and dragging:
                mx, my = ev.pos
                wx, wy, _, _ = get_window_rect(handle)
                move_window(handle, wx + mx - drag_off[0],
                            wy + my - drag_off[1])

        state.update()

        # Blink
        blink_timer += dt
        phase = blink_timer % blink_interval
        is_blink = phase > blink_interval - blink_dur

        # Draw at base resolution, then scale up
        base_surf.fill(get_bg_fill(state.theme_name))
        draw_buddy(base_surf, t, state, is_blink)

        if state.scale == 1.0:
            screen.blit(base_surf, (0, 0))
        else:
            scaled = pygame.transform.smoothscale(
                base_surf, screen.get_size())
            screen.blit(scaled, (0, 0))
        pygame.display.flip()

    pygame.quit()
    lock_sock.close()
    sys.exit()


if __name__ == "__main__":
    main()
