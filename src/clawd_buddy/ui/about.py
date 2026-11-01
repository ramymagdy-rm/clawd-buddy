# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""The settings & About window, and the shared buddy-silhouette icon.

One window controls everything the tray menu does, and more. A sidebar
switches between five pages:

  • **Buddy**: live status, Celebrate / Bring to front / Center, size,
    theme, reduce motion, workspace badges, start at login.
  • **Sound**: sound pack, volume, quiet hours.
  • **Reminders**: today's cups, recent days, and the water-reminder
    schedule (interval, first reminder, sound, overnight pause).
  • **Focus**: the pomodoro timer, with a live countdown ring.
  • **About**: version, links, keyboard shortcuts.

Every change applies to the running buddy at once and is saved; there
is no Save button. The window polls the live state a few times a
second, so changes from the tray or the keyboard show up here too.

Open it from the tray ("Settings & About…") or by right-clicking the
buddy. It runs Tk on its own thread; tkinter and Pillow are imported
lazily so the buddy still launches on Pythons without `_tkinter`.

`_make_buddy_icon_image` is shared by the system tray and this window
because the buddy silhouette is the branding everywhere the app shows
itself.
"""

import datetime
import os
import threading

from .. import __version__ as APP_VERSION
from ..constants import SETTINGS_PAGES
from ..config import (
    REMINDER_INTERVALS,
    REMINDER_INTERVAL_LABELS,
    VOLUME_STEPS,
    _config_dir,
    save_quiet_hours_pref,
    save_reduce_motion_pref,
    save_reminder_anchor_minute_pref,
    save_reminder_enabled_pref,
    save_reminder_interval_pref,
    save_reminder_quiet_hours_pref,
    save_reminder_sound_pref,
    save_scale_pref,
    save_sound_pack_pref,
    save_theme_pref,
    save_volume_pref,
    save_workspace_badge_pref,
)
from .sound import (
    REMINDER_SOUND_CHOICES,
    REMINDER_SOUND_OFF,
    SOUND_PACK_NAMES,
    SOUND_PACK_OFF,
)


_REPO_URL = "https://github.com/ramymagdy-rm/clawd-buddy"

# Reentrancy guard: the tray callback fires synchronously and a user
# can spam-click the menu entry. A second request raises the open
# window (and switches page) instead of spinning up another Tk.
_ABOUT_DIALOG_OPEN = False
_RAISE_REQUEST = None   # None, or the page to show ("" = keep page)

PAGES = SETTINGS_PAGES

# Quiet-hours pickers: every half-hour.
_HHMM_OPTIONS = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
_HALF_HOURS = list(range(0, 24 * 60, 30))

# Pomodoro length picker (minutes).
_POMODORO_MINUTES = (1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60,
                     75, 90, 105, 120, 150, 180)

# Status colours, the same as the buddy's pill (drawing.ACCENT; that
# module imports pygame, so they're repeated here and a test keeps the
# two in step).
STATUS_COLORS = {
    "celebrating": (72, 214, 120),
    "waving":      (255, 196, 61),
    "greeting":    (64, 186, 230),
    "thinking":    (168, 140, 240),
}
_IDLE_COLOR = (128, 130, 150)

_MODE_TITLES = {
    "idle":        "Idle",
    "thinking":    "Thinking",
    "celebrating": "Done!",
    "waving":      "Needs your input",
    "greeting":    "New session",
}

_INTERVAL_SHORT = {
    30 * 60: "30m", 60 * 60: "1h", 90 * 60: "1.5h", 120 * 60: "2h",
    240 * 60: "4h",
}


def _interval_label_for(seconds):
    """Return the human label for a known interval, or the 1-hour label
    when the value isn't in the preset set, so a hand-edited config
    that drifted out of range still shows something sensible."""
    return REMINDER_INTERVAL_LABELS.get(
        seconds, REMINDER_INTERVAL_LABELS[REMINDER_INTERVALS[1]]
    )


def _interval_from_label(label):
    """Inverse of `_interval_label_for`. Returns the seconds value for
    a known label, or `None` when the string doesn't match any preset."""
    for sec, lbl in REMINDER_INTERVAL_LABELS.items():
        if lbl == label:
            return sec
    return None


# Interval labels in build order, shortest to longest.
_INTERVAL_LABEL_OPTIONS = [
    REMINDER_INTERVAL_LABELS[s] for s in REMINDER_INTERVALS
]


def _format_seconds(secs):
    """Seconds-remaining as a short phrase for the reminder countdown.
    Negative values (overdue) render as "now"."""
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


def _format_clock(secs):
    """Seconds as a countdown clock: 24:59, or 1:05:00 past an hour."""
    secs = max(0, int(round(secs or 0)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _hhmm_to_minutes(text):
    """Parse HH:MM into minutes from midnight; None on garbage."""
    try:
        hh, mm = text.split(":")
        h, m = int(hh), int(mm)
        if not (0 <= h < 24 and 0 <= m < 60):
            return None
        return h * 60 + m
    except (ValueError, AttributeError):
        return None


def _minutes_to_hhmm(minutes):
    """Inverse of `_hhmm_to_minutes`. "00:00" for None or garbage."""
    if not isinstance(minutes, int) or not (0 <= minutes < 1440):
        return "00:00"
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _short_path(path, limit=44):
    """`path` with the home folder as ~, cut in the middle if long."""
    home = os.path.expanduser("~")
    if home and path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) > limit:
        keep = (limit - 1) // 2
        path = path[:keep] + "…" + path[-keep:]
    return path


def _span_text(start, end):
    """How a quiet-hours window reads: "Overnight, 9 hours"."""
    if start == end:
        return "Start and end are the same"
    mins = (end - start) % (24 * 60)
    h, m = divmod(mins, 60)
    length = f"{h} hour{'s' if h != 1 else ''}" + (f" {m} min" if m else "")
    return ("Overnight, " if end < start else "") + length


def _rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def status_summary(state):
    """(title, colour hex, detail) describing what the buddy is doing,
    for the sidebar and the Buddy page."""
    mode = getattr(state, "mode", "idle")
    n = state.working_sessions
    title = _MODE_TITLES.get(mode, mode.title())
    if mode == "thinking" and n > 1:
        title = f"Thinking ×{n}"
    color = _rgb_hex(STATUS_COLORS.get(mode, _IDLE_COLOR))
    if n == 1:
        detail = "1 Claude Code session working"
    elif n > 1:
        detail = f"{n} Claude Code sessions working"
    elif state.reminder_active:
        detail = "Time to drink some water"
    elif state.pomodoro_active:
        phase = "Focus" if state.pomodoro_phase == "work" else "Break"
        left = _format_clock(state.pomodoro_seconds_remaining())
        detail = f"{phase} · {left} left"
    else:
        detail = "Waiting for Claude Code"
    return title, color, detail


def week_bars(state, today=None):
    """Recent drinking history as [(weekday, cups)], oldest first,
    ending with today. Up to seven bars."""
    today = today or datetime.date.today()

    def label(iso):
        try:
            return datetime.date.fromisoformat(iso).strftime("%a")[:2]
        except (TypeError, ValueError):
            return "?"
    past = [(label(e.get("date")), int(e.get("count", 0)))
            for e in list(state.recent_days)[:6]]
    past.reverse()
    return past + [(today.strftime("%a")[:2], int(state.cups_today))]


def _make_buddy_icon_image():
    """Procedurally draw a 64x64 RGBA PIL Image of the buddy's face.

    Used as the system-tray icon and the About-dialog window icon so
    the buddy silhouette is the branding everywhere PIL is the right
    surface type. The pygame main window uses `make_buddy_icon_surface`
    below — same shape, different pixel container.

    It's the in-app character simplified for small sizes: the rounded
    body, the dark screen with two glowing pill eyes and a smile, and
    the feet. Authored on a 40×40 grid and scaled to fill the canvas
    with a 2px margin — Windows shrinks the tray image to ~16–24px, so
    any padding baked into the 64px source makes the buddy look tiny
    next to other tray icons. Drawn 4× oversized and LANCZOS-downsampled
    so edges stay antialiased at small sizes.
    """
    from PIL import Image, ImageDraw

    size, ss, margin = 64, 4, 2
    k = (size - 2 * margin) / 40 * ss  # design unit -> supersampled px

    def p(x, y):
        return (margin * ss + x * k, margin * ss + y * k)

    def box(x0, y0, x1, y1):
        return [*p(x0, y0), *p(x1, y1)]

    outer, inner, bevel = (35, 35, 48), (42, 42, 58), (70, 70, 88)
    screen, face, shoe = (22, 22, 32), (230, 235, 255), (50, 50, 68)
    blush = (150, 72, 96)

    img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(box(6, 33, 17, 40), radius=3.5 * k, fill=shoe)
    d.rounded_rectangle(box(23, 33, 34, 40), radius=3.5 * k, fill=shoe)
    d.rounded_rectangle(box(0, 0, 40, 36), radius=11 * k, fill=outer)
    d.rounded_rectangle(box(1.5, 1.5, 38.5, 32.5), radius=10 * k, fill=bevel)
    d.rounded_rectangle(box(1.5, 2.5, 38.5, 32.5), radius=10 * k, fill=inner)
    d.rounded_rectangle(box(4, 8, 36, 30), radius=7 * k, fill=screen)
    for x, c in ((8, (255, 95, 86)), (11, (255, 189, 46)), (14, (39, 201, 63))):
        d.ellipse(box(x - 1, 3.6, x + 1, 5.6), fill=c)
    d.rounded_rectangle(box(11.5, 13, 16.5, 21), radius=2.5 * k, fill=face)
    d.rounded_rectangle(box(23.5, 13, 28.5, 21), radius=2.5 * k, fill=face)
    d.ellipse(box(14.2, 14, 15.8, 15.6), fill=screen)
    d.ellipse(box(26.2, 14, 27.8, 15.6), fill=screen)
    d.ellipse(box(6.5, 21.5, 11, 23.8), fill=blush)
    d.ellipse(box(29, 21.5, 33.5, 23.8), fill=blush)
    d.arc(box(16.5, 21, 23.5, 26.5), start=20, end=160, fill=face,
          width=round(1.6 * k))
    return img.resize((size, size), Image.LANCZOS)


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




def show_about_dialog(state=None, page=None):
    """Open the settings & About window on its own thread, so it blocks
    neither the tray menu (pystray callbacks are synchronous) nor the
    pygame loop. If it's already open, raise it (and switch to `page`).

    `state` is the live `BuddyState`. Without one (older callers,
    tests) only the About page is shown.
    """
    global _ABOUT_DIALOG_OPEN, _RAISE_REQUEST
    if _ABOUT_DIALOG_OPEN:
        _RAISE_REQUEST = page or ""
        return
    _ABOUT_DIALOG_OPEN = True
    _RAISE_REQUEST = None
    threading.Thread(target=_run_about_dialog, args=(state, page),
                     daemon=True).start()


def _run_about_dialog(state, page=None):
    global _ABOUT_DIALOG_OPEN
    try:
        import tkinter as tk

        root = tk.Tk(className="clawd-buddy")
        root.withdraw()
        root.title("Clawd Buddy")
        root.resizable(False, False)
        try:
            from PIL import ImageTk
            icon_photo = ImageTk.PhotoImage(_make_buddy_icon_image(),
                                            master=root)
            root.iconphoto(True, icon_photo)
            root._buddy_icon_ref = icon_photo
        except Exception as ie:
            print(f"[buddy] Settings window icon failed: {ie}")

        ControlCenter(root, state, page)

        # Centre on screen once Tk knows the natural size.
        root.update_idletasks()
        w, h = root.winfo_reqwidth(), root.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 2)}")
        root.deiconify()
        # Open above everything (the buddy is always on top), then
        # behave like a normal window.
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        root.after(600, lambda: root.attributes("-topmost", False))
        root.protocol("WM_DELETE_WINDOW", root.destroy)
        root.mainloop()
    except Exception as e:
        print(f"[buddy] Settings window failed: {e}")
    finally:
        _ABOUT_DIALOG_OPEN = False


class ControlCenter:
    """Builds the window into `root` and keeps it in sync with `state`."""

    TICK_MS = 400

    def __init__(self, root, state, page=None):
        import tkinter as tk
        from . import tkkit

        self.tk = tk
        self.root = root
        self.state = state
        # No text fields here, so no input method either. On X11 Tk
        # otherwise asks the input method (ibus, fcitx) for a context
        # for every widget it shows; when that daemon is busy, the
        # window took over 40 seconds to appear.
        try:
            root.tk.call("tk", "useinputmethods", "-displayof", root, 0)
        except tk.TclError:
            pass
        palette =tkkit.DARK if tkkit.system_prefers_dark() else tkkit.LIGHT
        self.kit = kit = tkkit.Kit(root, palette)
        self.k = tkkit
        self.p = p = palette
        root.configure(bg=p["bg"])

        self.side = tk.Frame(root, bg=p["side"], width=kit.px(212))
        self.side.pack(side="left", fill="y")
        self.side.pack_propagate(False)
        main = tk.Frame(root, bg=p["bg"])
        main.pack(side="left", fill="both", expand=True)
        self.stack = tk.Frame(main, bg=p["bg"])
        self.stack.pack(fill="both", expand=True, padx=kit.px(28),
                        pady=(kit.px(22), kit.px(26)))
        self.stack.grid_columnconfigure(0, weight=1)
        self.stack.grid_rowconfigure(0, weight=1)

        builders = {
            "buddy": ("Buddy", "buddy", self._build_buddy),
            "sound": ("Sound", "sound", self._build_sound),
            "reminders": ("Reminders", "water", self._build_reminders),
            "focus": ("Focus", "focus", self._build_focus),
            "about": ("About", "info", self._build_about),
        }
        keys = PAGES if state is not None else ("about",)
        self.pages, self.nav = {}, {}
        # Main controls by name, for tests and the raise-to-page path.
        self.controls = {}
        self._build_sidebar(keys, builders)
        for key in keys:
            frame = tk.Frame(self.stack, bg=p["bg"])
            frame.grid(row=0, column=0, sticky="nsew")
            builders[key][2](frame)
            self.pages[key] = frame
        self.current = None
        self.show(page if page in self.pages else keys[0])

        root.bind("<Escape>", lambda _e: root.destroy())
        root.bind("<Control-w>", lambda _e: root.destroy())
        self._tick()

    # ── Navigation ───────────────────────────────────────────────
    def show(self, key):
        if key not in self.pages or key == self.current:
            return
        self.current = key
        self.pages[key].tkraise()
        for k, item in self.nav.items():
            item.selected = k == key
            item.draw()

    def _tick(self):
        global _RAISE_REQUEST
        if _RAISE_REQUEST is not None:
            page, _RAISE_REQUEST = _RAISE_REQUEST, None
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            if page:
                self.show(page)
        self.kit.refresh_all()
        try:
            self.root.after(self.TICK_MS, self._tick)
        except self.tk.TclError:
            pass  # window closed

    # ── Layout helpers ───────────────────────────────────────────
    def _header(self, parent, title, subtitle):
        tk, p, kit = self.tk, self.p, self.kit
        tk.Label(parent, text=title, font=kit.f_title, fg=p["text"],
                 bg=p["bg"], anchor="w").pack(fill="x")
        tk.Label(parent, text=subtitle, font=kit.f_body, fg=p["muted"],
                 bg=p["bg"], anchor="w").pack(fill="x",
                                              pady=(kit.px(2), kit.px(14)))

    def _section(self, parent, title=None):
        tk, p, kit = self.tk, self.p, self.kit
        if title:
            tk.Label(parent, text=title.upper(), font=kit.f_small,
                     fg=p["faint"], bg=p["bg"], anchor="w").pack(
                fill="x", pady=(kit.px(4), kit.px(6)), padx=kit.px(4))
        card = self.k.Card(parent, kit)
        card.pack(fill="x", pady=(0, kit.px(14)))
        card.rows = 0
        return card

    def _row(self, card, title, sub=None, stacked=False):
        """A labelled row in a card. Returns (control_frame, sub_label);
        put the control in control_frame. `stacked` puts the control
        under the label instead of at the right."""
        tk, p, kit = self.tk, self.p, self.kit
        body = card.body
        if card.rows:
            tk.Frame(body, bg=p["border"], height=1).pack(
                fill="x", pady=kit.px(11))
        card.rows += 1
        row = tk.Frame(body, bg=p["card"])
        row.pack(fill="x")
        text = tk.Frame(row, bg=p["card"])
        text.pack(side="top" if stacked else "left", fill="x", expand=True)
        tk.Label(text, text=title, font=kit.f_bold, fg=p["text"],
                 bg=p["card"], anchor="w").pack(fill="x")
        sub_label = None
        if sub is not None:
            sub_label = tk.Label(text, text=sub, font=kit.f_small,
                                 fg=p["muted"], bg=p["card"], anchor="w",
                                 justify="left")
            sub_label.pack(fill="x")
        ctrl = tk.Frame(row, bg=p["card"])
        if stacked:
            ctrl.pack(side="top", anchor="w", pady=(kit.px(8), 0))
        else:
            ctrl.pack(side="right", padx=(kit.px(16), 0))
        return ctrl, sub_label

    def _live(self, fn):
        """Register `fn` to run on every refresh tick."""
        class _Hook:
            refresh = staticmethod(fn)
        self.kit.register(_Hook())
        fn()

    def _label(self, parent, text="", font=None, fg=None, bg=None, **kw):
        return self.tk.Label(parent, text=text, font=font or self.kit.f_body,
                             fg=fg or self.p["text"], bg=bg or self.p["card"],
                             **kw)

    # ── Sidebar ──────────────────────────────────────────────────
    def _build_sidebar(self, keys, builders):
        tk, p, kit = self.tk, self.p, self.kit
        side = self.side
        brand = tk.Frame(side, bg=p["side"])
        brand.pack(fill="x", padx=kit.px(18), pady=(kit.px(20), kit.px(14)))
        try:
            from PIL import ImageTk
            img = _make_buddy_icon_image().resize((kit.px(36), kit.px(36)))
            self._brand_icon = ImageTk.PhotoImage(img, master=self.root)
            tk.Label(brand, image=self._brand_icon, bg=p["side"]).pack(
                side="left", padx=(0, kit.px(10)))
        except Exception:
            pass
        names = tk.Frame(brand, bg=p["side"])
        names.pack(side="left")
        tk.Label(names, text="Clawd Buddy", font=kit.f_h2, fg=p["text"],
                 bg=p["side"], anchor="w").pack(fill="x")
        tk.Label(names, text=f"v{APP_VERSION}", font=kit.f_small,
                 fg=p["muted"], bg=p["side"], anchor="w").pack(fill="x")

        if self.state is not None:
            self._build_status_chip(side)

        for key in keys:
            title, icon, _ = builders[key]
            item = self._nav_item(side, key, title, icon)
            item.pack(fill="x", padx=kit.px(10), pady=kit.px(1))
            self.nav[key] = item

        if self.state is not None:
            self._build_quit(side)

    def _build_status_chip(self, side):
        tk, p, kit = self.tk, self.p, self.kit
        box = tk.Frame(side, bg=p["side"])
        box.pack(fill="x", padx=kit.px(18), pady=(0, kit.px(16)))
        dot = tk.Canvas(box, width=kit.px(10), height=kit.px(10),
                        bg=p["side"], highlightthickness=0)
        dot.pack(side="left", anchor="n", pady=(kit.px(5), 0))
        text = tk.Frame(box, bg=p["side"])
        text.pack(side="left", padx=(kit.px(8), 0), fill="x")
        title = tk.Label(text, font=kit.f_bold, fg=p["text"], bg=p["side"],
                         anchor="w")
        title.pack(fill="x")
        detail = tk.Label(text, font=kit.f_small, fg=p["muted"],
                          bg=p["side"], anchor="w", justify="left",
                          wraplength=kit.px(150))
        detail.pack(fill="x")
        last = {}

        def refresh():
            t, color, d = status_summary(self.state)
            if last.get("v") == (t, color, d):
                return
            last["v"] = (t, color, d)
            title.configure(text=t)
            detail.configure(text=d)
            dot.delete("all")
            dot.create_image(0, 0, anchor="nw",
                             image=kit.circle(kit.px(10), color))
        self._live(refresh)

    def _nav_item(self, parent, key, title, icon):
        kit, p, mix = self.kit, self.p, self.k.mix
        show = self.show

        class _Nav(self.tk.Canvas):
            def __init__(self):
                super().__init__(parent, height=kit.px(36), bg=p["side"],
                                 highlightthickness=0, cursor="hand2")
                self.selected = False
                self.hover = False
                self.bind("<Button-1>", lambda _e: show(key))
                self.bind("<Enter>", lambda _e: self._hov(True))
                self.bind("<Leave>", lambda _e: self._hov(False))
                self.bind("<Configure>", lambda _e: self.draw())

            def _hov(self, v):
                self.hover = v
                self.draw()

            def draw(self):
                self.delete("all")
                w, h = max(self.winfo_width(), 2), kit.px(36)
                if self.selected or self.hover:
                    fill = p["nav_sel"] if self.selected else p["hover"]
                    if not self.selected:
                        fill = mix(p["side"], fill, 0.6)
                    self.create_image(0, 0, anchor="nw",
                                      image=kit.rrect(w, h, kit.px(9), fill))
                color = p["accent2"] if self.selected else p["muted"]
                self.create_image(kit.px(12), h / 2, anchor="w",
                                  image=kit.icon(icon, kit.px(18), color))
                self.create_text(kit.px(40), h / 2, anchor="w", text=title,
                                 fill=p["text"] if self.selected
                                 else p["muted"],
                                 font=kit.f_bold if self.selected
                                 else kit.f_body)
        return _Nav()

    def _build_quit(self, side):
        kit, p = self.kit, self.p
        holder = self.tk.Frame(side, bg=p["side"])
        holder.pack(side="bottom", fill="x", padx=kit.px(14),
                    pady=kit.px(16))
        armed = {"until": None}

        def on_quit():
            # Two clicks, so a stray one doesn't make the buddy vanish.
            import time
            now = time.monotonic()
            if armed["until"] and now < armed["until"]:
                self.state.should_quit = True
                self.root.destroy()
                return
            armed["until"] = now + 3
            btn.set_text("Click again to quit")

            def disarm():
                armed["until"] = None
                btn.set_text("Quit Clawd Buddy")
            self.root.after(3000, disarm)

        btn = self.k.Button(holder, kit, "Quit Clawd Buddy", on_quit,
                            kind="danger", bg=p["side"], width=184)
        btn.pack(fill="x")

    # ── Pages ────────────────────────────────────────────────────
    def _build_buddy(self, page):
        tk, p, kit, k, st = self.tk, self.p, self.kit, self.k, self.state
        self._header(page, "Buddy", "What it's doing, and how it looks.")

        hero = self._section(page)
        top = tk.Frame(hero.body, bg=p["card"])
        top.pack(fill="x")
        dot = tk.Canvas(top, width=kit.px(14), height=kit.px(14),
                        bg=p["card"], highlightthickness=0)
        dot.pack(side="left", padx=(0, kit.px(10)))
        title = self._label(top, font=kit.f_title)
        title.pack(side="left")
        detail = self._label(hero.body, fg=p["muted"], anchor="w")
        detail.pack(fill="x", pady=(kit.px(2), 0))
        chips = tk.Canvas(hero.body, height=kit.px(1), bg=p["card"],
                          highlightthickness=0)
        chips.pack(fill="x", pady=(kit.px(8), 0))
        buttons = tk.Frame(hero.body, bg=p["card"])
        buttons.pack(fill="x", pady=(kit.px(12), 0))
        k.Button(buttons, kit, "Celebrate", st.celebrate,
                 kind="primary").pack(side="left")
        k.Button(buttons, kit, "Bring to front", st.bring_to_front).pack(
            side="left", padx=kit.px(8))
        k.Button(buttons, kit, "Center on screen",
                 st.center_on_screen).pack(side="left")
        last = {}

        def refresh():
            t, color, d = status_summary(st)
            labels = tuple(st.working_workspaces()) if (
                st.working_sessions) else ()
            if last.get("v") == (t, color, d, labels):
                return
            last["v"] = (t, color, d, labels)
            title.configure(text=t)
            detail.configure(text=d)
            dot.delete("all")
            dot.create_image(0, 0, anchor="nw",
                             image=kit.circle(kit.px(14), color))
            self._draw_chips(chips, labels)
        self._live(refresh)

        look = self._section(page, "Appearance")
        ctrl, _ = self._row(look, "Size", "Ctrl+1 … Ctrl+7 on the buddy")
        c = self.controls
        c["size"] = k.Segmented(
            ctrl, kit, [(n, st.SCALE_LABELS[n]) for n in st.SCALE_PRESETS],
            lambda: st.scale_preset, self._set_size)
        c["size"].pack()
        self._build_theme_picker(look)
        ctrl, _ = self._row(look, "Reduce motion",
                            "Calmer animations, no confetti")
        c["reduce_motion"] = k.Toggle(ctrl, kit, lambda: st.reduce_motion,
                                      self._set_reduce_motion)
        c["reduce_motion"].pack()
        ctrl, _ = self._row(look, "Workspace badges",
                            "Show which project each session is in")
        c["badges"] = k.Toggle(ctrl, kit,
                               lambda: st.workspace_badge_enabled,
                               self._set_badges)
        c["badges"].pack()

        from ..platform import startup_supported
        if startup_supported():
            system = self._section(page, "System")
            ctrl, _ = self._row(system, "Start at login",
                                "Open the buddy when you sign in")
            c["startup"] = k.Toggle(ctrl, kit, self._startup_get,
                                    self._startup_set)
            c["startup"].pack()

    def _build_theme_picker(self, card):
        """Theme row: a Classic / Characters / Princesses / Animals
        switch over a grid of colour dots for that group. Every grid is
        the same size, so switching doesn't make the window jump."""
        from .themes import (THEME_GROUPS, swatch_colors, theme_group,
                             theme_label)
        tk, k, kit, st, c = self.tk, self.k, self.kit, self.state, self.controls
        ctrl, _ = self._row(card, "Theme", stacked=True)
        cols = 8
        cell = k.swatch_cell(kit, [theme_label(n) for _key, _t, names
                                   in THEME_GROUPS for n in names])
        rows = max(-(-len(names) // cols) for _k, _t, names in THEME_GROUPS)
        grids = tk.Frame(ctrl, bg=self.p["card"])
        frames = {}
        for key, _title, names in THEME_GROUPS:
            items = []
            for name in names:
                fill, accent = swatch_colors(name)
                items.append((name, theme_label(name), _rgb_hex(fill),
                              _rgb_hex(accent)))
            frames[key] = k.Swatches(grids, kit, items, lambda: st.theme_name,
                                     self._set_theme, columns=cols,
                                     rows=rows, cell=cell)
            c["theme" if key == "classic" else f"theme_{key}"] = frames[key]
        shown = {"group": theme_group(st.theme_name),
                 "theme": st.theme_name}

        def show(key):
            shown["group"] = key
            for name, f in frames.items():
                if name == key:
                    f.pack(anchor="w")
                else:
                    f.pack_forget()
        c["theme_group"] = k.Segmented(
            ctrl, kit, [(key, title) for key, title, _n in THEME_GROUPS],
            lambda: shown["group"], show)
        c["theme_group"].pack(anchor="w", pady=(0, kit.px(12)))
        grids.pack(anchor="w")
        show(shown["group"])

        def follow():
            # A theme picked elsewhere (the tray) brings its group up.
            if st.theme_name != shown["theme"]:
                shown["theme"] = st.theme_name
                group = theme_group(st.theme_name)
                if group != shown["group"]:
                    show(group)
                    c["theme_group"].refresh()
        self._live(follow)

    def _draw_chips(self, canvas, labels):
        from ..state import workspace_badge_color
        kit = self.kit
        canvas.delete("all")
        if not labels:
            canvas.configure(height=1)
            return
        h = kit.px(22)
        canvas.configure(height=h)
        x = 0
        for label in labels:
            w = kit.f_small.measure(label) + kit.px(18)
            fill = _rgb_hex(workspace_badge_color(label))
            canvas.create_image(x, 0, anchor="nw",
                                image=kit.rrect(w, h, h // 2, fill))
            canvas.create_text(x + w / 2, h / 2, text=label, fill="#ffffff",
                               font=kit.f_small)
            x += w + kit.px(6)

    def _build_sound(self, page):
        kit, k, st = self.kit, self.k, self.state
        self._header(page, "Sound",
                     "What the buddy plays when Claude finishes or needs you.")
        card = self._section(page)
        ctrl, _ = self._row(card, "Sound pack",
                            "Picking one plays a preview", stacked=True)
        pack = k.Segmented(ctrl, kit,
                           [(SOUND_PACK_OFF, "Off")]
                           + [(n, n.title()) for n in SOUND_PACK_NAMES],
                           lambda: st.sound_pack, self._set_pack)
        pack.pack(anchor="w")
        self.controls["sound_pack"] = pack
        ctrl, _ = self._row(card, "Volume")
        volume = k.Segmented(ctrl, kit,
                             [(v, f"{int(round(v * 100))}%")
                              for v in VOLUME_STEPS],
                             self._volume_get, self._set_volume)
        volume.pack()
        self.controls["volume"] = volume

        def gate():
            volume.set_enabled(st.sound_pack != SOUND_PACK_OFF)
        self._live(gate)

        quiet = self._section(page, "Quiet hours")
        self.controls["quiet"] = self._quiet_rows(
            quiet, "Mute at night",
            "No sounds between these times",
            get_pair=lambda: (st.quiet_start, st.quiet_end),
            apply_pair=self._set_quiet,
            default=(22 * 60, 8 * 60))

    def _build_reminders(self, page):
        tk, p, kit, k, st = self.tk, self.p, self.kit, self.k, self.state
        self._header(page, "Reminders", "A nudge to drink water now and then.")

        hero = self._section(page)
        row = tk.Frame(hero.body, bg=p["card"])
        row.pack(fill="x")
        left = tk.Frame(row, bg=p["card"])
        left.pack(side="left", anchor="n")
        nums = tk.Frame(left, bg=p["card"])
        nums.pack(anchor="w")
        cups = self._label(nums, font=kit.f_huge)
        cups.pack(side="left")
        cups_word = self._label(nums, fg=p["muted"])
        cups_word.pack(side="left", anchor="s", padx=(kit.px(6), 0),
                       pady=(0, kit.px(8)))
        status = self._label(left, fg=p["muted"], anchor="w")
        status.pack(anchor="w")
        k.Button(left, kit, "I drank water", st.drink_acknowledged,
                 kind="primary").pack(anchor="w", pady=(kit.px(12), 0))
        k.Bars(row, kit, lambda: week_bars(st), width=196,
               height=88).pack(side="right", anchor="s")

        def refresh():
            n = st.cups_today
            cups.configure(text=str(n))
            cups_word.configure(text="cup today" if n == 1
                                else "cups today")
            if not st.reminder_enabled:
                s = "Reminders are off"
            elif st.reminder_active:
                s = "Reminding you now"
            elif st.is_reminder_quiet_now():
                s = "Paused for the night"
            else:
                s = "Next reminder " + _format_seconds(
                    st.reminder_seconds_until_next())
            status.configure(text=s)
        self._live(refresh)

        card = self._section(page, "Schedule")
        ctrl, _ = self._row(card, "Remind me to drink water")
        self.controls["reminder"] = k.Toggle(
            ctrl, kit, lambda: st.reminder_enabled,
            self._set_reminder_enabled)
        self.controls["reminder"].pack()
        ctrl, _ = self._row(card, "How often")
        every = k.Segmented(ctrl, kit,
                            [(s, _INTERVAL_SHORT.get(s, str(s)))
                             for s in REMINDER_INTERVALS],
                            lambda: st.reminder_interval,
                            self._set_reminder_interval)
        every.pack()
        self.controls["interval"] = every
        ctrl, _ = self._row(card, "Day starts at",
                            "Reminders line up from this time")
        anchor = k.Stepper(ctrl, kit, _HALF_HOURS,
                           lambda: st.reminder_anchor_minute,
                           self._set_reminder_anchor, fmt=_minutes_to_hhmm,
                           wrap=True)
        anchor.pack()
        ctrl, _ = self._row(card, "Sound")
        sound = k.Segmented(ctrl, kit,
                            [(n, n.title()) for n in REMINDER_SOUND_CHOICES],
                            lambda: st.reminder_sound,
                            self._set_reminder_sound)
        sound.pack()
        self.controls["reminder_sound"] = sound
        quiet = self._quiet_rows(
            card, "Pause overnight", "No reminders between these times",
            get_pair=lambda: (st.reminder_quiet_start, st.reminder_quiet_end),
            apply_pair=self._set_reminder_quiet,
            default=(23 * 60, 8 * 60))

        def gate():
            on = bool(st.reminder_enabled)
            for w in (every, anchor, sound):
                w.set_enabled(on)
            quiet(on)
        self._live(gate)

    def _quiet_rows(self, card, title, sub, get_pair, apply_pair, default):
        """A toggle row plus a from/to row for a quiet-hours window.
        Returns a function that enables / disables the whole block."""
        k, kit, p = self.k, self.kit, self.p
        s0, e0 = get_pair()
        local = {"pair": (s0, e0) if s0 is not None else default,
                 "seen": (s0, e0), "outer": True}

        def is_on():
            return get_pair()[0] is not None

        def set_on(on):
            if on:
                s, e = local["pair"]
                if s == e:
                    s, e = default
                    local["pair"] = (s, e)
                apply_pair(s, e)
            else:
                apply_pair(None, None)
            local["seen"] = get_pair()

        ctrl, _ = self._row(card, title, sub)
        toggle = k.Toggle(ctrl, kit, is_on, set_on)
        toggle.pack()
        ctrl, note = self._row(card, "Hours", "")

        def make(i):
            def get():
                return local["pair"][i]

            def set_(v):
                pair = list(local["pair"])
                pair[i] = v
                local["pair"] = tuple(pair)
                s, e = local["pair"]
                if is_on() and s != e:
                    apply_pair(s, e)
                    local["seen"] = get_pair()
                note_text()
            return get, set_

        g0, s0_ = make(0)
        g1, s1_ = make(1)
        start = k.Stepper(ctrl, kit, _HALF_HOURS, g0, s0_,
                          fmt=_minutes_to_hhmm, wrap=True)
        start.pack(side="left")
        self._label(ctrl, "to", fg=p["muted"]).pack(side="left",
                                                     padx=kit.px(8))
        end = k.Stepper(ctrl, kit, _HALF_HOURS, g1, s1_,
                        fmt=_minutes_to_hhmm, wrap=True)
        end.pack(side="left")

        def note_text():
            note.configure(text=_span_text(*local["pair"]))

        def sync():
            # Changed elsewhere (tray, config)? Follow it.
            pair = get_pair()
            if pair != local["seen"]:
                local["seen"] = pair
                if pair[0] is not None:
                    local["pair"] = pair
                    note_text()
            on = is_on() and local["outer"]
            start.set_enabled(on)
            end.set_enabled(on)
        note_text()
        self._live(sync)

        def enable(on):
            local["outer"] = on
            toggle.set_enabled(on)
            sync()
        enable.toggle, enable.start, enable.end = toggle, start, end
        return enable

    def _build_focus(self, page):
        tk, p, kit, k, st = self.tk, self.p, self.kit, self.k, self.state
        self._header(page, "Focus",
                     "A pomodoro timer. The buddy celebrates when a round "
                     "ends.")
        hero = self._section(page)
        row = tk.Frame(hero.body, bg=p["card"])
        row.pack(fill="x")
        d = kit.px(156)
        ring = tk.Canvas(row, width=d, height=d, bg=p["card"],
                         highlightthickness=0)
        ring.pack(side="left")
        ring_img = ring.create_image(0, 0, anchor="nw")
        clock = ring.create_text(d / 2, d / 2 - kit.px(6), text="",
                                 fill=p["text"], font=kit.f_big)
        phase_t = ring.create_text(d / 2, d / 2 + kit.px(24), text="",
                                   fill=p["muted"], font=kit.f_small)
        right = tk.Frame(row, bg=p["card"])
        right.pack(side="left", fill="both", expand=True,
                   padx=(kit.px(24), 0))
        headline = self._label(right, font=kit.f_h2, anchor="w")
        headline.pack(fill="x", pady=(kit.px(28), 0))
        rounds = self._label(right, fg=p["muted"], anchor="w")
        rounds.pack(fill="x")
        btns = tk.Frame(right, bg=p["card"])
        btns.pack(fill="x", pady=(kit.px(14), 0))
        start = k.Button(btns, kit, "Start", self._pomodoro_start,
                         kind="primary", width=96)
        start.pack(side="left")
        stop = k.Button(btns, kit, "Stop", st.stop_pomodoro, width=80)
        stop.pack(side="left", padx=kit.px(8))
        self.controls["pomodoro_start"] = start
        self.controls["pomodoro_stop"] = stop
        green = _rgb_hex(STATUS_COLORS["celebrating"])
        track = k.mix(p["inset"], p["faint"], 0.25)
        self._focus = {"work": st.pomodoro_work_s // 60,
                       "break": st.pomodoro_break_s // 60}

        def refresh():
            active = st.pomodoro_active
            if active:
                work = st.pomodoro_phase == "work"
                total = st.pomodoro_work_s if work else st.pomodoro_break_s
                left = st.pomodoro_seconds_remaining() or 0
                frac = 1 - left / total if total else 0
                color = p["accent"] if work else green
                text = _format_clock(left)
                ph = "FOCUS" if work else "BREAK"
                head = "Focusing" if work else "On a break"
            else:
                frac, color = 0, p["accent"]
                text = _format_clock(self._focus["work"] * 60)
                ph, head = "READY", "Ready when you are"
            img = kit.ring(d, frac, color, track, kit.px(9))
            ring._img = img
            ring.itemconfigure(ring_img, image=img)
            ring.itemconfigure(clock, text=text)
            ring.itemconfigure(phase_t, text=ph)
            headline.configure(text=head)
            n = st.pomodoro_cycles
            rounds.configure(text=(f"{n} round{'s' if n != 1 else ''} done"
                                   if active else
                                   f"{self._focus['work']} min focus, "
                                   f"{self._focus['break']} min break"))
            start.set_text("Restart" if active else "Start")
            stop.set_enabled(active)
        self._live(refresh)

        card = self._section(page, "Timer")
        for key, title, sub in (
                ("work", "Focus length", "Takes effect on the next start"),
                ("break", "Break length", None)):
            ctrl, _ = self._row(card, title, sub)
            w = k.Stepper(ctrl, kit, _POMODORO_MINUTES,
                          lambda key=key: self._focus[key],
                          lambda v, key=key: self._focus.__setitem__(key, v),
                          fmt=lambda v: f"{v} min")
            w.pack()
            self.controls[f"pomodoro_{key}"] = w

    def _build_about(self, page):
        import webbrowser
        tk, p, kit, k = self.tk, self.p, self.kit, self.k
        hero = tk.Frame(page, bg=p["bg"])
        hero.pack(fill="x", pady=(0, kit.px(16)))
        try:
            from PIL import ImageTk
            img = _make_buddy_icon_image().resize((kit.px(64), kit.px(64)))
            self._about_icon = ImageTk.PhotoImage(img, master=self.root)
            tk.Label(hero, image=self._about_icon, bg=p["bg"]).pack(
                side="left", padx=(0, kit.px(16)))
        except Exception:
            pass
        names = tk.Frame(hero, bg=p["bg"])
        names.pack(side="left")
        tk.Label(names, text="Clawd Buddy", font=kit.f_title, fg=p["text"],
                 bg=p["bg"], anchor="w").pack(fill="x")
        tk.Label(names, text=f"Version {APP_VERSION}", font=kit.f_body,
                 fg=p["muted"], bg=p["bg"], anchor="w").pack(fill="x")
        tk.Label(names, text="A tiny desktop pet that reacts to your "
                 "coding assistant.", font=kit.f_body, fg=p["muted"],
                 bg=p["bg"], anchor="w").pack(fill="x", pady=(kit.px(4), 0))

        card = self._section(page)
        ctrl, _ = self._row(card, "Source code", "MIT License, by Ramy Ezzat")
        k.Button(ctrl, kit, "GitHub ↗",
                 lambda: webbrowser.open(_REPO_URL)).pack()
        ctrl, _ = self._row(card, "Settings file",
                            _short_path(_config_dir()))

        def open_config():
            path = _config_dir()
            os.makedirs(path, exist_ok=True)
            webbrowser.open("file://" + path if os.name != "nt" else path)
        k.Button(ctrl, kit, "Open folder", open_config).pack()

        keys = self._section(page, "Shortcuts")
        for combo, what in (
                ("Right-click", "Open this window"),
                ("Drag", "Move the buddy"),
                ("Space", "Celebrate, or confirm a drink"),
                ("Ctrl+1 … 6", "Change the size")):
            ctrl, _ = self._row(keys, what)
            self._keycap(ctrl, combo)

    def _keycap(self, parent, text):
        kit, p = self.kit, self.p
        w = kit.f_small.measure(text) + kit.px(16)
        h = kit.px(22)
        c = self.tk.Canvas(parent, width=w, height=h, bg=p["card"],
                           highlightthickness=0)
        c.create_image(0, 0, anchor="nw", image=kit.rrect(
            w, h, kit.px(6), p["inset"], p["border"], 1))
        c.create_text(w / 2, h / 2, text=text, fill=p["text"],
                      font=kit.f_small)
        c.pack()

    # ── Actions (apply to the buddy, then save) ──────────────────
    def _set_size(self, preset):
        self.state.set_scale(preset)
        save_scale_pref(preset)

    def _set_theme(self, name):
        self.state.set_theme(name)
        save_theme_pref(name)

    def _set_reduce_motion(self, on):
        self.state.set_reduce_motion(on)
        save_reduce_motion_pref(on)

    def _set_badges(self, on):
        self.state.set_workspace_badge_enabled(on)
        save_workspace_badge_pref(on)

    def _startup_get(self):
        from ..platform import startup_enabled
        return startup_enabled()

    def _startup_set(self, on):
        from ..platform import disable_startup, enable_startup
        try:
            (enable_startup if on else disable_startup)()
        except Exception as e:
            print(f"[buddy] Start at login: {e}")

    def _set_pack(self, pack):
        self.state.set_sound_pack(pack)
        save_sound_pack_pref(pack)

    def _volume_get(self):
        v = self.state.volume
        return min(VOLUME_STEPS, key=lambda s: abs(s - v))

    def _set_volume(self, v):
        self.state.set_volume(v)
        save_volume_pref(v)

    def _set_quiet(self, s, e):
        self.state.set_quiet_hours(s, e)
        save_quiet_hours_pref(s, e)

    def _set_reminder_enabled(self, on):
        self.state.set_reminder_enabled(on)
        save_reminder_enabled_pref(on)

    def _set_reminder_interval(self, sec):
        self.state.set_reminder_interval(sec)
        save_reminder_interval_pref(sec)

    def _set_reminder_anchor(self, minutes):
        self.state.set_reminder_anchor_minute(minutes)
        save_reminder_anchor_minute_pref(minutes)

    def _set_reminder_sound(self, name):
        self.state.set_reminder_sound(name)
        save_reminder_sound_pref(name)
        if name != REMINDER_SOUND_OFF:
            self.state._pending_reminder_sound = name  # preview

    def _set_reminder_quiet(self, s, e):
        self.state.set_reminder_quiet_hours(s, e)
        save_reminder_quiet_hours_pref(s, e)

    def _pomodoro_start(self):
        self.state.start_pomodoro(self._focus["work"] * 60,
                                  self._focus["break"] * 60)
