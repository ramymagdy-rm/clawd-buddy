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
  --session-id ID  Explicit session id for --prompt-start / --send / --wave
                   (overrides stdin)
  --top            Signal running buddy to re-assert always-on-top and exit
  --quit           Ask the running buddy to exit cleanly and exit
  --theme THEME    Color theme — one of: dark, light, dracula, monokai,
                   nord, gruvbox, solarized, sunset (default: dark)
  --pomodoro W/B   Start a pomodoro cycle on the running buddy (minutes,
                   e.g. 25/5 — celebrates at break, waves back to work)
  --pomodoro-stop  End the running buddy's pomodoro cycle
  --http-port N    Also accept signals over HTTP on localhost:N
                   (POST /signal, GET /status — mirrors the TCP protocol)
  --http-token T   Require a Bearer token on every HTTP request
  --workspace L    Attach workspace label L to the outgoing signal
                   (one-letter badge above the buddy when several
                   workspaces are active; auto-derived from hook cwd)
  --help           Show this help and exit

Controls:
  Drag             Click and drag to reposition
  Space            Test celebration
  Ctrl+1..7        Size: S 1x / M 1.25x / L 1.5x / L+ 2x / XL 3x / XXL 4x /
                   XXXL 5x
  Escape           Quit

Switch themes from the system-tray right-click menu (Theme submenu)
or with the --theme CLI flag at launch.
"""

import json
import os
import sys

# Before anything can import pygame: keep its "Hello from the pygame
# community" banner out of hook output (Claude Code shows hook stdout).
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"

# Force X11 on Linux — Wayland restricts window positioning & always-on-top
if sys.platform == "linux":
    os.environ.setdefault("SDL_VIDEODRIVER", "x11")

# Only light modules at import time. Hooks run `clawd-buddy --send` /
# `--wave` / `--prompt-start` on every prompt, and those one-shot
# signals must not pay for pygame, Pillow, pystray or http.server —
# the GUI-only imports live in `_run_buddy`.
from .cli import parse_args, read_hook_stdin, workspace_label_from_cwd
from .config import load_saved_theme, save_theme_pref
from .constants import SOCK_PORT
from .ipc import request_status, send_signal


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
        from .platform import enable_startup
        enable_startup()
        sys.exit(0)
    if args.no_startup:
        from .platform import disable_startup
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

    # --send / --wave / --top / --quit / --prompt-start / --message /
    # --drank / --pomodoro / --pomodoro-stop / --settings
    # (any of these signals a running instance and exits)
    if (args.send is not None or args.wave or args.top or args.quit
            or args.prompt_start or args.message is not None or args.drank
            or args.pomodoro is not None or args.pomodoro_stop
            or args.settings is not None):
        payload_obj = {}
        # Claude Code passes hook metadata (session_id, cwd, …) as JSON
        # on stdin to every hook command; from a terminal there's none.
        hook = read_hook_stdin()
        if args.quit:
            payload_obj["action"] = "quit"
        elif args.top:
            payload_obj["action"] = "raise"
        elif args.wave:
            payload_obj["action"] = "wave"
        elif args.drank:
            # M4: external acknowledgment for the water-reminder.
            payload_obj["action"] = "drank"
        elif args.settings is not None:
            payload_obj["action"] = "settings"
            payload_obj["page"] = args.settings
        elif args.pomodoro_stop:
            # M6: end the running pomodoro cycle.
            payload_obj["action"] = "pomodoro_stop"
        elif args.pomodoro is not None:
            # M6: start a work/break cycle. The CLI validated the
            # minutes; the wire format is seconds (the state layer's
            # native unit).
            work_min, break_min = args.pomodoro
            payload_obj["action"] = "pomodoro_start"
            payload_obj["work_seconds"] = work_min * 60
            payload_obj["break_seconds"] = break_min * 60
        elif args.message is not None:
            payload_obj["action"] = "message"
            payload_obj["text"] = args.message
        elif args.prompt_start:
            payload_obj["action"] = "prompt_start"
        else:
            payload_obj["action"] = "celebrate"
        # Which Claude Code session is signaling, so the buddy can tell
        # concurrent sessions apart (one's Stop mustn't end another's
        # thinking). An explicit --session-id wins over the hook's. A
        # prompt without one falls back to the time-based new-session
        # heuristic; a Stop without one ends every session.
        if payload_obj["action"] in ("prompt_start", "celebrate", "wave"):
            session_id = args.session_id or hook.get("session_id")
            if session_id:
                payload_obj["session_id"] = session_id
        # M7: attach a workspace label to whatever signal is going out.
        # Explicit --workspace wins; otherwise derive from the hook
        # payload's cwd. Harmless extra key for receivers that don't care.
        workspace = args.workspace or workspace_label_from_cwd(hook.get("cwd"))
        if workspace:
            payload_obj["workspace"] = workspace
        if send_signal(payload_obj, port=port):
            print(f"[buddy] Sent: {payload_obj['action']}")
        else:
            print(f"[buddy] No buddy on port {port}")
            sys.exit(1)
        sys.exit(0)

    _run_buddy(args, port)


def _run_buddy(args, port):
    """Start the GUI buddy: detach, take the single-instance lock, open
    the window and run the render loop. Everything heavy is imported
    here so the one-shot signal path in `main` stays fast."""
    import socket
    import threading
    import time

    from .config import (
        load_saved_quiet_hours,
        load_saved_reduce_motion,
        load_saved_reminder_anchor_minute,
        load_saved_reminder_enabled,
        load_saved_reminder_interval,
        load_saved_reminder_quiet_hours,
        load_saved_reminder_sound,
        load_saved_scale_preset,
        load_saved_sound_pack,
        load_saved_volume,
        load_saved_workspace_badge,
        save_scale_pref,
    )
    from .constants import FPS_ACTIVE, FPS_IDLE, WIN_H, WIN_W
    from .ipc import socket_listener
    from .webhook import webhook_listener
    from .platform import (
        auto_detach,
        center_window,
        get_bg_fill,
        get_initial_position,
        get_window_handle,
        get_window_rect,
        get_work_areas,
        move_window,
        prepare_window_transparency,
        raise_window,
        resize_window,
        set_dpi_awareness,
        set_input_region,
        setup_window,
        window_has_alpha,
    )
    from . import history
    from .placement import DragPlacement, area_at, visible_limits
    from .state import BuddyState
    from .ui.about import make_buddy_icon_surface, show_about_dialog
    from .ui.drawing import (
        GROUND_Y, HIT_BOX, OFFSET_LIMITS, BuddyRenderer, compose_frame,
        frame_size_for)
    from .ui.sound import apply_volume, init_reminder_sounds, init_sounds
    from .ui.tray import create_tray

    import pygame

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
            # M6: the webhook listener lives in the detached process —
            # forward its flags or `--http-port` would silently vanish.
            if args.http_port is not None:
                cmd += ["--http-port", str(args.http_port)]
            if args.http_token is not None:
                cmd += ["--http-token", args.http_token]
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

    # Declare DPI awareness before any screen metric or window is created.
    # On scaled Windows 11 displays a DPI-unaware process reads a
    # shrunk logical screen size but a physical taskbar position, and
    # get_initial_position() then places the window off-screen (issue #1).
    # Must run before get_initial_position() and pygame.init() below.
    mode = set_dpi_awareness()
    if mode:
        print(f"[buddy] DPI awareness: {mode}")

    # Linux: request a 32-bit ARGB window so the background is truly
    # transparent instead of a solid rectangle around the buddy. Must
    # run before the window is created; no-op on Windows.
    alpha_mode = prepare_window_transparency()
    if alpha_mode:
        print(f"[buddy] Transparency: {alpha_mode}")

    # Compute initial window position (may init display subsystem)
    win_x, win_y = get_initial_position()
    os.environ["SDL_VIDEO_WINDOW_POS"] = f"{win_x},{win_y}"

    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.NOFRAME)
    pygame.display.set_caption("Clawd Buddy")
    # Brand the OS taskbar / Alt-Tab thumbnail with the buddy silhouette
    # instead of the default pygame/Python feather. Best-effort — a
    # failure here is purely cosmetic and must not block startup.
    try:
        pygame.display.set_icon(make_buddy_icon_surface())
    except Exception as e:
        print(f"[buddy] Window icon failed: {e}")
    clock = pygame.time.Clock()

    handle = get_window_handle()
    setup_window(handle, topmost=not args.no_topmost)

    topmost = not args.no_topmost
    # M3: load accessibility / comfort prefs (reduce-motion, volume,
    # quiet-hours) alongside the existing theme + sound-pack prefs so
    # the buddy launches with whatever the user last configured.
    # M4: load reminder prefs (enabled, interval, sound, reminder
    # quiet-hours) the same way.
    saved_volume = load_saved_volume()
    saved_quiet_start, saved_quiet_end = load_saved_quiet_hours()
    saved_reminder_qs, saved_reminder_qe = load_saved_reminder_quiet_hours()
    # M4.1: pre-seed the in-memory cup counter from ~/.clawd-buddy/
    # history.json so the count survives restarts. `history.load_
    # history()` degrades to `(None, [])` for any error so a missing
    # / corrupt file never blocks startup.
    saved_today, saved_recent = history.load_history()
    cups_today_seed = saved_today["count"] if saved_today else 0
    cups_today_date_seed = saved_today["date"] if saved_today else None
    state = BuddyState(
        theme_name=args.theme,
        sound_pack=load_saved_sound_pack(),
        reduce_motion=load_saved_reduce_motion(),
        volume=saved_volume,
        quiet_start=saved_quiet_start,
        quiet_end=saved_quiet_end,
        reminder_enabled=load_saved_reminder_enabled(),
        reminder_interval=load_saved_reminder_interval(),
        reminder_sound=load_saved_reminder_sound(),
        reminder_quiet_start=saved_reminder_qs,
        reminder_quiet_end=saved_reminder_qe,
        reminder_anchor_minute=load_saved_reminder_anchor_minute(),
        # M4.1 seed + persistence wiring.
        cups_today=cups_today_seed,
        cups_today_date=cups_today_date_seed,
        recent_days=saved_recent,
        history_save_fn=history.save_history,
        # M7: workspace-badge toggle (default on; only renders once a
        # second workspace signals anyway).
        workspace_badge_enabled=load_saved_workspace_badge(),
    )
    state.topmost = topmost

    # Audio is best-effort: init may fail on headless machines / containers /
    # missing audio device — we still run silently in that case. Every
    # pack's Sound objects are pre-built so tray previews are instant.
    sounds_by_pack = init_sounds(user_volume=saved_volume)
    # M4: reminder sounds live in their own dict (single sounds, not
    # celebrate/wave pairs) — built after init_sounds so we share the
    # already-initialised mixer.
    reminder_sounds = init_reminder_sounds(user_volume=saved_volume)

    if args.test:
        state.celebrate()

    # The size picked last time (tray Size menu / Ctrl+1..6). The window
    # opens at 1x on the taskbar and the first frame resizes it around
    # the buddy's feet.
    state.set_scale(load_saved_scale_preset())

    # The window has per-pixel alpha on Linux with a compositor; there
    # the frame is supersampled and filtered down for smooth edges.
    # Otherwise (Windows colour-key, bare X11) it's an opaque frame at
    # window size with hard edges. See ui/drawing.py.
    transparent = window_has_alpha(screen)
    renderer = BuddyRenderer()

    # Background threads
    threading.Thread(target=socket_listener, args=(state, port),
                     daemon=True).start()
    threading.Thread(target=create_tray, args=(state,),
                     daemon=True).start()
    # M6: optional HTTP webhook listener — a thin transport over the
    # same dispatch path as the TCP listener above. The `http_port`
    # mirror lets `--status` report the HTTP surface (same pattern as
    # `state.topmost`).
    if args.http_port is not None:
        state.http_port = args.http_port
        threading.Thread(
            target=webhook_listener,
            args=(state, args.http_port),
            kwargs={"token": args.http_token, "tcp_port": port},
            daemon=True,
        ).start()

    # Drag state. The window can only go as far as the window manager
    # allows (mutter keeps it inside the monitor's work area); past that
    # the character slides inside its own window, so it can still reach
    # the top and sides of the screen. See placement.py.
    placement = DragPlacement()
    work_areas = []
    reconcile_at = None

    def pointer_pos(ev_pos):
        """Pointer position on the desktop. Falls back to window origin
        + event position on pygame builds without `desktop=`."""
        try:
            return pygame.mouse.get_pos(desktop=True)
        except TypeError:
            wx, wy, _, _ = get_window_rect(handle)
            return wx + ev_pos[0], wy + ev_pos[1]

    def offset_limits_px():
        sc = state.scale
        return tuple(v * sc for v in OFFSET_LIMITS)

    def visible_box_px():
        """The character plus its ground shadow, in window pixels: what
        must stay on screen when the window is bigger than it."""
        sc = state.scale
        x, y, w, h = HIT_BOX
        return (x * sc, y * sc, w * sc, (h + 4) * sc)

    def limits_at(wx, wy):
        """Offset limits for the window at (wx, wy), kept to the visible
        part of the window when it's bigger than the monitor (XXXL)."""
        areas = work_areas or get_work_areas()
        if not areas:
            return offset_limits_px()
        w, h = screen.get_size()
        bx, by, bw, bh = visible_box_px()
        ox, oy = placement.offset
        here = (wx + bx + ox + bw / 2, wy + by + oy + bh / 2)
        return visible_limits(offset_limits_px(), (wx, wy, w, h),
                              (bx, by, bw, bh), area_at(areas, here))

    def settle(desired):
        """Aim the character at where it would be with its window at
        `desired`, wherever the window manager actually put the window,
        and check again once it has settled."""
        nonlocal reconcile_at
        wx, wy, _, _ = get_window_rect(handle)
        placement.aim(desired, (wx, wy), limits_at(wx, wy))
        sync_offset()
        reconcile_at = t + 0.3

    def sync_offset():
        sc = state.scale
        ox, oy = placement.offset
        renderer.offset = (ox / sc, oy / sc)

    # Only the character itself takes mouse input; clicks on the
    # transparent rest of the window reach whatever is behind it.
    applied_region = None
    region_recheck_at = None

    def update_input_region():
        nonlocal applied_region
        sc = state.scale
        x, y, w, h = renderer.hit_rect()
        region = (handle, int(x * sc), int(y * sc),
                  int(round(w * sc)), int(round(h * sc)))
        if region != applied_region:
            set_input_region(handle, [region[1:]])
            applied_region = region

    # Blink
    blink_timer = 0.0
    blink_interval = 3.5
    blink_dur = 0.12

    # Frame bookkeeping for partial updates: the frame surface (rebuilt
    # on resize), the region of it painted last frame (cleared before
    # the next draw), the screen region shown last frame (folded into
    # the next display update so the old pose gets erased) and the
    # background colour the frame was filled with.
    frame = None
    frame_dirty = None
    shown = None
    frame_bg = None

    running = True
    while running:
        # 60 FPS while something is moving fast (reactions, confetti,
        # an easing transition, a drag); 30 FPS for the ambient idle and
        # thinking loops, which keeps the idle CPU cost low.
        fast = placement.dragging or renderer.wants_fast_frames(state)
        dt = clock.tick(FPS_ACTIVE if fast else FPS_IDLE) / 1000.0
        t = time.time()

        if state.should_quit:
            break

        # Apply pending scale change
        if state._scale_changed:
            state._scale_changed = False
            # Grow or shrink around the buddy's feet, so it stays put.
            ox, oy = renderer.offset
            feet = ((WIN_W / 2 + ox) / WIN_W, (GROUND_Y + oy) / WIN_H)
            wx, wy, ow, oh = get_window_rect(handle)
            fx, fy = wx + ow * feet[0], wy + oh * feet[1]
            screen, handle = resize_window(handle, state.scale, topmost,
                                           anchor=feet)
            frame = None
            # Where the window would be with the feet in place and no
            # offset. A window bigger than the monitor (XXXL) gets
            # pinned to the top of the work area instead; the character
            # then slides up inside it to stay on screen.
            sc = state.scale
            work_areas = get_work_areas()
            settle((fx - WIN_W / 2 * sc, fy - GROUND_Y * sc))
            # The window manager may work out the clickable region
            # against the old size; set it again once the resize lands.
            region_recheck_at = t + 0.3

        # Apply pending bring-to-front request
        # Settings window asked for over IPC (`--settings`).
        if state._settings_requested is not None:
            page, state._settings_requested = state._settings_requested, None
            show_about_dialog(state, page or None)

        if state._raise_requested:
            state._raise_requested = False
            topmost = True
            state.topmost = True
            raise_window(handle)

        # Apply pending center-on-screen request (tray → main thread, so
        # the window move stays off the tray daemon thread).
        if state._center_requested:
            state._center_requested = False
            center_window(handle)
            placement.reset()
            work_areas = get_work_areas()
            wx, wy, _, _ = get_window_rect(handle)
            settle((wx, wy))

        # Shortly after a drag ends, check where the window manager
        # actually put the window and re-aim the character at the spot
        # the drag asked for, in case it clamped differently than the
        # published work areas predicted.
        if reconcile_at is not None and t >= reconcile_at:
            reconcile_at = None
            wx, wy, _, _ = get_window_rect(handle)
            if placement.reconcile((wx, wy), limits_at(wx, wy)):
                sync_offset()

        # M3: tray's Volume submenu mutates state.volume on the tray
        # thread and flips _volume_changed; the main loop re-applies
        # the multiplier to every cached pygame Sound. Same pattern
        # as _scale_changed — keeps mixer access single-threaded.
        # M4: include the reminder sounds in the re-apply pass so
        # the water drop also follows the volume slider.
        if state._volume_changed:
            state._volume_changed = False
            apply_volume(sounds_by_pack, state.volume,
                         reminder_sounds=reminder_sounds)

        # Drain pending notification sound. Producers (socket listener,
        # tray callbacks, key handler) just set the flag; playback happens
        # on the main thread to keep mixer access single-threaded. We look
        # up the pair for the *current* sound pack so tray previews fire
        # immediately when the user picks a new pack from the submenu.
        #
        # M3: skip playback when quiet hours are active. Animation still
        # plays — quiet hours are about audio comfort, not hiding the
        # visual signal.
        if state._pending_sound is not None:
            snd_name = state._pending_sound
            state._pending_sound = None
            if not state.is_quiet_now():
                pair = sounds_by_pack.get(state.sound_pack)
                if pair is not None:
                    snd = pair[0] if snd_name == "celebrate" else pair[1]
                    try:
                        snd.play()
                    except pygame.error as e:
                        print(f"[buddy] Sound play failed: {e}")

        # M4: drain pending reminder sound. Independent from the event
        # sound pipeline above — reminders have their own quiet-hours
        # window (state.is_reminder_quiet_now) and their own Sound dict.
        # The state's `_tick_reminder` already suppresses queueing
        # during reminder quiet hours, but we re-check at play time for
        # the same reason as the event pipeline: tray previews route
        # through the same flag and should respect the window too.
        if state._pending_reminder_sound is not None:
            rname = state._pending_reminder_sound
            state._pending_reminder_sound = None
            if not state.is_reminder_quiet_now():
                snd = reminder_sounds.get(rname)
                if snd is not None:
                    try:
                        snd.play()
                    except pygame.error as e:
                        print(f"[buddy] Reminder sound play failed: {e}")

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.WINDOWSIZECHANGED:
                applied_region = None   # re-send it for the new size
            elif ev.type in (pygame.WINDOWEXPOSED, pygame.VIDEOEXPOSE):
                # Without a compositor X11 forgets uncovered pixels, so
                # repaint the whole window, not just the dirty region.
                shown = None
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_SPACE:
                    # M4: Space is mode-aware. If a water reminder is
                    # firing, Space means "I drank" (acknowledge +
                    # reset timer). Otherwise it keeps its existing
                    # "test celebration" behaviour so users haven't
                    # lost a familiar shortcut. Only a celebration:
                    # sessions that are working keep thinking after it.
                    if state.reminder_active:
                        state.drink_acknowledged()
                    else:
                        state.celebrate()
                elif pygame.K_1 <= ev.key <= pygame.K_7:
                    # Ctrl+1..7 picks a size (S … XXXL), like the tray
                    # Size menu. Theme switching is via the tray only.
                    mods = pygame.key.get_mods()
                    if mods & pygame.KMOD_CTRL:
                        state.set_scale(ev.key - pygame.K_0)
                        save_scale_pref(ev.key - pygame.K_0)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                # Work areas change rarely (monitors, docks); one read
                # per drag is plenty.
                work_areas = get_work_areas()
                wx, wy, _, _ = get_window_rect(handle)
                placement.begin(pointer_pos(ev.pos), (wx, wy))
                reconcile_at = None
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 3:
                # Right-click opens the settings window (it runs on its
                # own thread; a second click just raises it).
                show_about_dialog(state)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if placement.dragging:
                    placement.end()
                    reconcile_at = t + 0.25
            elif ev.type == pygame.MOUSEMOTION and placement.dragging:
                tx, ty = placement.update(
                    pointer_pos(ev.pos), screen.get_size(), work_areas,
                    offset_limits_px(), box=visible_box_px())
                move_window(handle, tx, ty)
                sync_offset()

        state.update()

        # Blink
        blink_timer += dt
        phase = blink_timer % blink_interval
        is_blink = phase > blink_interval - blink_dur

        bg = get_bg_fill(state.theme_name, transparent)
        if frame is None or bg != frame_bg:
            frame = pygame.Surface(
                frame_size_for(screen.get_size(), transparent),
                pygame.SRCALPHA if transparent else 0)
            frame.fill(bg)
            frame_bg = bg
            shown = None
        elif frame_dirty is not None:
            frame.fill(bg, frame_dirty)
        if region_recheck_at is not None and t >= region_recheck_at:
            region_recheck_at = None
            applied_region = None
        update_input_region()
        renderer.draw(frame, t, state, is_blink)
        frame_dirty = renderer.dirty
        content = compose_frame(screen, frame, transparent, frame_dirty)
        if shown is None:
            pygame.display.flip()
        else:
            pygame.display.update(content.union(shown))
        shown = content

    pygame.quit()
    lock_sock.close()
    sys.exit()


if __name__ == "__main__":
    main()
