# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Tests for the /release skill's helper (.claude/skills/release/scripts/release_tool.py).

The skill drives git, uv and gh itself and is exercised by running a
release. What's tested here is the part that makes decisions: reading the
CHANGELOG, choosing the next release step from the repo's state, and
judging whether a built wheel + sdist is complete. The archives are built
by hand in tmp_path, so no build tool or network is needed.
"""

import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("tomllib")  # the helper needs Python 3.11+

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / ".claude" / "skills" / "release" / "scripts" / "release_tool.py"


def _load():
    spec = importlib.util.spec_from_file_location("release_tool", TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


rt = _load()


# ── the real repo ───────────────────────────────────────────────────────

def test_repo_versions_agree():
    proj = rt.load_project((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    bump = rt.bumpversion_current((ROOT / ".bumpversion.toml").read_text(encoding="utf-8"))
    assert proj.version == bump


def test_repo_changelog_parses_and_tops_with_current_or_unreleased():
    proj = rt.load_project((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sections = rt.changelog_sections((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    assert sections[0].version in (proj.version, "Unreleased")
    released = [s for s in sections if s.version != "Unreleased"]
    assert released and all(s.date for s in released)


# ── CHANGELOG ───────────────────────────────────────────────────────────

CHANGELOG = """# Changelog

Intro text.

## [Unreleased]

### Added

- New thing.

## [1.2.3] - 2026-10-31

### Fixed

- **A bug.** Details
  continue here.

## [1.2.2] - 2026-10-01

- Older.
"""


def test_changelog_sections():
    sections = rt.changelog_sections(CHANGELOG)
    assert [(s.version, s.date) for s in sections] == [
        ("Unreleased", None), ("1.2.3", "2026-10-31"), ("1.2.2", "2026-10-01")]


def test_release_notes_is_the_section_body():
    assert rt.release_notes(CHANGELOG, "1.2.3") == (
        "### Fixed\n\n- **A bug.** Details\n  continue here.\n")
    assert rt.release_notes(CHANGELOG, "1.2.2") == "- Older.\n"


def test_release_notes_missing_version():
    assert rt.release_notes(CHANGELOG, "9.9.9") is None


def test_parse_porcelain_keeps_the_first_character():
    # The first line starts with a space; stripping the output first once
    # turned "CHANGELOG.md" into "HANGELOG.md".
    out = " M CHANGELOG.md\nM  CONTRIBUTING.md\nMM src/clawd_buddy/app.py\n"
    assert rt.parse_porcelain(out) == ["CHANGELOG.md", "CONTRIBUTING.md", "src/clawd_buddy/app.py"]


# ── choosing the next step ──────────────────────────────────────────────

def _facts(**overrides):
    """A fully released 1.2.3 with nothing new on develop."""
    base = dict(
        version="1.2.3", bumpversion="1.2.3",
        changelog_top=rt.Section("1.2.3", "2026-10-31", "- x"),
        tag_local=True, tag_remote=True, tag_on_main=True,
        on_pypi=True, gh_release=True,
        unreleased_commits=0, main_only_commits=0,
        branch="develop", dirty=[], sync={"develop": (0, 0), "main": (0, 0)},
        today="2026-10-31",
    )
    base.update(overrides)
    return rt.Facts(**base)


UNTAGGED = dict(tag_local=False, tag_remote=False, tag_on_main=None,
                on_pypi=False, gh_release=False, unreleased_commits=2)


@pytest.mark.parametrize("overrides, expected", [
    ({}, "up-to-date"),
    ({"unreleased_commits": 3}, "bump"),
    ({"on_pypi": False, "gh_release": False}, "publish"),
    ({"gh_release": False}, "github-release"),
    (UNTAGGED, "full"),
    ({**UNTAGGED, "changelog_top": rt.Section("Unreleased", None, "- x")}, "full"),
    # Publishing builds from a clean checkout of the tag, so local edits don't matter.
    ({"on_pypi": False, "dirty": ["CHANGELOG.md"]}, "publish"),
    # A local tag that isn't pushed yet still counts as tagged (resume after step 4).
    ({"tag_remote": False, "tag_on_main": False, "on_pypi": False, "gh_release": False}, "publish"),
])
def test_plan_next(overrides, expected):
    assert rt.plan(_facts(**overrides)).next == expected


@pytest.mark.parametrize("overrides, mentions", [
    ({"bumpversion": "1.2.2"}, ".bumpversion.toml"),
    ({"on_pypi": None}, "PyPI"),
    ({**UNTAGGED, "on_pypi": True}, "no v1.2.3 tag"),
    ({**UNTAGGED, "dirty": ["CHANGELOG.md"]}, "uncommitted"),
    ({"unreleased_commits": 3, "dirty": ["src/clawd_buddy/app.py"]}, "uncommitted"),
    ({**UNTAGGED, "changelog_top": rt.Section("1.2.2", "2026-10-01", "")}, "CHANGELOG"),
    ({**UNTAGGED, "main_only_commits": 1}, "merge main into develop"),
    ({**UNTAGGED, "unreleased_commits": 0}, "nothing to release"),
    ({"sync": {"develop": (1, 2)}}, "diverged"),
])
def test_plan_blocked(overrides, mentions):
    p = rt.plan(_facts(**overrides))
    assert p.next == "blocked"
    assert any(mentions in b for b in p.blockers), p.blockers


def test_plan_warns_but_goes_on_when_only_behind():
    p = rt.plan(_facts(on_pypi=False, gh_release=False, sync={"main": (0, 2)}))
    assert p.next == "publish"
    assert any("behind" in w for w in p.warnings)


def test_plan_warns_about_a_stale_changelog_date():
    p = rt.plan(_facts(**UNTAGGED, changelog_top=rt.Section("1.2.3", "2026-10-01", "")))
    assert p.next == "full"
    assert any("today" in w for w in p.warnings)


# ── checking the built distributions ────────────────────────────────────

PROJ = rt.Project(
    name="clawd-buddy", version="1.2.3",
    dependencies=["pygame-ce>=2.5", "jeepney>=0.8; sys_platform == 'linux'"],
    scripts={"clawd-buddy": "clawd_buddy.app:main"},
    gui_scripts={"clawd-buddyw": "clawd_buddy.app:main"},
)
SRC = ["src/clawd_buddy/__init__.py", "src/clawd_buddy/app.py", "src/clawd_buddy/ui/sni.py"]
TAG_FILES = {"pyproject.toml", "README.md", "LICENSE", *SRC}
ENTRY_POINTS = ("[console_scripts]\nclawd-buddy = clawd_buddy.app:main\n\n"
                "[gui_scripts]\nclawd-buddyw = clawd_buddy.app:main\n")


def _metadata(version="1.2.3", deps=("pygame-ce>=2.5", 'jeepney>=0.8; sys_platform == "linux"')):
    return "\n".join([
        "Metadata-Version: 2.4", "Name: clawd-buddy", f"Version: {version}",
        *[f"Requires-Dist: {d}" for d in deps],
        "Provides-Extra: dev", "Requires-Dist: pytest>=8; extra == 'dev'",
        "Description-Content-Type: text/markdown", "", "# Clawd Buddy", "",
    ])


def _build(dist, version="1.2.3", *, drop=(), metadata=None, entry_points=ENTRY_POINTS,
           sdist_extra=(), extra_files=()):
    """Write a wheel + sdist shaped like hatchling's into `dist`."""
    dist.mkdir(exist_ok=True)
    meta = metadata or _metadata(version)
    info = f"clawd_buddy-{version}.dist-info"
    with zipfile.ZipFile(dist / f"clawd_buddy-{version}-py3-none-any.whl", "w") as z:
        for s in SRC:
            if s not in drop:
                z.writestr(s.removeprefix("src/"), "")
        z.writestr(f"{info}/METADATA", meta)
        z.writestr(f"{info}/entry_points.txt", entry_points)
    top = f"clawd_buddy-{version}"
    members = [("pyproject.toml", ""), ("README.md", ""), ("LICENSE", ""), ("PKG-INFO", meta),
               *[(s, "") for s in SRC if s not in drop], *[(x, "") for x in sdist_extra]]
    with tarfile.open(dist / f"clawd_buddy-{version}.tar.gz", "w:gz") as t:
        for name, text in members:
            data = text.encode()
            ti = tarfile.TarInfo(f"{top}/{name}")
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))
    for name in extra_files:
        (dist / name).write_text("")
    return dist


def _check(dist):
    return rt.check_dist(dist, "1.2.3", PROJ, SRC, TAG_FILES)


def test_good_build_passes(tmp_path):
    assert _check(_build(tmp_path / "dist", extra_files=[".gitignore"])) == []


def test_missing_dist_files(tmp_path):
    (tmp_path / "dist").mkdir()
    errors = _check(tmp_path / "dist")
    assert any("missing clawd_buddy-1.2.3-py3-none-any.whl" in e for e in errors)
    assert any("missing clawd_buddy-1.2.3.tar.gz" in e for e in errors)


def test_stale_artifacts_are_rejected(tmp_path):
    dist = _build(tmp_path / "dist", extra_files=["clawd_buddy-1.2.2-py3-none-any.whl", "notes-1.2.2.md"])
    errors = _check(dist)
    assert any("clawd_buddy-1.2.2-py3-none-any.whl" in e for e in errors)
    assert any("notes-1.2.2.md" in e for e in errors)


def test_missing_module_is_reported_for_wheel_and_sdist(tmp_path):
    errors = _check(_build(tmp_path / "dist", drop=["src/clawd_buddy/ui/sni.py"]))
    assert any(e.startswith("clawd_buddy-1.2.3-py3-none-any.whl") and "ui/sni.py" in e for e in errors)
    assert any(e.startswith("clawd_buddy-1.2.3.tar.gz") and "ui/sni.py" in e for e in errors)


def test_metadata_version_mismatch(tmp_path):
    errors = _check(_build(tmp_path / "dist", metadata=_metadata("9.9.9")))
    assert any("'9.9.9'" in e for e in errors)


def test_missing_dependency(tmp_path):
    errors = _check(_build(tmp_path / "dist", metadata=_metadata(deps=("pygame-ce>=2.5",))))
    assert any("jeepney" in e for e in errors)


def test_missing_gui_entry_point(tmp_path):
    errors = _check(_build(tmp_path / "dist",
                           entry_points="[console_scripts]\nclawd-buddy = clawd_buddy.app:main\n"))
    assert any("clawd-buddyw" in e for e in errors)


def test_untracked_files_leaking_into_the_sdist(tmp_path):
    errors = _check(_build(tmp_path / "dist", sdist_extra=["assets/bmc_qr.png"]))
    assert any("assets/bmc_qr.png" in e and "isn't in v1.2.3" in e for e in errors)
