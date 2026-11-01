# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Colour themes for the buddy.

Each theme is a dict of named colour roles → RGB triples. The drawing
code reads roles like `body_outer` or `eye_white`; theme authors can add
new themes by adding an entry to `THEMES` with the same set of keys.

The character themes (Nemo, Batman, Pikachu…) add a costume on top of
the colours; see `COSTUMES`.

`THEME_NAMES` is the *display order* in the system-tray Theme submenu —
keep it in sync with `THEMES` (Python preserves insertion order for
dicts since 3.7, so iterating `THEMES.keys()` gives the same order).

The Linux `bg_fill` key is the window background fill used only when the
window can't be made transparent (X11 without a compositing manager — see
`platform._linux._linux_prepare_argb_window`). X11 has no colour-key
transparency, so pick a colour that visually disappears against the
surrounding panel/dock.
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

    # ── Character themes ─────────────────────────────────────────
    # Fan-made colour schemes inspired by cartoon and comic characters,
    # not affiliated with their rights holders. Each one also has a
    # costume in COSTUMES below (stripes, ears, an emblem…), which is
    # what makes it read as the character.
    "nemo": {
        # Clownfish: bright orange with white, black-edged bands.
        "body_outer":  (226, 92, 18),
        "body_inner":  (250, 124, 34),
        "title_bar":   (255, 160, 70),
        "screen_bg":   (18, 42, 78),
        "eye_white":   (255, 255, 255),
        "pupil":       (18, 42, 78),
        "mouth":       (255, 170, 110),
        "mouth_happy": (255, 196, 90),
        "limb":        (240, 110, 28),
        "shoe":        (196, 74, 12),
        "wave_eye":    (255, 220, 120),
        "bg_fill":     (18, 42, 78),
    },
    "dory": {
        # Blue tang: royal blue, a black marking, yellow fins.
        "body_outer":  (28, 78, 196),
        "body_inner":  (42, 104, 228),
        "title_bar":   (90, 150, 245),
        "screen_bg":   (14, 30, 72),
        "eye_white":   (236, 244, 255),
        "pupil":       (14, 30, 72),
        "mouth":       (120, 170, 250),
        "mouth_happy": (255, 214, 50),
        "limb":        (255, 206, 40),
        "shoe":        (240, 184, 20),
        "wave_eye":    (255, 214, 50),
        "bg_fill":     (14, 30, 72),
    },
    "batman": {
        # Dark knight: charcoal cowl, white eye slits, yellow emblem.
        "body_outer":  (30, 31, 38),
        "body_inner":  (46, 48, 58),
        "title_bar":   (70, 72, 86),
        "screen_bg":   (14, 14, 20),
        "eye_white":   (245, 245, 250),
        "pupil":       (14, 14, 20),
        "mouth":       (150, 152, 170),
        "mouth_happy": (250, 208, 40),
        "limb":        (34, 35, 44),
        "shoe":        (20, 20, 26),
        "wave_eye":    (250, 208, 40),
        "bg_fill":     (14, 14, 20),
    },
    "ironman": {
        # Red armour, gold faceplate, glowing eyes and arc reactor.
        "body_outer":  (150, 18, 26),
        "body_inner":  (188, 30, 38),
        "title_bar":   (220, 60, 60),
        "screen_bg":   (196, 140, 42),
        "eye_white":   (255, 255, 255),
        "pupil":       (226, 252, 255),
        "mouth":       (150, 100, 30),
        "mouth_happy": (120, 230, 255),
        "limb":        (176, 26, 34),
        "shoe":        (196, 140, 42),
        "wave_eye":    (120, 230, 255),
        "bg_fill":     (150, 18, 26),
    },
    "hulk": {
        # Green giant: green skin, black hair, purple shorts.
        "body_outer":  (62, 128, 40),
        "body_inner":  (88, 160, 56),
        "title_bar":   (130, 200, 90),
        "screen_bg":   (22, 54, 20),
        "eye_white":   (214, 255, 190),
        "pupil":       (22, 54, 20),
        "mouth":       (150, 210, 120),
        "mouth_happy": (190, 255, 140),
        "limb":        (76, 146, 48),
        "shoe":        (112, 58, 150),
        "wave_eye":    (190, 255, 140),
        "bg_fill":     (22, 54, 20),
    },
    "spiderman": {
        # Red mask with a web and big white eyes, blue arms.
        "body_outer":  (170, 20, 30),
        "body_inner":  (206, 32, 42),
        "title_bar":   (230, 70, 70),
        "screen_bg":   (178, 22, 32),
        "eye_white":   (255, 255, 255),
        "pupil":       (40, 10, 14),
        "mouth":       (255, 180, 180),
        "mouth_happy": (255, 255, 255),
        "limb":        (30, 66, 170),
        "shoe":        (170, 20, 30),
        "wave_eye":    (255, 255, 255),
        "bg_fill":     (178, 22, 32),
    },
    "captain": {
        # Star-spangled: blue with a white star on a red-ringed shield.
        "body_outer":  (24, 52, 130),
        "body_inner":  (36, 72, 166),
        "title_bar":   (90, 120, 200),
        "screen_bg":   (14, 26, 64),
        "eye_white":   (240, 244, 255),
        "pupil":       (14, 26, 64),
        "mouth":       (140, 160, 220),
        "mouth_happy": (255, 255, 255),
        "limb":        (196, 30, 40),
        "shoe":        (196, 30, 40),
        "wave_eye":    (255, 255, 255),
        "bg_fill":     (14, 26, 64),
    },
    "pikachu": {
        # Electric yellow, black-tipped ears, red cheeks.
        "body_outer":  (232, 182, 20),
        "body_inner":  (252, 212, 52),
        "title_bar":   (255, 230, 120),
        "screen_bg":   (255, 228, 104),
        "eye_white":   (255, 255, 255),
        "pupil":       (40, 28, 20),
        "mouth":       (110, 60, 40),
        "mouth_happy": (210, 60, 50),
        "limb":        (244, 196, 34),
        "shoe":        (214, 160, 16),
        "wave_eye":    (40, 28, 20),
        "bg_fill":     (255, 228, 104),
    },
}

THEME_NAMES = list(THEMES.keys())  # display order for tray menu
DEFAULT_THEME = "dark"

# The first eight are the classic palettes; the rest are characters.
CLASSIC_THEMES = ("dark", "light", "dracula", "monokai", "nord", "gruvbox",
                  "solarized", "sunset")
CHARACTER_THEMES = tuple(n for n in THEMES if n not in CLASSIC_THEMES)

# How a theme is named in menus, when `name.title()` isn't right.
THEME_LABELS = {
    "ironman": "Iron Man",
    "spiderman": "Spider-Man",
    "captain": "Captain",
}

_BLACK, _WHITE = (16, 16, 20), (255, 255, 255)

# What a character wears on top of its colours. The drawing code knows
# these parts (all optional):
#   traffic  False hides the three window dots on the head.
#   bands    [(x0, x1, y0, y1, fill, edge)]: stripes across the shell,
#            as fractions of the body box, clipped to its rounded shape;
#            `edge` (or None) outlines them.
#   ears     "bat" | "pointy" (with "ear_tip") | "fin", in "ear" colour.
#   hair     colour of a spiky fringe over the head.
#   emblem   "bat" | "reactor" | "star", on the forehead.
#   web      colour of a spider web drawn on the screen behind the face.
#   blush    cheek colour, instead of the default pink.
#   accent   second colour of the theme's dot in the settings window.
COSTUMES = {
    "nemo": {
        "traffic": False,
        "accent": _WHITE,
        "bands": [(0.06, 0.20, 0, 1, _WHITE, _BLACK),
                  (0.43, 0.57, 0, 1, _WHITE, _BLACK),
                  (0.80, 0.94, 0, 1, _WHITE, _BLACK)],
    },
    "dory": {
        "traffic": False,
        "accent": (255, 206, 40),
        "bands": [(0, 1, 0, 0.21, _BLACK, None),
                  (0.84, 1, 0, 1, _BLACK, None)],
        "ears": "fin", "ear": (255, 206, 40),
    },
    "batman": {
        "traffic": False,
        "accent": (250, 208, 40),
        "ears": "bat", "ear": (30, 31, 38),
        "emblem": "bat",
    },
    "ironman": {
        "traffic": False,
        "accent": (196, 140, 42),
        "emblem": "reactor",
    },
    "hulk": {
        "traffic": False,
        "accent": (112, 58, 150),
        "hair": (22, 22, 26),
    },
    "spiderman": {
        "traffic": False,
        "accent": (30, 66, 170),
        "web": (96, 10, 18),
    },
    "captain": {
        "traffic": False,
        "accent": _WHITE,
        "emblem": "star",
    },
    "pikachu": {
        "traffic": False,
        "accent": (226, 64, 50),
        "ears": "pointy", "ear": (244, 196, 34), "ear_tip": (30, 24, 20),
        "blush": (226, 64, 50),
    },
}

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


def theme_label(name):
    """Display name for a theme: "Iron Man", "Dracula"."""
    return THEME_LABELS.get(name, name.title())


def costume(name):
    """The costume parts for a theme (see COSTUMES); {} for none."""
    return COSTUMES.get(name, {})


def swatch_colors(name):
    """(fill, accent) for a theme's colour dot in pickers."""
    t = get_theme(name)
    return t["body_inner"], costume(name).get("accent", t["mouth_happy"])
