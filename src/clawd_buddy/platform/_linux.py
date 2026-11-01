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
_xext = None  # libXext (SHAPE extension); False when unavailable

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

class _XVisualInfo(ctypes.Structure):
    """Mirror of Xlib's XVisualInfo (filled in by XMatchVisualInfo)."""
    _fields_ = [
        ("visual", ctypes.c_void_p),
        ("visualid", ctypes.c_ulong),
        ("screen", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("c_class", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
        ("colormap_size", ctypes.c_int),
        ("bits_per_rgb", ctypes.c_int),
    ]

_TRUE_COLOR = 4  # Xlib visual class constant

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

        _x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
        _x11.XDefaultScreen.restype = ctypes.c_int

        _x11.XMatchVisualInfo.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(_XVisualInfo),
        ]
        _x11.XMatchVisualInfo.restype = ctypes.c_int

        _x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        _x11.XGetSelectionOwner.restype = ctypes.c_ulong

        _x11.XGetWindowProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_long, ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        _x11.XGetWindowProperty.restype = ctypes.c_int

        _x11.XFree.argtypes = [ctypes.c_void_p]
        _x11.XFree.restype = ctypes.c_int

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

def _linux_root_cardinals(name):
    """Read a CARDINAL[] property off the root window as a list of ints,
    or None when it isn't set."""
    if not _linux_init_x11():
        return None
    atom = _x11.XInternAtom(_x11_display, name.encode(), 1)
    if not atom:
        return None
    root = _x11.XDefaultRootWindow(_x11_display)
    act_type = ctypes.c_ulong()
    act_format = ctypes.c_int()
    n_items = ctypes.c_ulong()
    after = ctypes.c_ulong()
    data = ctypes.c_void_p()
    XA_CARDINAL = 6
    status = _x11.XGetWindowProperty(
        _x11_display, root, atom, 0, 1024, 0, XA_CARDINAL,
        ctypes.byref(act_type), ctypes.byref(act_format),
        ctypes.byref(n_items), ctypes.byref(after), ctypes.byref(data))
    if status != 0 or not data.value:
        return None
    try:
        if act_format.value != 32:
            return None
        # Format-32 properties come back as C longs, whatever their size.
        arr = ctypes.cast(data, ctypes.POINTER(ctypes.c_long))
        return [int(arr[i]) for i in range(n_items.value)]
    finally:
        _x11.XFree(data)

def _linux_get_work_areas():
    """Usable screen rectangles (x, y, w, h), one per monitor when the
    window manager says so.

    Mutter keeps client-moved windows fully inside a monitor's work area
    (below the top bar, right of the dock). It publishes those per-monitor
    areas in `_GTK_WORKAREAS_D<desktop>`; other window managers only set
    the single `_NET_WORKAREA` rectangle, used as a fallback. Returns []
    when neither is available.
    """
    desktop = _linux_root_cardinals("_NET_CURRENT_DESKTOP")
    d = desktop[0] if desktop else 0
    for name, index in ((f"_GTK_WORKAREAS_D{d}", None),
                        ("_NET_WORKAREA", d)):
        vals = _linux_root_cardinals(name)
        if not vals or len(vals) % 4:
            continue
        rects = [tuple(vals[i:i + 4]) for i in range(0, len(vals), 4)]
        if index is not None:
            rects = [rects[index]] if index < len(rects) else rects[:1]
        rects = [r for r in rects if r[2] > 0 and r[3] > 0]
        if rects:
            return rects
    return []

class _XRectangle(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short),
                ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]

def _linux_init_xext():
    global _xext
    if _xext is None:
        try:
            lib = ctypes.cdll.LoadLibrary("libXext.so.6")
            lib.XShapeCombineRectangles.argtypes = [
                ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, ctypes.POINTER(_XRectangle),
                ctypes.c_int, ctypes.c_int, ctypes.c_int]
            lib.XShapeCombineRectangles.restype = None
            lib.XShapeQueryExtension.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int)]
            lib.XShapeQueryExtension.restype = ctypes.c_int
            ev, err = ctypes.c_int(), ctypes.c_int()
            ok = (_linux_init_x11() and lib.XShapeQueryExtension(
                _x11_display, ctypes.byref(ev), ctypes.byref(err)))
            _xext = lib if ok else False
        except (OSError, AttributeError):
            _xext = False
    return _xext or None

def _linux_set_input_region(window_id, rects):
    """Limit where the window accepts mouse input to `rects` (window
    pixels, (x, y, w, h)). Clicks anywhere else go to whatever is behind
    the buddy instead of being swallowed by its transparent window.
    Returns True when the region was applied."""
    lib = _linux_init_xext()
    if lib is None or not window_id:
        return False
    arr = (_XRectangle * len(rects))(*[
        _XRectangle(int(x), int(y), max(0, int(w)), max(0, int(h)))
        for x, y, w, h in rects])
    SHAPE_INPUT, SHAPE_SET, UNSORTED = 2, 0, 0
    lib.XShapeCombineRectangles(_x11_display, window_id, SHAPE_INPUT, 0, 0,
                                arr, len(rects), SHAPE_SET, UNSORTED)
    _x11.XFlush(_x11_display)
    return True

def _linux_compositor_running():
    """True when a compositing manager owns the _NET_WM_CM_Sn selection.

    Only a compositor honours a window's alpha channel; without one an
    ARGB window's transparent pixels render as solid black."""
    if not _linux_init_x11():
        return False
    screen = _x11.XDefaultScreen(_x11_display)
    atom = _x11.XInternAtom(
        _x11_display, f"_NET_WM_CM_S{screen}".encode(), 0)
    return _x11.XGetSelectionOwner(_x11_display, atom) != 0

def _linux_find_argb_visual():
    """Return the id of a 32-bit TrueColor (ARGB) visual, or None."""
    if not _linux_init_x11():
        return None
    vinfo = _XVisualInfo()
    screen = _x11.XDefaultScreen(_x11_display)
    if not _x11.XMatchVisualInfo(
            _x11_display, screen, 32, _TRUE_COLOR, ctypes.byref(vinfo)):
        return None
    return vinfo.visualid

def _linux_prepare_argb_window():
    """Ask SDL for a window with a real alpha channel. Must run before
    the window is created. Returns a short description for the startup
    log, or None when per-pixel alpha isn't available.

    X11 has no colour-key transparency like Win32's LWA_COLORKEY, so
    the window background used to be painted with the theme's `bg_fill`.
    That only blends in on a matching panel; on GNOME (Ubuntu 22.04+,
    Wayland via XWayland) the buddy sits over the desktop instead, so you
    see a black rectangle around it. A 32-bit ARGB visual plus a
    compositor gives true per-pixel transparency instead.

    Two SDL settings are needed, both read from the environment:
      * SDL_VIDEO_X11_WINDOW_VISUALID makes SDL create the window with
        the ARGB visual instead of the default 24-bit one.
      * SDL_FRAMEBUFFER_ACCELERATION=0 makes the window surface use the
        native X11 framebuffer, whose pixel format follows the window's
        visual (ARGB8888). The default OpenGL-texture framebuffer always
        picks a format with no alpha, so the window would stay opaque.

    `setdefault` keeps any value the user exported themselves. Whether
    it actually worked is checked afterwards from the display surface's
    alpha mask (see `platform.window_has_alpha`), so a failure here just
    leaves the old opaque `bg_fill` background.
    """
    if os.environ.get("SDL_VIDEODRIVER", "x11") != "x11":
        return None
    if not _linux_compositor_running():
        return None
    visual = _linux_find_argb_visual()
    if visual is None:
        return None
    os.environ.setdefault("SDL_VIDEO_X11_WINDOW_VISUALID", hex(visual))
    os.environ.setdefault("SDL_FRAMEBUFFER_ACCELERATION", "0")
    return (f"per-pixel alpha "
            f"(visual {os.environ['SDL_VIDEO_X11_WINDOW_VISUALID']})")

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

# ═══════════════════════════════════════════════════════════════════
# App launcher — so the dock (and Activities search) shows the buddy
# ═══════════════════════════════════════════════════════════════════
# GNOME, KDE and friends name and draw a window in the dock from the
# .desktop file whose StartupWMClass matches the window's WM_CLASS.
# Without one the settings window shows up as "app.py" with a generic
# icon. Installed per user, refreshed on every start.
WM_CLASS = "clawd-buddy"
_LAUNCHER_DIR = os.path.expanduser("~/.local/share/applications")
_ICON_PATH = os.path.expanduser(
    "~/.local/share/icons/hicolor/256x256/apps/clawd-buddy.png")


def _desktop_quote(arg):
    """Quote one Exec argument per the Desktop Entry spec."""
    arg = arg.replace("%", "%%")   # % starts a field code
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def launcher_command(argv0=None, python=None):
    """The command that starts this very install of the buddy: its
    `clawd-buddy` script when it was started through one, otherwise
    `python -m clawd_buddy.app` with the running interpreter."""
    argv0 = argv0 if argv0 is not None else sys.argv[0]
    python = python or sys.executable
    if (os.path.basename(argv0).startswith("clawd-buddy")
            and os.path.isfile(argv0)):
        return [os.path.abspath(argv0)]
    return [python, "-m", "clawd_buddy.app"]


def launcher_desktop_entry(cmd, icon_path):
    """Text of the launcher .desktop file for the command `cmd`."""
    exe = " ".join(_desktop_quote(a) for a in cmd)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Clawd Buddy\n"
        "GenericName=Desktop pet\n"
        "Comment=An animated desktop pet that reacts to Claude Code\n"
        f"Exec={exe}\n"
        f"Icon={icon_path}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        "Keywords=claude;pet;buddy;pomodoro;\n"
        f"StartupWMClass={WM_CLASS}\n"
        "StartupNotify=false\n"
        "Actions=settings;quit;\n"
        "\n"
        "[Desktop Action settings]\n"
        "Name=Settings\n"
        f"Exec={exe} --settings\n"
        "\n"
        "[Desktop Action quit]\n"
        "Name=Quit\n"
        f"Exec={exe} --quit\n"
    )


def _write_if_changed(path, data):
    """Write `data` (bytes) to `path` unless it already holds exactly
    that. Returns True when it wrote."""
    try:
        with open(path, "rb") as f:
            if f.read() == data:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return True


def _linux_install_launcher(icon_png):
    """Install (or refresh) the per-user launcher and its icon.
    `icon_png` is the 256×256 icon as PNG bytes."""
    _write_if_changed(_ICON_PATH, icon_png)
    entry = launcher_desktop_entry(launcher_command(), _ICON_PATH)
    path = os.path.join(_LAUNCHER_DIR, _DESKTOP_NAME)
    return _write_if_changed(path, entry.encode())


def _linux_disable_startup():
    path = os.path.join(_LINUX_AUTOSTART_DIR, _DESKTOP_NAME)
    if os.path.exists(path):
        os.remove(path)
        print(f"[buddy] Disabled run at login")
        print(f"        Removed {path}")
    else:
        print(f"[buddy] Not in autostart (nothing to remove)")

def _linux_startup_enabled():
    return os.path.exists(os.path.join(_LINUX_AUTOSTART_DIR, _DESKTOP_NAME))

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

