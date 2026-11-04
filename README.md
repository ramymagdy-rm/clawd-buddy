<div align="center">

<img src="https://raw.githubusercontent.com/ramymagdy-rm/clawd-buddy/main/assets/buddy-gif.gif" alt="Clawd Buddy" width="360">

# Clawd Buddy

**A tiny animated pet that sits on your taskbar and reacts to
[Claude Code](https://claude.ai/code) while you work.**

[![PyPI](https://img.shields.io/pypi/v/clawd-buddy)](https://pypi.org/project/clawd-buddy/)
[![Python](https://img.shields.io/pypi/pyversions/clawd-buddy)](https://pypi.org/project/clawd-buddy/)
[![Platforms](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-blue)](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/platforms.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/LICENSE)

</div>

It thinks while Claude works, celebrates when it's done, and waves when
Claude needs your input, so you can tell what's happening without
switching windows.

| When | The buddy |
| --- | --- |
| 👋 **New session** | hops and waves hello |
| 💭 **Claude is working** | taps away with a "Thinking…" pill |
| 🎉 **Claude is done** | hops, throws confetti and plays a little fanfare |
| ✋ **Claude needs you** | bounces, waves and rings a doorbell |

## Features

- **Follows every session.** Tracks several Claude Code sessions at
  once, and a [workspace badge](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/features.md#workspace-badge)
  shows which project needs you.
- **[38 themes](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/themes.md)**:
  classic palettes plus characters, princesses and animals.
- **[Sound packs](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/features.md#sound-packs)**,
  volume, quiet hours and a reduce-motion mode.
- **Wellbeing:** a [water reminder](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/features.md#water-reminder)
  with a daily cup count, and a [pomodoro timer](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/features.md#pomodoro).
- **Works with anything:** speech bubbles, a local socket and an
  optional HTTP webhook let scripts and CI drive it too
  ([integrations](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/integrations.md)).
- **One settings window** for all of it: right-click the buddy.

## Install

```bash
uv tool install clawd-buddy      # recommended
pipx install clawd-buddy         # or with pipx
pip install clawd-buddy          # or into the current environment
```

Requires Python 3.10+ on **Windows 10/11** or **Linux** (X11 or
XWayland). To upgrade: `uv tool upgrade clawd-buddy` or
`pipx upgrade clawd-buddy`.

## Quick start

**1. Start the buddy.** It appears at the bottom of your screen.

```bash
clawd-buddy
```

**2. Connect it to Claude Code.** Add these hooks to
`~/.claude/settings.json` (merge them into `hooks` if you have some
already):

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "clawd-buddy --prompt-start", "timeout": 5 }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "clawd-buddy --send done", "timeout": 5 }] }
    ],
    "PermissionRequest": [
      { "hooks": [{ "type": "command", "command": "clawd-buddy --wave", "timeout": 5 }] }
    ]
  }
}
```

What each hook does, and how to use another port:
[Claude Code hooks](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/integrations.md#claude-code-hooks).

**3. Optional: start it at login.**

```bash
clawd-buddy --startup
```

That's it. Start a Claude Code session anywhere and the buddy reacts.

## Using it

| Input | What it does |
| --- | --- |
| **Drag** | move the buddy anywhere |
| **Right-click** | open the settings window |
| **Ctrl+1 … Ctrl+7** | change its size, from S to XXXL |
| **Space** | test celebration |
| **Escape** | quit |
| **Tray icon** | the same settings, from the system tray |

A few handy commands:

```bash
clawd-buddy --message "tests green"   # show a speech bubble
clawd-buddy --pomodoro 25/5           # 25 min focus, 5 min break
clawd-buddy --status                  # what the buddy is doing, as JSON
clawd-buddy --quit                    # close it
```

## Documentation

| Page | What's in it |
| --- | --- |
| 📖 [Features](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/features.md) | Settings window, sounds, reminders, pomodoro, controls, tray menu |
| 🎨 [Themes](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/themes.md) | All 38 themes |
| 🎬 [Animations](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/animations.md) | What each state looks like |
| 🔌 [Integrations](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/integrations.md) | Hooks, every command, the signal protocol, HTTP webhook |
| 🖥️ [Platforms](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/platforms.md) | Windows and Linux details, run at login, where settings live |
| 🛠️ [Troubleshooting](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/docs/troubleshooting.md) | When something doesn't work |

What's new is in the [CHANGELOG](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/CHANGELOG.md),
and [CONTRIBUTING.md](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/CONTRIBUTING.md) explains how to work on the buddy.

## License

[MIT](https://github.com/ramymagdy-rm/clawd-buddy/blob/main/LICENSE).

Clawd Buddy is an independent open-source project. It isn't affiliated
with, endorsed by, or sponsored by Anthropic. "Claude" and "Claude Code"
are trademarks of Anthropic, PBC.
