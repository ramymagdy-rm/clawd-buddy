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


# ── rounded_rect ─────────────────────────────────────────────────────
class TestRoundedRect:
    def test_basic_call_does_not_crash(self, surface):
        drawing.rounded_rect(surface, (255, 0, 0), (10, 10, 50, 30), 5)

    def test_zero_radius(self, surface):
        # r=0 is degenerate (no corners drawn) — should still complete.
        drawing.rounded_rect(surface, (0, 255, 0), (0, 0, 20, 20), 0)

    def test_radius_clamped_to_half_dimension(self, surface):
        # rounded_rect clamps r to half the smaller dimension; passing a
        # large radius shouldn't error.
        drawing.rounded_rect(surface, (0, 0, 255), (0, 0, 10, 10), 100)

    def test_paints_centre_pixel(self, surface):
        # A solid filled rect at (10,10) → (60,40) should colour the
        # middle pixel.
        color = (123, 45, 200)
        drawing.rounded_rect(surface, color, (10, 10, 50, 30), 5)
        px = surface.get_at((35, 25))[:3]
        assert tuple(px) == color


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
