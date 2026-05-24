# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License -- see LICENSE in the project root.

"""Linux / X11 platform impl -- libX11 ctypes wrappers plus the XDG
autostart .desktop helper.

Imported ONLY when sys.platform == "linux"; the libX11 LoadLibrary call
happens lazily inside `_linux_init_x11()` so importing this module on a
non-Linux platform is safe but useless.

Cross-platform callers should import the facade from
`clawd_buddy.platform`, not this module directly.
"""

import ctypes
import os
import shutil
import subprocess
import sys

import pygame

from ..constants import WIN_H, WIN_W

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

