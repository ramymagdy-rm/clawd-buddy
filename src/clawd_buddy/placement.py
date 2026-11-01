# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Where the buddy goes when it's dragged.

The window is a lot bigger than the character: it keeps room above the
head for the status pill, the speech bubble and confetti. Window
managers such as mutter keep client-moved windows fully inside a
monitor's work area, so on its own the window would stop at the top bar
with the character still ~140 px further down.

So a drag is split in two. The window goes as far as the window manager
allows (predicted from its published work areas), and the character
covers the rest of the distance by sliding inside its own window. That
slide is the renderer's *offset*. The character keeps following the
pointer all the way to the edge of the screen.

Pure logic in screen pixels: no pygame, no platform calls.
"""


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    w = min(ax + aw, bx + bw) - max(ax, bx)
    h = min(ay + ah, by + bh) - max(ay, by)
    return w * h if w > 0 and h > 0 else 0


def covered(rect, areas):
    """True when `rect` lies entirely inside the union of `areas` (the
    areas are monitors' work areas, so they never overlap)."""
    need = rect[2] * rect[3]
    return sum(_overlap(rect, a) for a in areas) >= need


def overlaps_any(rect, areas):
    """True when any part of `rect` is on one of `areas`."""
    return any(_overlap(rect, a) for a in areas)


def area_at(areas, point):
    """The area under `point`, or the nearest one."""
    inside = [a for a in areas if _contains(a, point)]
    return inside[0] if inside else min(
        areas, key=lambda a: _distance(a, point))


def _contains(area, point):
    x, y, w, h = area
    return x <= point[0] < x + w and y <= point[1] < y + h


def _distance(area, point):
    x, y, w, h = area
    dx = max(x - point[0], 0, point[0] - (x + w - 1))
    dy = max(y - point[1], 0, point[1] - (y + h - 1))
    return dx * dx + dy * dy


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def visible_limits(limits, win_rect, box, area):
    """Tighten offset `limits` so the character stays on screen when
    its window is bigger than the work area `area` (XXXL on a 1080p
    monitor). On such an axis the window manager pins the window to the
    area's edge and the rest hangs off screen, so the character may
    only slide within the part of the window that's visible. `box` is
    the character's box inside the window at offset 0 (screen pixels).
    Axes where the window fits are left alone, so a normal window can
    still straddle two monitors."""
    x0, x1, y0, y1 = limits
    wx, wy, ww, wh = win_rect
    bx, by, bw, bh = box
    ax, ay, aw, ah = area
    if ww >= aw:
        x0, x1 = _tighten(x0, x1, ax - wx - bx, ax + aw - wx - bx - bw)
    if wh >= ah:
        y0, y1 = _tighten(y0, y1, ay - wy - by, ay + ah - wy - by - bh)
    return x0, x1, y0, y1


def _tighten(lo, hi, new_lo, new_hi):
    lo, hi = max(lo, new_lo), min(hi, new_hi)
    if lo > hi:            # can't fit at all: centre it on what's left
        lo = hi = (lo + hi) / 2
    return lo, hi


def clamp_into(rect, areas, point):
    """Where a window manager that keeps windows inside `areas` would put
    a window asked to go to `rect`: unchanged if it already fits (it may
    straddle monitors), otherwise pushed into the work area under
    `point` (the pointer), or the nearest one. Returns (x, y)."""
    x, y, w, h = rect
    if not areas or covered(rect, areas):
        return x, y
    ax, ay, aw, ah = area_at(areas, point)
    nx = ax if w >= aw else _clamp(x, ax, ax + aw - w)
    ny = ay if h >= ah else _clamp(y, ay, ay + ah - h)
    return nx, ny


class DragPlacement:
    """Tracks the character's offset inside the window (screen pixels)
    across drags.

    `limits` everywhere is (min_x, max_x, min_y, max_y): how far the
    character may slide inside the window before it would leave it.
    """

    def __init__(self):
        self.offset = (0, 0)
        self._grab = None
        self._desired = None

    def begin(self, pointer, window_pos):
        """Mouse down on the character at screen point `pointer`."""
        ox, oy = self.offset
        self._grab = (pointer[0] - (window_pos[0] + ox),
                      pointer[1] - (window_pos[1] + oy))

    @property
    def dragging(self):
        return self._grab is not None

    def update(self, pointer, win_size, areas, limits, box=None):
        """Pointer moved to `pointer`. Returns where to move the window;
        `offset` is updated so window + offset lands under the pointer.
        With `box` (the character's box in the window, see
        `visible_limits`) the character stays on screen even when the
        window is bigger than the monitor."""
        desired = (int(round(pointer[0] - self._grab[0])),
                   int(round(pointer[1] - self._grab[1])))
        self._desired = desired
        tx, ty = clamp_into((*desired, *win_size), areas, pointer)
        if box is not None and areas:
            limits = visible_limits(limits, (tx, ty, *win_size), box,
                                    area_at(areas, pointer))
        self.offset = self._fit(desired, (tx, ty), limits)
        return int(tx), int(ty)

    def aim(self, desired, window_pos, limits):
        """Put the character where it would be with its window at
        `desired` (and no offset), given the window really is at
        `window_pos`. Used after a resize, which may leave the window
        somewhere else when it no longer fits the screen."""
        self._desired = (int(round(desired[0])), int(round(desired[1])))
        self.offset = self._fit(self._desired, window_pos, limits)

    def end(self):
        self._grab = None

    def reconcile(self, window_pos, limits):
        """After the window manager has placed the window, re-aim the
        offset at the spot the drag asked for, in case the manager
        clamped differently than predicted. Returns True if it changed."""
        if self._desired is None:
            return False
        new = self._fit(self._desired, window_pos, limits)
        changed = new != self.offset
        self.offset = new
        return changed

    def reset(self):
        """Back to the default spot (window moved by something else)."""
        self.offset = (0, 0)
        self._desired = None

    @staticmethod
    def _fit(desired, window_pos, limits):
        x0, x1, y0, y1 = limits
        return (_clamp(desired[0] - window_pos[0], x0, x1),
                _clamp(desired[1] - window_pos[1], y0, y1))
