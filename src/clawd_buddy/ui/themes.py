# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Colour themes for the buddy.

Each theme is a dict of named colour roles → RGB triples. The drawing
code reads roles like `body_outer` or `eye_white`; theme authors can add
new themes by adding an entry to `THEMES` with the same set of keys.

`THEME_NAMES` is the *display order* in the system-tray Theme submenu —
keep it in sync with `THEMES` (Python preserves insertion order for
dicts since 3.7, so iterating `THEMES.keys()` gives the same order).

The Linux `bg_fill` key is the window background fill since X11 cannot
do color-key transparency — pick a colour that visually disappears
against the surrounding panel/dock.
"""

# Ordered list of themes — also the display order in the
# system-tray "Theme" submenu.
THEMES = {
    "dark": {
        "body_outer":  (35, 35, 48),
        "body_inner":  (42, 42, 58),
        "title_bar":   (70, 70, 92),
        "screen_bg":   (22, 22, 32),
        "eye_white":   (230, 235, 255),
        "pupil":       (25, 25, 40),
        "mouth":       (120, 130, 160),
        "mouth_happy": (255, 220, 80),
        "limb":        (35, 35, 48),
        "shoe":        (50, 50, 68),
        "wave_eye":    (255, 190, 80),
        "bg_fill":     (1, 1, 1),
    },
    "light": {
        "body_outer":  (195, 200, 215),
        "body_inner":  (215, 220, 235),
        "title_bar":   (175, 180, 200),
        "screen_bg":   (238, 240, 248),
        "eye_white":   (255, 255, 255),
        "pupil":       (35, 35, 55),
        "mouth":       (135, 140, 168),
        "mouth_happy": (255, 180, 40),
        "limb":        (175, 180, 200),
        "shoe":        (155, 160, 180),
        "wave_eye":    (230, 150, 30),
        "bg_fill":     (250, 250, 255),
    },
    "dracula": {
        # Deep magenta-purple — red-leaning to stand apart from nord
        "body_outer":  (95, 40, 140),
        "body_inner":  (120, 65, 170),
        "title_bar":   (170, 100, 220),
        "screen_bg":   (50, 20, 80),
        "eye_white":   (248, 248, 242),
        "pupil":       (50, 20, 80),
        "mouth":       (189, 147, 249),
        "mouth_happy": (255, 121, 198),
        "limb":        (95, 40, 140),
        "shoe":        (55, 25, 85),
        "wave_eye":    (255, 184, 108),
        "bg_fill":     (50, 20, 80),
    },
    "monokai": {
        # Saturated forest green — clearly not gray-blue
        "body_outer":  (50, 95, 25),
        "body_inner":  (75, 125, 40),
        "title_bar":   (150, 190, 60),
        "screen_bg":   (30, 50, 18),
        "eye_white":   (248, 248, 242),
        "pupil":       (30, 50, 18),
        "mouth":       (166, 226, 46),
        "mouth_happy": (253, 151, 31),
        "limb":        (50, 95, 25),
        "shoe":        (32, 55, 18),
        "wave_eye":    (249, 38, 114),
        "bg_fill":     (30, 50, 18),
    },
    "nord": {
        # Strong steel / frost blue — green-leaning to stand apart from dracula
        "body_outer":  (30, 95, 165),
        "body_inner":  (55, 125, 195),
        "title_bar":   (100, 160, 220),
        "screen_bg":   (20, 55, 95),
        "eye_white":   (236, 239, 244),
        "pupil":       (20, 55, 95),
        "mouth":       (136, 192, 208),
        "mouth_happy": (163, 190, 140),
        "limb":        (30, 95, 165),
        "shoe":        (20, 55, 95),
        "wave_eye":    (235, 203, 139),
        "bg_fill":     (20, 55, 95),
    },
    "gruvbox": {
        # Warm burnt orange — red-dominant to stand apart from monokai's green
        "body_outer":  (140, 65, 20),
        "body_inner":  (175, 95, 35),
        "title_bar":   (235, 145, 40),
        "screen_bg":   (70, 35, 15),
        "eye_white":   (235, 219, 178),
        "pupil":       (70, 35, 15),
        "mouth":       (184, 187, 38),
        "mouth_happy": (250, 189, 47),
        "limb":        (140, 65, 20),
        "shoe":        (70, 35, 15),
        "wave_eye":    (254, 128, 25),
        "bg_fill":     (70, 35, 15),
    },
    "solarized": {
        # Warm beige / cream (clearly a light theme, yellow-tinted)
        "body_outer":  (220, 200, 140),
        "body_inner":  (245, 225, 170),
        "title_bar":   (170, 155, 100),
        "screen_bg":   (253, 246, 227),
        "eye_white":   (255, 255, 255),
        "pupil":       (7, 54, 66),
        "mouth":       (88, 110, 117),
        "mouth_happy": (181, 137, 0),
        "limb":        (170, 155, 100),
        "shoe":        (130, 115, 70),
        "wave_eye":    (203, 75, 22),
        "bg_fill":     (245, 225, 170),
    },
    "sunset": {
        # Vivid coral / peach (clearly warm, not gray)
        "body_outer":  (255, 130, 100),
        "body_inner":  (255, 170, 140),
        "title_bar":   (230, 80, 60),
        "screen_bg":   (255, 210, 185),
        "eye_white":   (255, 255, 255),
        "pupil":       (90, 35, 25),
        "mouth":       (205, 92, 92),
        "mouth_happy": (255, 99, 71),
        "limb":        (230, 80, 60),
        "shoe":        (180, 60, 40),
        "wave_eye":    (255, 220, 80),
        "bg_fill":     (255, 210, 185),
    },
}

THEME_NAMES = list(THEMES.keys())  # display order for tray menu
DEFAULT_THEME = "dark"

# Every theme must define this exact set of colour roles. Used at import
# time by tests to catch theme authors who forget a key.
REQUIRED_KEYS = frozenset({
    "body_outer", "body_inner", "title_bar", "screen_bg",
    "eye_white", "pupil", "mouth", "mouth_happy",
    "limb", "shoe", "wave_eye", "bg_fill",
})


def get_theme(name):
    """Return the theme dict for `name`, falling back to DEFAULT_THEME."""
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def is_known_theme(name):
    return name in THEMES
