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


def clamp_into(rect, areas, point):
    """Where a window manager that keeps windows inside `areas` would put
    a window asked to go to `rect`: unchanged if it already fits (it may
    straddle monitors), otherwise pushed into the work area under
    `point` (the pointer), or the nearest one. Returns (x, y)."""
    x, y, w, h = rect
    if not areas or covered(rect, areas):
        return x, y
    inside = [a for a in areas if _contains(a, point)]
    ax, ay, aw, ah = inside[0] if inside else min(
        areas, key=lambda a: _distance(a, point))
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

    def update(self, pointer, win_size, areas, limits):
        """Pointer moved to `pointer`. Returns where to move the window;
        `offset` is updated so window + offset lands under the pointer."""
        desired = (int(round(pointer[0] - self._grab[0])),
                   int(round(pointer[1] - self._grab[1])))
        self._desired = desired
        tx, ty = clamp_into((*desired, *win_size), areas, pointer)
        self.offset = self._fit(desired, (tx, ty), limits)
        return int(tx), int(ty)

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
