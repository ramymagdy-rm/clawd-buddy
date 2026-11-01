# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Dragging past what the window manager allows: the window stops at
the work-area edge and the character slides the rest of the way inside
its own window."""

from clawd_buddy.placement import (
    DragPlacement, clamp_into, covered, visible_limits)

# The two-monitor layout this was reported on, as mutter publishes it in
# _GTK_WORKAREAS_D0: a laptop panel at the right with no top bar, and
# the primary monitor at the left, 120 px lower, with a 32 px top bar
# and a 67 px dock.
LAPTOP = (1920, 0, 1920, 1200)
PRIMARY = (67, 152, 1853, 1048)
AREAS = [LAPTOP, PRIMARY]
WIN = (200, 260)
LIMITS = (-42, 42, -121, 40)


class TestClampInto:
    def test_inside_one_area_is_untouched(self):
        assert clamp_into((400, 400, *WIN), AREAS, (500, 600)) == (400, 400)

    def test_top_bar_stops_the_window(self):
        # Measured on mutter: asking for y=60 on the primary lands at 152.
        assert clamp_into((400, 60, *WIN), AREAS, (500, 200)) == (400, 152)

    def test_dock_stops_the_window(self):
        assert clamp_into((-30, 500, *WIN), AREAS, (40, 600)) == (67, 500)

    def test_laptop_panel_reaches_its_top(self):
        assert clamp_into((2500, -40, *WIN), AREAS, (2600, 100)) == (2500, 0)

    def test_straddling_two_areas_is_allowed(self):
        rect = (1850, 500, *WIN)
        assert covered(rect, AREAS)
        assert clamp_into(rect, AREAS, (1950, 600)) == (1850, 500)

    def test_pointer_outside_every_area_uses_nearest(self):
        # Primary's area starts at y=152; the pointer is in the dead
        # zone above it, left of the laptop panel.
        assert clamp_into((400, 20, *WIN), AREAS, (500, 60)) == (400, 152)

    def test_no_areas_means_no_clamping(self):
        # Windows: the OS doesn't keep windows on screen.
        assert clamp_into((-500, -500, *WIN), [], (0, 0)) == (-500, -500)

    def test_window_larger_than_area_aligns_to_its_origin(self):
        assert clamp_into((10, 10, 300, 300), [(0, 0, 200, 200)],
                          (50, 50)) == (0, 0)


class TestDragPlacement:
    def _drag(self, start_win, start_ptr, to_ptr, areas=AREAS):
        p = DragPlacement()
        p.begin(start_ptr, start_win)
        win = p.update(to_ptr, WIN, areas, LIMITS)
        return p, win

    def test_free_drag_moves_the_window_only(self):
        p, win = self._drag((400, 500), (500, 680), (520, 650))
        assert win == (420, 470)
        assert p.offset == (0, 0)

    def test_drag_into_top_bar_slides_the_character_up(self):
        # Window can't go above 152; the character takes the other 100.
        p, win = self._drag((400, 300), (500, 480), (500, 232))
        assert win == (400, 152)
        assert p.offset == (0, -100)

    def test_character_offset_is_limited_to_the_window(self):
        p, win = self._drag((400, 300), (500, 480), (500, -500))
        assert win[1] == 152
        assert p.offset[1] == LIMITS[2]

    def test_sideways_into_the_dock(self):
        p, win = self._drag((100, 500), (200, 680), (150, 680))
        assert win == (67, 500)
        assert p.offset == (-17, 0)

    def test_grab_point_survives_an_offset(self):
        # Second drag starts on a character that already sits 100 px up
        # in its window: it must not jump under the pointer.
        p, _ = self._drag((400, 300), (500, 480), (500, 232))
        p.end()
        p.begin((500, 232), (400, 152))
        win = p.update((500, 232), WIN, AREAS, LIMITS)
        assert win == (400, 152)
        assert p.offset == (0, -100)

    def test_dragging_back_down_returns_the_offset_to_zero(self):
        p, _ = self._drag((400, 300), (500, 480), (500, 232))
        p.end()
        p.begin((500, 232), (400, 152))
        win = p.update((500, 600), WIN, AREAS, LIMITS)
        assert p.offset == (0, 0)
        assert win == (400, 420)

    def test_reconcile_follows_where_the_wm_really_put_it(self):
        # Predicted no clamp, but the WM stopped the window 30 px lower.
        p, win = self._drag((400, 500), (500, 680), (500, 650), areas=[])
        assert win == (400, 470) and p.offset == (0, 0)
        assert p.reconcile((400, 500), LIMITS)
        assert p.offset == (0, -30)
        assert not p.reconcile((400, 500), LIMITS)

    def test_reset(self):
        p, _ = self._drag((400, 300), (500, 480), (500, 232))
        p.reset()
        assert p.offset == (0, 0)
        assert not p.reconcile((0, 0), LIMITS)

    def test_dragging_flag(self):
        p = DragPlacement()
        assert not p.dragging
        p.begin((0, 0), (0, 0))
        assert p.dragging
        p.end()
        assert not p.dragging


def test_window_position_is_whole_pixels():
    # XMoveWindow / SetWindowPos take ints; fractional pointer or limits
    # (125% / 150% scale) must not leak through.
    p = DragPlacement()
    p.begin((500.4, 480.6), (400, 300))
    x, y = p.update((500.9, 100.2), WIN, AREAS, (-52.5, 52.5, -151.25, 50))
    assert isinstance(x, int) and isinstance(y, int)


class TestBiggerThanTheScreen:
    """XXXL (5×): a 1000×1300 window on the 1048-tall primary work area.
    The window manager pins it to the top bar and the bottom hangs off
    the screen, so the character must stay in the visible part."""
    SIZE = (1000, 1300)
    # HIT_BOX × 5 and OFFSET_LIMITS × 5 (see ui/drawing.py).
    BOX = (220, 615, 560, 475)
    LIMITS = (-210, 210, -605, 200)

    def test_window_that_fits_is_left_alone(self):
        assert visible_limits(LIMITS, (400, 300, *WIN), (44, 123, 112, 95),
                              PRIMARY) == LIMITS

    def test_too_tall_keeps_the_character_above_the_bottom(self):
        x0, x1, y0, y1 = visible_limits(
            self.LIMITS, (400, 152, *self.SIZE), self.BOX, PRIMARY)
        assert (x0, x1) == self.LIMITS[:2]       # width still fits
        assert y0 == self.LIMITS[2]
        # Character bottom at 152 + 615 + 475 + y1 = the area bottom.
        assert 152 + 615 + 475 + y1 == 152 + 1048

    def test_drag_down_stops_at_the_bottom_of_the_screen(self):
        p = DragPlacement()
        p.begin((900, 1000), (400, 152))
        win = p.update((900, 5000), self.SIZE, AREAS, self.LIMITS,
                       box=self.BOX)
        assert win[1] == 152
        assert 152 + 615 + 475 + p.offset[1] <= 1200

    def test_drag_up_still_reaches_the_top_bar(self):
        p = DragPlacement()
        p.begin((900, 900), (400, 152))
        p.update((900, 300), self.SIZE, AREAS, self.LIMITS, box=self.BOX)
        assert 152 + 615 + p.offset[1] == 152 + 615 - 600

    def test_aim_after_growing(self):
        # Feet were at y 1100; at 5× they sit 1070 below the window top,
        # so the window "should" be at y 30, but it's pinned at 152.
        p = DragPlacement()
        limits = visible_limits(self.LIMITS, (400, 152, *self.SIZE),
                                self.BOX, PRIMARY)
        p.aim((400, 1100 - 1070), (400, 152), limits)
        assert p.offset == (0, -122)
        # The window manager put it somewhere else after all: re-aim.
        assert p.reconcile((400, 160), limits)
        assert p.offset == (0, -130)

    def test_box_that_cannot_fit_is_centred(self):
        tiny = (0, 0, 800, 400)
        x0, x1, y0, y1 = visible_limits(
            self.LIMITS, (0, 0, *self.SIZE), self.BOX, tiny)
        assert y0 == y1
