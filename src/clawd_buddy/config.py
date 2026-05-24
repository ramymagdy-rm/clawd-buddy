# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Persistent user configuration — theme + sound-pack preferences.

The config file lives in a per-OS user directory and is JSON-encoded.
All readers tolerate missing/malformed data by falling back to defaults,
and writers are atomic (write-then-rename) so a crash mid-save can't
truncate the file.

The config schema is intentionally tiny — we don't pull in pydantic /
schema libs for two keys. Migration logic (e.g. the old `sound: bool`
key → new `sound_pack: str`) lives next to the readers that consume
each key.
"""

import json
import os
import sys

from .ui.sound import DEFAULT_SOUND_PACK, SOUND_PACK_CHOICES, SOUND_PACK_OFF
from .ui.themes import is_known_theme


# Config-dir resolution is a thin function rather than a module-level
# constant so tests can override $APPDATA / $XDG_CONFIG_HOME at runtime
# and get the new value without re-importing.
def _config_dir():
    """Per-OS directory for clawd-buddy's user config."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser(
            "~\\AppData\\Roaming"
        )
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config"
        )
    return os.path.join(base, "clawd-buddy")


def _config_path():
    return os.path.join(_config_dir(), "config.json")


def load_config():
    """Read config.json. Returns an empty dict on any error.

    The buddy must always launch; corrupt configs degrade silently to
    defaults rather than blocking startup with a parse error.
    """
    try:
        with open(_config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return {}


def save_config(data):
    """Atomically write config.json. Non-fatal on failure.

    Writes to `config.json.tmp` first then renames into place — this
    prevents a crash mid-write from leaving a truncated config file
    that subsequent loads can't parse.
    """
    path = _config_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[buddy] Could not save config: {e}")


def load_saved_theme():
    """Return the last remembered theme name, or None if unknown / invalid."""
    name = load_config().get("theme")
    return name if is_known_theme(name) else None


def save_theme_pref(name):
    """Persist the user's theme selection. Called on launch override and
    whenever the tray Theme submenu changes the active theme."""
    if not is_known_theme(name):
        return
    cfg = load_config()
    if cfg.get("theme") == name:
        return  # no-op write avoided
    cfg["theme"] = name
    save_config(cfg)


def load_saved_sound_pack():
    """Return the last remembered sound-pack name.

    Defaults to DEFAULT_SOUND_PACK on first run / corrupt config so the
    buddy still chirps out of the box. Also migrates the legacy
    `sound: bool` key written by an earlier iteration of this feature:
      sound=False ⇒ "off", sound=True ⇒ DEFAULT_SOUND_PACK.
    The new key takes precedence if both exist.
    """
    cfg = load_config()
    pack = cfg.get("sound_pack")
    if isinstance(pack, str) and pack in SOUND_PACK_CHOICES:
        return pack
    legacy = cfg.get("sound")
    if legacy is False:
        return SOUND_PACK_OFF
    return DEFAULT_SOUND_PACK


def save_sound_pack_pref(pack):
    """Persist the chosen sound pack. Called from the tray Sound submenu.

    Also strips the legacy `sound: bool` key on first new write so the
    config doesn't accumulate dead keys after migration.
    """
    if pack not in SOUND_PACK_CHOICES:
        return
    cfg = load_config()
    if cfg.get("sound_pack") == pack and "sound" not in cfg:
        return
    cfg["sound_pack"] = pack
    cfg.pop("sound", None)
    save_config(cfg)
