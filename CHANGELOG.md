# Changelog

All notable changes to Clawd Buddy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
