# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Persistent drinking history — daily cup counts for the M4 reminder.

History lives in `~/.clawd-buddy/history.json` on both Windows and
Linux. This is **runtime data** (frequent appends, easy to back up
via dotfile management), kept separate from the **settings** that
live in the platform config dir (`%APPDATA%\\clawd-buddy\\config.json`
on Windows, `~/.config/clawd-buddy/config.json` on Linux).

Schema:

    {
      "today": {"date": "2026-05-25", "count": 3},
      "recent": [
        {"date": "2026-05-24", "count": 6},
        {"date": "2026-05-23", "count": 5},
        ...up to RECENT_DAYS_MAX entries...
      ]
    }

`today` is the in-progress day. `recent` is the most-recent N closed
days (newest first), trimmed to `RECENT_DAYS_MAX` (default 7). Day
strings are local-calendar `YYYY-MM-DD`; counts are non-negative
integers.

The reader degrades gracefully — a corrupt or partial file produces
`(None_today, [])` rather than raising, mirroring `config.load_config`.
The writer is atomic (write-then-rename) so a crash mid-save can't
leave a truncated history that subsequent loads can't parse.
"""

import json
import os


# Cap on `recent` length — long enough to power a small bar-chart-ish
# display in the About → Reminders tab, short enough that a buddy
# instance that never closes doesn't accumulate years of data in a
# JSON file the user never asked for.
RECENT_DAYS_MAX = 7


def _history_dir():
    """Directory that holds runtime data (history, future counters,
    activity logs). Same path on Windows and Linux:

      Windows: `C:\\Users\\<name>\\.clawd-buddy\\`
      Linux:   `~/.clawd-buddy/`

    `os.path.expanduser("~")` resolves the home dir on both platforms
    without any `sys.platform` branching — that's the whole reason
    runtime data lives here instead of next to `config.json`.
    """
    return os.path.join(os.path.expanduser("~"), ".clawd-buddy")


def _history_path():
    return os.path.join(_history_dir(), "history.json")


def load_history():
    """Read history.json into a normalised `(today_entry, recent_list)`.

    `today_entry` is either `None` (no in-progress day on file) or a
    dict `{"date": "YYYY-MM-DD", "count": int}` with a non-negative
    integer count. `recent_list` is the trimmed-to-max list of past
    days (newest first); malformed individual entries are dropped
    rather than failing the whole load.

    Returns `(None, [])` for every error case — missing file, bad
    JSON, wrong top-level type, garbage values. The buddy must always
    launch; corrupt history degrades silently to "no history yet"
    rather than blocking startup with a parse error (same contract
    as `config.load_config`).
    """
    try:
        with open(_history_path(), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, []
    if not isinstance(raw, dict):
        return None, []
    today = _validate_entry(raw.get("today"))
    recent_raw = raw.get("recent", [])
    recent = []
    if isinstance(recent_raw, list):
        for item in recent_raw:
            v = _validate_entry(item)
            if v is not None:
                recent.append(v)
    # Trim defensively in case the file held more than the cap (e.g.
    # a future build bumped RECENT_DAYS_MAX and then this one rolled
    # it back).
    del recent[RECENT_DAYS_MAX:]
    return today, recent


def save_history(today, recent):
    """Atomically write `today` + `recent` to history.json.

    `today` is `None` (no in-progress day to record) or a
    `{"date": str, "count": int}` dict. `recent` is the list to
    persist; the writer trims to `RECENT_DAYS_MAX` so any caller
    that drops a list larger than the cap can't blow up the file.

    Atomic write via write-to-tmp + rename so a crash mid-save can't
    leave a truncated `history.json` that the next load can't parse.
    Creates `~/.clawd-buddy/` on first write — runtime data dir
    appears the moment it's actually needed, not at every launch.

    Non-fatal on filesystem errors — prints a single warning and
    returns. The in-memory count survives; only the persisted copy
    is lost. Matches `config.save_config`'s contract.
    """
    today_clean = _validate_entry(today)
    recent_clean = []
    if isinstance(recent, list):
        for item in recent:
            v = _validate_entry(item)
            if v is not None:
                recent_clean.append(v)
    del recent_clean[RECENT_DAYS_MAX:]
    payload = {"recent": recent_clean}
    if today_clean is not None:
        payload["today"] = today_clean
    path = _history_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[buddy] Could not save history: {e}")


def _validate_entry(entry):
    """Return a clean `{"date": str, "count": int}` or `None`.

    Reject anything that doesn't match the schema — missing keys,
    wrong types, malformed date string, negative count. Used by
    both the reader (drop bad entries) and the writer (refuse to
    persist a malformed entry, even if the caller hands one in).
    """
    if not isinstance(entry, dict):
        return None
    date = entry.get("date")
    count = entry.get("count")
    if not isinstance(date, str) or not _is_iso_date(date):
        return None
    if not isinstance(count, int) or isinstance(count, bool):
        # `isinstance(True, int)` is True in Python; bool-as-count
        # would technically pass but is clearly garbage.
        return None
    if count < 0:
        return None
    return {"date": date, "count": count}


def _is_iso_date(s):
    """True if `s` looks like `YYYY-MM-DD` with valid ranges. We don't
    pull in `datetime.fromisoformat` because the validator runs against
    every load and we don't need to confirm "is this a real calendar
    day?" — just that the string is well-formed enough to be a useful
    key. Garbage years (e.g. 0000) sort and compare consistently."""
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        return False
    try:
        y = int(s[0:4])
        m = int(s[5:7])
        d = int(s[8:10])
    except ValueError:
        return False
    if not (0 <= y <= 9999):
        return False
    if not (1 <= m <= 12):
        return False
    if not (1 <= d <= 31):
        return False
    return True
