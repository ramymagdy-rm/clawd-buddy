# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Procedural drawing of the buddy character.

Pure pygame surface mutation — no platform code, no state ownership.
`draw_buddy(surf, t, state, blink)` is called once per frame from the
main loop with whichever pygame surface should receive the paint.

The look is a compact "screen pet": a soft rounded terminal body with a
glowing face on its screen, nub arms and feet, and a floating status
pill above its head that names what the assistant is doing (Thinking…,
Needs input, Done, New session).

Resolution independence
-----------------------
All geometry below is authored in *logical* units against the 1x window
(`WIN_W` x `WIN_H`). The pixel scale `k` is derived from the surface
width, so the same code renders crisply at 100%..200% and, in
transparent mode, at 2x supersampling (`SUPERSAMPLE`) that
`compose_frame` filters back down into antialiased edges.

Two paint modes
---------------
* *Soft* (the surface has per-pixel alpha — Linux ARGB windows): soft
  ground shadow, state glow, pill shadow, supersampled edges.
* *Hard* (opaque surface — Windows colour-key, Linux without a
  compositor): every pixel is either fully painted or background. No
  translucent effects, because anything blended into the colour key
  would show up as a dark halo on Windows.

Translucency inside the character (blush, highlights) is always done by
pre-mixing colours, never by drawing RGBA onto the frame, so both modes
share one code path and the frame's alpha stays 0 or 255 except for the
deliberate soft effects.
"""

import math

import pygame

from ..constants import TKEY, WIN_H, WIN_W
from ..state import workspace_badge_color
from .themes import costume as _costume


# Transparent frames are drawn at this multiple of the window size and
# smoothscaled down by `compose_frame`, which is what antialiases edges.
SUPERSAMPLE = 2

# Semantic state colours — fixed across themes so their meaning never
# changes: green = done, yellow = needs you, cyan = new session,
# purple = working.
ACCENT = {
    "celebrating": (72, 214, 120),
    "waving":      (255, 196, 61),
    "greeting":    (64, 186, 230),
    "thinking":    (168, 140, 240),
}

STATUS_TEXT = {
    "celebrating": "Done",
    "waving":      "Needs input",
    "greeting":    "New session",
    "thinking":    "Thinking…",
}

# Logical geometry of the character (1x units).
GROUND_Y = WIN_H - 46      # where the feet touch down
BODY_W, BODY_H = 88, 70
BODY_R = 24
FEET_TUCK = 5              # how far the body overlaps the feet
PILL_H = 20
PILL_GAP = 13              # body top → pill bottom
BASE_TOP = GROUND_Y - FEET_TUCK - BODY_H   # body top at rest

# The character's clickable box at rest (logical x, y, w, h): body, nub
# arms and feet, with headroom for hops and raised arms. Only this part
# of the window takes mouse input; see platform.set_input_region.
HIT_BOX = (WIN_W / 2 - BODY_W / 2 - 12, BASE_TOP - 16,
           BODY_W + 24, BODY_H + FEET_TUCK + 16 + 4)

# How far the character may slide inside its window (logical min_x,
# max_x, min_y, max_y) — keeps HIT_BOX a couple of units inside the
# window. Used when the window manager won't let the window itself go
# any further (see placement.py).
OFFSET_LIMITS = (2 - HIT_BOX[0], WIN_W - 2 - (HIT_BOX[0] + HIT_BOX[2]),
                 2 - HIT_BOX[1], WIN_H - 2 - (HIT_BOX[1] + HIT_BOX[3]))

_TRAFFIC = ((255, 95, 86), (255, 189, 46), (39, 201, 63))
_BLUSH = (255, 110, 140)
_WHITE = (255, 255, 255)

REACTIVE = ("celebrating", "waving", "greeting")


# ── small helpers ────────────────────────────────────────────────────
def _mix(a, b, f):
    """Linear blend of two RGB colours (f=0 → a, f=1 → b). Never returns
    the Windows colour key, so pre-mixed colours can't punch holes."""
    c = (int(round(a[0] + (b[0] - a[0]) * f)),
         int(round(a[1] + (b[1] - a[1]) * f)),
         int(round(a[2] + (b[2] - a[2]) * f)))
    return (2, 2, 2) if c == TKEY else c


def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _window(x, start, end, ramp):
    """0 outside [start, end], 1 inside, with smooth `ramp`-long edges —
    lets a pose hold for a moment and glide in and out of it."""
    if x <= start or x >= end:
        return 0.0
    e = min((x - start) / ramp, (end - x) / ramp, 1.0)
    return e * e * (3 - 2 * e)


def _ease_out(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


_PALETTES = {}


def _palette(th):
    """Derive the redesign's colour roles from a theme dict. Cached per
    theme identity — themes are module-level constants."""
    key = id(th)
    pal = _PALETTES.get(key)
    if pal is not None:
        return pal
    screen = th["screen_bg"]
    dark_screen = _lum(screen) < 128
    # Eyes glow on dark screens, ink on light ones.
    face = th["eye_white"] if dark_screen else th["pupil"]
    happy = th["mouth_happy"]
    if abs(_lum(happy) - _lum(screen)) < 70:
        happy = face
    dark_ui = _lum(th["body_inner"]) < 150
    if dark_ui:
        pill_bg, pill_edge, pill_text = (30, 31, 42), (62, 64, 82), (236, 238, 246)
    else:
        pill_bg, pill_edge, pill_text = (255, 255, 255), (214, 217, 228), (38, 40, 54)
    pal = {
        "face": face,
        "happy": happy,
        "blush": _mix(screen, _BLUSH, 0.55 if dark_screen else 0.45),
        "sparkle": screen,
        "bevel": _mix(th["body_inner"], _WHITE, 0.16),
        "pill_bg": pill_bg,
        "pill_edge": pill_edge,
        "pill_text": pill_text,
        "dark_ui": dark_ui,
    }
    _PALETTES[key] = pal
    return pal


# ── fonts and cached sprites ─────────────────────────────────────────
_FONT_PATH = {}
_FONTS = {}
_TEXT_CACHE = {}
_SPRITES = {}
_FONT_FAMILIES = ("inter,segoeui,sfprotext,helveticaneue,ubuntu,"
                  "cantarell,notosans,dejavusans,arial")


def _ensure_font_init():
    if not pygame.font.get_init():
        pygame.font.init()


def _font(px, bold=False):
    """Font at an exact pixel size. The family lookup runs once; Font
    objects are cached per (size, weight)."""
    px = max(6, int(round(px)))
    key = (px, bold)
    f = _FONTS.get(key)
    if f is None:
        _ensure_font_init()
        if bold not in _FONT_PATH:
            _FONT_PATH[bold] = pygame.font.match_font(_FONT_FAMILIES, bold=bold)
        f = pygame.font.Font(_FONT_PATH[bold], px)
        if bold and _FONT_PATH[bold] is None:
            f.set_bold(True)
        _FONTS[key] = f
    return f


def _text(s, px, color, bold=False):
    key = (s, int(round(px)), color, bold)
    surf = _TEXT_CACHE.get(key)
    if surf is None:
        if len(_TEXT_CACHE) > 128:
            _TEXT_CACHE.clear()
        surf = _font(px, bold).render(s, True, color)
        _TEXT_CACHE[key] = surf
    return surf


# Kept for the bubble word-wrapper and its tests: the logical-size font.
_BUBBLE_FONT_SIZE = 12


def _bubble_font():
    """Return (and cache) the speech-bubble font at 1x."""
    return _font(_BUBBLE_FONT_SIZE)


def _soft_blob(w, h, color, peak_alpha):
    """A blurred ellipse sprite (shadow / glow), cached by its pixel size.

    Built small with concentric ellipses ramping alpha toward the
    centre, then smoothscaled up — the upscale is the blur. Only used on
    surfaces with per-pixel alpha.
    """
    w, h = max(2, int(w)), max(2, int(h))
    key = ("blob", w, h, color, peak_alpha)
    spr = _SPRITES.get(key)
    if spr is None:
        if len(_SPRITES) > 96:
            _SPRITES.clear()
        n = 24
        small = pygame.Surface((n * 2, n * 2), pygame.SRCALPHA)
        for i in range(n, 0, -1):
            f = i / n
            a = int(peak_alpha * (1 - f) ** 1.6)
            if a <= 0:
                continue
            r = pygame.Rect(0, 0, int(2 * n * f), int(2 * n * f))
            r.center = (n, n)
            pygame.draw.ellipse(small, (*color, a), r)
        spr = pygame.transform.smoothscale(small, (w, h))
        _SPRITES[key] = spr
    return spr


def _soft_rect(w, h, r, color, alpha, blur):
    """Blurred rounded-rect sprite for the pill / bubble drop shadow."""
    w, h, blur = int(w), int(h), max(1, int(blur))
    key = ("srect", w, h, r, color, alpha, blur)
    spr = _SPRITES.get(key)
    if spr is None:
        if len(_SPRITES) > 96:
            _SPRITES.clear()
        d = 4  # downsample factor; the upscale does the blurring
        sw, sh = max(2, (w + 2 * blur) // d), max(2, (h + 2 * blur) // d)
        small = pygame.Surface((sw, sh), pygame.SRCALPHA)
        b = max(1, blur // d)
        pygame.draw.rect(small, (*color, alpha),
                         (b, b, max(1, sw - 2 * b), max(1, sh - 2 * b)),
                         border_radius=max(0, r // d))
        spr = pygame.transform.smoothscale(small, (w + 2 * blur, h + 2 * blur))
        _SPRITES[key] = spr
    return spr


# ── Pen: logical-unit drawing on a k-scaled surface ──────────────────
class _Pen:
    """Draws in logical units and remembers the bounding box of every
    pixel it touched (`dirty`, in surface pixels), so the compositor and
    the window update can skip the empty parts of the frame.

    `ox`/`oy` translate every position (logical units): the character
    is drawn with the renderer's offset, the pill and bubble without.
    """

    __slots__ = ("surf", "k", "soft", "dirty", "ox", "oy")

    def __init__(self, surf):
        self.surf = surf
        self.k = surf.get_width() / WIN_W
        self.soft = bool(surf.get_flags() & pygame.SRCALPHA)
        self.dirty = None
        self.ox = self.oy = 0.0

    def _mark(self, r):
        if r.w and r.h:
            self.dirty = r if self.dirty is None else self.dirty.union(r)

    def p(self, v):
        return int(round(v * self.k))

    def pt(self, x, y):
        k = self.k
        return (int(round((x + self.ox) * k)), int(round((y + self.oy) * k)))

    def rect(self, x, y, w, h):
        k = self.k
        x, y = x + self.ox, y + self.oy
        x0, y0 = int(round(x * k)), int(round(y * k))
        return pygame.Rect(x0, y0, max(1, int(round((x + w) * k)) - x0),
                           max(1, int(round((y + h) * k)) - y0))

    def rrect(self, color, x, y, w, h, r):
        self._mark(pygame.draw.rect(
            self.surf, color, self.rect(x, y, w, h),
            border_radius=max(0, self.p(min(r, w / 2, h / 2)))))

    def circle(self, color, x, y, r, width=0):
        self._mark(pygame.draw.circle(
            self.surf, color, self.pt(x, y), max(1, self.p(r)),
            self.p(width) if width else 0))

    def ellipse(self, color, x, y, w, h):
        self._mark(pygame.draw.ellipse(self.surf, color,
                                       self.rect(x, y, w, h)))

    def capsule(self, color, x1, y1, x2, y2, thick):
        """A round-capped thick segment (arms, eyes, check marks)."""
        r = thick / 2
        self._mark(pygame.draw.line(
            self.surf, color, self.pt(x1, y1), self.pt(x2, y2),
            max(1, self.p(thick))))
        self.circle(color, x1, y1, r)
        self.circle(color, x2, y2, r)

    def polyline(self, color, pts, thick):
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            self.capsule(color, x1, y1, x2, y2, thick)

    def polygon(self, color, pts):
        self._mark(pygame.draw.polygon(
            self.surf, color, [self.pt(x, y) for x, y in pts]))

    def blit_center(self, spr, x, y):
        self.blit(spr, spr.get_rect(center=self.pt(x, y)))

    def blit(self, spr, dest):
        self._mark(self.surf.blit(spr, dest))


# ── speech bubble, workspace chip ────────────────────────────────────
def _wrap_bubble_text(font, text, max_px, max_lines=2):
    """Word-wrap `text` to fit within `max_px` pixels per line, capped at
    `max_lines`. Long final line is truncated with an ellipsis.

    Word wrapping is good enough for the bubble's status-ping use case
    — we don't try to hyphenate single words longer than the line; they
    overflow and then get truncated by the ellipsis pass.
    """
    words = text.split()
    if not words:
        return []
    lines = []
    current = ""
    for w in words:
        candidate = w if not current else f"{current} {w}"
        if font.size(candidate)[0] <= max_px:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)

    if not lines:
        return []

    last = lines[-1]
    if font.size(last)[0] > max_px or len(lines) == max_lines and len(words) > sum(len(l.split()) for l in lines):
        candidate = last + "…"
        while font.size(candidate)[0] > max_px and len(candidate) > 1:
            candidate = candidate[:-2] + "…"
        lines[-1] = candidate
    return lines


_BUBBLE_PAD_X, _BUBBLE_PAD_Y, _BUBBLE_TAIL, _BUBBLE_R = 8, 5, 5, 9
_EDGE_MARGIN = 6  # gap kept between the pill / bubble and the window edge


def _bubble_layout(text):
    """(lines, width, height) of the speech bubble for `text` in logical
    units, tail excluded; None when there's nothing to show."""
    f1 = _bubble_font()
    max_text = WIN_W - 2 * _EDGE_MARGIN - 2 * _BUBBLE_PAD_X
    lines = _wrap_bubble_text(f1, text, max_text, max_lines=2)
    if not lines:
        return None
    line_h = f1.get_linesize()
    bw = max(f1.size(l)[0] for l in lines) + 2 * _BUBBLE_PAD_X
    bh = line_h * len(lines) + 2 * _BUBBLE_PAD_Y
    return lines, bw, bh


def _speech_bubble(pen, layout, cx, tip_y, pal, below=False):
    """Rounded speech bubble whose tail tip touches `tip_y` (logical,
    window space) under `cx`. The bubble sits above the tip, or below it
    with the tail pointing up when `below`. Clamped inside the window;
    at most two lines, longer text ends in an ellipsis."""
    lines, bw, bh = layout
    tail_h, radius, margin = _BUBBLE_TAIL, _BUBBLE_R, _EDGE_MARGIN
    bx = max(margin, min(cx - bw / 2, WIN_W - margin - bw))
    by = tip_y + tail_h if below else tip_y - tail_h - bh
    by = max(margin, min(by, WIN_H - margin - bh))

    if pen.soft:
        sh = _soft_rect(pen.p(bw), pen.p(bh), pen.p(radius), (0, 0, 0), 70,
                        pen.p(6))
        pen.blit_center(sh, bx + bw / 2, by + bh / 2 + 2)
    tail_x = max(bx + radius + 4, min(cx, bx + bw - radius - 4))
    if below:
        tail = [(tail_x - 6, by + 1), (tail_x + 6, by + 1),
                (tail_x, by - tail_h)]
        edge = [(x, y - 1) for x, y in tail]
    else:
        tail = [(tail_x - 6, by + bh - 1), (tail_x + 6, by + bh - 1),
                (tail_x, by + bh + tail_h)]
        edge = [(x, y + 1) for x, y in tail]
    pen.polygon(pal["pill_edge"], edge)
    pen.rrect(pal["pill_edge"], bx - 1, by - 1, bw + 2, bh + 2, radius + 1)
    pen.rrect(pal["pill_bg"], bx, by, bw, bh, radius)
    pen.polygon(pal["pill_bg"], tail)

    f1 = _bubble_font()
    line_h = f1.get_linesize()
    px_size = _BUBBLE_FONT_SIZE * pen.k
    for i, line in enumerate(lines):
        ts = _text(line, px_size, pal["pill_text"])
        pen.blit_center(ts, bx + bw / 2,
                        by + _BUBBLE_PAD_Y + i * line_h + line_h / 2)


def _workspace_chip(pen, letter, color, x, y, size=14):
    """Rounded square carrying the workspace's first letter at (x, y)
    (top-left, logical units)."""
    pen.rrect(color, x, y, size, size, 4)
    glyph = _text(letter, 9.5 * pen.k, _WHITE, bold=True)
    pen.blit_center(glyph, x + size / 2, y + size / 2)


def compose_frame(screen, frame, transparent, dirty=None):
    """Copy the `frame` onto the window surface `screen`, scaling it to
    the window size when they differ (supersampled frames, or a 1x frame
    on a resized window).

    `dirty` (frame pixels, e.g. `BuddyRenderer.dirty`) limits the
    expensive premultiply + downscale to the part of the frame that has
    content; everything outside it is known to be background. Returns
    the screen-space Rect that now holds content, for a partial
    `pygame.display.update`.

    Opaque mode (Windows colour-key, Linux without a compositor) is a
    plain blit. Transparent mode (Linux ARGB window) needs two extra
    steps:
      * X11 compositors read a window's alpha as *premultiplied*, so the
        frame is premultiplied first. Without this, the soft shadow and
        glow would look too bright. Scaling after premultiplying also
        keeps smoothscale from pulling dark fringes in from the
        (0, 0, 0, 0) background — which is what makes supersampled
        edges come out clean.
      * The screen is cleared to (0, 0, 0, 0) before blitting, so the
        BLEND_PREMULTIPLIED blit copies the frame's pixels exactly instead
        of mixing them with the previous frame.
    """
    sw, sh = screen.get_size()
    fw, fh = frame.get_size()
    full = pygame.Rect(0, 0, sw, sh)
    if not transparent:
        # Opaque frames are already filled with the background, and in
        # practice drawn at window size: a plain blit is the cheap path.
        if (fw, fh) != (sw, sh):
            frame = pygame.transform.smoothscale(frame, (sw, sh))
        screen.blit(frame, (0, 0))
        return full if dirty is None else _to_screen(dirty, fw / sw, fh / sh,
                                                     full)

    screen.fill((0, 0, 0, 0))
    if dirty is None:
        dst = full
        piece = frame
    else:
        ssx, ssy = fw / sw, fh / sh
        dst = _to_screen(dirty, ssx, ssy, full)
        if not dst.w or not dst.h:
            return dst
        src = pygame.Rect(int(round(dst.x * ssx)), int(round(dst.y * ssy)),
                          int(round(dst.w * ssx)), int(round(dst.h * ssy)))
        piece = frame.subsurface(src.clip(frame.get_rect()))
    piece = piece.premul_alpha()
    if piece.get_size() != dst.size:
        piece = pygame.transform.smoothscale(piece, dst.size)
    screen.blit(piece, dst.topleft, special_flags=pygame.BLEND_PREMULTIPLIED)
    return dst


def _to_screen(dirty, ssx, ssy, bounds):
    """Frame-pixel rect → the screen-pixel rect covering it (padded by a
    pixel so the downscale filter never clips an antialiased edge)."""
    x0 = int(dirty.left // ssx) - 1
    y0 = int(dirty.top // ssy) - 1
    x1 = int(math.ceil(dirty.right / ssx)) + 1
    y1 = int(math.ceil(dirty.bottom / ssy)) + 1
    return pygame.Rect(x0, y0, x1 - x0, y1 - y0).clip(bounds)


def frame_size_for(screen_size, transparent):
    """Size of the surface `draw_buddy` should paint for a window of
    `screen_size`: supersampled when the window has real alpha."""
    ss = SUPERSAMPLE if transparent else 1
    return (screen_size[0] * ss, screen_size[1] * ss)


# ── the renderer ─────────────────────────────────────────────────────
class BuddyRenderer:
    """Draws the buddy and owns the little bit of animation memory the
    redesign needs: when the current mode started, the pose it is
    gliding from, and the pill's slide-in.

    Mode switches crossfade from the last pose shown to the new mode's
    live pose over `TRANSITION_S`, so nothing snaps; once the crossfade
    ends the mode's own motion plays exactly as authored.

    The main loop keeps one instance; `draw_buddy` uses a module-level
    one so stateless callers (tests, previews) keep working.
    """

    TRANSITION_S = 0.22
    PILL_SLIDE_S = 0.2

    def __init__(self):
        self._last_t = None
        self._mode = None
        self._mode_t = -10.0
        self._pose = None
        self._from = None
        self._expr = None
        self._expr_t = -10.0
        self._pill_key = None
        self._pill_t = -10.0
        # Bounding box (frame pixels) of everything the last draw()
        # painted, or None. Feed it to compose_frame.
        self.dirty = None
        # Where the character sits inside the window, relative to its
        # default spot (logical units, within OFFSET_LIMITS). The main
        # loop sets it while dragging against a screen edge.
        self.offset = (0.0, 0.0)

    def hit_rect(self):
        """The character's clickable box in logical window coordinates,
        following the current offset."""
        x, y, w, h = HIT_BOX
        return (x + self.offset[0], y + self.offset[1], w, h)

    def wants_fast_frames(self, state):
        """Whether the main loop should run at its fast frame rate: a
        reaction is playing, confetti is falling, or a transition or the
        pill's slide-in is under way. Reduce-motion poses are static,
        so they never need it."""
        if getattr(state, "reduce_motion", False):
            return False
        if state.mode in REACTIVE or state.confetti:
            return True
        t = self._last_t
        if t is None:
            return False
        return (t - self._mode_t < self.TRANSITION_S
                or t - self._pill_t < self.PILL_SLIDE_S)

    # ── frame entry point ────────────────────────────────────────────
    def draw(self, surf, t, state, blink):
        dt = 1 / 60 if self._last_t is None else t - self._last_t
        dt = min(max(dt, 1 / 240), 1 / 15)
        self._last_t = t

        mode = state.mode
        if mode != self._mode:
            self._mode = mode
            self._mode_t = t
            self._from = self._pose
        tm = t - self._mode_t
        reduced = bool(getattr(state, "reduce_motion", False))

        target = self._target_pose(mode, t, tm, reduced)
        if self._from is not None and not reduced and tm < self.TRANSITION_S:
            f = _ease_out(tm / self.TRANSITION_S)
            fr = self._from
            target = {k: fr[k] + (v - fr[k]) * f for k, v in target.items()}
        self._pose = pose = target

        pen = _Pen(surf)
        th = state.theme
        pal = _palette(th)
        cos = _costume(state.theme_name)
        cx = WIN_W / 2
        ox, oy = self.offset

        lift = pose["lift"]
        sx, sy = pose["sx"], pose["sy"]
        bw, bh = BODY_W * sx, BODY_H * sy
        feet_y = GROUND_Y - lift
        body_bottom = feet_y - FEET_TUCK
        body_x = cx + pose["sway"] - bw / 2
        body_y = body_bottom - bh

        # The character (and its confetti) move with the offset.
        pen.ox, pen.oy = ox, oy
        if pen.soft:
            self._draw_shadow(pen, cx + pose["sway"] * 0.5, lift)
            self._draw_glow(pen, mode, t, cx, body_y + bh / 2, reduced)
        # Costume parts behind the character: a cape, long hair, a mane.
        if cos.get("cape"):
            _draw_cape(pen, cos["cape"], body_x, body_y, bw, feet_y)
        if cos.get("hair") and cos.get("hair_style", "spiky") != "spiky":
            _draw_hair_back(pen, cos["hair"], cos["hair_style"],
                            body_x, body_y, bw, bh)
        if cos.get("mane"):
            _draw_mane(pen, cos["mane"], body_x, body_y, bw, bh)
        self._draw_feet(pen, th, cx + pose["sway"], feet_y)
        self._draw_arms(pen, th, body_x, body_y, bw, bh, pose)
        if cos.get("ears"):
            _draw_ears(pen, cos, body_x, body_y, bw)
        self._draw_body(pen, th, pal, body_x, body_y, bw, bh, cos)
        self._draw_face(pen, th, pal, body_x, body_y, bw, bh, pose, mode,
                        t, blink, cos)

        # The pill and bubble are laid out in window space: above the
        # head when there's room, otherwise below the feet (the
        # character has been dragged up against the top of the screen).
        pen.ox = pen.oy = 0.0
        pill = self._pill_content(state, mode, t, pen)
        bubble = _bubble_layout(state.bubble_text) if state.bubble_text else None
        need = ((PILL_GAP + PILL_H) if pill else 8) + (
            (bubble[2] + _BUBBLE_TAIL + 4) if bubble else 0)
        above = BASE_TOP + oy - need >= _EDGE_MARGIN
        mid_x = cx + ox
        if above:
            y = BASE_TOP + oy - (PILL_GAP if pill else 8)
            if pill:
                y -= PILL_H
                self._draw_pill(pen, state, pal, mode, t, pill, mid_x, y,
                                reduced, slide_dir=1)
                y -= 4
            if bubble:
                _speech_bubble(pen, bubble, mid_x, y, pal)
        else:
            y = GROUND_Y + oy + 8
            if pill:
                self._draw_pill(pen, state, pal, mode, t, pill, mid_x, y,
                                reduced, slide_dir=-1)
                y += PILL_H + 4
            if bubble:
                _speech_bubble(pen, bubble, mid_x, y, pal, below=True)

        pen.ox, pen.oy = ox, oy
        self._draw_confetti(pen, state, dt)
        self.dirty = pen.dirty

    # ── pose targets per mode ────────────────────────────────────────
    def _target_pose(self, mode, t, tm, reduced):
        tau = 2 * math.pi
        pose = {
            "lift": 0.0, "sx": 1.0, "sy": 1.0, "sway": 0.0,
            "arm_l": 0.42, "arm_r": 0.42,
            "look_x": 0.0, "look_y": 0.0, "open": 1.0,
        }
        if reduced:
            if mode == "waving":
                pose["arm_r"] = 2.3
            elif mode == "greeting":
                pose["arm_r"] = 2.0
            elif mode == "celebrating":
                pose["arm_l"] = pose["arm_r"] = 2.4
            elif mode == "thinking":
                pose.update(look_x=2.5, look_y=-2.5, open=0.8)
            return pose

        if mode == "celebrating":
            hop_s, n_hops = 0.62, 3
            if tm < hop_s * n_hops:
                lift, sx, sy = _hop(tm % hop_s, hop_s, height=13)
                pose.update(lift=lift, sx=sx, sy=sy)
            else:
                pose["sway"] = math.sin(tau * 0.9 * tm) * 2.5
                b = math.sin(tau * 1.8 * tm)
                pose["sy"] = 1 + 0.025 * b
                pose["sx"] = 1 - 0.015 * b
            wig = math.sin(tau * 2.6 * t) * 0.22
            pose["arm_l"] = 2.45 + wig
            pose["arm_r"] = 2.45 - wig
        elif mode == "waving":
            bounce = abs(math.sin(math.pi * 1.6 * tm))
            pose["lift"] = bounce * 3
            pose["sy"] = 1 - 0.05 * (1 - bounce) ** 6
            pose["sx"] = 1 + 0.035 * (1 - bounce) ** 6
            pose["arm_r"] = 2.35 + math.sin(tau * 2.6 * t) * 0.42
            pose["arm_l"] = 0.36
        elif mode == "greeting":
            hop_s = 0.6
            if tm < hop_s:
                lift, sx, sy = _hop(tm, hop_s, height=10)
                pose.update(lift=lift, sx=sx, sy=sy)
            pose["arm_r"] = 2.1 + math.sin(tau * 2.0 * t) * 0.35
        elif mode == "thinking":
            # "Working" loop: a gentle hover while the arms tap away.
            pose["lift"] = 1.5 + math.sin(tau * 0.8 * t) * 1.5
            tap = tau * 2.8 * t
            pose["arm_l"] = 0.95 + 0.3 * max(0.0, math.sin(tap))
            pose["arm_r"] = 0.95 + 0.3 * max(0.0, math.sin(tap + math.pi))
            pose["look_x"] = 2.5 + math.sin(t * 0.9) * 1.2
            pose["look_y"] = -2.5
            pose["open"] = 0.78
        else:  # idle
            br = math.sin(tau * t / 3.4)
            pose["sy"] = 1 + 0.022 * br
            pose["sx"] = 1 - 0.014 * br
            pose["arm_l"] = pose["arm_r"] = 0.42 + 0.06 * math.sin(
                tau * t / 3.4 + 1)
            # Glance around now and then so the idle pet looks alive
            # without constant motion.
            ph = t % 9.0
            pose["look_x"] = 3.2 * (_window(ph, 6.6, 7.6, 0.18)
                                    - _window(ph, 5.0, 6.2, 0.18))
        return pose

    # ── layers ───────────────────────────────────────────────────────
    def _draw_shadow(self, pen, x, lift):
        f = max(0.35, 1 - lift / 34)
        spr = _soft_blob(pen.p(BODY_W * 0.95 * f), pen.p(12 * f),
                         (0, 0, 0), int(150 * f))
        pen.blit_center(spr, x, GROUND_Y + 1)

    def _draw_glow(self, pen, mode, t, x, y, reduced):
        color = ACCENT.get(mode)
        if color is None or mode == "thinking":
            return
        speed = {"celebrating": 5.0, "waving": 4.0}.get(mode, 3.0)
        pulse = 0.5 if reduced else (math.sin(t * speed) + 1) / 2
        spr = _soft_blob(pen.p(BODY_W * 1.7), pen.p(BODY_H * 1.8), color, 120)
        spr.set_alpha(int(110 + 145 * pulse))
        pen.blit_center(spr, x, y)
        spr.set_alpha(255)

    def _draw_feet(self, pen, th, cx, feet_y):
        for dx in (-16, 16):
            pen.rrect(th["shoe"], cx + dx - 9, feet_y - 9, 18, 9, 4.5)

    def _draw_arms(self, pen, th, bx, by, bw, bh, pose):
        length, thick = 17, 9
        py = by + bh * 0.58
        for side, ang in ((-1, pose["arm_l"]), (1, pose["arm_r"])):
            px = bx + 3 if side < 0 else bx + bw - 3
            ex = px + side * math.sin(ang) * length
            ey = py + math.cos(ang) * length
            pen.capsule(th["limb"], px, py, ex, ey, thick)

    def _draw_body(self, pen, th, pal, bx, by, bw, bh, cos=None):
        cos = cos or {}
        r = BODY_R * min(bw / BODY_W, bh / BODY_H)
        pen.rrect(th["body_outer"], bx, by, bw, bh, r)
        # Inner shell: a lighter bevel line along the top, and a thicker
        # rim left at the bottom so the body reads as a chunky device.
        pen.rrect(pal["bevel"], bx + 2.5, by + 2.5, bw - 5, bh - 7.5, r - 2)
        inner = (bx + 2.5, by + 4, bw - 5, bh - 9, r - 2)
        pen.rrect(th["body_inner"], *inner)
        for band in cos.get("bands", ()):
            _draw_band(pen, inner, *band)
        if cos.get("traffic", True):
            for i, c in enumerate(_TRAFFIC):
                pen.circle(c, bx + 13 + i * 6.5, by + 9.5, 1.9)
        if cos.get("hair") and cos.get("hair_style", "spiky") == "spiky":
            _draw_hair(pen, cos["hair"], bx, by, bw)
        if cos.get("emblem") and not _hair_over_face(cos):
            _draw_emblem(pen, cos["emblem"], th, bx + bw / 2, by + 10)

    def _draw_face(self, pen, th, pal, bx, by, bw, bh, pose, mode, t, blink,
                   cos=None):
        cos = cos or {}
        sx, sy = bx + 8, by + 16
        sw, sh = bw - 16, bh - 27
        pen.rrect(th["screen_bg"], sx, sy, sw, sh, 13)
        if cos.get("web"):
            _draw_web(pen, cos["web"], sx, sy, sw, sh)
        if _hair_over_face(cos):
            # Drawn over the top of the face, so the fringe sits on it.
            r = BODY_R * min(bw / BODY_W, bh / BODY_H)
            _draw_hair_cap(pen, cos["hair"], cos["hair_style"],
                           bx, by, bw, bh, r)
            if cos.get("headband"):
                _draw_headband(pen, cos["headband"], bx, by, bw, bh, r)
            if cos.get("emblem"):
                _draw_emblem(pen, cos["emblem"], th, bx + bw / 2, by + 10)

        fc = pal["face"]
        cx = sx + sw / 2
        ey = sy + sh * 0.45 + pose["look_y"]
        lx = pose["look_x"]

        # Goggles and eye patches sit still on the face; the eyes look
        # around inside them.
        gy = sy + sh * 0.45
        if cos.get("goggles"):
            r = BODY_R * min(bw / BODY_W, bh / BODY_H)
            _draw_goggles(pen, cos["goggles"], (bx, by, bw, bh, r), cx, gy)
        eye_c, sparkle = fc, pal["sparkle"]
        if cos.get("mask"):
            _draw_mask(pen, cos["mask"], cx, gy)
            eye_c, sparkle = cos.get("eye", fc), cos["mask"]
        if cos.get("hair_style") == "braid":
            _draw_braid(pen, cos["hair"], bx, by, bw, bh)

        expr = {"celebrating": "happy", "greeting": "happy",
                "waving": "wide"}.get(mode, "open")
        if expr != self._expr:
            if self._expr is not None:
                self._expr_t = t
            self._expr = expr
        # A quick blink hides the swap between eye shapes.
        swap_blink = (t - self._expr_t) < 0.09
        openness = pose["open"]
        if (blink and mode != "waving") or swap_blink:
            openness = 0.14

        for dx in (-13, 13):
            ex = cx + dx + lx
            if expr == "happy" and not swap_blink:
                pen.polyline(eye_c, [(ex - 5, ey + 2), (ex, ey - 3),
                                     (ex + 5, ey + 2)], 3.2)
            elif expr == "wide":
                r = 6.6 * max(openness, 0.2)
                pen.ellipse(eye_c, ex - 6.6, ey - r, 13.2, 2 * r)
                if openness > 0.5:
                    pen.circle(sparkle, ex - 2.2, ey - 2.4, 2.0)
            else:
                h = max(3.0, 14 * openness)
                pen.rrect(eye_c, ex - 4.6, ey - h / 2, 9.2, h, 4.6)
                if openness > 0.5:
                    pen.circle(sparkle, ex + 1.3, ey - h / 2 + 3.4, 1.7)

        # Blush under the eyes (pre-mixed, so no alpha on the frame).
        blush = cos.get("blush", pal["blush"])
        if blush is not None:
            for dx in (-23, 23):
                pen.ellipse(blush, cx + dx + lx * 0.5 - 4.5, ey + 6, 9, 4.5)

        my = sy + sh * 0.8 + pose["look_y"] * 0.4
        mx = cx + lx * 0.6
        ny = sy + sh * 0.64 + pose["look_y"] * 0.5
        if cos.get("whiskers"):
            _draw_whiskers(pen, cos["whiskers"], mx, ny)
        if cos.get("nose"):
            _draw_nose(pen, cos["nose"], mx, ny)
        if cos.get("beak"):
            _draw_beak(pen, cos["beak"], mx, my,
                       mode in ("celebrating", "greeting"))
        elif mode == "celebrating":
            pts = [(mx - 6 + 12 * i / 8, my - 2 + 6 * math.sin(math.pi * i / 8))
                   for i in range(9)]
            pen.polygon(pal["happy"], pts)
        elif mode == "greeting":
            pen.polyline(pal["happy"], _arc_pts(mx, my - 1.5, 5.5, 3), 2.2)
        elif mode == "waving":
            pen.circle(fc, mx, my - 1, 3.2)
            pen.circle(th["screen_bg"], mx, my - 1, 1.6)
        elif mode == "thinking":
            pen.capsule(fc, mx + 1, my, mx + 6, my - 0.8, 2.0)
        else:
            pen.polyline(fc, _arc_pts(mx, my - 1.2, 4, 2), 2.0)

    _PILL_FONT, _PILL_PAD, _PILL_GAP_IN, _PILL_ICON, _PILL_CHIP = 11, 7, 5, 10, 14
    _PILL_CHIP_GAP = 3

    def _pill_content(self, state, mode, t, pen):
        """(status, workspace labels, width) of the status pill, or None when it
        has nothing to show. Also restarts the slide-in on a change."""
        status = STATUS_TEXT.get(mode)
        if mode == "thinking" and state.working_sessions > 1:
            status = f"Thinking \u00d7{state.working_sessions}"
        labels = tuple(state.workspace_badge_labels())
        if status is None and not labels:
            self._pill_key = None
            return None
        key = (status, labels)
        if key != self._pill_key:
            self._pill_key = key
            self._pill_t = t
        w = self._PILL_PAD * 2
        if labels:
            w += len(labels) * (self._PILL_CHIP + self._PILL_CHIP_GAP) \
                - self._PILL_CHIP_GAP
        if status:
            text_w = _font(self._PILL_FONT * pen.k, bold=True).size(
                status)[0] / pen.k
            w += ((self._PILL_GAP_IN if labels else 0) + self._PILL_ICON
                  + self._PILL_GAP_IN + text_w)
        return status, labels, w

    def _draw_pill(self, pen, state, pal, mode, t, content, cx, top,
                   reduced, slide_dir):
        """Floating status pill centred on `cx` with its top at `top`
        (window space), clamped inside the window. It slides in from
        the character's side: `slide_dir` 1 = from below, -1 = above."""
        status, labels, w = content
        slide = 0.0 if reduced else 6 * slide_dir * (1 - _ease_out(
            (t - self._pill_t) / self.PILL_SLIDE_S))
        x = max(_EDGE_MARGIN, min(cx - w / 2, WIN_W - _EDGE_MARGIN - w))
        y = top + slide

        if pen.soft:
            sh = _soft_rect(pen.p(w), pen.p(PILL_H), pen.p(PILL_H / 2),
                            (0, 0, 0), 80, pen.p(6))
            pen.blit_center(sh, x + w / 2, y + PILL_H / 2 + 2)
        pen.rrect(pal["pill_edge"], x - 1, y - 1, w + 2, PILL_H + 2,
                  PILL_H / 2 + 1)
        pen.rrect(pal["pill_bg"], x, y, w, PILL_H, PILL_H / 2)

        gap, icon_w, chip = self._PILL_GAP_IN, self._PILL_ICON, self._PILL_CHIP
        cur = x + self._PILL_PAD
        mid = y + PILL_H / 2
        for i, label in enumerate(labels):
            _workspace_chip(pen, label[0].upper(),
                            workspace_badge_color(label),
                            cur, mid - chip / 2, chip)
            cur += chip + (gap if i == len(labels) - 1
                           else self._PILL_CHIP_GAP)
        if status:
            _status_icon(pen, mode, cur + icon_w / 2, mid, t, pal, reduced)
            cur += icon_w + gap
            ts = _text(status, self._PILL_FONT * pen.k, pal["pill_text"],
                       bold=True)
            pen.blit(ts, ts.get_rect(midleft=pen.pt(cur, mid)))

    def _draw_confetti(self, pen, state, dt):
        # Physics were tuned per frame at 120 FPS; scale by elapsed time
        # so the burst looks the same at any frame rate.
        # Gravity uses the exact constant-acceleration step, so a long
        # frame lands the particle where several short ones would.
        f = dt * 120
        drag = 0.99 ** f
        g = 0.18
        alive = []
        for p in state.confetti:
            p[0] += p[2] * f
            p[1] += p[3] * f + 0.5 * g * f * f
            p[3] += g * f
            p[2] *= drag
            if p[1] < WIN_H + 10:
                alive.append(p)
                s = p[5]
                a = (p[0] * 0.21 + p[1] * 0.13)
                if s % 2:
                    pen.circle(p[4], p[0], p[1], s * 0.45)
                else:
                    ca, sa = math.cos(a), math.sin(a)
                    hw, hh = s * 0.6, s * 0.32
                    pen.polygon(p[4], [
                        (p[0] + ca * hw - sa * hh, p[1] + sa * hw + ca * hh),
                        (p[0] - ca * hw - sa * hh, p[1] - sa * hw + ca * hh),
                        (p[0] - ca * hw + sa * hh, p[1] - sa * hw - ca * hh),
                        (p[0] + ca * hw + sa * hh, p[1] + sa * hw - ca * hh),
                    ])
        state.confetti = alive


# ── character costumes (see themes.COSTUMES) ─────────────────────────
def _rrect_span(x, rx, ry, rw, rh, r):
    """Top and bottom y of a rounded rectangle at column x, or None.
    Columns a rounding error past an edge count as on it: shapes that
    sample right up to the edge (hair, stripes) would otherwise lose
    their last column on some frames and flicker as the body breathes."""
    if x < rx - 1e-6 or x > rx + rw + 1e-6:
        return None
    x = min(max(x, rx), rx + rw)
    if x < rx + r:
        dx = rx + r - x
    elif x > rx + rw - r:
        dx = x - (rx + rw - r)
    else:
        dx = 0.0
    dy = r - math.sqrt(max(0.0, r * r - dx * dx))
    return ry + dy, ry + rh - dy


def _clipped_band(rect, x0, x1, y0, y1, steps=12):
    """Polygon of the box (x0..x1, y0..y1) cut to the rounded `rect`."""
    top, bottom = [], []
    for i in range(steps + 1):
        x = x0 + (x1 - x0) * (i / steps)
        span = _rrect_span(x, *rect)
        if span is None:
            continue
        t, b = max(y0, span[0]), min(y1, span[1])
        if t < b:
            top.append((x, t))
            bottom.append((x, b))
    return top + bottom[::-1] if len(top) > 1 else None


def _draw_band(pen, rect, f0, f1, g0, g1, fill, edge):
    """A stripe across the shell; f/g are fractions of `rect`'s box."""
    rx, ry, rw, rh, _ = rect
    x0, x1 = rx + rw * f0, rx + rw * f1
    y0, y1 = ry + rh * g0, ry + rh * g1
    if edge:
        poly = _clipped_band(rect, x0 - 1.6, x1 + 1.6, y0, y1)
        if poly:
            pen.polygon(edge, poly)
    poly = _clipped_band(rect, x0, x1, y0, y1)
    if poly:
        pen.polygon(fill, poly)


def _draw_ears(pen, cos, bx, by, bw):
    """Ears (or a fin) behind the head; their bases hide under it."""
    kind, color = cos["ears"], cos.get("ear", (30, 30, 36))
    if kind == "fin":
        pen.polygon(color, [(bx + bw * 0.44, by + 8), (bx + bw * 0.58, by - 9),
                            (bx + bw * 0.66, by - 7), (bx + bw * 0.78, by + 6)])
        return
    inner = cos.get("ear_inner")
    for side in (-1, 1):
        def at(f, y):
            return (bx + bw / 2 + side * (f - 0.5) * -bw, y)
        if kind == "round":
            x, y = at(0.17, by + 3)
            pen.circle(color, x, y, 9.5)
            if inner:
                pen.circle(inner, x, y, 5.2)
        elif kind == "long":
            (x0, y0), (x1, y1) = at(0.33, by + 8), at(0.25, by - 22)
            pen.capsule(color, x0, y0, x1, y1, 12)
            if inner:
                pen.capsule(inner, x0, y0 - 2, x1 + side * 0.3, y1 + 4, 5.5)
        elif kind == "wide":
            pts = [at(0.10, by + 18), at(-0.30, by - 8), at(-0.12, by - 2),
                   at(0.38, by + 4)]
            pen.polygon(color, pts)
            if inner:
                pen.polygon(inner, _shrink(pts, 0.55, (0, 1.5)))
        elif kind == "bat":
            pen.polygon(color, [at(0.13, by + 12), at(0.19, by - 12),
                                at(0.40, by + 5)])
        elif kind == "pointy":
            base_a, base_b = at(0.17, by + 10), at(0.42, by + 4)
            tip = at(-0.04, by - 13)
            pen.polygon(color, [base_a, tip, base_b])
            if inner:
                pen.polygon(inner, _shrink([base_a, tip, base_b], 0.5,
                                           (0, 2.5)))
            tip_color = cos.get("ear_tip")
            if tip_color:
                k = 0.6
                a = (base_a[0] + (tip[0] - base_a[0]) * k,
                     base_a[1] + (tip[1] - base_a[1]) * k)
                b = (base_b[0] + (tip[0] - base_b[0]) * k,
                     base_b[1] + (tip[1] - base_b[1]) * k)
                pen.polygon(tip_color, [a, tip, b])


def _draw_hair(pen, color, bx, by, bw):
    """A spiky fringe that follows the curve of the head."""
    head = (bx - 1, by - 1, bw + 2, 40, BODY_R)
    n = 16
    top, bottom = [], []
    for i in range(n + 1):
        x = bx + 1 + (bw - 2) * i / n
        edge = _rrect_span(x, *head)[0]
        mid = 1 - abs(i / n - 0.5) * 2          # 0 at the sides, 1 mid
        spike = (5 + 3 * mid) if i % 2 else 0.5
        top.append((x, edge - spike))
        bottom.append((x, edge + 9 + 3 * mid + (2.5 if i % 4 == 1 else 0)))
    pen.polygon(color, top + bottom[::-1])


_BAT = ((-10, -1), (-6, -3.2), (-3, -2), (-1.5, -3.8), (-0.8, -2.2),
        (0.8, -2.2), (1.5, -3.8), (3, -2), (6, -3.2), (10, -1), (7, 0.7),
        (5.5, 0), (4, 1.9), (2, 1.2), (0, 3.1), (-2, 1.2), (-4, 1.9),
        (-5.5, 0), (-7, 0.7))


def _star(cx, cy, r_out, r_in):
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _draw_emblem(pen, kind, th, x, y):
    """A small emblem on the forehead, centred on (x, y)."""
    if kind == "bat":
        pen.ellipse((20, 20, 24), x - 14, y - 6, 28, 12)
        pen.ellipse(th["mouth_happy"], x - 13, y - 5, 26, 10)
        pen.polygon((20, 20, 24), [(x + dx, y + dy) for dx, dy in _BAT])
    elif kind == "reactor":
        if pen.soft:
            spr = _soft_blob(pen.p(26), pen.p(20), (120, 230, 255), 170)
            pen.blit_center(spr, x, y)
        pen.circle((70, 80, 92), x, y, 5.6)
        pen.circle((190, 245, 255), x, y, 4.4)
        pen.circle((110, 222, 255), x, y, 3.0)
        pen.circle((255, 255, 255), x, y, 1.5)
    elif kind == "super":
        red, gold = (200, 30, 40), (255, 214, 50)
        shield = [(x - 7.5, y - 4.5), (x + 7.5, y - 4.5), (x + 9, y - 1.5),
                  (x, y + 6.5), (x - 9, y - 1.5)]
        pen.polygon(red, shield)
        pen.polygon(gold, _shrink(shield, 0.74, (0, -0.2)))
        pen.polyline(red, [(x + 2.6, y - 2.6), (x - 1.8, y - 2.6),
                           (x - 2.2, y - 0.9), (x + 1.8, y + 0.2),
                           (x + 1.4, y + 1.9), (x - 2.4, y + 1.9)], 1.3)
    elif kind == "bow":
        x, y = x + 15, y - 9
        red = (200, 30, 40)
        pen.polygon(red, [(x, y), (x - 7.5, y - 4.5), (x - 7.5, y + 4.5)])
        pen.polygon(red, [(x, y), (x + 7.5, y - 4.5), (x + 7.5, y + 4.5)])
        pen.circle(_mix(red, (0, 0, 0), 0.25), x, y, 2.2)
    elif kind == "star":
        pen.circle((196, 30, 40), x, y, 5.8)
        pen.circle((245, 245, 250), x, y, 4.5)
        pen.circle((196, 30, 40), x, y, 3.5)
        pen.circle(th["body_outer"], x, y, 2.6)
        pen.polygon((255, 255, 255), _star(x, y, 2.5, 1.0))


def _shrink(pts, k, shift=(0, 0)):
    """`pts` scaled by `k` about their centroid, then moved by `shift`."""
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return [(cx + (x - cx) * k + shift[0], cy + (y - cy) * k + shift[1])
            for x, y in pts]


def _ellipse_pts(cx, cy, rx, ry, angle, n=20):
    ca, sa = math.cos(angle), math.sin(angle)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        x, y = rx * math.cos(a), ry * math.sin(a)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


_HAIR_SIDE = {"long": 0.62, "very_long": 0.62, "bob": 0.5, "braid": 0.3}


def _hair_over_face(cos):
    """Long hair, a bob or a braid: hair framing the face."""
    return bool(cos.get("hair")) and cos.get("hair_style", "spiky") != "spiky"


def _draw_hair_cap(pen, color, style, bx, by, bw, bh, r):
    """Hair over the head: a fringe down to the face (swept back for a
    braid) and locks down both sides of it."""
    head = (bx - 1.2, by - 1.2, bw + 2.4, bh + 2.4, r + 1.2)
    cx = bx + bw / 2
    # The face starts 16 below the head top; a fringe reaches just past
    # it, and a braid's swept-back hair just meets it.
    fringe, part_depth = (16.5, 0) if style == "braid" else (18.5, 2.5)
    side = by + bh * _HAIR_SIDE.get(style, 0.6)
    def fringe_y(x):
        f = abs(x - cx) / (bw / 2)
        # Side-swept: the parting sits left of centre.
        part = math.exp(-((x - (cx - 9)) / 4.5) ** 2) * part_depth
        # Curving down at the sides far enough to cover the face's
        # rounded top corners, so no gown shows between hair and face.
        return by + fringe + 7 * (f / 0.8) ** 2 - part

    # The side locks start at a fixed fraction of the width. That edge
    # gets its own points (a clean vertical step) instead of falling
    # between two samples, where it would slide a whole sample sideways
    # whenever breathing moved it past one.
    n = 28
    lock_l, lock_r = cx - 0.8 * bw / 2, cx + 0.8 * bw / 2
    xs = sorted({head[0] + head[2] * (i / n) for i in range(n + 1)}
                | {lock_l, lock_r})
    top, bottom = [], []
    for x in xs:
        span = _rrect_span(x, *head)
        if span is None:
            continue
        top.append((x, span[0]))
        if x == lock_l:
            ys = (side, fringe_y(x))
        elif x == lock_r:
            ys = (fringe_y(x), side)
        else:
            ys = (side if x < lock_l or x > lock_r else fringe_y(x),)
        bottom.extend((x, min(y, span[1])) for y in ys)
    pen.polygon(color, top + bottom[::-1])


def _draw_hair_back(pen, color, style, bx, by, bw, bh):
    """Long hair hanging behind the body, showing at its sides."""
    length = {"long": bh * 0.95, "very_long": bh + 4,
              "bob": bh * 0.56}.get(style)
    if not length:
        return
    for x in (bx - 5, bx + bw - 13):
        pen.rrect(color, x, by + 4, 18, length, 8)
    if style == "very_long":
        # So long it pools on the floor.
        pen.ellipse(color, bx + bw - 12, by + bh, 30, 9)
        pen.ellipse(color, bx - 14, by + bh + 1, 22, 8)


def _draw_braid(pen, color, bx, by, bw, bh):
    """A braid over the shoulder, down the right side of the body."""
    dark = _mix(color, (60, 50, 40), 0.25)
    x, y = bx + bw - 9, by + 14
    for i in range(7):
        wob = 1.6 if i % 2 else -1.6
        pen.ellipse(dark, x + wob - 5.2, y - 4.2, 10.4, 8.6)
        pen.ellipse(color, x + wob - 4.4, y - 3.4, 8.8, 7)
        x += 0.9
        y += 7.6
    pen.capsule(dark, x - 1, y - 4, x + 1, y + 2, 2.4)


def _draw_headband(pen, color, bx, by, bw, bh, r):
    head = (bx - 1.2, by - 1.2, bw + 2.4, bh + 2.4, r + 1.2)
    pts = []
    for i in range(17):
        x = bx + 7 + (bw - 14) * i / 16
        pts.append((x, _rrect_span(x, *head)[0] + 6.5))
    pen.polyline(color, pts, 3.2)


def _draw_cape(pen, color, bx, by, bw, feet_y):
    """A cape behind the body, flaring out to the ground."""
    pts = [(bx + 10, by + 14), (bx + bw - 10, by + 14),
           (bx + bw + 11, feet_y + 2)]
    for i in range(1, 6):
        x = bx + bw + 11 - (bw + 22) * i / 6
        pts.append((x, feet_y + (4 if i % 2 else 1)))
    pts.append((bx - 11, feet_y + 2))
    pen.polygon(color, pts)


def _draw_mane(pen, color, bx, by, bw, bh):
    """A shaggy mane around the head."""
    cx, cy = bx + bw / 2, by + bh * 0.48
    rx, ry = bw / 2 + 10, bh * 0.5 + 12
    pts = []
    for i in range(32):
        a = 2 * math.pi * i / 32
        k = 1.0 if i % 2 == 0 else 0.86
        pts.append((cx + rx * k * math.cos(a), cy + ry * k * math.sin(a)))
    pen.polygon(color, pts)


def _draw_goggles(pen, g, body, cx, gy):
    """Goggles around both eyes (Minion), or binoculars (Wall-E)."""
    if g.get("strap"):
        poly = _clipped_band(body, body[0], body[0] + body[2],
                             gy - 3.5, gy + 3.5, steps=20)
        if poly:
            pen.polygon(g["strap"], poly)
    for dx in (-13, 13):
        x = cx + dx
        if g.get("bridge"):
            pen.rrect(g["rim"], x - 12.5, gy - 10.5, 25, 21, 8)
            pen.rrect(g["lens"], x - 10, gy - 8, 20, 16, 6)
        else:
            pen.circle(g["rim"], x, gy, 11.5)
            pen.circle(g["lens"], x, gy, 9)
    if g.get("bridge"):
        pen.rrect(g["rim"], cx - 4, gy - 3, 8, 6, 2)


def _draw_mask(pen, color, cx, gy):
    """A patch around each eye (panda, Deadpool), drooping outwards."""
    for side in (-1, 1):
        pen.polygon(color, _ellipse_pts(cx + side * 13.5, gy + 1, 10, 8,
                                        side * 0.5))


def _draw_nose(pen, color, x, y):
    pen.ellipse(color, x - 3.2, y - 2.4, 6.4, 3.2)
    pen.polygon(color, [(x - 3, y - 1.2), (x + 3, y - 1.2), (x, y + 2)])


def _draw_whiskers(pen, color, x, y):
    for side in (-1, 1):
        for k in (-1, 0, 1):
            pen.polyline(color, [(x + side * 15, y + k * 1.8),
                                 (x + side * 30, y + k * 4.2 - 1)], 0.9)


def _draw_beak(pen, color, x, y, open_):
    edge = _mix(color, (0, 0, 0), 0.22)
    if open_:
        pen.polygon(edge, [(x - 5.5, y - 4), (x + 5.5, y - 4), (x, y)])
        pen.polygon(color, [(x - 4.5, y - 3.5), (x + 4.5, y - 3.5),
                            (x, y - 0.6)])
        pen.polygon(color, [(x - 3.5, y + 0.8), (x + 3.5, y + 0.8),
                            (x, y + 3.8)])
    else:
        pen.polygon(edge, [(x - 5.5, y - 3), (x + 5.5, y - 3), (x, y + 3)])
        pen.polygon(color, [(x - 4.5, y - 2.5), (x + 4.5, y - 2.5),
                            (x, y + 2)])


def _draw_web(pen, color, sx, sy, sw, sh):
    """A spider web on the screen, centred between the eyes."""
    cx, cy = sx + sw / 2, sy + sh * 0.42
    angles = [i * math.pi / 4 + math.pi / 8 for i in range(8)]
    rays = []
    for a in angles:
        dx, dy = math.cos(a), math.sin(a)
        # Distance from the centre to the screen edge along this ray.
        tx = ((sx + sw - 3 - cx) / dx) if dx > 0 else ((sx + 3 - cx) / dx)
        ty = ((sy + sh - 3 - cy) / dy) if dy > 0 else ((sy + 3 - cy) / dy)
        reach = min(tx, ty)
        rays.append((dx, dy, reach))
        pen.capsule(color, cx, cy, cx + dx * reach, cy + dy * reach, 0.9)
    for frac in (0.38, 0.72):
        ring = [(cx + dx * reach * frac, cy + dy * reach * frac)
                for dx, dy, reach in rays]
        pen.polyline(color, ring + ring[:1], 0.9)


def _hop(u, period, height):
    """One hop of `period` seconds at phase `u`: a short squash on the
    ground, a parabolic arc with a little stretch, and a landing squash.
    Returns (lift, sx, sy)."""
    ground = 0.16 * period
    if u < ground / 2 or u > period - ground / 2:
        g = (u + ground / 2) % period / ground  # 0..1 across the contact
        sq = math.sin(math.pi * g) * 0.13
        return 0.0, 1 + sq * 0.75, 1 - sq
    w = (u - ground / 2) / (period - ground)
    arc = 4 * w * (1 - w)
    stretch = 0.07 * (1 - arc)
    return height * arc, 1 - stretch * 0.6, 1 + stretch


def _arc_pts(cx, cy, half_w, sag, n=6):
    return [(cx - half_w + 2 * half_w * i / n,
             cy + sag * math.sin(math.pi * i / n)) for i in range(n + 1)]


def _status_icon(pen, mode, x, y, t, pal, reduced):
    color = ACCENT.get(mode, pal["pill_text"])
    if mode == "thinking":
        # Activity spinner: 8 dots fading around a ring.
        step = 0 if reduced else int(t * 12) % 8
        for i in range(8):
            a = (i / 8) * 2 * math.pi
            fade = ((i - step) % 8) / 8
            c = _mix(pal["pill_bg"], color, 0.25 + 0.75 * (1 - fade))
            pen.circle(c, x + math.cos(a) * 3.6, y + math.sin(a) * 3.6, 1.15)
    elif mode == "celebrating":
        pen.circle(color, x, y, 5.2)
        pen.polyline(_WHITE, [(x - 2.4, y + 0.1), (x - 0.6, y + 1.9),
                              (x + 2.5, y - 1.8)], 1.5)
    elif mode == "waving":
        pulse = 0 if reduced else (math.sin(t * 6) + 1) / 2
        pen.circle(color, x, y, 5.0 + 0.6 * pulse)
        ink = (60, 45, 10)
        pen.capsule(ink, x, y - 2.6, x, y + 0.5, 1.6)
        pen.circle(ink, x, y + 2.5, 0.9)
    else:
        pen.circle(color, x, y, 4.2)
        pen.circle(_WHITE, x, y, 1.6)


# Module-level renderer for stateless callers.
_DEFAULT = BuddyRenderer()


def draw_buddy(surf, t, state, blink):
    """Render the buddy for the current frame.

    `t` is wall-clock time (the phase source for every animation).
    `state` carries the mode and theme. `blink` is precomputed by the
    main loop, which owns the blink timer. The surface's width sets the
    pixel scale; its alpha flag picks soft or hard painting.
    """
    _DEFAULT.draw(surf, t, state, blink)
