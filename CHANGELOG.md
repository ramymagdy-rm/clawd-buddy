# Changelog

All notable changes to Clawd Buddy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.11] - 2026-05-24

### Added — Milestone 1: Full session arc

- **Greeting animation** on the first prompt of a new Claude Code session.
  Soft cyan border, smaller happy arc eyes, a friendly hello with the
  right arm, ~1.8s. De-duplicated by Claude Code's `session_id` (passed
  via the hook's stdin JSON), with a 30-minute idle fallback when no id
  is available.
- **Thinking animation** while the assistant is responding — between
  `UserPromptSubmit` and the next `Stop`. Soft purple border with a
  gentler pulse, pupils that sweep upward, and three pulsing dots above
  the head. Holds indefinitely with a 10-minute safety cap.
- **`--prompt-start`** CLI flag — the single wiring point users add for
  the new `UserPromptSubmit` hook. Encapsulates the greet-if-new-session
  behavior together with starting the thinking animation. Reads
  `session_id` from piped JSON on stdin when run as a Claude Code hook
  command.
- **`--session-id ID`** CLI flag — composable override for
  `--prompt-start`'s session id (useful for scripting and tests).
- **Queued reactions** — incoming signals during an active animation are
  now queued (FIFO, capped at three) instead of being silently dropped.
  Previously a `PermissionRequest` arriving mid-celebrate was lost.
- **Unit-test suite** (`tests/test_buddy_state.py`, 32 tests) covering
  the state machine, queue semantics, preemption rules, session-greeting
  dedup, and the thinking safety cap. `pyproject.toml` gains a
  `[tool.pytest.ini_options]` block with `pythonpath = ["src"]` so
  `pytest` works without an editable install. New `pytest` dev
  dependency under `[project.optional-dependencies]`.

### Changed

- `BuddyState` is now a small state machine with explicit ambient
  (`idle`, `thinking`) vs. reactive (`celebrating`, `waving`,
  `greeting`) modes. Transitions go through a single `_request()`
  dispatcher that handles preemption (celebrate/wave/greet preempt
  thinking) and queueing (reactive-during-reactive is queued, not
  dropped). The public `trigger()` / `wave()` API is unchanged — they
  are now thin wrappers around `_request()`.
- `BuddyState.__init__` accepts an optional `clock` callable for
  deterministic time in tests.
- Socket protocol gains four new actions: `prompt_start`, `greet`,
  `thinking_start`, `thinking_end`. The existing `celebrate`, `wave`,
  `raise`, and `quit` actions are unchanged.

### Documentation

- `README.md` updated: new hook wiring section (`UserPromptSubmit`),
  new Animations entries for *Greet* and *Thinking*, updated signal
  protocol diagram, CLI reference, and queue note.
- `.ai/decisions/2026-05-24-milestone-1-session-arc.md` — full design
  rationale for the milestone (mode taxonomy, queue cap, session-greet
  heuristic, deferred audio decision).
- `.ai/feature-map.md` — feature ↔ milestone ↔ code ↔ tests ↔ decision
  map kept in sync with this release.
- `.ai/brainstorming/2026-05-24-1706-brainstorm.md` — source of M1's
  three feature decisions.

## [0.1.10] - 2026-05-24

### Added

- **`--version` CLI flag** — `clawd-buddy --version` prints the package
  version (e.g. `clawd-buddy 0.1.9`) and exits. Powered by argparse's
  built-in version action.
- **Tray version label + About dialog** — a disabled `Clawd Buddy vX.Y.Z`
  label sits above a clickable **About** entry, which opens a small
  tkinter popup with version, description, author, license, and a
  clickable repo link.
- **`__version__` on the package** — `from clawd_buddy import __version__`
  exposes the version string, sourced from `importlib.metadata` so
  `pyproject.toml` stays the single source of truth (with a `0.0.0+source`
  fallback for raw source-tree runs).
- **`.bumpversion.toml`** at the repo root — `bump-my-version` config that
  bumps `pyproject.toml`'s `version` field. Configured with
  `commit = false`, `tag = false`, `allow_dirty = true` so the tool
  edits files only; commits, tags, and merges stay in your hands. See
  the updated **Releasing** section of `CONTRIBUTING.md` for the new flow.

## [0.1.9] - 2026-05-24

### Added

- **Notification sound packs** — pick the audio style from a new tray
  **Sound** submenu. Four packs ship out of the box, plus an **Off** entry:
  - `Fanfare` — motivational achievement: ascending C-major arpeggio that
    lands on a full triad chord (celebrate) + warm two-note doorbell call
    (wave).
  - `Chime` — peaceful bell tones (fundamental + harmonics with
    exponential decay).
  - `Retro` — 8-bit square-wave coin-pickup flourish.
  - `Minimal` — single short soft pip.
- **Click-to-preview**: picking a pack from the submenu plays the
  celebrate sound immediately so you can audition options without waiting
  for the next event.
- **Pulsing attention border** around the buddy body during attention
  states: bright **green** while celebrating, warm **yellow** while
  waving. Colors are fixed across all 8 themes so the meaning stays
  consistent.

### Changed

- **Config key.** Sound preference now lives under
  `config.json` ⇒ `{"sound_pack": "fanfare" | "chime" | "retro" |
  "minimal" | "off"}`. The previous `{"sound": true|false}` key is
  auto-migrated on first run (`false → "off"`, `true → "fanfare"`) and
  dropped from the file.

### Notes

- Audio init is best-effort: on headless machines or sessions with no
  audio device, the buddy logs a one-line warning and runs silently —
  the visual attention border still works.
- All pack PCM is synthesized at startup with `pygame.mixer` (raised-cosine
  envelopes, stereo int16); no audio files are bundled. Adding a new pack
  is a matter of registering two PCM-builder functions in `SOUND_PACKS`.

## [0.1.6] - 2026-04-19

### Added

- Six new color themes for a total of **8**: `dracula`, `monokai`, `nord`,
  `gruvbox`, `solarized`, and `sunset` alongside the existing `dark` and
  `light`
- Tray **Theme** submenu lists all 8 themes as radio items; the active theme
  is checked
- Per-theme Linux background (`bg_fill`) — every theme now tints the X11
  window to match, instead of only dark vs light
- **Theme is remembered between launches.** The last-selected theme is
  persisted to `%APPDATA%\clawd-buddy\config.json` on Windows and
  `$XDG_CONFIG_HOME/clawd-buddy/config.json` (fallback
  `~/.config/clawd-buddy/config.json`) on Linux. Both the tray submenu and
  an explicit `--theme` CLI flag update the saved value.

- `--quit` CLI flag and matching `quit` socket action so a running buddy can
  be stopped cleanly even when the tray icon isn't visible
- Tray thread now logs any startup crash to
  `%TEMP%\clawd-buddy-tray.log` (Windows) or `/tmp/clawd-buddy-tray.log`
  (Linux) — previously a tray exception died silently in the daemon thread
  and left the buddy visible without a menu

### Changed

- `--theme` CLI flag accepts all 8 theme names (`choices` expanded)
- Module docstring and argparse epilog document the new themes
- Runtime theme switching is now **tray-only**: pick a theme from the
  system-tray **Theme** submenu. The launch-time `--theme` flag still works.

### Removed

- Keyboard leader shortcut `Ctrl+T, <1-8>` for switching themes (never fired
  reliably because it required the buddy window to have OS keyboard focus)
- `--theme-timeout` CLI flag (no longer applicable without the leader key)

## [0.1.5] - 2026-04-18

### Added

- `--top` CLI flag to re-assert always-on-top on a running buddy
- "Bring to Front" tray menu entry (right-click tray icon)
- `raise` socket action for programmatic z-order recovery
- Automatic snap-back to taskbar position when the buddy is off-screen

### Fixed

- Windows z-order reassert reliability: NOTOPMOST → TOPMOST toggle plus
  BringWindowToTop via AttachThreadInput, so `--top` actually surfaces the
  buddy when it's sitting behind other topmost windows
- Explicit ctypes argtypes on Win32 calls (`SetWindowPos`, `ShowWindow`,
  `BringWindowToTop`, `AttachThreadInput`, etc.) — prevents silent HWND
  truncation on 64-bit Python

## [0.1.0] - 2026-04-13

### Added

- Initial release
- Animated terminal character with idle, celebrate, and wave states
- Borderless transparent window positioned on the Windows taskbar
- Click-and-drag repositioning
- TCP socket listener (port 44556) for receiving signals
- `--send` flag to trigger celebration on a running instance
- `--wave` flag to trigger wave/attention animation
- `--test` flag to start with a celebration
- `--port` flag for custom TCP port
- `--no-topmost` flag to disable always-on-top
- `--startup` flag to enable run at Windows login
- `--no-startup` flag to disable run at Windows startup
- Single-instance enforcement via lock socket
- System tray icon with context menu
- Claude Code hook support (`Stop` and `PermissionRequest` events)
- Confetti particle system during celebrations
- Floating pulsing "!" indicator during wave state
- Hidden console window when started via startup launcher
