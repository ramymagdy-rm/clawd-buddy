# Changelog

All notable changes to Clawd Buddy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
