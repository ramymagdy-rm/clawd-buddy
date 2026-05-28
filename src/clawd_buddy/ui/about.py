# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""The About dialog and the shared buddy-silhouette icon.

M4 turned the dialog into a `ttk.Notebook` with two tabs:

  • **About** — the original version / author / link card.
  • **Reminders** — the rich editing surface for the water-drinking
    reminder (enable, interval, sound, quiet hours, plus a live
    countdown and a "Drank now" button).

tkinter is still imported lazily inside the worker so the buddy
launches on stripped-down Python installs without `_tkinter` — both
tabs degrade gracefully.

`_make_buddy_icon_image` is shared by the system-tray and the About
window because the buddy silhouette is the branding everywhere the
app shows itself.
"""

import threading

from .. import __version__ as APP_VERSION
from ..config import (
    REMINDER_INTERVALS,
    REMINDER_INTERVAL_LABELS,
    save_reminder_anchor_minute_pref,
    save_reminder_enabled_pref,
    save_reminder_interval_pref,
    save_reminder_quiet_hours_pref,
    save_reminder_sound_pref,
)
from .sound import REMINDER_SOUND_CHOICES, REMINDER_SOUND_OFF


_REPO_URL = "https://github.com/ramymagdy-rm/clawd-buddy"

# Reentrancy guard — the menu callback fires synchronously and a user
# can spam-click the About entry. Without this we'd spin up multiple
# Toplevels.
_ABOUT_DIALOG_OPEN = False

# Quiet-hours combobox values: every half-hour. 30-minute resolution
# covers the realistic schedules people actually keep without forcing
# users into a free-form text entry.
_HHMM_OPTIONS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def _interval_label_for(seconds):
    """Return the human label for a known interval, or the 1-hour label
    when the value isn't in the preset set. The combobox loader uses
    this so a hand-edited config that drifted out of range still shows
    *something* selected rather than rendering blank."""
    return REMINDER_INTERVAL_LABELS.get(
        seconds, REMINDER_INTERVAL_LABELS[REMINDER_INTERVALS[1]]
    )


def _interval_from_label(label):
    """Inverse of `_interval_label_for`. Returns the seconds value for
    a known label, or `None` when the string doesn't match any preset
    (the caller falls back to the current value in that case)."""
    for sec, lbl in REMINDER_INTERVAL_LABELS.items():
        if lbl == label:
            return sec
    return None


# Combobox values for the interval picker, in build order so the user
# scrolls from shortest to longest.
_INTERVAL_LABEL_OPTIONS = [
    REMINDER_INTERVAL_LABELS[s] for s in REMINDER_INTERVALS
]


def _make_buddy_icon_image():
    """Procedurally draw a 64x64 RGBA PIL Image of the buddy's face.

    Used as the system-tray icon and the About-dialog window icon so
    the buddy silhouette is the branding everywhere PIL is the right
    surface type. The pygame main window uses `make_buddy_icon_surface`
    below — same shape, different pixel container.
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


def make_buddy_icon_surface():
    """Return a 64×64 `pygame.Surface` of the buddy silhouette for
    `pygame.display.set_icon`, so the taskbar / Alt-Tab thumbnail shows
    the buddy face instead of the default pygame/Python feather.

    Built by converting the existing PIL icon through `pygame.image.
    frombytes` — keeps the silhouette identical to the tray + About
    icon without duplicating the procedural draw. Both `pygame` and
    `PIL` are required dependencies, so the import is unconditional;
    the caller is expected to have run `pygame.init()` already
    (`set_icon` insists on it on most platforms).
    """
    import pygame

    img = _make_buddy_icon_image()
    # `frombytes` is the post-2.3.0 spelling of the older `fromstring`.
    # `getattr` keeps the code working on older pygame builds in the
    # supported Python range, but prefers the new name when available
    # so the deprecation warning doesn't fire on modern installs.
    builder = getattr(pygame.image, "frombytes", None) \
        or pygame.image.fromstring
    return builder(img.tobytes(), img.size, img.mode)


def show_about_dialog(state=None):
    """Open the About dialog. Reentrant clicks are debounced — at most
    one dialog at a time. Spawned on its own thread so it doesn't block
    the tray menu (pystray's callbacks are synchronous) or the pygame
    loop.

    `state` is the live `BuddyState`; when provided, the Reminders
    tab edits its fields directly. When omitted (older callers or
    tests), the Reminders tab degrades to a read-only "no state
    attached" notice.
    """
    global _ABOUT_DIALOG_OPEN
    if _ABOUT_DIALOG_OPEN:
        return
    _ABOUT_DIALOG_OPEN = True
    threading.Thread(target=_run_about_dialog, args=(state,),
                     daemon=True).start()


def _format_seconds(secs):
    """Render a seconds-remaining value as a short human string for
    the Reminders-tab countdown label. Negative values (overdue)
    render as "now"."""
    if secs is None:
        return "—"
    if secs <= 0:
        return "now"
    if secs < 90:
        return f"in {int(secs)}s"
    mins = int(secs / 60)
    if mins < 90:
        return f"in {mins} min"
    hours = mins / 60
    return f"in {hours:.1f}h"


def _hhmm_to_minutes(text):
    """Parse an HH:MM string from the combobox into minutes-from-
    midnight. Returns None on garbage so callers can decide whether
    to fall back to the previous value or treat it as 'disabled'."""
    try:
        hh, mm = text.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        return h * 60 + m
    except (ValueError, AttributeError):
        return None


def _minutes_to_hhmm(minutes):
    """Inverse of `_hhmm_to_minutes`. Defaults to "00:00" for None so
    the combobox always has a visible value."""
    if not isinstance(minutes, int) or not (0 <= minutes < 1440):
        return "00:00"
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _run_about_dialog(state):
    global _ABOUT_DIALOG_OPEN
    try:
        import tkinter as tk
        from tkinter import ttk
        import webbrowser

        root = tk.Tk()
        root.title("About Clawd Buddy")
        root.resizable(False, False)

        # Replace the default tk feather icon with the buddy silhouette.
        # PhotoImage must be retained on `root` — tkinter doesn't keep
        # its own reference and the icon vanishes on GC otherwise.
        try:
            from PIL import ImageTk
            icon_photo = ImageTk.PhotoImage(_make_buddy_icon_image())
            root.iconphoto(True, icon_photo)
            root._buddy_icon_ref = icon_photo
        except Exception as ie:
            print(f"[buddy] About dialog icon failed: {ie}")

        notebook = ttk.Notebook(root)
        notebook.pack(expand=True, fill="both", padx=10, pady=10)

        _build_about_tab(notebook, webbrowser)
        _build_reminders_tab(notebook, state, root)

        # Center on screen — tk needs a refresh before geometry is known.
        root.update_idletasks()
        w = max(root.winfo_reqwidth(), 360)
        h = root.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception as e:
        print(f"[buddy] About dialog failed: {e}")
    finally:
        _ABOUT_DIALOG_OPEN = False


def _build_about_tab(notebook, webbrowser):
    """Build the existing About tab — version, author, repo link.
    Kept as a function for symmetry with `_build_reminders_tab`."""
    import tkinter as tk

    frame = tk.Frame(notebook, padx=24, pady=20)
    notebook.add(frame, text="About")

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


def _build_reminders_tab(notebook, state, root):
    """Build the Reminders tab — enable toggle, interval radios, sound
    combobox, quiet-hours combo pair, live countdown, Drank-now button.

    All changes save to `config.json` and mutate `state` immediately —
    no Save button. Tracks the live countdown via an `after()` loop so
    the user sees the next-fire time tick down without polling
    workarounds.
    """
    import tkinter as tk
    from tkinter import ttk

    frame = tk.Frame(notebook, padx=20, pady=16)
    notebook.add(frame, text="Reminders")

    if state is None:
        tk.Label(
            frame,
            text=("Reminder controls are only available when the\n"
                  "About dialog is opened from a running buddy."),
            font=("Segoe UI", 9),
            justify="center",
        ).pack(pady=20)
        return

    # ── Enable toggle ──────────────────────────────────────────
    enabled_var = tk.BooleanVar(value=bool(state.reminder_enabled))

    def on_enabled_change():
        state.set_reminder_enabled(enabled_var.get())
        save_reminder_enabled_pref(enabled_var.get())
        _refresh_widget_states()

    ttk.Checkbutton(
        frame,
        text="Remind me to drink water",
        variable=enabled_var,
        command=on_enabled_change,
    ).pack(anchor="w", pady=(0, 10))

    # ── Interval combobox ──────────────────────────────────────
    # Same scrolling-dropdown affordance as the quiet-hours selectors
    # below — keeps the Reminders tab visually uniform now that every
    # configurable value uses the same widget shape.
    tk.Label(frame, text="How often:",
             font=("Segoe UI", 9, "bold")).pack(anchor="w")
    interval_var = tk.StringVar(
        value=_interval_label_for(int(state.reminder_interval)))
    interval_combo = ttk.Combobox(
        frame,
        values=_INTERVAL_LABEL_OPTIONS,
        textvariable=interval_var,
        state="readonly",
        width=16,
    )
    interval_combo.pack(anchor="w", pady=(2, 10))

    def on_interval_change(_event=None):
        sec = _interval_from_label(interval_var.get())
        if sec is None:
            # Combobox can't normally emit an unknown label (readonly),
            # but guard anyway — silently snap the visible value back to
            # the current state rather than persisting garbage.
            interval_var.set(_interval_label_for(state.reminder_interval))
            return
        state.set_reminder_interval(sec)
        save_reminder_interval_pref(sec)

    interval_combo.bind("<<ComboboxSelected>>", on_interval_change)

    # ── Daily start time (HH:MM) ───────────────────────────────
    # M4.3 anchor — the wall-clock minute the schedule cycles from.
    # Same HH:MM combobox shape (30-min steps) as the quiet-hours
    # selectors. With interval=1h and start=09:00, reminders fire at
    # 09:00, 10:00, 11:00 … through the day.
    tk.Label(frame, text="Start reminders at:",
             font=("Segoe UI", 9, "bold")).pack(anchor="w")
    anchor_var = tk.StringVar(
        value=_minutes_to_hhmm(state.reminder_anchor_minute))
    anchor_combo = ttk.Combobox(
        frame, values=_HHMM_OPTIONS, textvariable=anchor_var,
        state="readonly", width=7)
    anchor_combo.pack(anchor="w", pady=(2, 10))

    def on_anchor_change(_event=None):
        m = _hhmm_to_minutes(anchor_var.get())
        if m is None:
            # Readonly combobox shouldn't emit garbage; snap back if
            # somehow it does rather than persisting an unparseable
            # anchor.
            anchor_var.set(_minutes_to_hhmm(state.reminder_anchor_minute))
            return
        state.set_reminder_anchor_minute(m)
        save_reminder_anchor_minute_pref(m)

    anchor_combo.bind("<<ComboboxSelected>>", on_anchor_change)

    # ── Sound combobox ─────────────────────────────────────────
    tk.Label(frame, text="Reminder sound:",
             font=("Segoe UI", 9, "bold")).pack(anchor="w")
    sound_var = tk.StringVar(value=state.reminder_sound)
    sound_combo = ttk.Combobox(
        frame,
        values=REMINDER_SOUND_CHOICES,
        textvariable=sound_var,
        state="readonly",
        width=12,
    )
    sound_combo.pack(anchor="w", pady=(2, 10))

    def on_sound_change(_event=None):
        state.set_reminder_sound(sound_var.get())
        save_reminder_sound_pref(sound_var.get())
        # Preview the new sound when it isn't 'off' so the user can
        # audition without waiting for the next interval to fire.
        if sound_var.get() != REMINDER_SOUND_OFF:
            state._pending_reminder_sound = sound_var.get()

    sound_combo.bind("<<ComboboxSelected>>", on_sound_change)

    # ── Quiet hours ────────────────────────────────────────────
    quiet_frame = tk.Frame(frame)
    quiet_frame.pack(anchor="w", pady=(0, 10))
    tk.Label(quiet_frame, text="Quiet hours (no reminders):",
             font=("Segoe UI", 9, "bold")).grid(row=0, column=0,
                                                columnspan=3, sticky="w")
    tk.Label(quiet_frame, text="from").grid(row=1, column=0, padx=(0, 4))

    quiet_start_var = tk.StringVar(
        value=_minutes_to_hhmm(state.reminder_quiet_start))
    quiet_end_var = tk.StringVar(
        value=_minutes_to_hhmm(state.reminder_quiet_end))

    quiet_start = ttk.Combobox(quiet_frame, values=_HHMM_OPTIONS,
                               textvariable=quiet_start_var,
                               state="readonly", width=7)
    quiet_start.grid(row=1, column=1)
    tk.Label(quiet_frame, text="to").grid(row=1, column=2, padx=4)
    quiet_end = ttk.Combobox(quiet_frame, values=_HHMM_OPTIONS,
                             textvariable=quiet_end_var,
                             state="readonly", width=7)
    quiet_end.grid(row=1, column=3)

    def on_quiet_change(_event=None):
        s = _hhmm_to_minutes(quiet_start_var.get())
        e = _hhmm_to_minutes(quiet_end_var.get())
        # Zero-length window ⇒ treat as disabled, like the M3 quiet
        # hours plumbing.
        if s == e:
            state.set_reminder_quiet_hours(None, None)
            save_reminder_quiet_hours_pref(None, None)
        else:
            state.set_reminder_quiet_hours(s, e)
            save_reminder_quiet_hours_pref(s, e)

    quiet_start.bind("<<ComboboxSelected>>", on_quiet_change)
    quiet_end.bind("<<ComboboxSelected>>", on_quiet_change)

    # ── Today's cup count (M4.1) ───────────────────────────────
    # Always visible — the count is meaningful even when the reminder
    # is disabled (you can still ack manually via the button below or
    # the tray's "I drank water" entry). Recent-days line sits under
    # the headline count; both refresh from the 1 Hz tick.
    cups_var = tk.StringVar(value="")
    cups_label = tk.Label(frame, textvariable=cups_var,
                          font=("Segoe UI", 11, "bold"))
    cups_label.pack(anchor="w", pady=(4, 0))

    recent_var = tk.StringVar(value="")
    recent_label = tk.Label(frame, textvariable=recent_var,
                            font=("Segoe UI", 9), fg="#666")
    recent_label.pack(anchor="w", pady=(0, 6))

    # ── Live status + Drank-now button ─────────────────────────
    status_var = tk.StringVar(value="")
    status_label = tk.Label(frame, textvariable=status_var,
                            font=("Segoe UI", 9), fg="#555")
    status_label.pack(anchor="w", pady=(4, 6))

    def on_drank():
        state.drink_acknowledged()
        # Bump the display immediately so the user sees the count tick
        # without waiting for the next 1 Hz refresh.
        _refresh_history_display()

    drank_btn = ttk.Button(frame, text="I drank water now",
                           command=on_drank)
    drank_btn.pack(anchor="w")

    # ── Refresh + tick loop ────────────────────────────────────
    def _refresh_widget_states():
        st = "normal" if enabled_var.get() else "disabled"
        combo_st = "readonly" if enabled_var.get() else "disabled"
        interval_combo.configure(state=combo_st)
        anchor_combo.configure(state=combo_st)
        sound_combo.configure(state=combo_st)
        quiet_start.configure(state=combo_st)
        quiet_end.configure(state=combo_st)
        # Drank-now button stays enabled even when the reminder is off
        # — the count is independent of the reminder firing.

    def _refresh_history_display():
        # Today line.
        cups = state.cups_today
        cups_var.set(f"{cups} cup{'s' if cups != 1 else ''} today")
        # Recent line — most recent first, e.g. "Recent: 6 · 5 · 7 · 4".
        if state.recent_days:
            counts = " · ".join(str(e["count"]) for e in state.recent_days)
            recent_var.set(f"Recent days: {counts}")
        else:
            recent_var.set("")

    def _tick_status():
        _refresh_history_display()
        if not enabled_var.get():
            status_var.set("Reminder disabled")
        elif state.reminder_active:
            status_var.set("Reminding now — press Space or click below")
        elif state.is_reminder_quiet_now():
            status_var.set("Quiet hours active — paused until morning")
        else:
            secs = state.reminder_seconds_until_next()
            status_var.set(f"Next reminder {_format_seconds(secs)}")
        # 1 Hz refresh — countdown ticks down visibly without spinning
        # the CPU. `after()` keeps the loop alive until the dialog is
        # destroyed, at which point tkinter cancels pending callbacks.
        try:
            root.after(1000, _tick_status)
        except tk.TclError:
            pass  # window closed

    _refresh_widget_states()
    _tick_status()
