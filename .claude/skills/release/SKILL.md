---
name: release
description: Release Clawd Buddy to PyPI, which is where `pip install clawd-buddy`, `pipx` and `uv tool install clawd-buddy` all get it from. Works out where the release stands, bumps the version if needed, finalizes the CHANGELOG, runs the tests, merges develop into main, tags, builds and verifies the wheel and sdist, then, after one go-ahead, pushes, uploads with `uv publish`, creates the GitHub release and checks that pip and uv install the new version. Picks up a half-finished release (for example tagged but never uploaded). Use whenever the user wants to release, ship, publish, cut or tag a version, upload to PyPI, "release to pip/uv", or asks whether a version is out yet.
argument-hint: "[patch | minor | major | X.Y.Z | status]"
---

# Release Clawd Buddy to PyPI

pip, pipx and uv all install from PyPI, so one upload reaches everyone.
This is the same flow as **Releasing** in `CONTRIBUTING.md`, with checks
added so a broken package can't get out.

## Why it's shaped this way

- **PyPI is permanent.** A version can never be uploaded twice, even after
  deleting it, so a bad upload burns that version number. That's why the
  package is built from the tag and verified *before* anything is pushed.
- **Everything before the go-ahead is local** (release commit, merge, tag,
  build) and can be undone. Pushing, uploading and the GitHub release are
  public. There's exactly one confirmation, right before going public, so
  the user decides once with all the evidence in front of them.
- **Re-running is safe.** `state` reads the repo, PyPI and GitHub each
  time and says what's left, so an interrupted release continues from where
  it stopped instead of being redone.
- When a check fails, stop and report it. Don't work around it: don't skip
  tests, don't force-push, and never move or delete a tag that's on origin.

## The helper

`python .claude/skills/release/scripts/release_tool.py <command>` (called
**T** below). It's stdlib-only and works in PowerShell and bash:

| Command | What it does |
|---|---|
| `T state` | Fetches origin, prints the facts and `NEXT:` with any `BLOCKED:` / `WARNING:` lines |
| `T build V` | Builds `dist/` from a clean checkout of tag vV in a temporary git worktree |
| `T verify-dist V` | Checks that `dist/` holds exactly a complete wheel + sdist of V, with nothing that isn't in the tag |
| `T notes V` | Writes the `[V]` CHANGELOG section, as tagged, to a temp file and prints its path |
| `T wait-pypi V` | Waits until PyPI's index (what pip and uv read) lists V |

## 1. Read the state

Note the branch you start on, since you'll return to it at the end. Run
`T state`.

- Argument `status`, or the user only asked whether something is out:
  explain the state in plain words and stop.
- `BLOCKED:` lines: report them, propose the fix, and stop. Fast-forwarding
  a branch that's only *behind* (a `WARNING:`) is fine to just do.
- Otherwise follow `NEXT:`:

| NEXT | Meaning | Steps |
|---|---|---|
| `bump` | the current version is out and develop has new commits | 2 → 3 → 4 → 5 → 6 → 7 → 8 |
| `full` | the version is bumped on develop but not tagged | 3 → 4 → 5 → 6 → 7 → 8 |
| `publish` | it's tagged but not on PyPI | 5 → 6 → 7 → 8 |
| `github-release` | it's on PyPI but has no GitHub release | 5 → 6 → only the `gh release` part of 7 |
| `up-to-date` | nothing to release | say so and stop |

## 2. Bump the version (NEXT = bump)

On an up-to-date `develop`:

```bash
uvx bump-my-version bump patch            # or minor / major from the argument
uvx bump-my-version bump --new-version X.Y.Z   # explicit version
```

The default is `patch`, matching every 0.1.x release so far. This updates
`pyproject.toml` and `.bumpversion.toml` and nothing else.

## 3. Finalize on develop (bump, full)

1. `git switch develop`. Its top CHANGELOG section must become
   `## [V] - <today>`:
   - `## [Unreleased]`: rename it.
   - `## [V] - <older date>`: change the date to today, because the date is
     the release date.
   - No section for the new changes: draft one from
     `git log v<previous>..develop --no-merges` and the diffs, in the
     file's own style (a bold one-line summary per bullet, then why it
     matters to a user). Show the draft and get the user's OK before
     committing, since it's the public face of the release.
2. Run the tests: `.venv/Scripts/python -m pytest -q` on Windows
   (`.venv/bin/python` elsewhere). If `.venv` is missing, create it per
   `CONTRIBUTING.md` (`uv venv && uv pip install -e ".[dev]"`). Any failure
   stops the release.
3. If anything changed, commit it on develop:
   `git add pyproject.toml .bumpversion.toml CHANGELOG.md` then
   `git commit -m "Release vV: <summary>"`. Don't add Co-Authored-By or any
   other attribution trailer, because the maintainer doesn't use them.

## 4. Merge and tag (bump, full)

```bash
git switch main
git merge --ff-only origin/main
git merge develop --no-ff -m "Merge branch 'develop' for vV release"
git tag -a vV -m "Release vV: <summary>"
```

`<summary>` is a short phrase naming the headline change, like the past
tags (`git tag -n1 --sort=-v:refname | head -3`). For example:
`Release v0.1.24: Linux tray menu (StatusNotifierItem over D-Bus)`.

## 5. Build and verify, from the tag

```bash
T build V                        # replaces dist/; old builds are already on PyPI
T verify-dist V
uvx twine check --strict dist/*
uvx --isolated --from dist/clawd_buddy-V-py3-none-any.whl clawd-buddy --version
```

Use `T build`, not a plain `uv build`. Hatchling packs every file that
isn't gitignored into the sdist, so building in the working tree would ship
untracked files such as stray images or work in progress. `T build` builds
from a clean checkout of the tag, so it works from any branch, even with
uncommitted changes.

The last line of the smoke test must read `clawd-buddy V`; a pygame banner
before it is normal. Any failure stops the release. Everything is still
local, so fix it on develop and start over from step 3.

On the `publish` and `github-release` paths the tests already ran when the
tag was made. The smoke test still proves the wheel installs and starts.

## 6. Get the go-ahead (the one confirmation)

Show a short summary, then ask and wait:

- the version, which path this is, and the tag with its message and commit
- tests (count passed), verify-dist, twine and the smoke test
- the first lines of the `[V]` CHANGELOG section
- exactly what going public will do (list only what's still needed):
  push main, develop and vV; `uv publish` (permanent); create the GitHub
  release

If the user wants a different tag message, re-create the tag with
`git tag -f -a` (safe only because it isn't pushed yet). If they decline,
everything stays local. Say so, and mention that `git tag -d vV` plus
resetting main/develop to origin would undo it, but don't run that unless
asked.

## 7. Go public

```bash
git push origin main develop
git push origin vV
uv publish --check-url https://pypi.org/simple/
```

`--check-url` skips files already on PyPI, so a retry after a partial
upload is safe. `uv publish` reads the token from `UV_PUBLISH_TOKEN`. On a
401/403, stop and ask the user to set one (pypi.org → Account settings →
API tokens, scoped to clawd-buddy), then re-run `/release`, which resumes
at `publish`. Never print the token.

Then the GitHub release, which matches past ones: the title is the tag,
the body is the CHANGELOG section, and the wheel and sdist are attached.

```bash
T notes V        # prints the notes file path
gh release create vV dist/clawd_buddy-V-py3-none-any.whl dist/clawd_buddy-V.tar.gz --title vV --notes-file <path> --verify-tag
```

If a push is rejected because origin moved, stop and report it. Don't
force-push.

## 8. Confirm pip and uv get it, then report

```bash
T wait-pypi V
uvx --isolated --refresh --from clawd-buddy==V clawd-buddy --version     # what uv tool install gets
uvx pip install --dry-run --no-deps --no-cache-dir clawd-buddy==V      # pip: "Would install clawd-buddy-V"
```

PyPI serves its index through a CDN cache, so for a minute or two after
the upload, uv can still say "there is no version of clawd-buddy==V" even
though `wait-pypi` passed. That's the cache, not a failed release. Retry
every 20 seconds or so for a few minutes before treating it as a problem.

Switch back to the branch you started on (develop if that was a detached
HEAD). Then report:

- what was released and how it was verified
- https://pypi.org/project/clawd-buddy/V/ and the GitHub release URL
- how users upgrade: `uv tool upgrade clawd-buddy`, `pipx upgrade clawd-buddy`,
  `pip install -U clawd-buddy`

If something went wrong after the upload, the version can't be replaced.
The fix is a new patch release. Whether to yank the broken one
(pypi.org → Manage → Releases) is the user's call.
