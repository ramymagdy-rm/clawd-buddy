# Changelog

All notable changes to Clawd Buddy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
