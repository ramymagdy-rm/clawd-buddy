# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Tests for the Windows "Clawd-Buddy.exe" host (platform/_winhost.py).

The resource builders are pure and checked on every OS by parsing their
output back. The decision logic in `ensure_host` (when to build, reuse,
clean up or fall back) runs against a fake venv. One Windows-only test
builds a real host and asks Windows what it's called.
"""

import io
import os
import struct
import sys

import pytest

from clawd_buddy import platform as plat
from clawd_buddy.platform import _winhost as wh


# ── Helpers ──────────────────────────────────────────────────────────
def parse_node(blob, offset=0):
    """Parse one VS_VERSIONINFO block → (key, value, children, end).
    Mirrors the layout rules Windows applies when reading it back."""
    length, value_len, wtype = struct.unpack_from("<HHH", blob, offset)
    end = offset + length
    pos = offset + 6
    key_end = blob.index(b"\0\0", pos)
    while (key_end - pos) % 2:            # UTF-16: stop on a char boundary
        key_end = blob.index(b"\0\0", key_end + 1)
    key = blob[pos:key_end].decode("utf-16-le")
    pos = key_end + 2
    pos += -(pos - offset) % 4
    size = value_len * 2 if wtype == 1 else value_len
    value = blob[pos:pos + size]
    pos += size
    children = []
    while True:
        pos += -(pos - offset) % 4
        if pos >= end:
            break
        child = parse_node(blob, pos)
        children.append(child)
        pos = child[3]
    return key, value, children, end


def strings_of(blob):
    _k, _v, children, _e = parse_node(blob)
    string_info = next(c for c in children if c[0] == "StringFileInfo")
    table = string_info[2][0]
    return table[0], {k: v.decode("utf-16-le").rstrip("\0")
                      for k, v, _c, _e in table[2]}


def make_ico(sizes=(16, 32, 256)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (256, 256), (200, 90, 40, 255)).save(
        buf, format="ICO", sizes=[(s, s) for s in sizes])
    return buf.getvalue()


# ── version_tuple ────────────────────────────────────────────────────
class TestVersionTuple:
    @pytest.mark.parametrize("text, expected", [
        ("0.1.25", (0, 1, 25, 0)),
        ("1.2.3.4", (1, 2, 3, 4)),
        ("1.2.3.4.5", (1, 2, 3, 4)),
        ("2", (2, 0, 0, 0)),
        ("0.2.0.dev1", (0, 2, 0, 0)),
        ("1.0rc2", (1, 0, 0, 0)),
        ("unknown", (0, 0, 0, 0)),
        ("1.99999", (1, 0xFFFF, 0, 0)),
    ])
    def test_cases(self, text, expected):
        assert wh.version_tuple(text) == expected


# ── build_version_resource ───────────────────────────────────────────
class TestVersionResource:
    def setup_method(self):
        self.strings = wh.host_strings("0.1.25")
        self.blob = wh.build_version_resource("0.1.25", self.strings)

    def test_root_block_spans_the_whole_resource(self):
        key, _v, _c, end = parse_node(self.blob)
        assert key == "VS_VERSION_INFO"
        assert end == len(self.blob)

    def test_fixed_file_info(self):
        _k, value, _c, _e = parse_node(self.blob)
        assert len(value) == 52
        fields = struct.unpack("<13I", value)
        assert fields[0] == 0xFEEF04BD
        assert fields[2:4] == ((0 << 16) | 1, (25 << 16) | 0)
        assert fields[9] == 1   # VFT_APP

    def test_string_table_round_trips(self):
        lang, strings = strings_of(self.blob)
        assert lang == "040904B0"
        assert strings == self.strings

    def test_task_manager_name(self):
        _lang, strings = strings_of(self.blob)
        assert strings["FileDescription"] == "Clawd Buddy"
        assert strings["OriginalFilename"] == "Clawd-Buddy.exe"

    def test_translation_matches_the_table(self):
        _k, _v, children, _e = parse_node(self.blob)
        var_info = next(c for c in children if c[0] == "VarFileInfo")
        _key, value, _c, _e = var_info[2][0]
        assert struct.unpack("<HH", value) == (0x0409, 1200)

    def test_blocks_nest_inside_their_parents(self):
        # wLength of every block must cover its children exactly, or
        # Windows reads past them into the next block.
        def walk(node):
            _k, _v, children, end = node
            for child in children:
                assert child[3] <= end
                walk(child)
            return len(children)
        assert walk(parse_node(self.blob)) == 2

    def test_non_ascii_strings_survive(self):
        blob = wh.build_version_resource("1.0", {"Comments": "Café ☕"})
        _lang, strings = strings_of(blob)
        assert strings == {"Comments": "Café ☕"}

    def test_comment_says_what_the_file_is(self):
        assert "pythonw.exe" in self.strings["Comments"]


# ── icon_resources ───────────────────────────────────────────────────
class TestIconResources:
    def test_group_points_at_each_image(self):
        ico = make_ico((16, 32, 256))
        group, images = wh.icon_resources(ico)
        reserved, kind, count = struct.unpack_from("<HHH", group, 0)
        assert (reserved, kind, count) == (0, 1, 3)
        assert len(group) == 6 + 14 * 3
        assert [i for i, _d in images] == [1, 2, 3]
        for n, (icon_id, data) in enumerate(images):
            (w, _h, _c, _r, planes, bits, size,
             gid) = struct.unpack_from("<BBBBHHIH", group, 6 + 14 * n)
            assert gid == icon_id
            assert size == len(data)
            assert planes == 1 and bits == 32
        # 256 px is stored as 0 in the one-byte width field.
        assert struct.unpack_from("<B", group, 6 + 14 * 2)[0] == 0

    def test_first_id_is_honoured(self):
        _g, images = wh.icon_resources(make_ico((16,)), first_id=7)
        assert images[0][0] == 7

    @pytest.mark.parametrize("bad", [
        b"\0\0\2\0\1\0" + b"\0" * 16,     # cursor, not icon
        b"\0\0\1\0\0\0",                  # no images
    ])
    def test_rejects_non_icons(self, bad):
        with pytest.raises(ValueError):
            wh.icon_resources(bad)

    def test_rejects_truncated_image(self):
        ico = make_ico((16,))
        with pytest.raises(ValueError):
            wh.icon_resources(ico[:-10])

    def test_buddy_icon_has_every_size(self):
        ico = wh.buddy_icon_ico()
        _g, images = wh.icon_resources(ico)
        assert len(images) == len(wh.ICON_SIZES)


# ── host_key / runtime_files ─────────────────────────────────────────
@pytest.fixture
def base(tmp_path):
    """A fake base interpreter folder: pythonw.exe and two DLLs."""
    folder = tmp_path / "base"
    folder.mkdir()
    (folder / "pythonw.exe").write_bytes(b"MZ exe")
    (folder / "python314.dll").write_bytes(b"dll one")
    (folder / "vcruntime140.dll").write_bytes(b"dll two")
    (folder / "LICENSE.txt").write_text("not a dll")
    return folder


class TestHostKey:
    def test_runtime_files(self, base):
        exe, dlls = wh.runtime_files(str(base))
        assert exe == str(base / "pythonw.exe")
        assert [os.path.basename(d) for d in dlls] == \
            ["python314.dll", "vcruntime140.dll"]

    def test_stable(self, base):
        exe, dlls = wh.runtime_files(str(base))
        assert wh.host_key("1.0", exe, dlls) == wh.host_key("1.0", exe, dlls)

    def test_changes_with_buddy_version(self, base):
        exe, dlls = wh.runtime_files(str(base))
        assert wh.host_key("1.0", exe, dlls) != wh.host_key("1.1", exe, dlls)

    def test_changes_when_python_is_upgraded(self, base):
        exe, dlls = wh.runtime_files(str(base))
        before = wh.host_key("1.0", exe, dlls)
        (base / "python314.dll").write_bytes(b"dll one, patched")
        assert wh.host_key("1.0", exe, dlls) != before


# ── ensure_host decisions ────────────────────────────────────────────
@pytest.fixture
def venv(tmp_path, base, monkeypatch):
    """Pretend we run from a venv on Windows whose base is `base`."""
    folder = tmp_path / "venv"
    folder.mkdir()
    (folder / "pyvenv.cfg").write_text(f"home = {base}\n")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "prefix", str(folder))
    monkeypatch.setattr(sys, "base_prefix", str(base))
    return folder


def current_folder(venv, base):
    exe, dlls = wh.runtime_files(str(base))
    return venv / (wh.HOST_DIR_PREFIX + wh.host_key(wh.__version__, exe,
                                                      dlls))


class TestEnsureHost:
    def test_none_off_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert wh.ensure_host() is None

    def test_none_outside_a_venv(self, venv, monkeypatch):
        monkeypatch.setattr(sys, "base_prefix", sys.prefix)
        assert wh.ensure_host() is None

    def test_none_without_pythonw(self, venv, base):
        (base / "pythonw.exe").unlink()
        assert wh.ensure_host() is None

    def test_builds_when_missing(self, venv, base, monkeypatch):
        built = []

        def fake_build(folder, source_exe, dlls):
            built.append(folder)
            os.makedirs(folder)
            open(os.path.join(folder, wh.HOST_EXE), "wb").close()

        monkeypatch.setattr(wh, "_build_host", fake_build)
        path = wh.ensure_host()
        expected = current_folder(venv, base)
        assert built == [str(expected)]
        assert path == str(expected / wh.HOST_EXE)

    def test_reuses_an_existing_host(self, venv, base, monkeypatch):
        folder = current_folder(venv, base)
        folder.mkdir()
        (folder / wh.HOST_EXE).write_bytes(b"MZ")
        monkeypatch.setattr(wh, "_build_host", pytest.fail)
        assert wh.ensure_host() == str(folder / wh.HOST_EXE)

    def test_build_failure_falls_back(self, venv, monkeypatch, capsys):
        def broken(*_a):
            raise OSError("access denied")
        monkeypatch.setattr(wh, "_build_host", broken)
        assert wh.ensure_host() is None
        assert "pythonw.exe" in capsys.readouterr().out

    def test_removes_old_hosts_but_keeps_current(self, venv, base):
        folder = current_folder(venv, base)
        folder.mkdir()
        (folder / wh.HOST_EXE).write_bytes(b"MZ")
        old = venv / (wh.HOST_DIR_PREFIX + "0123456789ab")
        old.mkdir()
        (old / wh.HOST_EXE).write_bytes(b"MZ")
        (old / "python314.dll").write_bytes(b"dll")
        unrelated = venv / "Lib"
        unrelated.mkdir()
        wh.ensure_host()
        assert folder.exists()
        assert not old.exists()
        assert unrelated.exists()

    def test_running_old_host_is_left_alone(self, venv, base, monkeypatch):
        folder = current_folder(venv, base)
        folder.mkdir()
        (folder / wh.HOST_EXE).write_bytes(b"MZ")
        old = venv / (wh.HOST_DIR_PREFIX + "0123456789ab")
        old.mkdir()
        (old / wh.HOST_EXE).write_bytes(b"MZ")
        (old / "python314.dll").write_bytes(b"dll")
        real_remove = os.remove

        def locked(path):
            if os.path.basename(path) == wh.HOST_EXE:
                raise PermissionError("in use")
            real_remove(path)

        monkeypatch.setattr(os, "remove", locked)
        wh.ensure_host()
        # The exe is locked, so its DLLs must not be touched either.
        assert (old / "python314.dll").exists()


class TestFacade:
    def test_exported(self):
        assert callable(plat.host_executable)

    def test_none_off_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert plat.host_executable() is None


# ── Startup entry from inside the host ───────────────────────────────
@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry")
class TestStartupExeFromHost:
    def test_finds_the_venv_launcher(self, tmp_path, monkeypatch):
        from clawd_buddy.platform import _windows
        scripts = tmp_path / "venv" / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "clawd-buddyw.exe").write_bytes(b"MZ")
        host = tmp_path / "venv" / "clawd-buddy-host-x"
        host.mkdir()
        monkeypatch.setattr(_windows.shutil, "which", lambda _n: None)
        monkeypatch.setattr(sys, "executable", str(host / wh.HOST_EXE))
        monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
        assert _windows._win_resolve_startup_exe() == \
            str(scripts / "clawd-buddyw.exe")

    def test_never_registers_the_interpreter(self, tmp_path, monkeypatch):
        # "clawd-buddy.exe" in the host folder is Clawd-Buddy.exe (names
        # are case-insensitive), i.e. Python itself. With no launcher on
        # PATH or in Scripts, the bare name is the only safe answer.
        from clawd_buddy.platform import _windows
        host = tmp_path / "venv" / "clawd-buddy-host-x"
        host.mkdir(parents=True)
        (host / wh.HOST_EXE).write_bytes(b"MZ")
        monkeypatch.setattr(_windows.shutil, "which", lambda _n: None)
        monkeypatch.setattr(sys, "executable", str(host / wh.HOST_EXE))
        monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
        assert _windows._win_resolve_startup_exe() == "clawd-buddy"

    def test_ignores_the_interpreter_on_path(self, tmp_path, monkeypatch):
        from clawd_buddy.platform import _windows
        host = tmp_path / "venv" / "clawd-buddy-host-x"
        host.mkdir(parents=True)
        exe = host / wh.HOST_EXE
        exe.write_bytes(b"MZ")
        scripts = tmp_path / "venv" / "Scripts"
        scripts.mkdir()
        (scripts / "clawd-buddyw.exe").write_bytes(b"MZ")
        monkeypatch.setattr(_windows.shutil, "which",
                            lambda n: str(host / "clawd-buddy.exe")
                            if n == "clawd-buddy" else None)
        monkeypatch.setattr(sys, "executable", str(exe))
        monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))
        assert _windows._win_resolve_startup_exe() == \
            str(scripts / "clawd-buddyw.exe")


# ── A real build (Windows, from a venv) ──────────────────────────────
def _version_string(path, name):
    import ctypes
    from ctypes import wintypes
    ver = ctypes.WinDLL("version")
    size = ver.GetFileVersionInfoSizeW(path, None)
    assert size, "no version resource"
    buf = ctypes.create_string_buffer(size)
    assert ver.GetFileVersionInfoW(path, 0, size, buf)
    value = ctypes.c_void_p()
    length = wintypes.UINT()
    query = f"\\StringFileInfo\\040904B0\\{name}"
    assert ver.VerQueryValueW(buf, query, ctypes.byref(value),
                              ctypes.byref(length))
    return ctypes.wstring_at(value.value, length.value).rstrip("\0")


@pytest.mark.skipif(sys.platform != "win32" or not wh.in_virtualenv(),
                    reason="builds a real exe from a venv's base Python")
class TestRealBuild:
    def test_task_manager_sees_clawd_buddy(self, tmp_path, monkeypatch):
        import site
        import clawd_buddy
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text(
            f"home = {sys.base_prefix}\n"
            "include-system-site-packages = false\n")
        # The fake venv has no packages of its own: lend it ours so the
        # build's start-up check can import the buddy.
        src = os.path.dirname(os.path.dirname(clawd_buddy.__file__))
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join(
            [src] + site.getsitepackages()))
        monkeypatch.setattr(sys, "prefix", str(venv))

        exe = wh.ensure_host()
        assert exe and os.path.exists(exe)
        assert os.path.basename(exe) == "Clawd-Buddy.exe"
        assert _version_string(exe, "FileDescription") == "Clawd Buddy"
        assert _version_string(exe, "ProductName") == "Clawd Buddy"

        kinds = [t for t, _n, _l in wh._existing_resources(
            exe, (wh.RT_VERSION, wh.RT_GROUP_ICON, 24))]
        assert kinds.count(wh.RT_VERSION) == 1
        assert kinds.count(wh.RT_GROUP_ICON) == 1
        assert 24 in kinds   # the manifest survives

        # A second launch reuses it rather than rebuilding.
        stamp = os.stat(exe).st_mtime_ns
        assert wh.ensure_host() == exe
        assert os.stat(exe).st_mtime_ns == stamp
