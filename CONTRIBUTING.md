# Contributing to Clawd Buddy

Thanks for your interest in contributing!

## Development setup

```bash
git clone https://github.com/ramymagdy-rm/clawd-buddy.git
cd clawd-buddy

# Create a venv and install in editable mode
uv venv
uv pip install -e ".[dev]"

# Or with pip
python -m venv venv
venv\Scripts\activate
pip install -e .
```

## Running locally

```bash
# Run from source
python -m clawd_buddy.app

# Or if installed in editable mode
clawd-buddy
```

## Project structure

```text
clawd-buddy/
├── src/clawd_buddy/
│   ├── __init__.py       # Package metadata
│   └── app.py            # All application code (rendering, state, socket, tray)
├── .claude/
│   ├── settings.json     # Claude Code hook definitions
│   └── commands/
│       └── buddy.md      # /buddy slash command for Claude Code
├── pyproject.toml        # Package configuration
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
└── LICENSE
```

## How the code is organized

Everything lives in `app.py` to keep the package simple:

- **Win32 helpers** — `ctypes` calls for transparency, positioning, taskbar detection
- **State machine** — `BuddyState` with three modes: `idle`, `celebrating`, `waving`
- **Drawing** — `draw_buddy()` renders the character based on current state and time
- **Socket listener** — TCP server on port 44556, parses JSON `{"action": "..."}` messages
- **System tray** — `pystray` icon with context menu
- **CLI** — `argparse` for `--send`, `--wave`, `--test`, `--startup`, etc.
- **Main loop** — pygame event loop at 60 FPS

## Making changes

1. Fork the repo and create a feature branch
2. Make your changes in `src/clawd_buddy/app.py`
3. Test manually: `clawd-buddy --test` (celebrate), `clawd-buddy --wave` (wave signal)
4. Update `CHANGELOG.md` under an `[Unreleased]` section
5. Open a pull request

## Adding a new animation state

1. Add the state name to `BuddyState` (add a property and trigger method)
2. Add drawing logic in `draw_buddy()` — follow the pattern of `cel`/`wav` branches
3. Add a new action string in `socket_listener()` dispatch
4. Add a CLI flag in `parse_args()` and handle it in `main()`
5. Document the new hook in `README.md`

## Guidelines

- Keep everything in `app.py` unless there's a strong reason to split
- No external assets — all rendering is procedural (pygame draw calls)
- Windows-only is fine for now; cross-platform support would need platform abstraction for the win32 calls
- Test all three states (idle, celebrate, wave) after any drawing changes
