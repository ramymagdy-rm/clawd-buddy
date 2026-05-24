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

import json
import os
import socket
import sys
import threading
import time

from .cli import parse_args, read_hook_stdin
from .config import load_saved_sound_pack, load_saved_theme, save_theme_pref
from .constants import FPS, SOCK_PORT, WIN_H, WIN_W
from .ipc import request_status, send_signal, socket_listener
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
from .state import BuddyState
from .ui.drawing import draw_buddy
from .ui.sound import init_sounds
from .ui.tray import create_tray

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Force X11 on Linux — Wayland restricts window positioning & always-on-top
if sys.platform == "linux":
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")

import pygame





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

    # --status — request/response: ask the running buddy for its state
    # and print the JSON to stdout. Exit 1 if no buddy is listening.
    if args.status:
        info = request_status(port=port)
        if info is None:
            print(f"[buddy] No buddy on port {port}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(info, indent=2))
        sys.exit(0)

    # --send / --wave / --top / --quit / --prompt-start / --message
    # (any of these signals a running instance and exits)
    if (args.send is not None or args.wave or args.top or args.quit
            or args.prompt_start or args.message is not None):
        payload_obj = {}
        if args.quit:
            payload_obj["action"] = "quit"
        elif args.top:
            payload_obj["action"] = "raise"
        elif args.wave:
            payload_obj["action"] = "wave"
        elif args.message is not None:
            payload_obj["action"] = "message"
            payload_obj["text"] = args.message
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
    state.topmost = topmost

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
            state.topmost = True
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
