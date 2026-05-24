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
from .cli import parse_args, read_hook_stdin
from .config import (
    load_config,
    load_saved_sound_pack,
    load_saved_theme,
    save_config,
    save_sound_pack_pref,
    save_theme_pref,
)
from .constants import (
    CHAR_H, CHAR_W, FPS, SOCK_HOST, SOCK_PORT, TKEY, WIN_H, WIN_W,
)
from .ipc import send_signal, socket_listener
from .platform import (
    auto_detach,
    disable_startup,
    enable_startup,
    get_bg_fill,
    get_initial_position,
    get_window_handle,
    get_window_rect,
    move_window,
    raise_window,
    resize_window,
    setup_window,
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
            hook = read_hook_stdin()
            session_id = args.session_id or hook.get("session_id")
            if session_id:
                payload_obj["session_id"] = session_id
        else:
            payload_obj["action"] = "celebrate"
        if send_signal(payload_obj, port=port):
            print(f"[buddy] Sent: {payload_obj['action']}")
        else:
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
            auto_detach()
            # Daemon continues executing below

    # Single instance lock
    lock_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock_sock.bind(("127.0.0.1", port + 1))
    except OSError:
        print("[buddy] Already running — sending signal.")
        # Best-effort hello — the running buddy treats unknown actions as
        # a celebrate, but a malformed payload here would just be ignored.
        send_signal({"message": "hello"}, port=port)
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
