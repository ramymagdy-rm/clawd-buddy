# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""A small kit of modern-looking tkinter widgets for the settings window.

Tk's own canvas draws shapes without antialiasing, so rounded corners
look jagged on Linux. Every shape here (cards, pills, switches, the
pomodoro ring, nav icons) is drawn with Pillow at 3× and downsampled,
then shown as a PhotoImage; text stays native Tk text. Images are
cached per kit, so redraws are cheap.

Widgets read their value through a `get` callable and write through a
`set` callable. `refresh()` re-reads `get` and redraws only when the
value changed, so the window can poll the live BuddyState a few times a
second and stay in sync with the tray and the keyboard shortcuts.

tkinter and Pillow are imported lazily: importing this module is free.
"""

import math
import sys

_SS = 3  # supersampling factor for Pillow shapes


# ── Palettes ─────────────────────────────────────────────────────────
DARK = {
    "bg":      "#121218",
    "side":    "#17171f",
    "card":    "#1e1e28",
    "inset":   "#2a2a36",
    "hover":   "#32323f",
    "border":  "#2b2b38",
    "text":    "#ececf4",
    "muted":   "#9496ad",
    "faint":   "#5f6176",
    "accent":  "#8b7cf6",
    "accent2": "#a395ff",
    "on_accent": "#ffffff",
    "danger":  "#ef5b62",
    "knob":    "#ffffff",
    "nav_sel": "#262633",
}

LIGHT = {
    "bg":      "#f3f3f7",
    "side":    "#e9e9f0",
    "card":    "#ffffff",
    "inset":   "#ececf2",
    "hover":   "#e2e2ea",
    "border":  "#e1e1ea",
    "text":    "#1b1b24",
    "muted":   "#666879",
    "faint":   "#a3a5b5",
    "accent":  "#6d5ce8",
    "accent2": "#5b49e0",
    "on_accent": "#ffffff",
    "danger":  "#d93a42",
    "knob":    "#ffffff",
    "nav_sel": "#dcdce6",
}

FONT_PREFERENCE = ("Segoe UI Variable Text", "Segoe UI", "SF Pro Text",
                   "Helvetica Neue", "Inter", "Cantarell", "Ubuntu",
                   "Noto Sans", "DejaVu Sans")


def system_prefers_dark():
    """Best-effort read of the desktop's light/dark preference.
    Unknown → dark (the buddy itself defaults to the dark theme)."""
    try:
        if sys.platform == "win32":
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion"
                    r"\Themes\Personalize") as key:
                light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return not light
        import subprocess
        if sys.platform == "darwin":
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=1)
            return "dark" in out.stdout.lower()
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface",
             "color-scheme"], capture_output=True, text=True, timeout=1)
        scheme = out.stdout.strip().strip("'").lower()
        if "dark" in scheme:
            return True
        if "light" in scheme:
            return False
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface",
             "gtk-theme"], capture_output=True, text=True, timeout=1)
        if out.returncode == 0 and out.stdout.strip():
            return "dark" in out.stdout.lower()
    except Exception:
        pass
    return True


def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb[:3])


def mix(a, b, t):
    """Blend two '#rrggbb' colours; t=0 → a, t=1 → b."""
    ra, rb = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


class Kit:
    """Palette, fonts and the Pillow shape cache for one Tk root."""

    def __init__(self, root, palette):
        import tkinter.font as tkfont

        self.root = root
        self.p = palette
        # Tk scales point-sized fonts itself; pixel sizes we scale here.
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        families = set(tkfont.families(root))
        family = next((f for f in FONT_PREFERENCE if f in families),
                      "TkDefaultFont")
        self.family = family

        def font(size, weight="normal"):
            return tkfont.Font(root=root, family=family, size=size,
                               weight=weight)

        self.f_small = font(9)
        self.f_body = font(10)
        self.f_bold = font(10, "bold")
        self.f_title = font(18, "bold")
        self.f_h2 = font(11, "bold")
        self.f_big = font(26, "bold")
        self.f_huge = font(30, "bold")
        self._cache = {}
        self.widgets = []

    def px(self, v):
        return int(round(v * self.scale))

    # ── Pillow shapes ────────────────────────────────────────────
    def _photo(self, key, draw, w, h, cache=True):
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        from PIL import Image, ImageDraw, ImageTk
        W, H = max(1, w), max(1, h)
        img = Image.new("RGBA", (W * _SS, H * _SS), (0, 0, 0, 0))
        draw(ImageDraw.Draw(img), _SS)
        img = img.resize((W, H), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img, master=self.root)
        if cache:
            self._cache[key] = photo
        return photo

    def rrect(self, w, h, r, fill, outline=None, width=1):
        """Rounded rectangle of w×h *device* pixels."""
        def draw(d, k):
            d.rounded_rectangle(
                [0, 0, w * k - 1, h * k - 1], radius=r * k,
                fill=hex_to_rgb(fill) if fill else None,
                outline=hex_to_rgb(outline) if outline else None,
                width=int(width * k) if outline else 0)
        return self._photo(("rr", w, h, r, fill, outline, width), draw, w, h)

    def circle(self, d_px, fill, ring=None, ring_w=0, inner=None,
               inner_frac=0.0):
        """Filled circle, optional outer ring and centred inner dot."""
        def draw(d, k):
            n = d_px * k
            if ring:
                d.ellipse([0, 0, n - 1, n - 1], fill=hex_to_rgb(ring))
                g = ring_w * k
                d.ellipse([g * 2, g * 2, n - 1 - g * 2, n - 1 - g * 2],
                          fill=hex_to_rgb(self.p["card"]))
                g *= 3
                d.ellipse([g, g, n - 1 - g, n - 1 - g],
                          fill=hex_to_rgb(fill))
            else:
                d.ellipse([0, 0, n - 1, n - 1], fill=hex_to_rgb(fill))
            if inner:
                m = n * (1 - inner_frac) / 2
                d.ellipse([m, m, n - 1 - m, n - 1 - m],
                          fill=hex_to_rgb(inner))
        return self._photo(("ci", d_px, fill, ring, ring_w, inner,
                            inner_frac), draw, d_px, d_px)

    def ring(self, d_px, frac, color, track, width):
        """Progress ring: `frac` of a full turn, clockwise from 12."""
        frac = round(max(0.0, min(1.0, frac)) * 400) / 400

        def draw(d, k):
            n, w = d_px * k, width * k
            d.ellipse([0, 0, n - 1, n - 1], outline=hex_to_rgb(track),
                      width=int(w))
            if frac > 0:
                d.arc([0, 0, n - 1, n - 1], start=-90,
                      end=-90 + 360 * frac, fill=hex_to_rgb(color),
                      width=int(w))
                # Round caps.
                r = (n - w) / 2
                c = n / 2
                for ang in (-90, -90 + 360 * frac):
                    a = math.radians(ang)
                    x, y = c + r * math.cos(a), c + r * math.sin(a)
                    d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2],
                              fill=hex_to_rgb(color))
        # Not cached: the ring changes every second. The caller keeps
        # the returned image alive while it is shown.
        return self._photo(("ring", d_px, frac, color, track, width),
                           draw, d_px, d_px, cache=False)

    def icon(self, name, size, color):
        """Tiny line icons for the sidebar (no emoji: colour-emoji fonts
        can crash Tk under X11)."""
        def draw(d, k):
            c = hex_to_rgb(color)
            n = size * k
            lw = max(1, int(1.7 * k * self.scale))

            def u(v):  # 24-unit design grid → pixels
                return v * n / 24
            if name == "buddy":
                d.rounded_rectangle([u(3), u(4), u(21), u(19)],
                                    radius=u(5), outline=c, width=lw)
                d.rounded_rectangle([u(8.5), u(9), u(10.5), u(13.5)],
                                    radius=u(1), fill=c)
                d.rounded_rectangle([u(13.5), u(9), u(15.5), u(13.5)],
                                    radius=u(1), fill=c)
                d.line([u(8), u(21), u(10), u(21)], fill=c, width=lw)
                d.line([u(14), u(21), u(16), u(21)], fill=c, width=lw)
            elif name == "sound":
                d.polygon([(u(3), u(9)), (u(7), u(9)), (u(12), u(4.5)),
                           (u(12), u(19.5)), (u(7), u(15)), (u(3), u(15))],
                          fill=c)
                d.arc([u(10), u(7), u(17), u(17)], -55, 55, fill=c,
                      width=lw)
                d.arc([u(10), u(3.5), u(21), u(20.5)], -55, 55, fill=c,
                      width=lw)
            elif name == "water":
                d.ellipse([u(5.5), u(9), u(18.5), u(22)], fill=c)
                d.polygon([(u(12), u(2)), (u(6.1), u(12.8)),
                           (u(17.9), u(12.8))], fill=c)
            elif name == "focus":
                d.ellipse([u(3.5), u(4.5), u(20.5), u(21.5)], outline=c,
                          width=lw)
                d.line([u(12), u(8), u(12), u(13)], fill=c, width=lw)
                d.line([u(12), u(13), u(15.5), u(15)], fill=c, width=lw)
                d.line([u(9.5), u(2), u(14.5), u(2)], fill=c, width=lw)
            elif name == "info":
                d.ellipse([u(3), u(3), u(21), u(21)], outline=c, width=lw)
                d.ellipse([u(11), u(6.5), u(13), u(8.5)], fill=c)
                d.line([u(12), u(10.5), u(12), u(17)], fill=c, width=lw)
            elif name == "power":
                d.arc([u(4), u(4.5), u(20), u(20.5)], -60, 240, fill=c,
                      width=lw)
                d.line([u(12), u(2.5), u(12), u(11)], fill=c, width=lw)
        return self._photo(("icon", name, size, color), draw, size, size)

    def register(self, widget):
        self.widgets.append(widget)
        return widget

    def refresh_all(self):
        for w in self.widgets:
            try:
                w.refresh()
            except Exception as e:  # never let one widget stop the tick
                print(f"[buddy] Settings refresh failed: {e}")


# ── Widgets ──────────────────────────────────────────────────────────
def _canvas_class():
    import tkinter as tk
    return tk.Canvas


class _Base:
    """Mixin for canvas widgets: hover tracking and a common bg."""

    def _init_base(self, kit, bg):
        self.kit = kit
        self.p = kit.p
        self._hover = None
        self.configure(bg=bg, highlightthickness=0, bd=0)
        self.bind("<Leave>", lambda _e: self._set_hover(None))

    def _set_hover(self, value):
        if value != self._hover:
            self._hover = value
            self.draw()

    def refresh(self):
        pass


def Card(parent, kit, pad=18):
    """A rounded card. Put children in `card.body`."""
    import tkinter as tk
    Canvas = _canvas_class()

    class _Card(Canvas):
        def __init__(self):
            super().__init__(parent, bg=kit.p["bg"], highlightthickness=0,
                             bd=0)
            self.kit = kit
            self.pad = kit.px(pad)
            self.body = tk.Frame(self, bg=kit.p["card"])
            self._win = self.create_window(self.pad, self.pad,
                                           window=self.body, anchor="nw")
            self._bg = None
            self._size = (0, 0)
            self.body.bind("<Configure>", self._fit)
            self.bind("<Configure>", self._fit)

        def _fit(self, _e=None):
            w = max(self.winfo_width(), 1)
            if w > 2 * self.pad:
                self.itemconfigure(self._win, width=w - 2 * self.pad)
            h = self.body.winfo_reqheight() + 2 * self.pad
            if int(self.cget("height")) != h:
                self.configure(height=h)
            # Keep the card at least as wide as its content.
            rw = self.body.winfo_reqwidth() + 2 * self.pad
            if int(self.cget("width")) != rw:
                self.configure(width=rw)
            size = (w, h)
            if size != self._size and w > 1:
                self._size = size
                img = kit.rrect(w, h, kit.px(14), kit.p["card"],
                                kit.p["border"], 1)
                if self._bg is None:
                    self._bg = self.create_image(0, 0, image=img,
                                                 anchor="nw")
                    self.tag_lower(self._bg)
                else:
                    self.itemconfigure(self._bg, image=img)

    return _Card()


def Toggle(parent, kit, get, set_, bg=None):
    Canvas = _canvas_class()

    class _Toggle(Canvas, _Base):
        W, H = 40, 22

        def __init__(self):
            Canvas.__init__(self, parent, width=kit.px(self.W),
                            height=kit.px(self.H), cursor="hand2")
            self._init_base(kit, bg or kit.p["card"])
            self.enabled = True
            self.value = bool(get())
            self._pos = 1.0 if self.value else 0.0
            self.bind("<Button-1>", self._click)
            self.bind("<Enter>", lambda _e: self._set_hover(True))
            self.draw()

        def _click(self, _e):
            if not self.enabled:
                return
            self.value = not self.value
            set_(self.value)
            self._animate()

        def _animate(self):
            target = 1.0 if self.value else 0.0
            step = 0.25 if target > self._pos else -0.25
            self._pos = max(0.0, min(1.0, self._pos + step))
            self.draw()
            if self._pos != target:
                self.after(16, self._animate)

        def set_enabled(self, on):
            if on != self.enabled:
                self.enabled = on
                self.configure(cursor="hand2" if on else "arrow")
                self.draw()

        def refresh(self):
            v = bool(get())
            if v != self.value:
                self.value = v
                self._pos = 1.0 if v else 0.0
                self.draw()

        def draw(self):
            self.delete("all")
            w, h = kit.px(self.W), kit.px(self.H)
            on = mix(self.p["inset"], self.p["accent"], self._pos)
            if self._hover and self.enabled:
                on = mix(on, self.p["text"], 0.08)
            if not self.enabled:
                on = mix(on, self.p["card"], 0.55)
            self.create_image(0, 0, anchor="nw",
                              image=kit.rrect(w, h, h // 2, on))
            k = h - kit.px(6)
            x = kit.px(3) + (w - k - kit.px(6)) * self._pos
            knob = self.p["knob"] if self.enabled else mix(
                self.p["knob"], self.p["card"], 0.5)
            self.create_image(x, kit.px(3), anchor="nw",
                              image=kit.circle(k, knob))

    return kit.register(_Toggle())


def Segmented(parent, kit, options, get, set_, bg=None, min_seg=0):
    """A pill-shaped segmented control. `options` is [(value, label)]."""
    Canvas = _canvas_class()

    class _Seg(Canvas, _Base):
        def __init__(self):
            self.options = list(options)
            pad = kit.px(12)
            self.seg = max([kit.f_body.measure(lbl) + 2 * pad
                            for _v, lbl in self.options]
                           + [kit.px(min_seg)])
            self.h = kit.px(30)
            Canvas.__init__(self, parent,
                            width=self.seg * len(self.options) + kit.px(6),
                            height=self.h, cursor="hand2")
            self._init_base(kit, bg or kit.p["card"])
            self.enabled = True
            self.value = get()
            self.bind("<Button-1>", self._click)
            self.bind("<Motion>", lambda e: self._set_hover(self._at(e.x)))
            self.draw()

        def _at(self, x):
            i = int((x - kit.px(3)) // self.seg)
            return i if 0 <= i < len(self.options) else None

        def _click(self, e):
            i = self._at(e.x)
            if i is None or not self.enabled:
                return
            v = self.options[i][0]
            self.value = v
            set_(v)
            self.draw()

        def set_enabled(self, on):
            if on != self.enabled:
                self.enabled = on
                self.draw()

        def refresh(self):
            v = get()
            if v != self.value:
                self.value = v
                self.draw()

        def draw(self):
            self.delete("all")
            n = len(self.options)
            w = self.seg * n + kit.px(6)
            self.create_image(0, 0, anchor="nw", image=kit.rrect(
                w, self.h, self.h // 2, self.p["inset"]))
            ih = self.h - kit.px(6)
            for i, (v, lbl) in enumerate(self.options):
                x = kit.px(3) + i * self.seg
                sel = v == self.value
                if sel:
                    fill = self.p["accent"]
                    if not self.enabled:
                        fill = mix(fill, self.p["inset"], 0.6)
                    self.create_image(x, kit.px(3), anchor="nw",
                                      image=kit.rrect(self.seg, ih, ih // 2,
                                                      fill))
                elif self._hover == i and self.enabled:
                    self.create_image(x, kit.px(3), anchor="nw",
                                      image=kit.rrect(self.seg, ih, ih // 2,
                                                      self.p["hover"]))
                color = self.p["on_accent"] if sel else self.p["text"]
                if not self.enabled:
                    color = self.p["faint"]
                self.create_text(x + self.seg / 2, self.h / 2, text=lbl,
                                 fill=color,
                                 font=kit.f_bold if sel else kit.f_body)

    return kit.register(_Seg())


def Button(parent, kit, text, command, kind="secondary", bg=None,
           width=None):
    """Rounded button. kind: primary | secondary | danger | ghost."""
    Canvas = _canvas_class()

    class _Button(Canvas, _Base):
        def __init__(self):
            self.text = text
            self.command = command
            self.h = kit.px(32)
            self.w = width and kit.px(width) or (
                kit.f_bold.measure(text) + kit.px(32))
            Canvas.__init__(self, parent, width=self.w, height=self.h,
                            cursor="hand2")
            self._init_base(kit, bg or kit.p["card"])
            self.enabled = True
            self._down = False
            self.bind("<Enter>", lambda _e: self._set_hover(True))
            self.bind("<ButtonPress-1>", self._press)
            self.bind("<ButtonRelease-1>", self._release)
            self.draw()

        def _press(self, _e):
            if self.enabled:
                self._down = True
                self.draw()

        def _release(self, e):
            was = self._down
            self._down = False
            self.draw()
            inside = 0 <= e.x < self.w and 0 <= e.y < self.h
            if was and inside and self.enabled:
                self.command()

        def set_text(self, t):
            if t != self.text:
                self.text = t
                self.draw()

        def set_enabled(self, on):
            if on != self.enabled:
                self.enabled = on
                self.configure(cursor="hand2" if on else "arrow")
                self.draw()

        def draw(self):
            self.delete("all")
            p = self.p
            if kind == "primary":
                fill, fg, line = p["accent"], p["on_accent"], None
            elif kind == "danger":
                fill, fg, line = mix(p["card"], p["danger"], 0.14), \
                    p["danger"], None
            elif kind == "ghost":
                fill, fg, line = None, p["muted"], None
            else:
                fill, fg, line = p["inset"], p["text"], None
            if self._hover and self.enabled:
                fill = mix(fill or self.cget("bg"), p["text"], 0.07)
                if kind == "ghost":
                    fg = p["text"]
            if self._down:
                fill = mix(fill or self.cget("bg"), p["bg"], 0.25)
            if not self.enabled:
                fill = fill and mix(fill, self.cget("bg"), 0.55)
                fg = p["faint"]
            if fill:
                self.create_image(0, 0, anchor="nw", image=kit.rrect(
                    self.w, self.h, kit.px(9), fill, line, 1))
            self.create_text(self.w / 2, self.h / 2, text=self.text,
                             fill=fg, font=kit.f_bold)

    return _Button()


def Stepper(parent, kit, values, get, set_, fmt=str, wrap=False, bg=None,
            min_text=""):
    """‹ value › picker over a fixed list of values. Click the arrows or
    scroll the mouse wheel over it."""
    Canvas = _canvas_class()

    class _Stepper(Canvas, _Base):
        def __init__(self):
            self.values = list(values)
            text_w = max([kit.f_bold.measure(fmt(v)) for v in self.values]
                         + [kit.f_bold.measure(min_text)])
            self.arrow = kit.px(26)
            self.w = text_w + 2 * self.arrow + kit.px(8)
            self.h = kit.px(30)
            Canvas.__init__(self, parent, width=self.w, height=self.h)
            self._init_base(kit, bg or kit.p["card"])
            self.enabled = True
            self.value = get()
            self.bind("<Button-1>", self._click)
            self.bind("<Motion>", lambda e: self._set_hover(self._zone(e.x)))
            self.bind("<MouseWheel>",
                      lambda e: self._step(1 if e.delta > 0 else -1))
            self.bind("<Button-4>", lambda _e: self._step(1))
            self.bind("<Button-5>", lambda _e: self._step(-1))
            self.draw()

        def _zone(self, x):
            if x < self.arrow:
                return -1
            if x > self.w - self.arrow:
                return 1
            return None

        def _click(self, e):
            z = self._zone(e.x)
            if z:
                self._step(z)

        def _index(self):
            if self.value in self.values:
                return self.values.index(self.value)
            # Off-list value (hand-edited config): nearest entry.
            try:
                return min(range(len(self.values)),
                           key=lambda i: abs(self.values[i] - self.value))
            except TypeError:
                return 0

        def _step(self, d):
            if not self.enabled:
                return
            i = self._index() + d
            if wrap:
                i %= len(self.values)
            elif not 0 <= i < len(self.values):
                return
            self.value = self.values[i]
            set_(self.value)
            self.draw()

        def set_enabled(self, on):
            if on != self.enabled:
                self.enabled = on
                self.draw()

        def refresh(self):
            v = get()
            if v != self.value:
                self.value = v
                self.draw()

        def draw(self):
            self.delete("all")
            p = self.p
            self.create_image(0, 0, anchor="nw", image=kit.rrect(
                self.w, self.h, kit.px(9), p["inset"]))
            fg = p["text"] if self.enabled else p["faint"]
            for z, x, glyph in ((-1, self.arrow / 2, "‹"),
                                (1, self.w - self.arrow / 2, "›")):
                at_end = not wrap and (
                    (z < 0 and self._index() == 0)
                    or (z > 0 and self._index() == len(self.values) - 1))
                color = p["faint"] if (at_end or not self.enabled) else (
                    p["accent2"] if self._hover == z else p["muted"])
                self.create_text(x, self.h / 2 - kit.px(1), text=glyph,
                                 fill=color, font=kit.f_h2)
            self.create_text(self.w / 2, self.h / 2, text=fmt(self.value),
                             fill=fg, font=kit.f_bold)

    return kit.register(_Stepper())


_SWATCH_D = 26   # swatch dot diameter


def Swatches(parent, kit, items, get, set_, bg=None, columns=None,
             rows=1, cell=None):
    """Grid of colour dots, `columns` to a row (all in one row by
    default), at least `rows` rows tall. `items` is
    [(value, label, fill, inner)]; `cell` fixes the column width so
    several grids line up."""
    Canvas = _canvas_class()

    class _Swatches(Canvas, _Base):
        D = _SWATCH_D

        def __init__(self):
            self.items = list(items)
            self.cols = columns or max(1, len(self.items))
            self.cell = cell or swatch_cell(kit, [lbl for _v, lbl, _f, _i
                                                  in self.items])
            self.row_h = kit.px(self.D) + kit.px(24)
            n_rows = max(rows, -(-len(self.items) // self.cols))
            self.h = self.row_h * n_rows
            Canvas.__init__(self, parent, width=self.cell * self.cols,
                            height=self.h, cursor="hand2")
            self._init_base(kit, bg or kit.p["card"])
            self.value = get()
            self.bind("<Button-1>", self._click)
            self.bind("<Motion>",
                      lambda e: self._set_hover(self._at(e.x, e.y)))
            self.draw()

        def _at(self, x, y=0):
            col, row = int(x // self.cell), int(y // self.row_h)
            if not 0 <= col < self.cols:
                return None
            i = row * self.cols + col
            return i if 0 <= i < len(self.items) else None

        def _click(self, e):
            i = self._at(e.x, e.y)
            if i is not None:
                self.value = self.items[i][0]
                set_(self.value)
                self.draw()

        def refresh(self):
            v = get()
            if v != self.value:
                self.value = v
                self.draw()

        def draw(self):
            self.delete("all")
            d = kit.px(self.D)
            for i, (v, lbl, fill, inner) in enumerate(self.items):
                row, col = divmod(i, self.cols)
                cx = col * self.cell + self.cell / 2
                top = row * self.row_h
                sel = v == self.value
                ring = self.p["accent"] if sel else (
                    self.p["faint"] if self._hover == i else None)
                img = kit.circle(d, fill, ring=ring, ring_w=kit.px(1),
                                 inner=inner, inner_frac=0.42)
                self.create_image(cx, top + d / 2, image=img)
                self.create_text(cx, top + d + kit.px(11), text=lbl,
                                 fill=self.p["text"] if sel
                                 else self.p["muted"],
                                 font=kit.f_small)

    return kit.register(_Swatches())


def swatch_cell(kit, labels):
    """Column width that fits every label under a swatch dot."""
    return max([kit.f_small.measure(lbl) for lbl in labels]
               + [kit.px(_SWATCH_D)]) + kit.px(10)



def Bars(parent, kit, get, bg=None, width=150, height=56):
    """Tiny bar chart of [(label, value)], newest last."""
    Canvas = _canvas_class()

    class _Bars(Canvas, _Base):
        def __init__(self):
            self.w, self.h = kit.px(width), kit.px(height)
            Canvas.__init__(self, parent, width=self.w, height=self.h)
            self._init_base(kit, bg or kit.p["card"])
            self.data = None
            self.refresh()

        def refresh(self):
            data = list(get())
            if data != self.data:
                self.data = data
                self.draw()

        def draw(self):
            self.delete("all")
            if not self.data:
                self.create_text(self.w / 2, self.h / 2,
                                 text="No history yet",
                                 fill=self.p["faint"], font=kit.f_small)
                return
            n = len(self.data)
            gap = kit.px(6)
            bw = max(kit.px(6), (self.w - gap * (n - 1)) // n)
            top = max(v for _l, v in self.data) or 1
            label_h = kit.px(14)
            avail = self.h - label_h - kit.px(2)
            for i, (lbl, v) in enumerate(self.data):
                x = i * (bw + gap)
                bh = max(kit.px(4), int(avail * v / top))
                last = i == n - 1
                fill = self.p["accent"] if last else mix(
                    self.p["inset"], self.p["accent"], 0.35)
                self.create_image(x, avail - bh, anchor="nw",
                                  image=kit.rrect(bw, bh, min(bw, bh) // 2,
                                                  fill))
                self.create_text(x + bw / 2, self.h - label_h / 2,
                                 text=lbl, fill=self.p["muted"],
                                 font=kit.f_small)

    return kit.register(_Bars())
