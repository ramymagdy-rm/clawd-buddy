# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License -- see LICENSE in the project root.

"""Windows platform impl -- ctypes wrappers around user32 / kernel32 /
shell32 plus the HKCU Run autostart helpers.

Imported ONLY when sys.platform == "win32"; the constants and ctypes
LoadLibrary calls at module top would fail on other platforms.

Cross-platform callers should import the facade from
`clawd_buddy.platform`, not this module directly.
"""

import ctypes
import ctypes.wintypes
import os
import shutil
import sys
import winreg

import pygame

from ..constants import WIN_H, WIN_W

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
user32.SetProcessDPIAware.restype = ctypes.wintypes.BOOL
kernel32 = ctypes.windll.kernel32
kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

# Per-Monitor-v2 DPI awareness context (Win10 1703+). Passed as a
# pointer-sized HANDLE — see _win_set_dpi_awareness for why this matters.
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
PROCESS_PER_MONITOR_DPI_AWARE = 2  # shcore SetProcessDpiAwareness value


def _win_set_dpi_awareness():
    """Declare this process DPI-aware, returning a short mode string
    (or None if every attempt failed).

    Windows 11 laptops default to 125–150% display scaling. Without
    opting in, the process runs DPI-*virtualized*: GetSystemMetrics
    reports a scaled-DOWN logical screen (e.g. 800px tall at 150% of a
    1200px panel) while SHAppBarMessage keeps reporting the taskbar in
    PHYSICAL pixels (top ~1152). get_initial_position() then computes a
    y below the logical screen and the window lands off-screen — visible
    nowhere, even though the process is alive and playing sounds
    (issue #1). Declaring awareness makes every metric share one
    physical pixel space, so the taskbar math lines up.

    MUST be called before the first top-level window is created and
    before any GetSystemMetrics / SHAppBarMessage call we rely on — DPI
    awareness is a one-shot, process-wide setting that cannot be changed
    once the process (or a library like SDL) has locked it in.

    Best-effort with a graceful fallback ladder across Windows versions;
    a failure here is never fatal — the clamp in get_initial_position()
    is the second line of defence.
    """
    # Per-Monitor-v2 (Win10 1703+) — the modern, preferred context. The
    # export is absent on older Windows, so attribute access can raise
    # AttributeError; ctypes also defaults the arg to a 32-bit int, which
    # truncates the -4 sentinel on 64-bit — pin argtypes to a HANDLE.
    try:
        fn = user32.SetProcessDpiAwarenessContext
        fn.argtypes = [ctypes.wintypes.HANDLE]
        fn.restype = ctypes.wintypes.BOOL
        if fn(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    # Per-Monitor (Win8.1+) via shcore — no v2 sub-modes but still makes
    # the coordinate spaces consistent.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(
            PROCESS_PER_MONITOR_DPI_AWARE)
        return "per-monitor"
    except (AttributeError, OSError):
        pass
    # System-DPI aware (Vista+) — last resort. Single-monitor setups (the
    # common case) get the same off-screen fix; only mixed-DPI multimon
    # loses the per-monitor nicety.
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except (AttributeError, OSError):
        pass
    return None

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

