#!/usr/bin/env python3
# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Checks behind the /release skill (.claude/skills/release/SKILL.md).

The skill runs every git / uv / gh command itself, so each step that
changes something stays visible and can be confirmed. This script only
answers the questions those steps depend on, the same way every time:

  state                 Where does the release stand? Prints the facts and
                        the NEXT path (bump, full, publish, github-release,
                        up-to-date or blocked).
  build VERSION         Build dist/ from a clean checkout of the vVERSION
                        tag (a temporary git worktree). Building in the
                        working tree would let untracked files leak into the
                        sdist, because hatchling packs everything that isn't
                        gitignored.
  verify-dist VERSION   Is dist/ exactly a complete wheel + sdist of
                        VERSION, holding nothing that isn't in the tag?
  notes VERSION         Write VERSION's CHANGELOG section (as tagged) to a
                        temp file for `gh release create --notes-file`;
                        print the path.
  wait-pypi VERSION     Wait until PyPI's simple index (what pip and uv
                        read) lists VERSION's wheel and sdist.

Standard library only. Needs Python 3.11+ (tomllib).
"""

from __future__ import annotations

import argparse
import configparser
import datetime as _dt
import email.parser
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = None

PYPI = "https://pypi.org"


# ── project metadata ────────────────────────────────────────────────────

@dataclass
class Project:
    name: str
    version: str
    dependencies: list[str]
    scripts: dict[str, str]
    gui_scripts: dict[str, str]

    @property
    def dist_name(self) -> str:
        """Filename stem of the wheel and sdist (clawd-buddy → clawd_buddy)."""
        return re.sub(r"[-_.]+", "_", self.name).lower()

    def wheel_name(self, version: str) -> str:
        return f"{self.dist_name}-{version}-py3-none-any.whl"

    def sdist_name(self, version: str) -> str:
        return f"{self.dist_name}-{version}.tar.gz"


def _toml(text: str) -> dict:
    if tomllib is None:
        sys.exit("release_tool needs Python 3.11+ (tomllib)")
    return tomllib.loads(text)


def load_project(pyproject_text: str) -> Project:
    p = _toml(pyproject_text)["project"]
    return Project(
        name=p["name"],
        version=p["version"],
        dependencies=list(p.get("dependencies", [])),
        scripts=dict(p.get("scripts", {})),
        gui_scripts=dict(p.get("gui-scripts", {})),
    )


def bumpversion_current(bumpversion_text: str) -> str | None:
    return _toml(bumpversion_text).get("tool", {}).get("bumpversion", {}).get("current_version")


def norm_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def req_name(requirement: str) -> str:
    """'jeepney>=0.8; sys_platform == "linux"' → 'jeepney'."""
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return norm_name(m.group(1)) if m else requirement.strip()


# ── CHANGELOG ───────────────────────────────────────────────────────────

_HEADER = re.compile(
    r"^## \[(?P<version>[^\]]+)\](?:[ \t]*-[ \t]*(?P<date>\d{4}-\d{2}-\d{2}))?[ \t]*$",
    re.M,
)


@dataclass
class Section:
    version: str          # "Unreleased" or X.Y.Z
    date: str | None
    body: str


def changelog_sections(text: str) -> list[Section]:
    heads = list(_HEADER.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append(Section(m["version"], m["date"], text[m.end():end].strip()))
    return out


def release_notes(changelog_text: str, version: str) -> str | None:
    for s in changelog_sections(changelog_text):
        if s.version == version:
            return s.body + "\n"
    return None


# ── deciding the next step ──────────────────────────────────────────────

@dataclass
class Facts:
    version: str                         # pyproject.toml
    bumpversion: str | None              # .bumpversion.toml current_version
    changelog_top: Section | None
    tag_local: bool
    tag_remote: bool | None              # None: couldn't ask origin
    tag_on_main: bool | None             # tag commit reachable from origin/main
    on_pypi: bool | None                 # None: couldn't reach PyPI
    gh_release: bool | None              # None: gh missing or not logged in
    unreleased_commits: int | None       # origin/develop commits not on origin/main
    main_only_commits: int | None        # origin/main commits not on origin/develop
    branch: str | None
    dirty: list[str] = field(default_factory=list)
    sync: dict[str, tuple[int, int]] = field(default_factory=dict)  # branch → (ahead, behind)
    today: str = ""
    pypi_latest: str | None = None


@dataclass
class Plan:
    next: str            # bump | full | publish | github-release | up-to-date | blocked
    why: str
    blockers: list[str]
    warnings: list[str]


def plan(f: Facts) -> Plan:
    v, tag = f.version, f"v{f.version}"
    tagged = f.tag_local or bool(f.tag_remote)
    blockers: list[str] = []
    warnings: list[str] = []

    if tagged:
        if f.on_pypi is False:
            nxt, why = "publish", f"{tag} is tagged but {v} is not on PyPI yet: build it from the tag and publish"
        elif f.on_pypi and f.gh_release is False:
            nxt, why = "github-release", f"{v} is on PyPI but {tag} has no GitHub release"
        elif f.unreleased_commits:
            nxt, why = "bump", (f"{v} is released and develop has {f.unreleased_commits} "
                                "commit(s) since, so the next release needs a new version")
        else:
            nxt, why = "up-to-date", f"{v} is tagged, on PyPI and on GitHub; develop has nothing new"
    else:
        nxt, why = "full", f"pyproject.toml is at {v}, which isn't tagged yet: release it"

    if f.bumpversion and f.bumpversion != v:
        blockers.append(f".bumpversion.toml says {f.bumpversion} but pyproject.toml says {v}; make them agree")
    if f.on_pypi is None:
        blockers.append(f"couldn't reach PyPI, so it's unknown whether {v} is published")
    if f.on_pypi and not tagged:
        blockers.append(f"PyPI already has {v} but there is no {tag} tag; find out how it was published first")
    # Only the paths that commit and switch branches care about the working
    # tree; publishing builds from a clean checkout of the tag.
    if f.dirty and nxt in ("full", "bump"):
        shown = ", ".join(f.dirty[:6]) + (" …" if len(f.dirty) > 6 else "")
        blockers.append(f"uncommitted changes to tracked files: {shown}")
    for br, (ahead, behind) in sorted(f.sync.items()):
        if ahead and behind:
            blockers.append(f"local {br} and origin/{br} have diverged ({ahead} ahead, {behind} behind)")
        elif ahead:
            warnings.append(f"local {br} has {ahead} unpushed commit(s); they become part of the release")
        elif behind:
            warnings.append(f"local {br} is {behind} commit(s) behind origin/{br}; fast-forward it first")

    if nxt in ("full", "bump") and f.main_only_commits:
        blockers.append(f"origin/main has {f.main_only_commits} commit(s) develop doesn't; "
                        "merge main into develop first")
    if nxt == "full":
        top = f.changelog_top
        if top is None or top.version not in (v, "Unreleased"):
            found = f"[{top.version}]" if top else "no section"
            blockers.append(f"CHANGELOG.md's top section is {found}; expected [{v}] or [Unreleased]")
        elif top.version == v and f.today and top.date != f.today:
            warnings.append(f"CHANGELOG dates [{v}] {top.date}; set it to today ({f.today}) when finalizing")
        if f.unreleased_commits == 0:
            blockers.append("develop has no commits that main lacks, so there is nothing to release")
    if tagged:
        if f.tag_local and f.tag_remote is False:
            warnings.append(f"{tag} exists locally but isn't pushed yet")
        if f.tag_on_main is False:
            warnings.append(f"{tag} isn't on origin/main (unpushed, or tagged on another branch)")
    if f.gh_release is None:
        warnings.append("gh CLI missing or not logged in; GitHub release status unknown")

    return Plan("blocked" if blockers else nxt, why, blockers, warnings)


# ── gathering facts from git, PyPI and GitHub ───────────────────────────

def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _git_out(root: Path, *args: str) -> str | None:
    r = _run(["git", *args], root)
    return r.stdout.strip() if r.returncode == 0 else None


def _is_ancestor(root: Path, a: str, b: str) -> bool | None:
    rc = _run(["git", "merge-base", "--is-ancestor", a, b], root).returncode
    return {0: True, 1: False}.get(rc)


def _count(root: Path, rng: str) -> int | None:
    out = _git_out(root, "rev-list", "--count", "--no-merges", rng)
    return int(out) if out is not None and out.isdigit() else None


def repo_root() -> Path:
    out = _git_out(Path.cwd(), "rev-parse", "--show-toplevel")
    if not out:
        sys.exit("release_tool: run this inside the clawd-buddy git checkout")
    return Path(out)


def parse_porcelain(out: str) -> list[str]:
    """Paths from `git status --porcelain` output ("XY path" per line).

    The status columns can start with a space (" M file"), so the output
    must not be stripped before slicing.
    """
    return [line[3:] for line in out.splitlines() if len(line) > 3]


def dirty_files(root: Path) -> list[str]:
    r = _run(["git", "status", "--porcelain", "--untracked-files=no"], root)
    return parse_porcelain(r.stdout) if r.returncode == 0 else []


def _get_json(url: str, timeout: float = 15, accept: str = "application/json", fresh: bool = True):
    """fresh=True asks PyPI's CDN to revalidate (the truth right now);
    fresh=False reads the cached copy, which is what pip and uv see."""
    headers = {"Accept": accept, "User-Agent": "clawd-buddy-release-tool"}
    if fresh:
        headers["Cache-Control"] = "no-cache"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def pypi_has_version(name: str, version: str) -> bool | None:
    try:
        _get_json(f"{PYPI}/pypi/{name}/{version}/json")
        return True
    except urllib.error.HTTPError as e:
        return False if e.code == 404 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def pypi_latest(name: str) -> str | None:
    try:
        return _get_json(f"{PYPI}/pypi/{name}/json")["info"]["version"]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


# The Accept header uv sends. PyPI's CDN caches per Accept value, so asking
# the same way reads the same cached copy uv will get.
_UV_ACCEPT = ("application/vnd.pypi.simple.v1+json, "
              "application/vnd.pypi.simple.v1+html;q=0.2, text/html;q=0.01")


def simple_index_files(name: str) -> set[str] | None:
    """Filenames on PyPI's simple index as installers see it, CDN cache included.

    Asking for a fresh copy can report a new upload a minute or more before
    the cached copy that uv and pip read shows it.
    """
    try:
        data = _get_json(f"{PYPI}/simple/{norm_name(name)}/", accept=_UV_ACCEPT, fresh=False)
        return {f["filename"] for f in data.get("files", [])}
    except urllib.error.HTTPError as e:
        return set() if e.code == 404 else None
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def gh_release_exists(root: Path, tag: str) -> bool | None:
    try:
        r = _run(["gh", "release", "view", tag, "--json", "tagName"], root)
    except FileNotFoundError:
        return None
    if r.returncode == 0:
        return True
    return False if "not found" in r.stderr.lower() else None


def gather(root: Path, fetch: bool = True) -> tuple[Facts, list[str]]:
    notes: list[str] = []
    if fetch:
        r = _run(["git", "fetch", "origin", "--prune", "--tags", "--quiet"], root)
        if r.returncode:
            notes.append(f"git fetch failed, facts may be stale: {r.stderr.strip()}")

    proj = load_project((root / "pyproject.toml").read_text(encoding="utf-8"))
    v, tag = proj.version, f"v{proj.version}"
    bv_file = root / ".bumpversion.toml"
    bv = bumpversion_current(bv_file.read_text(encoding="utf-8")) if bv_file.exists() else None
    sections = changelog_sections((root / "CHANGELOG.md").read_text(encoding="utf-8"))

    tag_local = _run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], root).returncode == 0
    lr = _run(["git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}"], root)
    tag_remote = bool(lr.stdout.strip()) if lr.returncode == 0 else None

    sync = {}
    for br in ("develop", "main"):
        out = _git_out(root, "rev-list", "--left-right", "--count", f"{br}...origin/{br}")
        if out:
            ahead, behind = (int(x) for x in out.split())
            sync[br] = (ahead, behind)

    facts = Facts(
        version=v,
        bumpversion=bv,
        changelog_top=sections[0] if sections else None,
        tag_local=tag_local,
        tag_remote=tag_remote,
        tag_on_main=_is_ancestor(root, tag, "origin/main") if tag_local else None,
        on_pypi=pypi_has_version(proj.name, v),
        gh_release=gh_release_exists(root, tag),
        unreleased_commits=_count(root, "origin/main..origin/develop"),
        main_only_commits=_count(root, "origin/develop..origin/main"),
        branch=_git_out(root, "rev-parse", "--abbrev-ref", "HEAD"),
        dirty=dirty_files(root),
        sync=sync,
        today=_dt.date.today().isoformat(),
        pypi_latest=pypi_latest(proj.name),
    )
    return facts, notes


def _yn(value: bool | None) -> str:
    return {True: "yes", False: "no", None: "unknown"}[value]


def print_state(f: Facts, p: Plan, notes: list[str]) -> None:
    tag = f"v{f.version}"
    top = f.changelog_top
    top_s = f"[{top.version}]" + (f" - {top.date}" if top and top.date else "") if top else "none"
    pypi_s = {True: "published", False: "not published", None: "unknown"}[f.on_pypi]
    gh_s = {True: "exists", False: "missing", None: "unknown"}[f.gh_release]
    sync_s = "; ".join(f"{br} " + ("in sync" if a == b == 0 else f"{a} ahead, {b} behind")
                       for br, (a, b) in sorted(f.sync.items())) or "unknown"
    rows = [
        ("version (pyproject.toml)", f.version),
        (".bumpversion.toml", f.bumpversion or "missing"),
        ("CHANGELOG top section", top_s),
        (f"tag {tag}", f"local {_yn(f.tag_local)}, origin {_yn(f.tag_remote)}, "
                       f"on origin/main {_yn(f.tag_on_main)}"),
        ("PyPI", f"{f.version} {pypi_s} (latest {f.pypi_latest or 'unknown'})"),
        (f"GitHub release {tag}", gh_s),
        ("develop not yet on main", f"{f.unreleased_commits} commit(s)"),
        ("main not on develop", f"{f.main_only_commits} commit(s)"),
        ("current branch", f.branch or "unknown"),
        ("local vs origin", sync_s),
        ("tracked changes", ", ".join(f.dirty) if f.dirty else "none"),
    ]
    print(f"Release state ({f.today})")
    for k, val in rows:
        print(f"  {k:<26} {val}")
    print()
    for n in notes:
        print(f"NOTE: {n}")
    print(f"NEXT: {p.next} - {p.why}")
    for b in p.blockers:
        print(f"BLOCKED: {b}")
    for w in p.warnings:
        print(f"WARNING: {w}")


# ── checking the built distributions ────────────────────────────────────

def _check_metadata(label: str, text: str, version: str, proj: Project) -> list[str]:
    msg = email.parser.Parser().parsestr(text)
    errors = []
    if norm_name(msg.get("Name", "")) != norm_name(proj.name):
        errors.append(f"{label}: Name is {msg.get('Name')!r}, expected {proj.name!r}")
    if msg.get("Version") != version:
        errors.append(f"{label}: Version is {msg.get('Version')!r}, expected {version!r}")
    got = {req_name(r) for r in msg.get_all("Requires-Dist") or [] if "extra ==" not in r}
    for dep in proj.dependencies:
        if req_name(dep) not in got:
            errors.append(f"{label}: Requires-Dist lacks {dep!r}")
    if not (msg.get("Description-Content-Type") or "").startswith("text/markdown"):
        errors.append(f"{label}: Description-Content-Type isn't text/markdown")
    if not (msg.get_payload() or "").strip():
        errors.append(f"{label}: long description (README) is empty")
    return errors


def _check_entry_points(label: str, text: str, proj: Project) -> list[str]:
    cp = configparser.ConfigParser(delimiters=("=",), interpolation=None)
    cp.optionxform = str
    cp.read_string(text)
    errors = []
    for section, wanted in (("console_scripts", proj.scripts), ("gui_scripts", proj.gui_scripts)):
        for cmd, target in wanted.items():
            got = cp.get(section, cmd, fallback=None)
            if got is None or got.strip() != target:
                errors.append(f"{label}: entry point [{section}] {cmd} = {got!r}, expected {target!r}")
    return errors


def check_dist(dist_dir: Path, version: str, proj: Project, src_files: list[str],
               tag_files: set[str] | None = None) -> list[str]:
    """Problems with dist_dir as a release of `version`; [] means good.

    src_files are the tag's files under src/ (src/clawd_buddy/…): every one
    must be in the sdist, and in the wheel without the src/ prefix.
    tag_files, when given, is every file in the tag; the sdist may hold
    nothing else (PKG-INFO aside), which catches untracked files leaking in.
    """
    wheel, sdist = dist_dir / proj.wheel_name(version), dist_dir / proj.sdist_name(version)
    expected = {wheel.name, sdist.name}
    present = ({p.name for p in dist_dir.iterdir() if p.is_file() and p.name != ".gitignore"}
               if dist_dir.is_dir() else set())
    errors = [f"unexpected file in {dist_dir.name}/: {name} (rebuild with `uv build --clear`)"
              for name in sorted(present - expected)]
    errors += [f"missing {name}" for name in sorted(expected - present)]

    if wheel.is_file():
        with zipfile.ZipFile(wheel) as z:
            names = set(z.namelist())
            info = f"{proj.dist_name}-{version}.dist-info"
            if f"{info}/METADATA" in names:
                errors += _check_metadata(wheel.name, z.read(f"{info}/METADATA").decode("utf-8"),
                                          version, proj)
            else:
                errors.append(f"{wheel.name}: no {info}/METADATA")
            ep = z.read(f"{info}/entry_points.txt").decode("utf-8") if f"{info}/entry_points.txt" in names else ""
            errors += _check_entry_points(wheel.name, ep, proj)
            for src in src_files:
                inner = src.removeprefix("src/")
                if inner not in names:
                    errors.append(f"{wheel.name}: missing {inner}")

    if sdist.is_file():
        top = f"{proj.dist_name}-{version}"
        with tarfile.open(sdist, "r:gz") as t:
            names = set(t.getnames())
            for must in ("pyproject.toml", "README.md", "LICENSE", "PKG-INFO", *src_files):
                if f"{top}/{must}" not in names:
                    errors.append(f"{sdist.name}: missing {must}")
            if f"{top}/PKG-INFO" in names:
                pkg_info = t.extractfile(f"{top}/PKG-INFO").read().decode("utf-8")
                errors += _check_metadata(sdist.name, pkg_info, version, proj)
            if tag_files is not None:
                for m in t.getmembers():
                    inner = m.name.removeprefix(f"{top}/")
                    if m.isfile() and inner != "PKG-INFO" and inner not in tag_files:
                        errors.append(f"{sdist.name}: contains {inner}, which isn't in v{version} "
                                      "(build with `release_tool.py build`)")
    return errors


def tag_files(root: Path, version: str) -> set[str] | None:
    out = _git_out(root, "ls-tree", "-r", "--name-only", f"v{version}")
    return set(out.splitlines()) if out else None


def tagged_text(root: Path, version: str, path: str) -> str | None:
    """A file as it is in the vVERSION tag, or None when there's no tag."""
    return _git_out(root, "show", f"v{version}:{path}")


def build_from_tag(root: Path, version: str, dist_dir: Path) -> int:
    tag = f"v{version}"
    if _git_out(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}") is None:
        print(f"FAIL: there is no {tag} tag", file=sys.stderr)
        return 1
    tmp = Path(tempfile.mkdtemp(prefix=f"clawd-buddy-{version}-"))
    tree = tmp / "src"
    try:
        r = _run(["git", "worktree", "add", "--detach", str(tree), tag], root)
        if r.returncode:
            print(f"FAIL: git worktree add: {r.stderr.strip()}", file=sys.stderr)
            return 1
        print(f"building {tag} from a clean checkout in {tree}", flush=True)
        return subprocess.run(["uv", "build", "--clear", "--out-dir", str(dist_dir), str(tree)],
                              cwd=root).returncode
    finally:
        _run(["git", "worktree", "remove", "--force", str(tree)], root)
        _run(["git", "worktree", "prune"], root)
        shutil.rmtree(tmp, ignore_errors=True)


# ── CLI ─────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("state", help="where the release stands, and what to do next")
    s.add_argument("--no-fetch", action="store_true", help="don't `git fetch origin` first")
    b = sub.add_parser("build", help="build dist/ from a clean checkout of the tag")
    b.add_argument("version")
    b.add_argument("--dist-dir", default="dist")
    d = sub.add_parser("verify-dist", help="check the built wheel and sdist")
    d.add_argument("version")
    d.add_argument("--dist-dir", default="dist")
    n = sub.add_parser("notes", help="write the CHANGELOG section to a temp file")
    n.add_argument("version")
    w = sub.add_parser("wait-pypi", help="wait until pip/uv can see the version")
    w.add_argument("version")
    w.add_argument("--timeout", type=int, default=300, help="seconds (default 300)")
    args = ap.parse_args(argv)

    root = repo_root()
    proj = load_project((root / "pyproject.toml").read_text(encoding="utf-8"))

    if args.cmd == "state":
        facts, notes = gather(root, fetch=not args.no_fetch)
        print_state(facts, plan(facts), notes)
        return 0

    def _dist_dir() -> Path:
        d = Path(args.dist_dir)
        return d if d.is_absolute() else root / d

    if args.cmd == "build":
        return build_from_tag(root, args.version, _dist_dir())

    if args.cmd == "verify-dist":
        files = tag_files(root, args.version)
        if files is None:
            print(f"FAIL: there is no v{args.version} tag")
            return 1
        # Judge the build against the tag, not whatever is checked out now.
        proj = load_project(tagged_text(root, args.version, "pyproject.toml") or "")
        src_files = sorted(f for f in files if f.startswith("src/"))
        errors = check_dist(_dist_dir(), args.version, proj, src_files, files)
        for e in errors:
            print(f"FAIL: {e}")
        if errors:
            return 1
        print(f"OK: {proj.wheel_name(args.version)} and {proj.sdist_name(args.version)} are complete, "
              f"version {args.version}, contents match v{args.version} ({len(src_files)} source files)")
        return 0

    if args.cmd == "notes":
        changelog = (tagged_text(root, args.version, "CHANGELOG.md")
                     or (root / "CHANGELOG.md").read_text(encoding="utf-8"))
        body = release_notes(changelog, args.version)
        if body is None:
            print(f"FAIL: CHANGELOG.md has no [{args.version}] section", file=sys.stderr)
            return 1
        out = Path(tempfile.gettempdir()) / f"{proj.name}-{args.version}-release-notes.md"
        out.write_text(body, encoding="utf-8")
        print(out)
        return 0

    if args.cmd == "wait-pypi":
        wanted = {proj.wheel_name(args.version), proj.sdist_name(args.version)}
        deadline = time.monotonic() + args.timeout
        while True:
            files = simple_index_files(proj.name)
            if files is not None and wanted <= files:
                print(f"OK: PyPI's simple index lists {', '.join(sorted(wanted))}")
                return 0
            if time.monotonic() >= deadline:
                missing = sorted(wanted - (files or set()))
                print(f"FAIL: after {args.timeout}s PyPI still doesn't list {', '.join(missing)}")
                return 1
            print("waiting for PyPI's index to update…", flush=True)
            time.sleep(10)

    return 2


if __name__ == "__main__":
    sys.exit(main())
