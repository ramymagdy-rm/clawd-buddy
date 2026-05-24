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


# ── M3 prefs: reduce_motion, volume, quiet_hours ─────────────────────
# Each load_ function tolerates missing / malformed values by returning
# a safe default — a corrupt config must never block startup or silently
# mute the buddy. Save_ functions skip writes when the value didn't
# change, so a tray click that re-selects the current option doesn't
# rewrite the file.

def load_saved_reduce_motion():
    """Return the persisted reduce-motion preference, defaulting to
    False (motion on) so first-run users get the standard experience."""
    return bool(load_config().get("reduce_motion", False))


def save_reduce_motion_pref(enabled):
    """Persist the reduce-motion toggle. Normalised to plain bool so
    the JSON file stays clean (no Python `True`/numeric edge cases)."""
    enabled = bool(enabled)
    cfg = load_config()
    if cfg.get("reduce_motion") is enabled:
        return
    cfg["reduce_motion"] = enabled
    save_config(cfg)


# Discrete volume steps surfaced in the tray Volume submenu. Stored as
# a float in config to leave room for a real continuous slider later
# without a schema migration.
VOLUME_STEPS = (0.0, 0.25, 0.50, 0.75, 1.00)
DEFAULT_VOLUME = 1.0


def load_saved_volume():
    """Return the persisted user volume (0.0–1.0). Clamps to range so
    a hand-edited config can't push pygame's mixer out-of-bounds."""
    v = load_config().get("volume", DEFAULT_VOLUME)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return DEFAULT_VOLUME
    if v != v:  # NaN
        return DEFAULT_VOLUME
    return max(0.0, min(1.0, v))


def save_volume_pref(v):
    """Persist the user volume (clamped 0.0–1.0)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return
    if v != v:  # NaN
        return
    v = max(0.0, min(1.0, v))
    cfg = load_config()
    if isinstance(cfg.get("volume"), (int, float)) and float(cfg["volume"]) == v:
        return
    cfg["volume"] = v
    save_config(cfg)


# Quiet-hours presets surfaced in the tray. Each entry is
# (label, start_minutes_from_midnight, end_minutes_from_midnight).
# "Off" lives outside this list because its endpoints are None.
QUIET_HOURS_PRESETS = (
    ("21:00 – 08:00", 21 * 60,  8 * 60),
    ("22:00 – 08:00", 22 * 60,  8 * 60),
    ("23:00 – 07:00", 23 * 60,  7 * 60),
    ("23:00 – 08:00", 23 * 60,  8 * 60),
    ("00:00 – 09:00",  0,       9 * 60),
)


def load_saved_quiet_hours():
    """Return (start, end) minutes-from-midnight pair, or (None, None)
    when quiet hours are disabled / missing / malformed. Quiet hours
    default to OFF — a brand-new buddy should chirp at the user, not
    surprise them with silence."""
    cfg = load_config()
    raw = cfg.get("quiet_hours")
    if not isinstance(raw, dict):
        return None, None
    s = raw.get("start")
    e = raw.get("end")
    if not (isinstance(s, int) and isinstance(e, int)):
        return None, None
    if not (0 <= s < 1440 and 0 <= e < 1440):
        return None, None
    if s == e:
        return None, None
    return s, e


def save_quiet_hours_pref(start, end):
    """Persist a quiet-hours window. Pass (None, None) to disable —
    the key is dropped from the config in that case rather than left
    as a null pair, so the JSON stays minimal."""
    cfg = load_config()
    if start is None or end is None:
        if "quiet_hours" not in cfg:
            return
        cfg.pop("quiet_hours", None)
        save_config(cfg)
        return
    if not (isinstance(start, int) and isinstance(end, int)):
        return
    if not (0 <= start < 1440 and 0 <= end < 1440):
        return
    if start == end:
        return
    new = {"start": start, "end": end}
    if cfg.get("quiet_hours") == new:
        return
    cfg["quiet_hours"] = new
    save_config(cfg)
