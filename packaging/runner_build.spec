# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a **single-workflow Runner** build.

This is the lean sibling of ``apps_build.spec``. It ships ONE workflow and the
Runner only — no Hub, no Designer, no DevScope. Output (after
``build_runner.py`` copies the trimmed vendor tree)::

    dist/<Name>-Runner/
        <Name>.exe        -> Runner GUI, auto-loads the bundled workflow
        _internal/        -> private runtime files
        vendor/            -> only the pieces this workflow needs (external)
        workflow/          -> workflow.json + templates/  (bundled into the exe)

Driven by a build-config JSON whose path is passed in the
``MACRO2K_RUNNER_BUILD_CFG`` environment variable (written by
``packaging/build_runner.py``)::

    {
      "root": "A:/.../adb-auto-game",   # project root
      "workflow_dir": "A:/.../workflows/BrownDust2",
      "app_name": "BrownDust2",         # exe basename (sanitized)
      "version": "1.0.0"                # -> Windows version resource
    }

Prefer ``build_runner.py`` (handles the cfg + vendor). Raw build::

    set MACRO2K_RUNNER_BUILD_CFG=C:\\path\\cfg.json
    pyinstaller --noconfirm --clean packaging/runner_build.spec
"""
import json
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = .../packaging

# --- read the per-workflow build config --------------------------------------
_cfg_path = os.environ.get("MACRO2K_RUNNER_BUILD_CFG", "")
if not _cfg_path or not os.path.isfile(_cfg_path):
    raise SystemExit(
        "runner_build.spec: set MACRO2K_RUNNER_BUILD_CFG to a build-config JSON "
        "(use packaging/build_runner.py)."
    )
with open(_cfg_path, "r", encoding="utf-8") as _fh:
    CFG = json.load(_fh)

APP_NAME = str(CFG.get("app_name") or "Workflow").strip() or "Workflow"
WORKFLOW_DIR = os.path.abspath(CFG["workflow_dir"])
if not os.path.isdir(WORKFLOW_DIR):
    raise SystemExit(f"runner_build.spec: workflow_dir not found: {WORKFLOW_DIR}")
VERSION = str(CFG.get("version") or "1.0.0").strip() or "1.0.0"
# PyAV (ffmpeg, ~65 MB) is only needed for the scrcpy H.264 capture source. When
# this workflow doesn't use scrcpy, drop it — the import is guarded and capture
# falls back to ADB screencap anyway.
INCLUDE_AV = bool(CFG.get("include_av", True))

# --- version string -> Windows PE version resource ---------------------------
def _ver_tuple(text):
    nums = []
    for part in text.replace("-", ".").split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return (tuple(nums) + (0, 0, 0, 0))[:4]

_vt = _ver_tuple(VERSION)
from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_vt, prodvers=_vt, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Macro2k"),
            StringStruct("FileDescription", f"{APP_NAME} — automation runner"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", APP_NAME),
            StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
            StringStruct("ProductName", APP_NAME),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x409, 1200])]),
    ],
)

# --- third-party collection (pywebview EdgeChromium backend via pythonnet) ---
datas = []
binaries = []
hiddenimports = []
for _pkg in ("webview", "clr_loader", "pythonnet"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass

hiddenimports += collect_submodules("ppadb")
hiddenimports += [
    "clr",            # pythonnet entry module
    "bottle",         # pywebview's local http server
    "proxy_tools",    # pywebview js-api proxy
    "pytesseract",    # OCR (calls the vendored tesseract.exe)
]

# --- bundled assets: runner web UI + the one workflow ------------------------
# Only web/runner is needed (no hub/, no wf/ designer). The workflow folder is
# bundled read-only under "workflow/"; the Runner writes its own config to
# data_root() so this copy just supplies the graph + template images.
_web_src = os.path.join(ROOT, "apps", "web")
extra_datas = [
    (os.path.join(_web_src, "shared"), os.path.join("web", "shared")),
    (os.path.join(_web_src, "runner"), os.path.join("web", "runner")),
    (WORKFLOW_DIR, "workflow"),
]

# --- exclude the world we don't ship -----------------------------------------
# On top of the shared exclusions, drop the designer/hub-only heavy deps: the
# runner never opens the graph editor, so OpenCV/numpy still ship (the engine
# needs them) but the neural OCR + Qt worlds do not.
excludes = [
    "PySide6", "shiboken6", "PyQt5", "PyQt6", "qtawesome",
    "torch", "torchvision", "torchaudio",
    "easyocr", "paddle", "paddleocr", "paddlepaddle",
    "scipy", "matplotlib", "pandas", "sympy", "sklearn", "skimage",
    "tkinter", "IPython", "notebook", "jupyter", "pytest",
]
if not INCLUDE_AV:
    excludes.append("av")   # ~65 MB of ffmpeg libs — only scrcpy capture needs it

a = Analysis(
    [os.path.join(ROOT, "packaging", "entry_runner_single.py")],
    pathex=[ROOT, os.path.join(ROOT, "apps")],
    binaries=binaries,
    datas=datas + extra_datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True, name=APP_NAME,
    console=False, disable_windowed_traceback=False,
    contents_directory="_internal",
    version=version_info,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name=f"{APP_NAME}-Runner",
)
