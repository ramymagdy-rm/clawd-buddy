# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""System-tray icon and right-click menu.

`create_tray(state)` runs the pystray icon loop on a daemon thread,
wires the menu items to BuddyState mutations, and persists theme /
sound-pack changes through the `config` module.

pystray itself is imported lazily inside `_create_tray_impl` so the
package import surface stays light for tests and for hooks that don't
need a tray (e.g. `clawd-buddy --send done`).
"""

import os
import sys
import time
import traceback

from .. import __version__ as APP_VERSION
from ..config import save_sound_pack_pref, save_theme_pref
from .about import _make_buddy_icon_image, show_about_dialog
from .sound import SOUND_PACK_NAMES, SOUND_PACK_OFF
from .themes import THEME_NAMES


def _tray_log_path():
    """Per-OS scratch path for tray startup errors.

    The tray runs on a daemon thread; an uncaught exception there used
    to kill the icon without any visible feedback (pythonw on Windows
    has no stderr). Logging to a file makes startup failures
    diagnosable after the fact.
    """
    if sys.platform == "win32":
        base = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    else:
        base = "/tmp"
    return os.path.join(base, "clawd-buddy-tray.log")


def create_tray(state):
    """Entry point for the tray daemon thread — swallow no exceptions
    silently. Logs crashes to `_tray_log_path()`."""
    try:
        _create_tray_impl(state)
    except Exception:
        path = _tray_log_path()
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n=== clawd-buddy tray crash @ {time.ctime()} ===\n")
                traceback.print_exc(file=f)
        except OSError:
            pass
        # Also try stderr (visible when run with --fg)
        try:
            sys.stderr.write(
                f"[buddy] Tray thread crashed — see {path}\n"
            )
            traceback.print_exc()
        except Exception:
            pass


def _create_tray_impl(state):
    """Build the pystray icon + menu and run its event loop.

    pystray's `_assert_action` rejects callables whose `__code__.co_argcount`
    exceeds 2 — even when the extra parameter is a default. Build the
    closures via factories so each closure has exactly the arg count
    pystray expects (action: 2, checked: 1).
    """
    import pystray

    img = _make_buddy_icon_image()

    def on_celebrate(_icon, _item):
        state.trigger()

    def on_bring_to_front(_icon, _item):
        state.bring_to_front()

    def on_about(_icon, _item):
        show_about_dialog()

    def on_quit(icon, _item):
        state.should_quit = True
        icon.stop()

    # Theme submenu — factory pattern keeps closure arity correct.
    def _make_action(name):
        def _action(_icon, _item):
            state.set_theme(name)
            save_theme_pref(name)
        return _action

    def _make_checker(name):
        def _checker(_item):
            return state.theme_name == name
        return _checker

    def _theme_item(name):
        return pystray.MenuItem(
            name.title(),
            _make_action(name),
            checked=_make_checker(name),
            radio=True,
        )

    theme_submenu = pystray.Menu(*[
        _theme_item(name) for name in THEME_NAMES
    ])

    # Sound submenu — same factory pattern. Clicking a pack switches AND
    # previews via state.set_sound_pack, then persists the choice.
    # "Off" mutes (no preview to play).
    def _make_pack_action(pack):
        def _action(_icon, _item):
            state.set_sound_pack(pack)
            save_sound_pack_pref(pack)
        return _action

    def _make_pack_checker(pack):
        def _checker(_item):
            return state.sound_pack == pack
        return _checker

    def _pack_item(pack, label):
        return pystray.MenuItem(
            label,
            _make_pack_action(pack),
            checked=_make_pack_checker(pack),
            radio=True,
        )

    sound_submenu = pystray.Menu(
        _pack_item(SOUND_PACK_OFF, "Off"),
        *[_pack_item(name, name.title()) for name in SOUND_PACK_NAMES],
    )

    menu = pystray.Menu(
        pystray.MenuItem("Test Celebration", on_celebrate),
        pystray.MenuItem("Bring to Front", on_bring_to_front),
        pystray.MenuItem("Theme", theme_submenu),
        pystray.MenuItem("Sound", sound_submenu),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Clawd Buddy v{APP_VERSION}", None, enabled=False),
        pystray.MenuItem("About", on_about),
        pystray.MenuItem("Quit", on_quit),
    )
    pystray.Icon("clawd-buddy", img, "Clawd Buddy", menu).run()
