# Contributing to Clawd Buddy

Thanks for your interest in contributing!

## Branching strategy

```text
main          Stable releases only — merged from develop
 └─ develop   Integration branch — features merge here first
     └─ feature/xyz   Individual feature branches
```

- **`main`** — production-ready releases. Only updated via merge from `develop` after a group of features is tested.
- **`develop`** — active development. All feature branches are created from and merged back into `develop`.
- **`feature/*`** — short-lived branches for individual features or fixes, branched off `develop`.

### Workflow

1. Create a feature branch from `develop`:

   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/my-feature
   ```

2. Make your changes, commit, and push:

   ```bash
   git push -u origin feature/my-feature
   ```

3. Open a pull request targeting **`develop`** (not `main`).
4. After review, merge into `develop`.
5. When a set of features in `develop` is ready for release, `develop` is merged into `main` and tagged.

## Development setup

```bash
git clone https://github.com/ramymagdy-rm/clawd-buddy.git
cd clawd-buddy
git checkout develop

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
python -m clawd_buddy.app --fg

# Or if installed in editable mode
clawd-buddy --fg
```

Use `--fg` to keep the buddy in the foreground so you can see log output in the terminal.

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

- **Platform helpers** — Windows (`ctypes` win32) and Linux (`ctypes` X11) for transparency, positioning, panel detection
- **Themes** — `THEMES` dict with `dark` and `light` color palettes
- **Cross-platform wrappers** — `get_window_handle()`, `setup_window()`, `move_window()`, etc. dispatch to the right platform
- **State machine** — `BuddyState` with three modes (`idle`, `celebrating`, `waving`), theme, and scale
- **Drawing** — `draw_buddy()` renders the character on a base surface; the main loop scales it to the window
- **Socket listener** — TCP server on port 44556, parses JSON `{"action": "..."}` messages
- **System tray** — `pystray` icon with context menu (celebrate, theme toggle, quit)
- **CLI** — `argparse` for `--send`, `--wave`, `--test`, `--theme`, `--startup`, etc.
- **Main loop** — pygame event loop at 120 FPS

## Making changes

1. Fork the repo and create a feature branch off `develop`
2. Make your changes in `src/clawd_buddy/app.py`
3. Test manually: `clawd-buddy --test` (celebrate), `clawd-buddy --wave` (wave signal)
4. Test both themes: `clawd-buddy --theme dark`, `clawd-buddy --theme light`
5. Update `CHANGELOG.md` under an `[Unreleased]` section
6. Open a pull request targeting `develop`

## Adding a new animation state

1. Add the state name to `BuddyState` (add a property and trigger method)
2. Add drawing logic in `draw_buddy()` — follow the pattern of `cel`/`wav` branches
3. Add a new action string in `socket_listener()` dispatch
4. Add a CLI flag in `parse_args()` and handle it in `main()`
5. Document the new hook in `README.md`

## Releasing

When `develop` has been merged into `main` and tagged, publish to PyPI with:

```bash
rm -r dist; uv build && uv publish
```

`uv build` produces the wheel and sdist in `dist/`; `uv publish` uploads both to PyPI. Make sure your `UV_PUBLISH_TOKEN` (or `~/.pypirc`) is configured.

## Guidelines

- Keep everything in `app.py` unless there's a strong reason to split
- No external assets — all rendering is procedural (pygame draw calls)
- Test all three states (idle, celebrate, wave) after any drawing changes
- All PRs target `develop`, not `main`
