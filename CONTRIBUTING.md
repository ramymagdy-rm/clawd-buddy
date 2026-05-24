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
│   ├── __init__.py        # Package metadata (__version__)
│   ├── app.py             # main() orchestration only
│   ├── constants.py       # Window dimensions, IPC port, transparency key
│   ├── state.py           # BuddyState state machine + queue + modes
│   ├── cli.py             # argparse + read_hook_stdin
│   ├── config.py          # ~/.config/clawd-buddy persistence
│   ├── ipc.py             # JSON-over-TCP protocol + dispatcher + client
│   ├── ui/
│   │   ├── themes.py      # 8 color theme registry
│   │   ├── sound.py       # Procedural PCM generators + pack registry
│   │   ├── drawing.py     # rounded_rect + draw_buddy
│   │   ├── about.py       # About dialog + shared buddy icon
│   │   └── tray.py        # pystray icon + right-click menu
│   └── platform/
│       ├── __init__.py    # Cross-platform facade
│       ├── _windows.py    # Win32 ctypes (transparency, taskbar, autostart)
│       └── _linux.py      # X11 / XDG (window props, panel, .desktop)
├── tests/                 # One test file per module
├── .claude/
│   ├── settings.json      # Claude Code hook definitions
│   └── commands/
│       └── buddy.md       # /buddy slash command for Claude Code
├── pyproject.toml         # Package configuration
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
└── LICENSE
```

## How the code is organized

Each module is focused and independently testable. See
`.ai/decisions/2026-05-24-app-decomposition.md` for the rationale.

- **`app.py`** — thin orchestrator: argparse → resolve theme → handle
  one-shot signal flags → daemonise → bind lock → init pygame → run
  the main loop.
- **`state.py`** — `BuddyState` with five modes (`idle`, `celebrating`,
  `waving`, `greeting`, `thinking`), a reaction queue, and the
  session-greeting dedup logic.
- **`ipc.py`** — socket listener thread plus the pure
  `parse_message` / `dispatch_action` functions used by tests.
- **`ui/`** — anything visual or audible: themes, sound packs, drawing
  primitives, About dialog, tray.
- **`platform/`** — every line of platform-specific code lives behind a
  cross-platform facade (`get_window_handle`, `setup_window`, …). The
  `_windows.py` / `_linux.py` impls are only imported when their OS
  matches `sys.platform`.
- **`config.py`** — atomic read/write of `config.json` with schema
  migration (legacy `sound: bool` → `sound_pack: str`).
- **`cli.py`** — every CLI flag and the Claude Code hook stdin reader.
- **`constants.py`** — window dimensions, IPC port, transparency key.
  Imported by both rendering and platform code so they stay in sync.

## Making changes

1. Fork the repo and create a feature branch off `develop`
2. Make your changes in the relevant module(s)
3. Add or update tests in `tests/test_<module>.py`
4. Run the test suite: `python -m pytest`
5. Test manually: `clawd-buddy --test` (celebrate), `clawd-buddy --wave` (wave signal)
6. Update `CHANGELOG.md` under an `[Unreleased]` section
7. Open a pull request targeting `develop`

## Adding a new animation state

1. Add the state name to `state.py` (mode constant, `BuddyState`
   property, trigger method that goes through `_request`)
2. Add drawing logic in `ui/drawing.py`'s `draw_buddy` — follow the
   `cel` / `wav` / `greet` / `think` branches
3. Add a new action constant in `ipc.py`'s `ACTION_*` block and route
   it in `dispatch_action`
4. Add a CLI flag in `cli.py` and handle it in `main()` (build the
   payload + call `send_signal`)
5. Add tests in `tests/test_buddy_state.py`, `tests/test_ipc.py`, and
   `tests/test_cli.py`
6. Document the new hook in `README.md`

## Releasing

### 1. Bump the version

The project version lives in `pyproject.toml` under `[project] version` and
is read at runtime via `importlib.metadata.version("clawd-buddy")` — so
**that one field is the single source of truth**. `bump-my-version` is
configured in `.bumpversion.toml` to keep it in sync with its own
`current_version`:

```bash
uvx bump-my-version bump patch    # 0.1.9 → 0.1.10
uvx bump-my-version bump minor    # 0.1.9 → 0.2.0
uvx bump-my-version bump major    # 0.1.9 → 1.0.0
```

`uvx` runs the tool in an ephemeral environment, no install required.
The config sets `commit = false` and `tag = false` on purpose — version
files are edited, but you handle the commit, CHANGELOG finalization, merge,
and tag manually.

### 2. Finalize the CHANGELOG

Rename the unreleased section to the new version + today's date:

```diff
- ## [Unreleased]
+ ## [0.1.10] - 2026-MM-DD
```

### 3. Commit, merge, tag

```bash
git add pyproject.toml .bumpversion.toml CHANGELOG.md
git commit -m "Release v0.1.10: <short summary>"
git checkout main
git merge develop --no-ff -m "Merge branch 'develop' for v0.1.10 release"
git tag -a v0.1.10 -m "Release v0.1.10: <short summary>"
git push origin main develop
git push origin v0.1.10
```

### 4. Publish to PyPI

```bash
rm -r dist; uv build && uv publish
```

`uv build` produces the wheel and sdist in `dist/`; `uv publish` uploads both to PyPI. Make sure your `UV_PUBLISH_TOKEN` (or `~/.pypirc`) is configured.

## Guidelines

- Keep everything in `app.py` unless there's a strong reason to split
- No external assets — all rendering is procedural (pygame draw calls)
- Test all three states (idle, celebrate, wave) after any drawing changes
- All PRs target `develop`, not `main`
