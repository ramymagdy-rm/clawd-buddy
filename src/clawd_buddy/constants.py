# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Window / rendering / IPC constants shared across modules.

Kept in one tiny module so any module can import the value it needs
without pulling in heavier dependencies (pygame, ctypes, etc.).
"""

# Window dimensions at 1.0 scale. Drawing primitives layout themselves
# against these values; the resize_window helper multiplies them by the
# active scale preset.
WIN_W, WIN_H = 200, 260

# Character bounding box inside the window. The buddy's body, arms, legs
# and indicators are all positioned relative to this.
CHAR_W, CHAR_H = 80, 62

# Rendering frame rate target for the main loop. Pygame clock ticks at
# this rate; idle CPU stays low because most frames are no-ops.
FPS = 120

# Color-key for Windows transparency. Any pixel painted in this exact
# colour becomes invisible on Win32 (LWA_COLORKEY). Drawing code MUST
# avoid emitting this exact RGB triple for any visible feature.
TKEY = (1, 1, 1)

# IPC socket — the main TCP listener the running buddy uses to receive
# signals from `clawd-buddy --send` / `--wave` / `--prompt-start` / etc.
SOCK_HOST = "127.0.0.1"
SOCK_PORT = 44556
