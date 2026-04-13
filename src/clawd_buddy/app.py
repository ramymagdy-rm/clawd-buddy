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
  --theme THEME    Color theme: dark or light (default: dark)
  --help           Show this help and exit

Controls:
  Drag             Click and drag to reposition
  Space            Test celebration
  Ctrl+1/2/3/4     Resize: 100% / 125% / 150% / 200%
  Escape           Quit
"""

import sys
import os
import math
import time
import json
import random
import threading
import socket
import ctypes
import argparse
import shutil

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Force X11 on Linux — Wayland restricts window positioning & always-on-top
if sys.platform == "linux":
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")

import pygame


# ── Themes ────────────────────────────────────────────────────────────
THEMES = {
    "dark": {
        "body_outer":  (35, 35, 48),
        "body_inner":  (42, 42, 58),
        "title_bar":   (70, 70, 92),
        "screen_bg":   (22, 22, 32),
        "eye_white":   (230, 235, 255),
        "pupil":       (25, 25, 40),
        "mouth":       (120, 130, 160),
        "mouth_happy": (255, 220, 80),
        "limb":        (35, 35, 48),
        "shoe":        (50, 50, 68),
        "wave_eye":    (255, 190, 80),
    },
    "light": {
        "body_outer":  (195, 200, 215),
        "body_inner":  (215, 220, 235),
        "title_bar":   (175, 180, 200),
        "screen_bg":   (238, 240, 248),
        "eye_white":   (255, 255, 255),
        "pupil":       (35, 35, 55),
        "mouth":       (135, 140, 168),
        "mouth_happy": (255, 180, 40),
        "limb":        (175, 180, 200),
        "shoe":        (155, 160, 180),
        "wave_eye":    (230, 150, 30),
    },
}

CONFETTI_COLORS = [
    (255, 107, 107), (78, 205, 196), (69, 183, 209),
    (255, 230, 109), (199, 128, 232), (255, 159, 67),
]


# ── Dimensions & constants ────────────────────────────────────────────
WIN_W, WIN_H = 200, 260
CHAR_W, CHAR_H = 80, 62
FPS = 120

# Transparent key — never draw with this exact color (Windows color-key)
TKEY = (1, 1, 1)

SOCK_HOST = "127.0.0.1"
SOCK_PORT = 44556


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
    HWND_TOPMOST     = -1
    HWND_NOTOPMOST   = -2

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

    # Startup — VBS launcher in Windows Startup folder
    _WIN_STARTUP_DIR = os.path.join(
        os.environ.get("APPDATA", ""), "Microsoft", "Windows",
        "Start Menu", "Programs", "Startup",
    )
    _VBS_NAME = "clawd-buddy-startup.vbs"

    def _win_enable_startup():
        exe = shutil.which("clawd-buddy")
        if not exe:
            candidate = os.path.join(
                os.path.dirname(sys.executable), "clawd-buddy.exe")
            exe = candidate if os.path.exists(candidate) else "clawd-buddy"
        vbs = (
            'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.Run """{exe}""", 0, False\n'
        )
        path = os.path.join(_WIN_STARTUP_DIR, _VBS_NAME)
        os.makedirs(_WIN_STARTUP_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(vbs)
        print(f"[buddy] Enabled run at startup")
        print(f"        {path}")

    def _win_disable_startup():
        path = os.path.join(_WIN_STARTUP_DIR, _VBS_NAME)
        if os.path.exists(path):
            os.remove(path)
            print(f"[buddy] Disabled run at startup")
            print(f"        Removed {path}")
        else:
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
    """Resize the pygame window and re-apply platform setup."""
    new_w = int(WIN_W * scale)
    new_h = int(WIN_H * scale)
    screen = pygame.display.set_mode((new_w, new_h), pygame.NOFRAME)
    # Re-acquire handle (may change after set_mode on some platforms)
    handle = get_window_handle()
    setup_window(handle, topmost)
    return screen, handle


def get_bg_fill(theme_name):
    """Background fill for the window surface each frame."""
    if sys.platform == "win32":
        return TKEY  # color-key transparency
    # Linux: no color-key transparency, use themed background
    if theme_name == "light":
        return (250, 250, 255)
    return (1, 1, 1)


# ── State ─────────────────────────────────────────────────────────────
class BuddyState:
    SCALE_PRESETS = {1: 1.0, 2: 1.25, 3: 1.5, 4: 2.0}

    def __init__(self, theme_name="dark"):
        self.mode = "idle"
        self.mode_start = 0.0
        self.cel_dur = 5.0
        self.wave_dur = 5.0
        self.confetti = []
        self.should_quit = False
        self.theme_name = theme_name
        self.theme = dict(THEMES[theme_name])
        self.scale = 1.0
        self._scale_changed = False

    @property
    def celebrating(self):
        return self.mode == "celebrating"

    @property
    def waving(self):
        return self.mode == "waving"

    def set_theme(self, name):
        if name in THEMES:
            self.theme_name = name
            self.theme = dict(THEMES[name])

    def set_scale(self, preset):
        """Set scale from preset number (1-4)."""
        if preset in self.SCALE_PRESETS:
            self.scale = self.SCALE_PRESETS[preset]
            self._scale_changed = True

    def trigger(self, _msg=""):
        self.mode = "celebrating"
        self.mode_start = time.time()
        self.confetti = _spawn_confetti(40)

    def wave(self):
        if self.mode != "celebrating":
            self.mode = "waving"
            self.mode_start = time.time()

    def update(self):
        elapsed = time.time() - self.mode_start
        if self.mode == "celebrating" and elapsed > self.cel_dur:
            self.mode = "idle"
        elif self.mode == "waving" and elapsed > self.wave_dur:
            self.mode = "idle"


def _spawn_confetti(n):
    cx = WIN_W // 2
    return [
        [cx + random.randint(-30, 30), WIN_H // 2 - 40,
         random.uniform(-3, 3), random.uniform(-7, -2),
         random.choice(CONFETTI_COLORS), random.randint(3, 6)]
        for _ in range(n)
    ]


# ── Drawing ───────────────────────────────────────────────────────────
def rounded_rect(surf, color, rect, r):
    x, y, w, h = rect
    r = min(r, w // 2, h // 2)
    pygame.draw.rect(surf, color, (x + r, y, w - 2 * r, h))
    pygame.draw.rect(surf, color, (x, y + r, w, h - 2 * r))
    for cx, cy in [(x+r, y+r), (x+w-r, y+r), (x+r, y+h-r), (x+w-r, y+h-r)]:
        pygame.draw.circle(surf, color, (cx, cy), r)


def draw_buddy(surf, t, state, blink):
    th = state.theme
    cel = state.celebrating
    wav = state.waving
    cx = WIN_W // 2
    base_y = WIN_H - 70
    bob = math.sin(t * 2.2) * 1.5
    if cel:
        bob = math.sin(t * 10) * 6
    elif wav:
        bob = math.sin(t * 4) * 3

    by = int(base_y - CHAR_H + bob)

    # ── Legs ──────────────────────────────────────────────────────
    leg_top = int(by + CHAR_H - 2)
    leg_len = 18
    if cel:
        l_swing = math.sin(t * 7) * 8
        r_swing = math.sin(t * 7 + math.pi) * 8
    elif wav:
        l_swing = math.sin(t * 3) * 3
        r_swing = math.sin(t * 3 + math.pi) * 3
    else:
        l_swing = math.sin(t * 1.8) * 1.5
        r_swing = math.sin(t * 1.8 + math.pi) * 1.5
    for sx, sw in [(-14, l_swing), (14, r_swing)]:
        fx = int(cx + sx + sw)
        fy = leg_top + leg_len
        pygame.draw.line(surf, th["limb"], (cx + sx, leg_top), (fx, fy), 5)
        rounded_rect(surf, th["shoe"], (fx - 7, fy - 2, 14, 8), 3)

    # ── Arms ──────────────────────────────────────────────────────
    arm_y = int(by + CHAR_H // 2 + bob)
    arm_len = 22
    if cel:
        la = math.sin(t * 8) * 0.5 - 1.3
        ra = math.sin(t * 8 + math.pi) * 0.5 + 0.3
    elif wav:
        la = math.sin(t * 1.2) * 0.1 - 0.2
        ra = math.sin(t * 6) * 0.4 - 1.0
    else:
        la = math.sin(t * 1.2) * 0.1 - 0.2
        ra = math.sin(t * 1.2 + 1) * 0.1 + 0.2

    lx1 = cx - CHAR_W // 2 - 2
    lx2 = int(lx1 + math.cos(math.pi + la) * arm_len)
    ly2 = int(arm_y + math.sin(math.pi + la) * arm_len)
    pygame.draw.line(surf, th["limb"], (lx1, arm_y), (lx2, ly2), 5)
    pygame.draw.circle(surf, th["limb"], (lx2, ly2), 4)

    rx1 = cx + CHAR_W // 2 + 2
    rx2 = int(rx1 + math.cos(ra) * arm_len)
    ry2 = int(arm_y + math.sin(ra) * arm_len)
    pygame.draw.line(surf, th["limb"], (rx1, arm_y), (rx2, ry2), 5)
    pygame.draw.circle(surf, th["limb"], (rx2, ry2), 4)

    # ── Body ──────────────────────────────────────────────────────
    bx = cx - CHAR_W // 2
    rounded_rect(surf, th["body_outer"], (bx, by, CHAR_W, CHAR_H), 8)
    rounded_rect(surf, th["body_inner"],
                 (bx + 2, by + 2, CHAR_W - 4, CHAR_H - 4), 7)

    # Title bar
    rounded_rect(surf, th["title_bar"],
                 (bx + 2, by + 2, CHAR_W - 4, 10), 6)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        pygame.draw.circle(surf, c, (bx + 10 + i * 9, by + 7), 2)

    # Screen area
    scr = (bx + 6, by + 14, CHAR_W - 12, CHAR_H - 22)
    rounded_rect(surf, th["screen_bg"], scr, 4)

    # ── Eyes ──────────────────────────────────────────────────────
    sx, sy, sw, sh = scr
    ey = sy + sh // 2 - 2
    lex = sx + sw // 3
    rex = sx + 2 * sw // 3
    er = 8

    if blink and not wav:
        for ex in (lex, rex):
            pygame.draw.line(surf, th["eye_white"],
                             (ex - 6, ey), (ex + 6, ey), 2)
    elif cel:
        for ex in (lex, rex):
            pygame.draw.arc(surf, th["mouth_happy"],
                            (ex - 7, ey - 5, 14, 10),
                            math.radians(0), math.radians(180), 3)
    elif wav:
        for ex in (lex, rex):
            pygame.draw.circle(surf, th["eye_white"], (ex, ey), er + 1)
            pygame.draw.circle(surf, th["pupil"], (ex, ey), 5)
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 3), 2)
    else:
        for ex in (lex, rex):
            pygame.draw.circle(surf, th["eye_white"], (ex, ey), er)
            px = ex + math.sin(t * 0.6 + ex * 0.01) * 2
            py = ey + math.cos(t * 0.8) * 1.5
            pygame.draw.circle(surf, th["pupil"], (int(px), int(py)), 4)
            pygame.draw.circle(surf, (255, 255, 255), (ex - 2, ey - 3), 2)

    # ── Mouth ─────────────────────────────────────────────────────
    my = sy + sh - 6
    if cel:
        pygame.draw.arc(surf, th["mouth_happy"],
                        (cx - 10, my - 7, 20, 12),
                        math.radians(200), math.radians(340), 2)
    elif wav:
        pygame.draw.circle(surf, th["wave_eye"], (cx, my - 2), 4, 2)
    else:
        w_m = 10 + math.sin(t * 1.5) * 1
        pygame.draw.line(surf, th["mouth"],
                         (int(cx - w_m / 2), my),
                         (int(cx + w_m / 2), my), 2)

    # ── Attention indicator ───────────────────────────────────────
    if wav:
        pulse = (math.sin(t * 5) + 1) / 2
        alpha_val = int(180 + 75 * pulse)
        ix = cx + 30
        iy = int(by - 18 + math.sin(t * 3) * 4)
        bang_surf = pygame.Surface((20, 28), pygame.SRCALPHA)
        bang_color = (*th["wave_eye"], alpha_val)
        pygame.draw.rect(bang_surf, bang_color, (7, 2, 6, 14),
                         border_radius=3)
        pygame.draw.circle(bang_surf, bang_color, (10, 22), 3)
        surf.blit(bang_surf, (ix - 10, iy - 14))

    # ── Confetti ──────────────────────────────────────────────────
    alive = []
    for p in state.confetti:
        p[0] += p[2]; p[1] += p[3]; p[3] += 0.18; p[2] *= 0.99
        if p[1] < WIN_H + 10:
            alive.append(p)
            pygame.draw.rect(surf, p[4],
                             (int(p[0]), int(p[1]), p[5], p[5]))
    state.confetti = alive


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
                try:
                    msg = json.loads(data)
                    action = msg.get("action", "celebrate")
                except (json.JSONDecodeError, AttributeError):
                    pass
                print(f"[buddy] Signal: {action}")
                if action == "wave":
                    state.wave()
                else:
                    state.trigger()
        except socket.timeout:
            continue
        except Exception as e:
            print(f"[buddy] Socket error: {e}")


# ── System tray ───────────────────────────────────────────────────────
def create_tray(state):
    import pystray
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

    def on_celebrate(_icon, _item):
        state.trigger()

    def on_theme_dark(_icon, _item):
        state.set_theme("dark")

    def on_theme_light(_icon, _item):
        state.set_theme("light")

    def on_quit(icon, _item):
        state.should_quit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Test Celebration", on_celebrate),
        pystray.MenuItem("Theme", pystray.Menu(
            pystray.MenuItem(
                "Dark", on_theme_dark,
                checked=lambda _: state.theme_name == "dark"),
            pystray.MenuItem(
                "Light", on_theme_light,
                checked=lambda _: state.theme_name == "light"),
        )),
        pystray.MenuItem("Quit", on_quit),
    )
    pystray.Icon("clawd-buddy", img, "Clawd Buddy", menu).run()


# ── CLI ───────────────────────────────────────────────────────────────
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
            "  clawd-buddy --theme light  Use light theme\n"
            "  clawd-buddy --startup      Run at login/startup\n"
            "  clawd-buddy --no-startup   Remove from login/startup\n"
        ),
    )
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
    p.add_argument("--theme", choices=["dark", "light"], default="dark",
                   help="Color theme (default: dark)")
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

    # --startup / --no-startup
    if args.startup:
        enable_startup()
        sys.exit(0)
    if args.no_startup:
        disable_startup()
        sys.exit(0)

    # --send / --wave (signal a running instance)
    if args.send is not None or args.wave:
        action = "wave" if args.wave else "celebrate"
        payload = json.dumps({"action": action}).encode()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SOCK_HOST, port))
            s.sendall(payload)
            s.close()
            print(f"[buddy] Sent: {action}")
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
    state = BuddyState(theme_name=args.theme)
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

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_SPACE:
                    state.trigger()
                elif ev.key in (pygame.K_1, pygame.K_2,
                                pygame.K_3, pygame.K_4):
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_CTRL:
                        preset = ev.key - pygame.K_0
                        state.set_scale(preset)
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
