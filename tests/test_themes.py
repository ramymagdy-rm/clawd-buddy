# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Unit tests for the colour-theme registry.

Themes are pure data; the value of testing them is catching authoring
mistakes — missing keys, malformed colours — at import time rather than
when a user picks the broken theme from the tray menu.
"""

import pytest

from clawd_buddy.ui import themes as themes_mod


# ── Registry shape ───────────────────────────────────────────────────
class TestRegistry:
    def test_themes_is_a_non_empty_dict(self):
        assert isinstance(themes_mod.THEMES, dict)
        assert len(themes_mod.THEMES) >= 2  # at least dark + light

    def test_theme_names_matches_themes_keys(self):
        # THEME_NAMES is the display order; it must mirror the dict order
        # because dict iteration since Py3.7 is insertion-ordered.
        assert themes_mod.THEME_NAMES == list(themes_mod.THEMES.keys())

    def test_default_theme_is_a_known_theme(self):
        assert themes_mod.DEFAULT_THEME in themes_mod.THEMES

    def test_required_keys_is_frozen(self):
        # Required-keys list is a contract; making it mutable would let
        # a careless edit weaken the schema check below.
        assert isinstance(themes_mod.REQUIRED_KEYS, frozenset)


# ── Per-theme shape ──────────────────────────────────────────────────
class TestEachTheme:
    @pytest.mark.parametrize("name", list(themes_mod.THEMES.keys()))
    def test_has_all_required_keys(self, name):
        missing = themes_mod.REQUIRED_KEYS - themes_mod.THEMES[name].keys()
        assert not missing, f"theme '{name}' missing keys: {missing}"

    @pytest.mark.parametrize("name", list(themes_mod.THEMES.keys()))
    def test_has_no_extra_keys(self, name):
        # Extra keys aren't broken — but catching them flags drift between
        # theme authors and the rendering code.
        extra = themes_mod.THEMES[name].keys() - themes_mod.REQUIRED_KEYS
        assert not extra, f"theme '{name}' has unexpected keys: {extra}"

    @pytest.mark.parametrize("name", list(themes_mod.THEMES.keys()))
    def test_all_values_are_valid_rgb(self, name):
        theme = themes_mod.THEMES[name]
        for key, val in theme.items():
            assert isinstance(val, tuple), (
                f"theme '{name}' key '{key}' is not a tuple: {val!r}")
            assert len(val) == 3, (
                f"theme '{name}' key '{key}' is not 3-tuple: {val!r}")
            for chan in val:
                assert isinstance(chan, int), (
                    f"theme '{name}' key '{key}' has non-int channel")
                assert 0 <= chan <= 255, (
                    f"theme '{name}' key '{key}' channel out of range: "
                    f"{chan!r}")


# ── Public helpers ───────────────────────────────────────────────────
class TestHelpers:
    def test_get_theme_returns_known_theme(self):
        assert themes_mod.get_theme("dark") is themes_mod.THEMES["dark"]

    def test_get_theme_falls_back_for_unknown(self):
        result = themes_mod.get_theme("does-not-exist")
        assert result is themes_mod.THEMES[themes_mod.DEFAULT_THEME]

    def test_is_known_theme_true(self):
        assert themes_mod.is_known_theme("dark") is True

    def test_is_known_theme_false(self):
        assert themes_mod.is_known_theme("rainbow-glitter") is False


# ── Character themes and costumes ────────────────────────────────────
_COSTUME_KEYS = {"traffic", "bands", "ears", "ear", "ear_tip", "hair",
                 "emblem", "web", "blush", "accent"}


def _is_rgb(c):
    return (isinstance(c, tuple) and len(c) == 3
            and all(isinstance(v, int) and 0 <= v <= 255 for v in c))


class TestCharacterThemes:
    def test_groups_cover_every_theme_in_order(self):
        assert (list(themes_mod.CLASSIC_THEMES)
                + list(themes_mod.CHARACTER_THEMES)) == themes_mod.THEME_NAMES

    def test_the_characters_are_there(self):
        for name in ("nemo", "dory", "batman", "ironman", "hulk",
                     "spiderman", "captain", "pikachu"):
            assert name in themes_mod.CHARACTER_THEMES

    def test_every_character_has_a_costume(self):
        for name in themes_mod.CHARACTER_THEMES:
            assert themes_mod.costume(name), name

    def test_classic_themes_wear_nothing(self):
        for name in themes_mod.CLASSIC_THEMES:
            assert themes_mod.costume(name) == {}

    def test_labels(self):
        assert themes_mod.theme_label("ironman") == "Iron Man"
        assert themes_mod.theme_label("spiderman") == "Spider-Man"
        assert themes_mod.theme_label("dracula") == "Dracula"

    @pytest.mark.parametrize("name", list(themes_mod.THEMES))
    def test_swatch_colors_are_rgb(self, name):
        fill, accent = themes_mod.swatch_colors(name)
        assert _is_rgb(fill) and _is_rgb(accent)


class TestCostumes:
    @pytest.mark.parametrize("name", list(themes_mod.COSTUMES))
    def test_known_theme_and_parts(self, name):
        assert name in themes_mod.THEMES
        c = themes_mod.COSTUMES[name]
        assert set(c) <= _COSTUME_KEYS, set(c) - _COSTUME_KEYS
        assert c.get("ears") in (None, "bat", "pointy", "fin")
        assert c.get("emblem") in (None, "bat", "reactor", "star")
        for key in ("ear", "ear_tip", "hair", "web", "blush", "accent"):
            if key in c:
                assert _is_rgb(c[key]), (name, key)

    @pytest.mark.parametrize("name", list(themes_mod.COSTUMES))
    def test_bands_are_fractions_and_colours(self, name):
        for band in themes_mod.COSTUMES[name].get("bands", ()):
            f0, f1, g0, g1, fill, edge = band
            assert 0 <= f0 < f1 <= 1 and 0 <= g0 < g1 <= 1
            assert _is_rgb(fill) and (edge is None or _is_rgb(edge))
