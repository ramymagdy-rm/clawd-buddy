# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Smoke tests for the drawing module.

Pixel-accurate rendering is impractical to assert on, but the drawing
code still has plenty of testable surface: it must not crash for any
valid state, and `draw_buddy` must consume/advance the confetti
particle list every frame.
"""

import pygame
import pytest

from clawd_buddy import state as buddy_state
from clawd_buddy.constants import WIN_H, WIN_W
from clawd_buddy.ui import drawing


@pytest.fixture(autouse=True, scope="module")
def _pygame_display():
    # SDL_VIDEODRIVER=dummy is set by conftest.py — pygame.display works
    # against an off-screen surface, so set_mode is safe here.
    pygame.display.init()
    yield
    pygame.display.quit()


@pytest.fixture
def surface():
    return pygame.Surface((WIN_W, WIN_H))


@pytest.fixture
def clock():
    """A frozen clock so BuddyState's elapsed-time math is stable."""

    class _Clock:
        def __init__(self):
            self.t = 1000.0

        def __call__(self):
            return self.t

        def advance(self, s):
            self.t += s

    return _Clock()


@pytest.fixture
def state(clock):
    return buddy_state.BuddyState(
        theme_name="dark", sound_pack="off", clock=clock,
    )


# ── draw_buddy state coverage ────────────────────────────────────────
class TestDrawBuddyAcrossModes:
    @pytest.mark.parametrize(
        "set_mode",
        [
            lambda s: None,                       # idle
            lambda s: s.trigger(),                # celebrating
            lambda s: s.wave(),                   # waving
            lambda s: s.greet(),                  # greeting
            lambda s: s.start_thinking(),         # thinking
        ],
        ids=["idle", "celebrating", "waving", "greeting", "thinking"],
    )
    @pytest.mark.parametrize("blink", [False, True])
    def test_does_not_crash(self, surface, state, set_mode, blink):
        set_mode(state)
        drawing.draw_buddy(surface, 1.0, state, blink)

    def test_every_theme(self, surface, state):
        # Walk every theme — catches a theme that's missing a colour key
        # that the drawing code reads.
        from clawd_buddy.ui.themes import THEMES

        for name in THEMES:
            state.set_theme(name)
            drawing.draw_buddy(surface, 1.0, state, blink=False)


# ── Character costumes ───────────────────────────────────────────────
class TestCostumes:
    def test_band_stays_inside_the_rounded_shell(self):
        rect = (10, 20, 80, 60, 20)
        poly = drawing._clipped_band(rect, 10, 30, 20, 80)
        assert poly
        for x, y in poly:
            top, bottom = drawing._rrect_span(x, *rect)
            assert top - 1e-6 <= y <= bottom + 1e-6

    def test_band_outside_the_shell_is_skipped(self):
        assert drawing._clipped_band((10, 20, 80, 60, 20), 0, 5, 0, 10) is None

    @pytest.mark.parametrize("theme", ["batman", "pikachu", "hulk", "dory"])
    def test_head_parts_draw_above_the_head(self, theme, clock):
        # Ears, hair and fins stick out above the body; a classic theme
        # leaves that strip empty.
        def strip_pixels(name):
            surf = pygame.Surface((drawing.WIN_W, drawing.WIN_H),
                                  pygame.SRCALPHA)
            st = buddy_state.BuddyState(theme_name=name, sound_pack="off",
                                        clock=clock)
            drawing.BuddyRenderer().draw(surf, 1000.0, st, blink=False)
            top = int(drawing.BASE_TOP)
            return sum(surf.get_at((x, y))[3] > 0
                       for x in range(drawing.WIN_W)
                       for y in range(top - 10, top - 1))
        assert strip_pixels("dark") == 0
        assert strip_pixels(theme) > 20

    def test_costumes_draw_in_every_mode(self, surface, state):
        for name in ("nemo", "ironman", "spiderman", "captain"):
            state.set_theme(name)
            for set_mode in (lambda s: None, lambda s: s.celebrate(),
                             lambda s: s.wave(), lambda s: s.start_thinking()):
                set_mode(state)
                drawing.draw_buddy(surface, 1.0, state, blink=False)


# ── Confetti lifecycle ───────────────────────────────────────────────
class TestConfettiLifecycle:
    def test_celebrate_spawns_particles(self, state):
        assert state.confetti == []
        state.trigger()
        assert len(state.confetti) == 40

    def test_draw_steps_particles_downward(self, surface, state):
        state.trigger()
        before = [(p[0], p[1]) for p in state.confetti]
        drawing.draw_buddy(surface, 0.0, state, blink=False)
        after = [(p[0], p[1]) for p in state.confetti]
        # At least some particles should have moved (vy applies + gravity).
        moved = sum(1 for a, b in zip(before, after) if a != b)
        assert moved > 0

    def test_particles_removed_when_offscreen(self, surface, state):
        state.trigger()
        # Force every particle below the floor so the next frame discards
        # them all.
        for p in state.confetti:
            p[1] = WIN_H + 100
        drawing.draw_buddy(surface, 0.0, state, blink=False)
        assert state.confetti == []


# ── Speech bubble (M2) ───────────────────────────────────────────────
class TestSpeechBubble:
    def test_no_op_for_empty_text(self, surface, state):
        # The bubble is skipped on empty text — easiest way to assert it
        # is to confirm calling draw_buddy without a bubble works and
        # leaves bubble_text empty.
        before = surface.copy()
        drawing.draw_buddy(surface, 0.0, state, blink=False)
        # We can't compare entire surfaces (the buddy was drawn), but we
        # can be sure no crash and bubble_text remained empty.
        assert state.bubble_text == ""
        del before  # silence unused-var

    def test_renders_simple_bubble_without_crashing(self, surface, state):
        state.set_message("hello")
        drawing.draw_buddy(surface, 0.0, state, blink=False)

    def test_renders_long_text_with_wrap_and_truncate(self, surface, state):
        long_msg = (
            "this is a much longer status message than the bubble can show "
            "in a single line and definitely won't fit on two lines either"
        )
        state.set_message(long_msg)
        drawing.draw_buddy(surface, 0.0, state, blink=False)
        # The state-level cap ensures the bubble_text fits the contract;
        # the renderer further truncates visually.
        assert state.bubble_text  # not cleared

    def test_renders_across_modes(self, surface, state):
        # Bubbles must coexist with every mode — render path branches on
        # the active mode, so walk through them all with a bubble.
        for setter in (lambda s: None, lambda s: s.trigger(),
                       lambda s: s.wave(), lambda s: s.greet(),
                       lambda s: s.start_thinking()):
            fresh = buddy_state.BuddyState(theme_name="dark",
                                           sound_pack="off")
            setter(fresh)
            fresh.set_message("ping")
            drawing.draw_buddy(surface, 0.0, fresh, blink=False)

    def test_renders_across_themes(self, surface, state):
        # A theme missing a colour the bubble reads (mouth / screen_bg /
        # body_outer) would crash here.
        from clawd_buddy.ui.themes import THEMES
        state.set_message("ping")
        for name in THEMES:
            state.set_theme(name)
            drawing.draw_buddy(surface, 0.0, state, blink=False)


# ── Reduce-motion rendering (M3) ─────────────────────────────────────
class TestReduceMotionRendering:
    """Pixel-accurate motion is hard to assert, but we can pin the two
    invariants that matter: reduce-motion (a) doesn't crash for any
    mode, and (b) skips confetti spawning so the celebrate animation
    runs without the particle swarm."""

    @pytest.mark.parametrize(
        "set_mode",
        [
            lambda s: None,
            lambda s: s.trigger(),
            lambda s: s.wave(),
            lambda s: s.greet(),
            lambda s: s.start_thinking(),
        ],
        ids=["idle", "celebrating", "waving", "greeting", "thinking"],
    )
    def test_does_not_crash_with_reduce_motion(self, surface, clock, set_mode):
        s = buddy_state.BuddyState(theme_name="dark", sound_pack="off",
                                   clock=clock, reduce_motion=True)
        set_mode(s)
        drawing.draw_buddy(surface, 1.0, s, blink=False)

    def test_celebrate_skips_confetti_spawn(self, clock):
        s = buddy_state.BuddyState(theme_name="dark", sound_pack="off",
                                   clock=clock, reduce_motion=True)
        s.trigger()
        assert s.confetti == []

    def test_render_with_bubble_and_reduce_motion(self, surface, clock):
        s = buddy_state.BuddyState(theme_name="dark", sound_pack="off",
                                   clock=clock, reduce_motion=True)
        s.set_message("ping")
        s.start_thinking()
        drawing.draw_buddy(surface, 1.0, s, blink=False)


class TestWrapBubbleText:
    def test_short_text_one_line(self):
        font = drawing._bubble_font()
        lines = drawing._wrap_bubble_text(font, "hi", 200)
        assert lines == ["hi"]

    def test_empty_returns_empty_list(self):
        font = drawing._bubble_font()
        assert drawing._wrap_bubble_text(font, "", 200) == []

    def test_caps_at_max_lines(self):
        font = drawing._bubble_font()
        # Force narrow line budget so every word goes on its own line.
        narrow = font.size("xxx")[0] + 1
        lines = drawing._wrap_bubble_text(
            font, "one two three four five", narrow, max_lines=2)
        assert len(lines) <= 2

    def test_overflowing_final_line_ends_with_ellipsis(self):
        font = drawing._bubble_font()
        narrow = font.size("xxx")[0] + 1
        lines = drawing._wrap_bubble_text(
            font, "one two three four five", narrow, max_lines=2)
        assert lines[-1].endswith("…")


# ── M7: workspace badge ──────────────────────────────────────────────
class TestWorkspaceBadge:
    def _make_visible(self, state):
        state.record_workspace("api")
        state.record_workspace("web")
        assert state.workspace_badge_visible()

    def test_badge_alone_shows_a_pill_while_idle(self, surface, state):
        # Idle has no status text; a visible badge still gets a pill so
        # the workspace letter has somewhere to live.
        self._make_visible(state)
        r = drawing.BuddyRenderer()
        r.draw(surface, 1000.0, state, blink=False)
        assert r._pill_key == (None, ("web",))

    def test_two_working_sessions_show_both_chips_and_a_count(
            self, surface, state):
        state.record_workspace("api")
        state.record_workspace("web")
        state.start_thinking(session_id="a", workspace="api")
        state.start_thinking(session_id="b", workspace="web")
        r = drawing.BuddyRenderer()
        r.draw(surface, 1000.0, state, blink=False)
        assert r._pill_key == ("Thinking \u00d72", ("api", "web"))

    def test_one_working_session_is_plain_thinking(self, surface, state):
        state.start_thinking(session_id="a")
        r = drawing.BuddyRenderer()
        r.draw(surface, 1000.0, state, blink=False)
        assert r._pill_key == ("Thinking…", ())

    def test_widest_pill_fits_the_window(self, surface, state):
        for i, ws in enumerate(("api", "web", "cli", "docs")):
            state.record_workspace(ws)
            state.start_thinking(session_id=str(i), workspace=ws)
        r = drawing.BuddyRenderer()
        pen = drawing._Pen(surface)
        _, labels, w = r._pill_content(state, state.mode, 0.0, pen)
        assert len(labels) == 3
        assert w <= WIN_W - 2 * drawing._EDGE_MARGIN

    def test_draw_buddy_with_visible_badge(self, surface, state):
        self._make_visible(state)
        drawing.draw_buddy(surface, 1000.0, state, blink=False)

    def test_draw_buddy_with_badge_in_every_mode(self, surface, state):
        self._make_visible(state)
        for action in ("trigger", "wave", "greet", "start_thinking"):
            getattr(state, action)()
            drawing.draw_buddy(surface, 1000.0, state, blink=False)

    def test_badge_paints_pixels(self, surface, state):
        # The badge square must actually land on the surface — compare
        # a badge-on frame against a badge-off frame.
        self._make_visible(state)
        drawing.draw_buddy(surface, 1000.0, state, blink=False)
        with_badge = pygame.image.tobytes(surface, "RGB")
        surface.fill((0, 0, 0))
        state.set_workspace_badge_enabled(False)
        drawing.draw_buddy(surface, 1000.0, state, blink=False)
        without_badge = pygame.image.tobytes(surface, "RGB")
        assert with_badge != without_badge

    def test_reduce_motion_still_renders_badge(self, surface, state):
        self._make_visible(state)
        state.set_reduce_motion(True)
        drawing.draw_buddy(surface, 1000.0, state, blink=False)


# ── Transparent-window compositing (Linux ARGB) ──────────────────────
class TestTransparentBackground:
    """On Linux with a compositor the window has a real alpha channel;
    the background must stay fully clear so no rectangle shows around
    the buddy."""

    def _alpha(self, surf, pos):
        return surf.get_at(pos).a

    def test_draw_buddy_leaves_background_clear(self, state):
        surf = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        drawing.draw_buddy(surf, 1000.0, state, blink=False)
        for corner in [(0, 0), (WIN_W - 1, 0),
                       (0, WIN_H - 1), (WIN_W - 1, WIN_H - 1)]:
            assert self._alpha(surf, corner) == 0
        # ...while the body itself is solid.
        assert self._alpha(surf, (WIN_W // 2, WIN_H - 100)) == 255

    def test_every_mode_keeps_corners_clear(self, state):
        surf = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        for action in ("trigger", "wave", "greet", "start_thinking"):
            getattr(state, action)()
            surf.fill((0, 0, 0, 0))
            drawing.draw_buddy(surf, 1000.0, state, blink=False)
            assert self._alpha(surf, (0, 0)) == 0
            assert self._alpha(surf, (WIN_W - 1, 0)) == 0


class TestComposeFrame:
    def _frame(self, size=(10, 10)):
        """Clear frame with one opaque and one half-transparent pixel."""
        frame = pygame.Surface(size, pygame.SRCALPHA)
        frame.fill((0, 0, 0, 0))
        frame.fill((200, 100, 50, 255), (0, 0, 5, 5))
        frame.set_at((8, 8), (200, 100, 50, 128))
        return frame

    def test_opaque_mode_is_a_plain_copy(self):
        screen = pygame.Surface((10, 10))
        frame = pygame.Surface((10, 10))
        frame.fill((30, 60, 90))
        drawing.compose_frame(screen, frame, transparent=False)
        assert screen.get_at((5, 5))[:3] == (30, 60, 90)

    def test_transparent_mode_writes_premultiplied_alpha(self):
        # X11 compositors read alpha as premultiplied: RGB must be
        # scaled by alpha or semi-transparent pixels glow too bright.
        screen = pygame.Surface((10, 10), pygame.SRCALPHA)
        drawing.compose_frame(screen, self._frame(), transparent=True)
        assert tuple(screen.get_at((2, 2))) == (200, 100, 50, 255)
        r, g, b, a = screen.get_at((8, 8))
        assert a == 128
        assert (r, g, b) == pytest.approx((100, 50, 25), abs=1)
        assert tuple(screen.get_at((9, 0))) == (0, 0, 0, 0)

    def test_transparent_mode_clears_previous_frame(self):
        # Leftovers from the last frame must not show through clear
        # pixels (the buddy bobs, so pixels move every frame).
        screen = pygame.Surface((10, 10), pygame.SRCALPHA)
        screen.fill((255, 255, 255, 255))
        drawing.compose_frame(screen, self._frame(), transparent=True)
        assert tuple(screen.get_at((9, 0))) == (0, 0, 0, 0)

    def test_transparent_mode_scales_to_window(self):
        # Ctrl+2..4: frame is drawn at native size and scaled up.
        screen = pygame.Surface((20, 20), pygame.SRCALPHA)
        drawing.compose_frame(screen, self._frame(), transparent=True)
        assert tuple(screen.get_at((3, 3))) == (200, 100, 50, 255)
        assert tuple(screen.get_at((19, 0))) == (0, 0, 0, 0)

    def test_opaque_mode_scales_to_window(self):
        screen = pygame.Surface((20, 20))
        frame = pygame.Surface((10, 10))
        frame.fill((30, 60, 90))
        drawing.compose_frame(screen, frame, transparent=False)
        assert screen.get_at((19, 19))[:3] == (30, 60, 90)


# ── Redesign: renderer, scaling, compositing ─────────────────────────
class TestRenderer:
    def test_dirty_rect_covers_the_body(self, surface, state):
        r = drawing.BuddyRenderer()
        r.draw(surface, 1000.0, state, blink=False)
        assert r.dirty is not None
        assert r.dirty.collidepoint(WIN_W // 2, WIN_H - 100)
        # Idle with no pill or bubble: the top of the window is untouched,
        # which is what makes partial compositing cheap.
        assert r.dirty.top > 60

    def test_dirty_rect_grows_for_pill_and_bubble(self, surface, state):
        r = drawing.BuddyRenderer()
        r.draw(surface, 1000.0, state, blink=False)
        idle_top = r.dirty.top
        state.start_thinking()
        state.set_message("hello there")
        r.draw(surface, 1001.0, state, blink=False)
        assert r.dirty.top < idle_top

    @pytest.mark.parametrize("scale", [1.25, 1.5, 2.0])
    def test_renders_at_any_scale(self, state, scale):
        # Geometry is in logical units; the surface width sets the pixel
        # scale, so the body lands at the same relative spot.
        w, h = int(WIN_W * scale), int(WIN_H * scale)
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        drawing.BuddyRenderer().draw(surf, 1000.0, state, blink=False)
        assert surf.get_at((w // 2, int((WIN_H - 100) * scale))).a == 255
        assert surf.get_at((0, 0)).a == 0

    def test_frame_size_supersamples_only_with_alpha(self):
        assert drawing.frame_size_for((200, 260), True) == (
            200 * drawing.SUPERSAMPLE, 260 * drawing.SUPERSAMPLE)
        assert drawing.frame_size_for((200, 260), False) == (200, 260)

    def test_hard_mode_skips_soft_effects(self, state):
        # Opaque frames (Windows colour key) must not get translucent
        # shadows or glows: they'd blend into the key colour and show up
        # as dark halos. Below the feet only the shadow would paint.
        state.wave()
        surf = pygame.Surface((WIN_W, WIN_H))
        surf.fill((1, 1, 1))
        drawing.BuddyRenderer().draw(surf, 1000.0, state, blink=False)
        assert surf.get_at((WIN_W // 2, drawing.GROUND_Y + 2))[:3] == (1, 1, 1)

    def test_soft_mode_paints_ground_shadow(self, state):
        surf = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        drawing.BuddyRenderer().draw(surf, 1000.0, state, blink=False)
        assert 0 < surf.get_at((WIN_W // 2, drawing.GROUND_Y + 2)).a < 255


class TestFrameRateHint:
    def _settle(self, r, surface, state, t0, secs=1.0):
        t = t0
        while t < t0 + secs:
            r.draw(surface, t, state, blink=False)
            t += 1 / 30
        return t

    def test_idle_settles_to_slow_frames(self, surface, state):
        r = drawing.BuddyRenderer()
        self._settle(r, surface, state, 1000.0)
        assert not r.wants_fast_frames(state)

    def test_thinking_settles_to_slow_frames(self, surface, state):
        # Regression: the thinking loop's tapping arms must not count as
        # "still transitioning" and pin the loop at the fast rate.
        r = drawing.BuddyRenderer()
        t = self._settle(r, surface, state, 1000.0)
        state.start_thinking()
        r.draw(surface, t, state, blink=False)
        assert r.wants_fast_frames(state)  # transition just started
        self._settle(r, surface, state, t + 0.01)
        assert not r.wants_fast_frames(state)

    @pytest.mark.parametrize("action", ["trigger", "wave", "greet"])
    def test_reactions_run_fast(self, surface, state, action):
        r = drawing.BuddyRenderer()
        getattr(state, action)()
        self._settle(r, surface, state, 1000.0)
        assert r.wants_fast_frames(state)


class TestConfettiFrameRateIndependence:
    def _fall(self, fps, secs=0.5):
        p = [100.0, 90.0, 1.0, -4.0, (255, 0, 0), 4]
        st = buddy_state.BuddyState(theme_name="dark", sound_pack="off")
        st.confetti = [p]
        r = drawing.BuddyRenderer()
        surf = pygame.Surface((WIN_W, WIN_H))
        n = int(secs * fps)
        for i in range(n + 1):
            r.draw(surf, 1000.0 + i / fps, st, blink=False)
        return p[0], p[1]

    def test_same_trajectory_at_30_and_120_fps(self):
        x30, y30 = self._fall(30)
        x120, y120 = self._fall(120)
        assert x30 == pytest.approx(x120, abs=3)
        assert y30 == pytest.approx(y120, abs=8)


class TestPalette:
    def test_face_contrasts_with_screen_on_every_theme(self):
        # The face glows on dark screens and is inked on light ones;
        # either way it must read clearly.
        from clawd_buddy.ui.themes import THEMES
        for name, th in THEMES.items():
            pal = drawing._palette(th)
            diff = abs(drawing._lum(pal["face"]) - drawing._lum(th["screen_bg"]))
            assert diff > 100, name

    def test_mix_never_returns_the_colour_key(self):
        from clawd_buddy.constants import TKEY
        assert drawing._mix((0, 0, 0), (2, 2, 2), 0.5) != TKEY


class TestComposeDirty:
    def _render(self, state):
        frame = pygame.Surface((WIN_W * 2, WIN_H * 2), pygame.SRCALPHA)
        frame.fill((0, 0, 0, 0))
        r = drawing.BuddyRenderer()
        state.start_thinking()
        r.draw(frame, 1000.0, state, blink=False)
        return frame, r.dirty

    def test_partial_compose_matches_full_compose(self, state):
        frame, dirty = self._render(state)
        full = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        part = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        drawing.compose_frame(full, frame, True)
        rect = drawing.compose_frame(part, frame, True, dirty)
        assert pygame.image.tobytes(full, "RGBA") == \
            pygame.image.tobytes(part, "RGBA")
        assert rect.w < WIN_W or rect.h < WIN_H

    def test_returns_screen_rect_covering_content(self, state):
        frame, dirty = self._render(state)
        screen = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        rect = drawing.compose_frame(screen, frame, True, dirty)
        assert rect.collidepoint(WIN_W // 2, WIN_H - 100)
        assert pygame.Rect(0, 0, WIN_W, WIN_H).contains(rect)


def test_reduce_motion_never_asks_for_fast_frames(surface, clock):
    s = buddy_state.BuddyState(theme_name="dark", sound_pack="off",
                               clock=clock, reduce_motion=True)
    s.wave()
    r = drawing.BuddyRenderer()
    r.draw(surface, 1000.0, s, blink=False)
    assert not r.wants_fast_frames(s)


# ── Character offset inside the window (drag past the WM's limit) ────
class TestOffset:
    def _render(self, state, offset):
        surf = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))
        r = drawing.BuddyRenderer()
        r.offset = offset
        r.draw(surf, 1000.0, state, blink=False)
        return surf, r

    def test_hit_box_stays_inside_the_window_at_every_limit(self):
        x0, x1, y0, y1 = drawing.OFFSET_LIMITS
        for ox, oy in [(x0, y0), (x1, y0), (x0, y1), (x1, y1)]:
            r = drawing.BuddyRenderer()
            r.offset = (ox, oy)
            x, y, w, h = r.hit_rect()
            assert x >= 0 and y >= 0
            assert x + w <= WIN_W and y + h <= WIN_H

    def test_hit_box_covers_the_body(self, state):
        surf, r = self._render(state, (0, 0))
        x, y, w, h = r.hit_rect()
        assert pygame.Rect(x, y, w, h).collidepoint(WIN_W // 2, WIN_H - 100)

    def test_offset_moves_the_character(self, state):
        oy = drawing.OFFSET_LIMITS[2]
        surf, _ = self._render(state, (0, oy))
        body = (WIN_W // 2, WIN_H - 100 + oy)
        assert surf.get_at(body).a == 255
        assert surf.get_at((WIN_W // 2, WIN_H - 100)).a == 0

    def test_pill_and_bubble_flip_below_at_the_top(self, state):
        state.start_thinking()
        state.set_message("Drink water!")
        oy = drawing.OFFSET_LIMITS[2]
        surf, r = self._render(state, (0, oy))
        # Everything still fits in the window, and something is painted
        # below the feet (the pill), nothing above the head.
        assert r.dirty.top >= 0 and r.dirty.bottom <= WIN_H
        below = drawing.GROUND_Y + oy + 12
        row = [surf.get_at((x, int(below))).a for x in range(WIN_W)]
        assert max(row) == 255

    def test_pill_stays_above_by_default(self, state):
        state.start_thinking()
        surf, r = self._render(state, (0, 0))
        pill_y = drawing.BASE_TOP - drawing.PILL_GAP - drawing.PILL_H / 2
        row = [surf.get_at((x, int(pill_y))).a for x in range(WIN_W)]
        assert max(row) == 255
