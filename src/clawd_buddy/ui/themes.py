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



def _theme(outer, inner, title, screen, eye_white, pupil, mouth, happy,
           limb, shoe, wave_eye, bg_fill=None):
    """A theme dict from its colour roles, in REQUIRED_KEYS order."""
    return {
        "body_outer": outer, "body_inner": inner, "title_bar": title,
        "screen_bg": screen, "eye_white": eye_white, "pupil": pupil,
        "mouth": mouth, "mouth_happy": happy, "limb": limb, "shoe": shoe,
        "wave_eye": wave_eye, "bg_fill": bg_fill or screen,
    }


_INK = (24, 24, 30)
_SKIN = (252, 228, 212)

THEMES.update({
    # ── More characters ──────────────────────────────────────────────
    # Yellow, goggles on a black strap, blue overalls.
    "minion": _theme((226, 186, 20), (252, 216, 46), (255, 232, 110),
                     (252, 218, 56), (255, 255, 255), (70, 44, 26),
                     (120, 70, 40), (150, 60, 40), (244, 204, 40),
                     (30, 30, 34), (70, 44, 26)),
    # Rusty yellow box with grey binocular eyes.
    "walle": _theme((176, 124, 34), (212, 158, 50), (232, 190, 92),
                    (58, 56, 54), (236, 236, 228), (30, 30, 32),
                    (150, 150, 140), (250, 210, 90), (112, 112, 112),
                    (52, 52, 52), (250, 210, 90)),
    # Blue suit, red cape and boots, the S shield.
    "superman": _theme((22, 60, 150), (34, 82, 190), (90, 140, 230),
                       (12, 24, 62), (238, 244, 255), (12, 24, 62),
                       (130, 160, 230), (255, 214, 50), (34, 82, 190),
                       (200, 30, 40), (255, 214, 50)),
    # Blue, with huge ears and a big dark-eyed face.
    "stitch": _theme((50, 94, 180), (72, 122, 210), (120, 160, 235),
                     (156, 194, 242), (255, 255, 255), (18, 24, 56),
                     (40, 50, 110), (200, 70, 120), (66, 114, 204),
                     (40, 70, 140), (18, 24, 56)),
    # Pink puffball, rosy cheeks, red shoes.
    "kirby": _theme((236, 128, 164), (250, 162, 192), (255, 192, 212),
                    (255, 178, 204), (255, 255, 255), (28, 24, 70),
                    (170, 50, 80), (200, 30, 60), (248, 150, 184),
                    (214, 40, 60), (28, 24, 70)),
    # White space suit, purple hood, green panels.
    "buzz": _theme((200, 200, 212), (236, 236, 242), (180, 140, 220),
                   (34, 24, 52), (236, 240, 255), (34, 24, 52),
                   (170, 150, 210), (130, 220, 90), (112, 190, 64),
                   (120, 80, 170), (130, 220, 90)),
    # Red and black mask with big white eyes.
    "deadpool": _theme((128, 14, 22), (168, 22, 32), (210, 50, 50),
                       (176, 22, 32), (255, 255, 255), (40, 10, 14),
                       (255, 190, 190), (255, 255, 255), (36, 30, 34),
                       (36, 30, 34), (255, 255, 255)),

    # ── Princesses (gown colours, a face and their hair) ─────────────
    "elsa": _theme((110, 170, 215), (152, 202, 236), (200, 230, 250),
                   _SKIN, (255, 255, 255), (38, 70, 124),
                   (190, 110, 120), (210, 70, 110), _SKIN,
                   (170, 216, 242), (38, 70, 124), (152, 202, 236)),
    "ariel": _theme((24, 140, 124), (40, 172, 150), (100, 210, 190),
                    _SKIN, (255, 255, 255), (30, 60, 112),
                    (190, 100, 110), (210, 50, 80), _SKIN,
                    (24, 140, 124), (30, 60, 112), (40, 172, 150)),
    "belle": _theme((214, 158, 28), (242, 192, 52), (255, 222, 112),
                    (250, 222, 200), (255, 255, 255), (72, 44, 28),
                    (180, 100, 90), (200, 60, 70), (242, 192, 52),
                    (214, 158, 28), (72, 44, 28), (242, 192, 52)),
    "cinderella": _theme((118, 168, 224), (162, 202, 242), (210, 232, 252),
                         _SKIN, (255, 255, 255), (38, 70, 124),
                         (190, 110, 120), (210, 70, 110), (236, 242, 255),
                         (200, 232, 255), (38, 70, 124), (162, 202, 242)),
    "snowwhite": _theme((28, 52, 130), (42, 72, 164), (90, 120, 204),
                        (252, 234, 226), (255, 255, 255), (36, 26, 26),
                        (200, 60, 70), (200, 30, 40), (252, 234, 226),
                        (250, 220, 90), (36, 26, 26), (42, 72, 164)),
    "jasmine": _theme((22, 138, 150), (38, 170, 182), (110, 210, 216),
                      (222, 172, 132), (255, 255, 255), (36, 22, 18),
                      (150, 70, 60), (170, 40, 60), (222, 172, 132),
                      (22, 138, 150), (36, 22, 18), (38, 170, 182)),
    "rapunzel": _theme((138, 84, 174), (172, 112, 204), (212, 162, 232),
                       _SKIN, (255, 255, 255), (52, 86, 40),
                       (200, 110, 130), (220, 70, 120), _SKIN,
                       (138, 84, 174), (52, 86, 40), (172, 112, 204)),

    # ── Animals ──────────────────────────────────────────────────────
    "panda": _theme((206, 206, 210), (240, 240, 242), (226, 226, 230),
                    (250, 250, 250), (255, 255, 255), _INK,
                    (60, 60, 66), (220, 60, 90), _INK, _INK, _INK),
    "fox": _theme((198, 94, 26), (232, 122, 40), (246, 162, 92),
                  (252, 238, 222), (255, 255, 255), (44, 26, 16),
                  (110, 60, 40), (200, 60, 50), (64, 38, 24),
                  (44, 26, 16), (44, 26, 16)),
    "cat": _theme((118, 118, 130), (150, 150, 162), (182, 182, 192),
                  (226, 226, 232), (255, 255, 255), (30, 64, 40),
                  (90, 70, 80), (220, 90, 120), (140, 140, 152),
                  (230, 230, 236), (30, 64, 40)),
    "tiger": _theme((208, 108, 22), (240, 140, 40), (250, 180, 100),
                    (252, 240, 224), (255, 255, 255), (36, 26, 18),
                    (110, 60, 40), (200, 60, 50), (236, 134, 38),
                    (252, 240, 224), (36, 26, 18)),
    "penguin": _theme((20, 22, 28), (32, 34, 44), (62, 64, 78),
                      (246, 246, 250), (255, 255, 255), (20, 22, 28),
                      (60, 60, 70), (250, 150, 40), (32, 34, 44),
                      (250, 156, 40), (20, 22, 28)),
    "frog": _theme((62, 148, 48), (90, 180, 70), (140, 210, 110),
                   (204, 238, 172), (255, 255, 255), (20, 50, 20),
                   (40, 90, 40), (220, 70, 90), (84, 172, 64),
                   (62, 148, 48), (20, 50, 20)),
    "bunny": _theme((218, 210, 222), (246, 241, 246), (234, 228, 238),
                    (253, 250, 253), (255, 255, 255), (64, 40, 64),
                    (150, 90, 120), (230, 90, 140), (240, 234, 242),
                    (218, 210, 222), (64, 40, 64)),
    "lion": _theme((204, 148, 52), (230, 180, 80), (246, 210, 130),
                   (252, 236, 200), (255, 255, 255), (64, 40, 20),
                   (120, 70, 40), (200, 70, 40), (226, 174, 76),
                   (204, 148, 52), (64, 40, 20)),
})

THEME_NAMES = list(THEMES.keys())  # display order for tray menu
DEFAULT_THEME = "dark"

# The first eight are the classic palettes; the rest are characters,
# grouped for the settings window and the tray's Theme menu.
CLASSIC_THEMES = ("dark", "light", "dracula", "monokai", "nord", "gruvbox",
                  "solarized", "sunset")
CHARACTER_THEMES = tuple(n for n in THEMES if n not in CLASSIC_THEMES)
PRINCESS_THEMES = ("elsa", "ariel", "belle", "cinderella", "snowwhite",
                   "jasmine", "rapunzel")
ANIMAL_THEMES = ("panda", "fox", "cat", "tiger", "penguin", "frog", "bunny",
                 "lion")
HERO_THEMES = tuple(n for n in CHARACTER_THEMES
                    if n not in PRINCESS_THEMES + ANIMAL_THEMES)

# (key, title, themes) for pickers.
THEME_GROUPS = (
    ("classic", "Classic", CLASSIC_THEMES),
    ("characters", "Characters", HERO_THEMES),
    ("princesses", "Princesses", PRINCESS_THEMES),
    ("animals", "Animals", ANIMAL_THEMES),
)

# How a theme is named in menus, when `name.title()` isn't right.
THEME_LABELS = {
    "ironman": "Iron Man",
    "spiderman": "Spider-Man",
    "captain": "Captain",
    "walle": "Wall-E",
    "snowwhite": "Snow White",
}

_BLACK, _WHITE = (16, 16, 20), (255, 255, 255)

# What a character wears on top of its colours. The drawing code knows
# these parts (all optional):
#   traffic  False hides the three window dots on the head.
#   bands    [(x0, x1, y0, y1, fill, edge)]: stripes across the shell,
#            as fractions of the body box, clipped to its rounded shape;
#            `edge` (or None) outlines them.
#   ears     "bat" | "pointy" | "fin" | "round" | "long" | "wide", in
#            "ear" colour, with an optional "ear_tip" (pointy) or
#            "ear_inner" (pointy, round, long, wide) colour.
#   mane     colour of a shaggy mane behind the head.
#   cape     colour of a cape behind the body.
#   hair     colour of the hair over the head, in "hair_style":
#            "spiky" (default), "long", "very_long", "bob" or "braid"
#            (swept back into a braid over the shoulder).
#   headband colour of a band across the hair.
#   emblem   "bat" | "reactor" | "star" | "super" on the forehead, or
#            "bow" on top of the head.
#   web      colour of a spider web drawn on the screen behind the face.
#   goggles  {"rim", "lens", "strap"} goggles around the eyes; "strap"
#            None and "bridge" True make them binoculars.
#   mask     colour of a patch around each eye; "eye" is then the eye
#            colour (so it shows on the patch).
#   nose     colour of a little nose above the mouth.
#   whiskers colour of three whiskers on each cheek.
#   beak     colour of a beak, instead of the mouth.
#   blush    cheek colour, instead of the default pink; None for none.
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
    "minion": {
        "traffic": False,
        "accent": (40, 90, 170),
        "goggles": {"rim": (176, 180, 190), "lens": (255, 255, 255),
                    "strap": (34, 34, 38)},
        "bands": [(0, 1, 0.84, 1, (40, 90, 170), None)],
    },
    "walle": {
        "traffic": False,
        "accent": (120, 120, 120),
        "goggles": {"rim": (128, 128, 128), "lens": (40, 40, 42),
                    "strap": None, "bridge": True},
        "blush": None,
    },
    "superman": {
        "traffic": False,
        "accent": (200, 30, 40),
        "cape": (200, 30, 40),
        "emblem": "super",
    },
    "stitch": {
        "traffic": False,
        "accent": (226, 140, 180),
        "ears": "wide", "ear": (50, 94, 180), "ear_inner": (226, 140, 180),
        "nose": (30, 40, 90),
    },
    "kirby": {
        "traffic": False,
        "accent": (214, 40, 60),
        "blush": (240, 90, 130),
    },
    "buzz": {
        "traffic": False,
        "accent": (112, 190, 64),
        "bands": [(0, 1, 0, 0.2, (120, 80, 170), None),
                  (0, 0.09, 0.3, 1, (112, 190, 64), None),
                  (0.91, 1, 0.3, 1, (112, 190, 64), None)],
    },
    "deadpool": {
        "traffic": False,
        "accent": (30, 26, 30),
        "mask": (30, 26, 30), "eye": (255, 255, 255),
    },
    "elsa": {
        "traffic": False,
        "accent": (245, 240, 225),
        "hair": (245, 238, 220), "hair_style": "braid",
    },
    "ariel": {
        "traffic": False,
        "accent": (214, 46, 40),
        "hair": (214, 46, 40), "hair_style": "long",
    },
    "belle": {
        "traffic": False,
        "accent": (112, 64, 30),
        "hair": (112, 64, 30), "hair_style": "long",
    },
    "cinderella": {
        "traffic": False,
        "accent": (240, 206, 110),
        "hair": (240, 206, 110), "hair_style": "long",
        "headband": (40, 52, 96),
    },
    "snowwhite": {
        "traffic": False,
        "accent": (200, 30, 40),
        "hair": (22, 22, 26), "hair_style": "bob",
        "emblem": "bow",
        "bands": [(0, 1, 0.84, 1, (250, 220, 90), None)],
    },
    "jasmine": {
        "traffic": False,
        "accent": (240, 190, 60),
        "hair": (26, 22, 28), "hair_style": "long",
        "headband": (240, 190, 60),
    },
    "rapunzel": {
        "traffic": False,
        "accent": (250, 210, 90),
        "hair": (250, 210, 90), "hair_style": "very_long",
    },
    "panda": {
        "traffic": False,
        "accent": _INK,
        "ears": "round", "ear": _INK,
        "mask": _INK, "eye": (255, 255, 255),
        "nose": _INK,
    },
    "fox": {
        "traffic": False,
        "accent": (252, 238, 222),
        "ears": "pointy", "ear": (198, 94, 26), "ear_tip": (60, 36, 24),
        "nose": (44, 26, 16),
    },
    "cat": {
        "traffic": False,
        "accent": (240, 160, 176),
        "ears": "pointy", "ear": (118, 118, 130),
        "ear_inner": (240, 170, 182),
        "bands": [(0.42, 0.46, 0, 0.17, (96, 96, 108), None),
                  (0.48, 0.52, 0, 0.21, (96, 96, 108), None),
                  (0.54, 0.58, 0, 0.17, (96, 96, 108), None)],
        "nose": (236, 130, 150),
        "whiskers": (90, 90, 102),
    },
    "tiger": {
        "traffic": False,
        "accent": (36, 26, 18),
        "ears": "round", "ear": (208, 108, 22), "ear_inner": (252, 240, 224),
        "bands": [(0.30, 0.36, 0, 0.18, (36, 26, 18), None),
                  (0.47, 0.53, 0, 0.22, (36, 26, 18), None),
                  (0.64, 0.70, 0, 0.18, (36, 26, 18), None),
                  (0, 0.12, 0.30, 0.38, (36, 26, 18), None),
                  (0, 0.12, 0.52, 0.60, (36, 26, 18), None),
                  (0.88, 1, 0.30, 0.38, (36, 26, 18), None),
                  (0.88, 1, 0.52, 0.60, (36, 26, 18), None)],
        "nose": (180, 80, 70),
        "whiskers": (60, 44, 34),
    },
    "penguin": {
        "traffic": False,
        "accent": (250, 156, 40),
        "beak": (250, 156, 40),
    },
    "frog": {
        "traffic": False,
        "accent": (204, 238, 172),
        "ears": "round", "ear": (62, 148, 48), "ear_inner": (204, 238, 172),
    },
    "bunny": {
        "traffic": False,
        "accent": (244, 168, 194),
        "ears": "long", "ear": (232, 226, 236), "ear_inner": (244, 168, 194),
        "nose": (236, 130, 160),
    },
    "lion": {
        "traffic": False,
        "accent": (176, 88, 30),
        "mane": (176, 88, 30),
        "ears": "round", "ear": (204, 148, 52), "ear_inner": (246, 210, 130),
        "nose": (96, 54, 30),
        "whiskers": (120, 80, 50),
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


def theme_group(name):
    """The THEME_GROUPS key a theme belongs to ("classic" if unknown)."""
    for key, _title, names in THEME_GROUPS:
        if name in names:
            return key
    return "classic"


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
