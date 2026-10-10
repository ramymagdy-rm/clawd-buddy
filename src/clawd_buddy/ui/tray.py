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
from ..config import (
    QUIET_HOURS_PRESETS,
    VOLUME_STEPS,
    save_quiet_hours_pref,
    save_reduce_motion_pref,
    save_reminder_enabled_pref,
    save_sound_pack_pref,
    save_theme_pref,
    save_volume_pref,
    save_workspace_badge_pref,
)
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

    def on_center(_icon, _item):
        state.center_on_screen()

    def on_about(_icon, _item):
        # M4: pass state so the About dialog's Reminders tab can read
        # and mutate it. Older callers (tests) can still call
        # show_about_dialog() without args — that path falls back to
        # an info-only Reminders tab.
        show_about_dialog(state)

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

    # M3: Volume submenu — discrete steps surfaced inside Sound, per the
    # roadmap ("Volume slider in the tray Sound submenu"). pystray has
    # no native slider widget, so stepped radios are the closest fit.
    # Selecting a step previews via state.set_volume → _pending_sound,
    # so the user hears the new level immediately.
    def _make_volume_action(step):
        def _action(_icon, _item):
            state.set_volume(step)
            save_volume_pref(step)
        return _action

    def _make_volume_checker(step):
        def _checker(_item):
            return abs(state.volume - step) < 1e-3
        return _checker

    def _volume_item(step):
        return pystray.MenuItem(
            f"{int(round(step * 100))}%",
            _make_volume_action(step),
            checked=_make_volume_checker(step),
            radio=True,
        )

    volume_submenu = pystray.Menu(*[_volume_item(s) for s in VOLUME_STEPS])

    # M3: Quiet Hours submenu — Off + a handful of common night windows.
    # Stored start/end as minutes-from-midnight; the "Off" item passes
    # (None, None) to disable the window without removing the menu.
    def _make_quiet_action(s, e):
        def _action(_icon, _item):
            state.set_quiet_hours(s, e)
            save_quiet_hours_pref(s, e)
        return _action

    def _make_quiet_checker(s, e):
        def _checker(_item):
            return state.quiet_start == s and state.quiet_end == e
        return _checker

    def _quiet_item(label, s, e):
        return pystray.MenuItem(
            label,
            _make_quiet_action(s, e),
            checked=_make_quiet_checker(s, e),
            radio=True,
        )

    quiet_submenu = pystray.Menu(
        _quiet_item("Off", None, None),
        *[_quiet_item(label, s, e)
          for label, s, e in QUIET_HOURS_PRESETS],
    )

    sound_submenu = pystray.Menu(
        _pack_item(SOUND_PACK_OFF, "Off"),
        *[_pack_item(name, name.title()) for name in SOUND_PACK_NAMES],
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Volume", volume_submenu),
        pystray.MenuItem("Quiet Hours", quiet_submenu),
    )

    # M3: Reduce Motion — top-level toggle (it's an accessibility
    # preference, not a sound preference). Closure factory keeps
    # pystray's arity check happy.
    def on_reduce_motion(_icon, item):
        new_val = not bool(item.checked)
        state.set_reduce_motion(new_val)
        save_reduce_motion_pref(new_val)

    def _reduce_motion_checker(_item):
        return state.reduce_motion

    # M4: Water Reminder — top-level toggle for quick on/off. The
    # detailed config (interval, sound, quiet hours) lives in the
    # About-window Reminders tab; this is just the fast path so a
    # user heading into a meeting can mute reminders in one click.
    def on_reminder_toggle(_icon, item):
        new_val = not bool(item.checked)
        state.set_reminder_enabled(new_val)
        save_reminder_enabled_pref(new_val)

    def _reminder_enabled_checker(_item):
        return state.reminder_enabled

    # M7: Workspace Badge — top-level toggle. Recording continues while
    # hidden, so flipping it back on mid-session shows correct data.
    def on_workspace_badge_toggle(_icon, item):
        new_val = not bool(item.checked)
        state.set_workspace_badge_enabled(new_val)
        save_workspace_badge_pref(new_val)

    def _workspace_badge_checker(_item):
        return state.workspace_badge_enabled

    # M4: "I drank water" — top-level acknowledgment shortcut. Hidden
    # via `visible=` when there's no active alarm, since clicking it
    # outside of an alarm is harmless (just resets the timer) but
    # adding noise to the always-visible menu hurts more than it
    # helps. pystray's `visible` accepts a callable that returns a
    # bool per render.
    def on_drank(_icon, _item):
        state.drink_acknowledged()

    def _drank_visible(_item):
        return state.reminder_active

    # M6: "Stop Pomodoro" — same hidden-until-relevant pattern as
    # "I drank water". The cycle is started from the CLI
    # (`--pomodoro 25/5`); the tray only needs the escape hatch, so
    # the always-visible menu stays uncluttered for non-pomodoro users.
    def on_pomodoro_stop(_icon, _item):
        state.stop_pomodoro()

    def _pomodoro_visible(_item):
        return state.pomodoro_active

    menu = pystray.Menu(
        pystray.MenuItem(
            "I drank water",
            on_drank,
            visible=_drank_visible,
        ),
        pystray.MenuItem(
            "Stop Pomodoro",
            on_pomodoro_stop,
            visible=_pomodoro_visible,
        ),
        pystray.MenuItem("Test Celebration", on_celebrate),
        pystray.MenuItem("Bring to Front", on_bring_to_front),
        pystray.MenuItem("Center on Screen", on_center),
        pystray.MenuItem("Theme", theme_submenu),
        pystray.MenuItem("Sound", sound_submenu),
        pystray.MenuItem(
            "Reduce Motion",
            on_reduce_motion,
            checked=_reduce_motion_checker,
        ),
        pystray.MenuItem(
            "Water Reminder",
            on_reminder_toggle,
            checked=_reminder_enabled_checker,
        ),
        pystray.MenuItem(
            "Workspace Badge",
            on_workspace_badge_toggle,
            checked=_workspace_badge_checker,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"Clawd Buddy v{APP_VERSION}", None, enabled=False),
        pystray.MenuItem("About…", on_about),
        pystray.MenuItem("Quit", on_quit),
    )
    pystray.Icon("clawd-buddy", img, "Clawd Buddy", menu).run()
