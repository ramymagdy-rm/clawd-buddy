# Changelog

All notable changes to Clawd Buddy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.17] - 2026-05-25

### Changed — Milestone 4 polish

- **Interval picker is now a scrolling dropdown**, matching the
  quiet-hours selectors. The previous radio group occupied five rows
  for a single setting; replacing it with a `ttk.Combobox` (positioned
  directly under the **Remind me to drink water** checkbox) makes the
  Reminders tab visually uniform — every configurable value now uses
  the same widget shape. Behaviour is unchanged: same five presets
  (`30 min` … `4 h`), same save-on-change semantics, same fallback to
  1 h when a config drifts off-preset.

### Added

- **Main-window taskbar icon is the buddy silhouette**, not the
  default pygame/Python feather. Same procedural icon already used by
  the system tray and the About dialog — surfaced through a new
  `make_buddy_icon_surface()` helper in `clawd_buddy.ui.about` that
  converts the existing PIL icon into a `pygame.Surface` via
  `pygame.image.frombytes`. Failures are non-fatal (cosmetic-only):
  startup logs a single line and continues.

### Documentation

- `.ai/decisions/2026-05-25-milestone-4-ui-polish.md` — small design
  note covering why the interval moved to a Combobox (visual uniformity
  with quiet hours, single source of truth via label helpers) and why
  the pygame window icon is built by re-routing the existing PIL icon
  through `frombytes` rather than redrawing in pygame primitives.
- `.ai/feature-map.md` — two new rows for the interval combobox and
  the pygame window icon.
- `.ai/roadmap.md` — new **Milestone 4.2 — UI polish** entry marked
  shipped.

## [0.1.16] - 2026-05-25

### Added — Milestone 4: Wellness nudges

- **Water-drinking reminder.** The buddy can now nudge you to drink
  water on a configurable schedule. Off by default — opt in via the
  system-tray **Water Reminder** toggle or the new About-window
  **Reminders** tab.
  - **Interval**: pick one of `30 min`, `1 h`, `1.5 h`, `2 h`, `4 h`.
  - **Distinctive sound**: a high-pitched water-drop bell (default),
    a calmer two-bell chime, a square-wave triple-beep, or off.
  - **Acknowledge with Space** while the reminder is firing. Space
    keeps its old "test celebration" meaning when no alarm is active
    — the binding is mode-aware. The tray menu also surfaces an
    "I drank water" entry whenever an alarm is up.
  - **Quiet hours** independent from the M3 notification quiet-hours
    — default 23:00–08:00. Inside the window the timer doesn't
    accumulate, so a user wakes up to a full interval rather than a
    7am water-spam.
  - **Reminder bubble** ("Drink water!") appears above the buddy
    while the alarm is active, and survives a `--message` ping
    expiring (the user's bubble takes precedence briefly, the
    reminder text returns when their bubble clears).
- **Tabbed About dialog.** The existing card moved into an **About**
  tab; the new **Reminders** tab is the rich editing surface
  (enable, interval, sound, quiet-hours start/end via 30-min HH:MM
  comboboxes, a live countdown, and a "Drank now" button).
- **`drank` IPC action** + **`--drank` CLI flag**. External tools
  (smart bottles, wrist macros, scripts) can acknowledge the
  reminder remotely. Fire-and-forget — exits 0 on delivery, 1 if no
  buddy is listening.
- **`--status` payload** gains a `reminder` block: `enabled`,
  `interval_seconds`, `sound`, `quiet_hours` (null or HH:MM dict),
  `active`, `seconds_until_next` (null when the reminder is
  disabled; 0 when an alarm is firing; positive otherwise).

### Changed

- `BuddyState.__init__` accepts five new keyword arguments
  (`reminder_enabled`, `reminder_interval`, `reminder_sound`,
  `reminder_quiet_start`, `reminder_quiet_end`); defaults preserve
  pre-M4 behaviour (reminder off; if turned on, 1h interval with
  23:00–08:00 quiet hours).
- `BuddyState.update()` calls a new `_tick_reminder` once per frame.
  Cheap when disabled — single bool check + return — so users who
  haven't opted in pay almost nothing.
- `clawd_buddy.ui.sound` adds a `REMINDER_SOUNDS` registry (`water`
  / `chime` / `beep`), a `REMINDER_BASE_VOLUME` constant, and an
  `init_reminder_sounds(user_volume)` builder. `apply_volume()`
  takes a new `reminder_sounds=` keyword so the water drop respects
  the volume slider too.
- `clawd_buddy.config` exposes `REMINDER_INTERVALS`,
  `REMINDER_INTERVAL_LABELS`, and load/save helpers under a
  `reminder` sub-dict (clusters the prefs and makes a "settings
  reset" trivial later).
- System-tray menu gains a top-level **Water Reminder** checkmark
  toggle and a conditional **I drank water** entry that only
  appears while an alarm is active.
- The About menu item is now labelled **About…** to hint at the
  richer dialog content.

### Documentation

- `.ai/decisions/2026-05-25-milestone-4-wellness-nudges.md` — design
  rationale covering the resume-thinking-style flag flow, why
  reminder quiet-hours are separate from M3's, the bubble-overlay
  reuse for the visual cue, the play-time vs trigger-time sound
  gate, and the schema decision to cluster reminder prefs under a
  `reminder` sub-dict.
- `README.md` — new **Water reminder** section; tray menu list
  updated; CLI reference includes `--drank`; `--status` example
  shows the new `reminder` block.
- `.ai/feature-map.md` and `.ai/roadmap.md` — M4 marked shipped.

## [0.1.15] - 2026-05-25

### Fixed — thinking animation no longer drops after an attention cue

- The buddy used to fall back to **idle** once a wave (yellow border)
  or a greet animation cleared, even if Claude was still working.
  `BuddyState` now tracks a `_resume_thinking` flag set when a wave or
  greet preempts thinking — the flag survives chained reactives and
  is cleared by `celebrate` (`Stop` ends thinking) or explicit
  `end_thinking`. Result: thinking now resumes after every wave /
  greet until the next `Stop` arrives, matching what users expected
  during a long permission-heavy session.

### Added — Milestone 3: Comfortable & accessible

- **Reduce Motion toggle** (system-tray menu). When checked, drawing
  skips bobbing, limb swings, confetti, and ambient pupil / mouth
  animation. The attention border and notification sounds stay —
  per the roadmap's accessibility goal ("border + sound only, no
  bobbing/confetti"). Persists in `config.json` under `reduce_motion`.
- **Volume submenu** (system-tray → **Sound** → **Volume**). Discrete
  `0% / 25% / 50% / 75% / 100%` steps multiply each pack's per-event
  base level. Picking a step previews the celebrate sound at the new
  volume. Stored as a float under `volume` in `config.json` so a
  future continuous slider can read the same file.
- **Quiet Hours submenu** (system-tray → **Sound** → **Quiet Hours**).
  `Off` plus five preset night windows (21:00–08:00, 22:00–08:00,
  23:00–07:00, 23:00–08:00, 00:00–09:00). When the local time falls
  inside the window, every notification sound is muted — animations
  still play (quiet hours are about audio comfort, not hiding the
  visual signal). Schedule wraps across midnight. Stored under
  `quiet_hours: {start, end}` (minutes-from-midnight) in
  `config.json`; omitted entirely when disabled.
- **`--status` payload** gains three fields: `reduce_motion` (bool),
  `volume` (float, 3-decimal rounded), and `quiet_hours` (either
  `null` or `{"start": "HH:MM", "end": "HH:MM"}` — the HH:MM strings
  are easier to read at a glance than minute offsets).

### Changed

- `BuddyState.__init__` accepts new keyword arguments `reduce_motion`,
  `volume`, `quiet_start`, `quiet_end`. Defaults preserve current
  behaviour (motion on, volume 1.0, quiet hours disabled). Setters
  (`set_reduce_motion`, `set_volume`, `set_quiet_hours`) clamp and
  validate the same way the constructor does.
- `BuddyState._volume_changed` is a new dirty flag (mirrors the
  `_scale_changed` pattern) — the main loop watches it and re-applies
  the per-pack volume to every cached `pygame.mixer.Sound` so the
  mixer stays single-threaded.
- `clawd_buddy.ui.sound` exposes `apply_volume(sounds_by_pack, vol)`
  and `BASE_VOLUMES`. `init_sounds()` now takes a `user_volume`
  keyword and applies it once before returning, so first-frame
  playback already respects the saved preference.
- `clawd_buddy.config` adds `load_saved_reduce_motion` /
  `save_reduce_motion_pref`, `load_saved_volume` / `save_volume_pref`,
  `load_saved_quiet_hours` / `save_quiet_hours_pref`, plus public
  `VOLUME_STEPS` and `QUIET_HOURS_PRESETS` tables used by the tray.

### Documentation

- `.ai/decisions/2026-05-25-milestone-3-comfortable-and-accessible.md`
  — design note covering the resume-thinking flag, the
  reduce-motion scope ("border + sound only"), why volume + quiet
  hours live in submenus (no native pystray slider), why quiet hours
  gate at *play* time rather than at *trigger* time, and the
  `_in_quiet_window` wraparound math.
- `README.md` — new **Comfort & accessibility** section; tray menu
  list updated; `--status` example updated with the three new
  fields.
- `.ai/feature-map.md` and `.ai/roadmap.md` — M3 entries marked
  shipped.

## [0.1.14] - 2026-05-24

### Added — Milestone 2: Buddy speaks

- **`--message "TEXT"` CLI flag** — show a small speech bubble above
  the running buddy for ~3 seconds. The bubble is **independent of the
  buddy's animation mode** — it coexists with idle, thinking, greeting,
  celebrate, and wave — so anything (scripts, CI jobs, other tools) can
  pop a short status ping without preempting an in-flight animation.
  Word-wrapped to two lines max, truncated with an ellipsis past that.
  Sending a new message replaces the current one. Pass `""` to dismiss
  any active bubble immediately.
- **`--status` CLI flag** — print the running buddy's state as JSON and
  exit. Fields: `version`, `pid`, `port`, `mode`, `queue_depth`,
  `last_session_id`, `last_action`, `last_action_ts`, `theme`,
  `sound_pack`, `topmost`, `bubble_text`. Exit code 1 if no buddy is
  listening on the port — this is now the recommended "is the buddy
  alive?" probe, replacing the older "try `--send` and check the exit
  code" hack.
- **`message` socket action** — same payload as `--message`, fire-and-
  forget, slots into the existing JSON-over-TCP protocol.
- **`status` socket action** — the first **request/response** action on
  the buddy's protocol. The server writes the JSON snapshot back on the
  same socket before closing; every other action stays fire-and-forget.
- **`request_status()` client helper** in `clawd_buddy.ipc` — the
  request/response twin of `send_signal()`. Returns the parsed dict or
  `None` if no buddy is listening.

### Changed

- `BuddyState` gains a small surface for the new features: `bubble_text`
  / `_bubble_expiry` for the speech bubble, `last_action` /
  `last_action_ts` populated by `dispatch_action`, and a `topmost`
  mirror written by the main loop so `--status` can report it without
  the IPC layer reaching into pygame / windowing code. `update()` now
  also clears expired bubbles each frame.
- `dispatch_action` now records every dispatched action on `state`
  (unknown actions are recorded as `celebrate`, matching the existing
  backward-compat fall-through). `KNOWN_ACTIONS` gains `message` and
  `status`.

### Documentation

- `.ai/decisions/2026-05-24-milestone-2-buddy-speaks.md` — full design
  rationale (bubble-as-overlay vs reactive mode, request/response
  protocol convention, truncation strategy, deferred alternatives).
- `README.md` updated: new **Speech bubble** animation section, new
  CLI reference rows for `--message` / `--status`, **Signal protocol**
  section now documents the `status` request/response.
- `.ai/feature-map.md` and `.ai/roadmap.md` — M2 entries marked
  shipped.

## [0.1.13] - 2026-05-24

### Removed

- **`FEATURES/SUGGESTIONS.md`** — pre-Clawd-Buddy planning notes for a
  separate "general-purpose dev assistant" concept that never matched
  this project's direction. Planning has lived under `.ai/roadmap.md`
  since v0.1.11; the orphaned file was just confusing. No code or
  packaged artefact is affected — `FEATURES/` was never included in the
  wheel.

## [0.1.12] - 2026-05-24

### Changed — Internal: app.py decomposed into modules

The previously-monolithic `src/clawd_buddy/app.py` (1879 lines) has been
broken into focused, independently-importable modules. **No user-visible
behaviour changes** — every CLI flag, hook, animation, theme, and sound
pack works identically. The new layout:

```text
src/clawd_buddy/
├── app.py          # main() orchestration (300 lines)
├── constants.py    # WIN_W/WIN_H/FPS/TKEY/SOCK_HOST/SOCK_PORT
├── state.py        # BuddyState state machine + mode constants
├── cli.py          # argparse setup + stdin hook reader
├── config.py       # ~/.config/clawd-buddy persistence
├── ipc.py          # socket protocol + dispatcher + send_signal client
├── ui/
│   ├── themes.py   # THEMES registry + helpers
│   ├── sound.py    # procedural PCM generators + pack registry
│   ├── drawing.py  # rounded_rect + draw_buddy
│   ├── about.py    # About dialog + shared buddy icon
│   └── tray.py     # pystray icon + right-click menu
└── platform/
    ├── __init__.py # cross-platform facade
    ├── _windows.py # Win32 ctypes impl
    └── _linux.py   # X11 / XDG impl
```

### Added — Extensive unit tests

Test count grew from 32 to 211 (179 new tests across the new modules).
Coverage now includes:

- **`tests/test_themes.py`** — registry shape, required-key invariants,
  RGB validity for every theme.
- **`tests/test_sound.py`** — PCM length / framing / envelope behaviour,
  per-pack non-empty output, celebrate ≠ wave per pack.
- **`tests/test_drawing.py`** — smoke tests for every mode + theme +
  blink combination; confetti lifecycle verified.
- **`tests/test_config.py`** — round-trip, atomic write, legacy `sound:
  bool` migration, schema rejection of unknown values.
- **`tests/test_ipc.py`** — `parse_message` and `dispatch_action`
  exhaustive coverage, end-to-end round-trip on an ephemeral port.
- **`tests/test_cli.py`** — every CLI flag, `--version` exit code,
  `read_hook_stdin` TTY / JSON / malformed handling.
- **`tests/test_platform.py`** — facade dispatch, OS-specific
  `get_bg_fill` behaviour, stub fallback for unsupported platforms.
- **`tests/test_about_and_tray.py`** — buddy icon image shape /
  non-blank, `_ABOUT_DIALOG_OPEN` reentrancy guard, tray log path.

### Documentation

- `.ai/decisions/2026-05-24-app-decomposition.md` — rationale for the
  module layout (concern grouping vs flat, `platform/` shadowing
  consideration, conditional impl import).
- `README.md` Architecture section now references the new module
  layout instead of "everything is in app.py".

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
