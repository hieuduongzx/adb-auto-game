"""Paths, constants and helpers shared by the Runner's API mixins (apps/runner/*)."""
from __future__ import annotations

import os
import sys

from src.utils import (
    bundle_dir,
    data_root,
    is_frozen,
    log_warning,
    titled,
)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

# In a frozen build, writable resources (data/) live under data_root() — next to
# the app when writable, else %LOCALAPPDATA% (read-only Program Files install).
if is_frozen():
    _PROJECT_ROOT = data_root()

# Bundled HTML: ``apps/web`` from source, ``<_MEIPASS>/web`` when frozen.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))

# Node params that hold a machine-specific absolute path. Each one found in a
# loaded flow becomes a runner control (and is remembered in the runner config),
# so a built .exe can be re-pointed on another PC without editing the JSON.
RUNTIME_PATH_PARAMS = ("path", "apk")

# PC-side emulator nodes whose install folder comes from the shared project
# emulator setting (Runner Settings → Emulator) unless the node picks "Custom".
# Their path is therefore NOT offered as a per-activity control.
EMULATOR_NODE_TYPES = frozenset({
    "launch_emulator", "resize_emulator", "kill_emulator",
    "restart_emulator", "emulator_resolution",
})

# Families the shared emulator setting can name (a node may still use a custom
# command locally, but the project setting only carries a known family).
EMULATOR_KINDS = ("ldplayer", "mumu", "nox", "memu", "bluestacks")

# Game requirements — files the player copies into the game's install folder.
# A built Runner ships them as <exe folder>/requirements/ (packaging/build_runner.py
# copies the workflow's vendor/ there); from source they are the workflow's vendor/.
REQUIREMENTS_DIR = "requirements"
REQUIREMENTS_SRC = "vendor"
REQUIREMENTS_SKIP = (".gitkeep", "Thumbs.db", "desktop.ini", ".DS_Store")


def _copy_tree_elevated(src: str, dst: str) -> bool:
    """Copy ``src``'s contents into ``dst`` through an elevated robocopy.

    Game folders often live under Program Files, where a normal copy is refused.
    This launches robocopy with the ``runas`` verb (one UAC prompt) and waits for
    it, so the files land with admin rights. Returns True when the copy finished
    with robocopy's success exit codes (0–7). No-op off Windows."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False

    skip = " ".join(f'"{name}"' for name in REQUIREMENTS_SKIP)
    params = (f'"{os.path.abspath(src)}" "{os.path.abspath(dst)}" '
              f'/E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XF {skip}')

    class _SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "robocopy.exe"
    info.lpParameters = params
    info.nShow = SW_HIDE
    try:
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            return False
    except Exception as exc:
        log_warning(f"Elevation failed: {exc}")
        return False
    if not info.hProcess:
        return False
    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return int(code.value) < 8
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)


def runner_title(name: str = "", version: str = "") -> str:
    """Window title: the game (workflow) name as a Runner, then the version —
    "BrownDust2 Runner 1.0.39". No workflow yet → "Macro2k Runner <suite>"."""
    name = str(name or "").strip()
    if not name:
        return titled("Macro2k Runner")
    base = name if name.lower().endswith("runner") else f"{name} Runner"
    return f"{base} {version}".strip()
