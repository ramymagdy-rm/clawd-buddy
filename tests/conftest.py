# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Pytest configuration for clawd_buddy tests.

We import `clawd_buddy.app` at collection time, which transitively imports
pygame. To stay safe on headless CI / dev machines, force SDL into its
dummy driver before the import happens.
"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
