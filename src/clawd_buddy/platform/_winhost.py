# Copyright (c) 2026 Ramy Ezzat
# Licensed under the MIT License — see LICENSE in the project root.

"""Windows: run the buddy as "Clawd Buddy.exe" instead of pythonw.exe.

Task Manager names a process after its executable: the Processes tab
shows the file description from the exe's version resource ("Python")
and the Details tab shows the image name ("pythonw.exe"). So without
help, the buddy is indistinguishable from any other Python program.

The fix is to give it its own executable. `ensure_host()` copies the
base interpreter's `pythonw.exe` (plus the DLLs it loads at start-up)
into a folder directly inside the buddy's virtual environment, names
the copy `Clawd Buddy.exe`, and rewrites its version resource and icon
so Task Manager shows "Clawd Buddy" with the buddy's face. Because the
folder sits one level below the venv, the copy finds the venv's
`pyvenv.cfg` exactly like the venv's own launcher does, so it gets the
same standard library and site-packages.

The host is rebuilt only when something it was built from changes (the
buddy's version, the interpreter or its DLLs): each build lives in a
folder named after a hash of those inputs, so a newer build never has
to overwrite an exe that a running buddy has locked. Every build is
checked by importing `clawd_buddy` with it before it's used, and any
failure along the way returns None so the caller falls back to plain
pythonw.exe. See
.ai/decisions/2026-11-04-windows-process-name.md for the trade-offs.

The resource builders (`build_version_resource`, `icon_resources`,
`host_key`) are pure and run on any OS so they can be unit-tested; only
`_update_resources` and `ensure_host` touch Win32.
"""

import hashlib
import os
import shutil
import struct
import subprocess
import sys

from .. import __version__

HOST_NAME = "Clawd Buddy"
HOST_EXE = HOST_NAME + ".exe"
HOST_DIR_PREFIX = "clawd-buddy-host-"
# Bump when the way a host is built changes, so existing hosts rebuild.
HOST_FORMAT = 1

# Resource types (winuser.h).
RT_ICON = 3
RT_GROUP_ICON = 14
RT_VERSION = 16
LANG_EN_US = 0x0409
CODEPAGE_UNICODE = 1200

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


# ── Version resource ─────────────────────────────────────────────────
def version_tuple(version):
    """'0.1.25' → (0, 1, 25, 0). Non-numeric parts ('dev1', 'rc2') are
    dropped and missing ones are zero, since a version resource holds
    exactly four 16-bit numbers."""
    parts = []
    for piece in str(version).split("."):
        digits = ""
        for ch in piece:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(min(int(digits), 0xFFFF))
    parts = (parts + [0, 0, 0, 0])[:4]
    return tuple(parts)


def _node(key, value=b"", value_len=0, wtype=0, children=()):
    """One VS_VERSIONINFO-style block: wLength, wValueLength, wType, the
    key as a NUL-terminated UTF-16 string, then the value and each child
    starting on a 32-bit boundary (blocks themselves start on one, so
    offsets within the block are enough)."""
    data = bytearray(6)   # header, filled in once the length is known
    data += (key + "\0").encode("utf-16-le")
    data += b"\0" * (-len(data) % 4)
    data += value
    for child in children:
        data += b"\0" * (-len(data) % 4)
        data += child
    struct.pack_into("<HHH", data, 0, len(data), value_len, wtype)
    return bytes(data)


def _string(key, text):
    value = (text + "\0").encode("utf-16-le")
    return _node(key, value, value_len=len(text) + 1, wtype=1)


def build_version_resource(version, strings):
    """Return the bytes of an RT_VERSION resource: a VS_FIXEDFILEINFO
    carrying `version` plus an en-US/Unicode string table of `strings`
    (an ordered mapping such as {"FileDescription": "Clawd Buddy"})."""
    a, b, c, d = version_tuple(version)
    ms, ls = (a << 16) | b, (c << 16) | d
    fixed = struct.pack(
        "<13I",
        0xFEEF04BD,   # dwSignature
        0x00010000,   # dwStrucVersion
        ms, ls,       # file version
        ms, ls,       # product version
        0x3F,         # dwFileFlagsMask
        0,            # dwFileFlags
        0x00040004,   # dwFileOS: VOS_NT_WINDOWS32
        1,            # dwFileType: VFT_APP
        0,            # dwFileSubtype
        0, 0,         # dwFileDate
    )
    table = _node(f"{LANG_EN_US:04X}{CODEPAGE_UNICODE:04X}", wtype=1,
                  children=[_string(k, v) for k, v in strings.items()])
    string_info = _node("StringFileInfo", wtype=1, children=[table])
    translation = _node("Translation",
                        struct.pack("<HH", LANG_EN_US, CODEPAGE_UNICODE),
                        value_len=4)
    var_info = _node("VarFileInfo", wtype=1, children=[translation])
    return _node("VS_VERSION_INFO", fixed, value_len=len(fixed),
                 children=[string_info, var_info])


def host_strings(version):
    """The text Task Manager and Explorer show for the host exe. The
    comment says plainly what the file is, for anyone who finds it."""
    py = ".".join(str(n) for n in sys.version_info[:3])
    return {
        "CompanyName": "Clawd Buddy",
        "FileDescription": HOST_NAME,
        "FileVersion": str(version),
        "InternalName": "clawd-buddy",
        "OriginalFilename": HOST_EXE,
        "ProductName": HOST_NAME,
        "ProductVersion": str(version),
        "Comments": (f"Python {py} (pythonw.exe), renamed so the running "
                     "Clawd Buddy is easy to spot. Safe to delete; it is "
                     "rebuilt when needed."),
    }


# ── Icon resources ───────────────────────────────────────────────────
def icon_resources(ico_bytes, first_id=1):
    """Split a .ico file into what an exe stores: the images as RT_ICON
    resources and an RT_GROUP_ICON directory that points at them by id.
    Returns (group_bytes, [(icon_id, image_bytes), ...])."""
    reserved, kind, count = struct.unpack_from("<HHH", ico_bytes, 0)
    if reserved != 0 or kind != 1 or count == 0:
        raise ValueError("not an icon file")
    group = struct.pack("<HHH", 0, 1, count)
    images = []
    for i in range(count):
        (w, h, colors, _res, planes, bits,
         size, offset) = struct.unpack_from("<BBBBHHII", ico_bytes, 6 + 16 * i)
        data = ico_bytes[offset:offset + size]
        if len(data) != size:
            raise ValueError("truncated icon image")
        icon_id = first_id + i
        # Pillow leaves planes at 0 for PNG images; Windows expects 1.
        group += struct.pack("<BBBBHHIH", w, h, colors, 0,
                             planes or 1, bits or 32, size, icon_id)
        images.append((icon_id, data))
    return group, images


def buddy_icon_ico():
    """The buddy's face as .ico bytes, at the sizes Windows asks for."""
    import io
    from ..ui.about import _make_buddy_icon_image
    buf = io.BytesIO()
    _make_buddy_icon_image(256).save(
        buf, format="ICO", sizes=[(s, s) for s in ICON_SIZES])
    return buf.getvalue()


# ── Where the host lives and when it's stale ─────────────────────────
def _file_fingerprint(path):
    st = os.stat(path)
    return f"{os.path.basename(path).lower()}:{st.st_size}:{st.st_mtime_ns}"


def runtime_files(base_dir):
    """The interpreter and the DLLs next to it that it loads at start-up
    (python3XX.dll, python3.dll, the VC runtime). Everything else in the
    standard library is found through pyvenv.cfg's `home`."""
    exe = os.path.join(base_dir, "pythonw.exe")
    dlls = sorted(
        os.path.join(base_dir, name) for name in os.listdir(base_dir)
        if name.lower().endswith(".dll"))
    return exe, dlls


def host_key(version, source_exe, dlls):
    """Short hash of everything a host is built from. A change to any of
    them (an upgrade of the buddy or of Python) gives a new folder."""
    parts = [str(HOST_FORMAT), str(version), _file_fingerprint(source_exe)]
    parts += [_file_fingerprint(p) for p in dlls]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def in_virtualenv():
    return os.path.normcase(os.path.abspath(sys.prefix)) != \
        os.path.normcase(os.path.abspath(sys.base_prefix))


# ── Win32 resource editing ───────────────────────────────────────────
def _win32():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ptr = ctypes.c_void_p
    k32.LoadLibraryExW.argtypes = [wintypes.LPCWSTR, wintypes.HANDLE,
                                   wintypes.DWORD]
    k32.LoadLibraryExW.restype = wintypes.HMODULE
    k32.FreeLibrary.argtypes = [wintypes.HMODULE]
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ptr, ptr,
                                    wintypes.WORD, ptr, wintypes.DWORD]
    k32.UpdateResourceW.restype = wintypes.BOOL
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    k32.EndUpdateResourceW.restype = wintypes.BOOL
    names_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ptr,
                                    ptr, ptr)
    langs_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMODULE, ptr,
                                    ptr, wintypes.WORD, ptr)
    k32.EnumResourceNamesW.argtypes = [wintypes.HMODULE, ptr, names_proc,
                                       ptr]
    k32.EnumResourceLanguagesW.argtypes = [wintypes.HMODULE, ptr, ptr,
                                           langs_proc, ptr]
    return ctypes, k32, names_proc, langs_proc


def _existing_resources(path, types):
    """[(type, name, lang), ...] for every resource of `types` in the
    file. `name` is an int id or a str."""
    ctypes, k32, names_proc, langs_proc = _win32()
    LOAD_AS_DATAFILE = 0x00000002 | 0x00000020   # | AS_IMAGE_RESOURCE
    module = k32.LoadLibraryExW(path, None, LOAD_AS_DATAFILE)
    if not module:
        raise ctypes.WinError(ctypes.get_last_error())
    found = []
    try:
        for rtype in types:
            names = []

            def on_name(_h, _t, name, _p, names=names):
                value = name or 0
                names.append(value if value <= 0xFFFF
                             else ctypes.wstring_at(value))
                return True

            k32.EnumResourceNamesW(module, rtype, names_proc(on_name), None)
            for name in names:
                name_arg = name if isinstance(name, int) \
                    else ctypes.c_wchar_p(name)

                def on_lang(_h, _t, _n, lang, _p, name=name):
                    found.append((rtype, name, lang))
                    return True

                k32.EnumResourceLanguagesW(module, rtype, name_arg,
                                           langs_proc(on_lang), None)
    finally:
        k32.FreeLibrary(module)
    return found


def _update_resources(path, version_blob, group_icon, icons):
    """Replace the version resource and icons of the exe at `path`,
    leaving everything else (notably its manifest) alone."""
    ctypes, k32, _np, _lp = _win32()
    old = _existing_resources(path, (RT_VERSION, RT_GROUP_ICON, RT_ICON))
    version_lang = next((lang for t, _n, lang in old if t == RT_VERSION),
                        LANG_EN_US)
    icon_lang = next((lang for t, _n, lang in old if t == RT_GROUP_ICON),
                     LANG_EN_US)
    handle = k32.BeginUpdateResourceW(path, False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    keep = []   # buffers must outlive EndUpdateResourceW

    def put(rtype, name, lang, data):
        if isinstance(name, str):
            name = ctypes.c_wchar_p(name)
            keep.append(name)
        buf = None
        if data is not None:
            buf = ctypes.create_string_buffer(data, len(data))
            keep.append(buf)
        if not k32.UpdateResourceW(handle, rtype, name, lang, buf,
                                   0 if data is None else len(data)):
            raise ctypes.WinError(ctypes.get_last_error())

    try:
        for rtype, name, lang in old:
            put(rtype, name, lang, None)   # delete
        put(RT_VERSION, 1, version_lang, version_blob)
        for icon_id, data in icons:
            put(RT_ICON, icon_id, icon_lang, data)
        put(RT_GROUP_ICON, 1, icon_lang, group_icon)
    except Exception:
        k32.EndUpdateResourceW(handle, True)   # discard
        raise
    if not k32.EndUpdateResourceW(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


# ── Building and finding the host ────────────────────────────────────
def _host_works(exe):
    """Run the new exe once: it must start, find the venv's packages and
    import the buddy. Catches anything the copy or the resource edit
    broke before a user ever launches it."""
    env = dict(os.environ)
    env.pop("__PYVENV_LAUNCHER__", None)
    try:
        done = subprocess.run(
            [exe, "-c", "import clawd_buddy, pygame, pystray"],
            env=env, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _remove_old_hosts(venv, current):
    """Delete hosts from earlier versions. One that's still running has
    its exe locked; removing the exe fails and the folder is left for
    next time, so a running buddy never loses its DLLs."""
    for name in os.listdir(venv):
        if not name.startswith(HOST_DIR_PREFIX) or name == current:
            continue
        folder = os.path.join(venv, name)
        try:
            exe = os.path.join(folder, HOST_EXE)
            if os.path.exists(exe):
                os.remove(exe)
            shutil.rmtree(folder)
        except OSError:
            pass


def _build_host(folder, source_exe, dlls):
    tmp = folder + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        exe = os.path.join(tmp, HOST_EXE)
        shutil.copy2(source_exe, exe)
        for dll in dlls:
            shutil.copy2(dll, tmp)
        group, icons = icon_resources(buddy_icon_ico())
        _update_resources(
            exe, build_version_resource(__version__,
                                        host_strings(__version__)),
            group, icons)
        if not _host_works(exe):
            raise RuntimeError("the renamed interpreter didn't start")
        shutil.rmtree(folder, ignore_errors=True)   # a half-deleted one
        os.replace(tmp, folder)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ensure_host():
    """Return the path of `Clawd Buddy.exe` for this install, building
    it first if needed, or None to launch with pythonw.exe as before.

    Only for venv installs (uv tool, pipx, a dev venv): the host has to
    sit inside a venv to find its packages. Never raises.
    """
    if sys.platform != "win32" or not in_virtualenv():
        return None
    try:
        source_exe, dlls = runtime_files(sys.base_prefix)
        if not os.path.exists(source_exe) or not dlls:
            return None
        venv = sys.prefix
        current = HOST_DIR_PREFIX + host_key(__version__, source_exe, dlls)
        folder = os.path.join(venv, current)
        exe = os.path.join(folder, HOST_EXE)
        if not os.path.exists(exe):
            _build_host(folder, source_exe, dlls)
            print(f"[buddy] Prepared {exe}")
        _remove_old_hosts(venv, current)
        return exe
    except Exception as e:   # read-only venv, Store Python, AV lock, …
        print(f"[buddy] Running as pythonw.exe ({HOST_EXE} unavailable: "
              f"{e})")
        return None
