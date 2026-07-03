# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec building two one-dir tools for ADB auto-game.

This spec emits two staging folders (one per tool); ``build.ps1`` then merges
them into a single shared folder::

    dist/Workflow2k/
        Workflow2k.exe      -> Workflow Designer (+ Runner via --runner)
        DevScope.exe        -> Dev / device inspector tool
        _workflow2k/        -> Workflow2k's private runtime files
        _devscope/          -> DevScope's private runtime files
        vendor/             -> shared adb / frida / tesseract (one copy)

Each EXE uses a distinct ``contents_directory`` so the two can live in one
folder without colliding. Both resolve their writable root (vendor/, data/,
out/) to the folder they sit in, so a single ``vendor/`` serves both — it is
NOT bundled here (kept external/updatable). Web HTML assets ARE bundled.
Neural OCR backends (easyocr / paddle / torch) are excluded; only Tesseract.

Prefer ``build.ps1`` (handles staging + merge + vendor). Raw build::

    pyinstaller --noconfirm --clean packaging/tools_build.spec
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = .../packaging
TOOLS = os.path.join(ROOT, "tools")

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

# pure-python-adb installs as the ``ppadb`` package; pull all submodules since
# clients/connections are imported dynamically.
hiddenimports += collect_submodules("ppadb")
hiddenimports += [
    "clr",            # pythonnet entry module
    "bottle",         # pywebview's local http server
    "proxy_tools",    # pywebview js-api proxy
    "pytesseract",    # OCR (calls the vendored tesseract.exe)
]

# --- bundled web assets ------------------------------------------------------
# (source folder, destination relative to the bundle root)
# ``tools/web`` holds every tool's HTML/JS/CSS — wf/ (designer), runner/, scope/.
web_tools = (os.path.join(ROOT, "tools", "web"), "web")

# --- exclude the world we don't ship -----------------------------------------
excludes = [
    "PySide6", "shiboken6", "PyQt5", "PyQt6", "qtawesome",
    "torch", "torchvision", "torchaudio",
    "easyocr", "paddle", "paddleocr", "paddlepaddle",
    "scipy", "matplotlib", "pandas", "sympy", "sklearn", "skimage",
    "tkinter", "IPython", "notebook", "jupyter", "pytest",
]

_common = dict(
    pathex=[ROOT, TOOLS],
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=excludes,
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)

# ── Workflow2k.exe (Workflow Designer + Runner) ──────────────────────────────
a_designer = Analysis(
    [os.path.join(ROOT, "packaging", "entry_designer.py")],
    datas=datas + [web_tools],
    **_common,
)
pyz_designer = PYZ(a_designer.pure)
exe_designer = EXE(
    pyz_designer, a_designer.scripts, [],
    exclude_binaries=True, name="Workflow2k",
    console=False, disable_windowed_traceback=False,
    contents_directory="_workflow2k",   # distinct so both tools share one folder
)
coll_designer = COLLECT(
    exe_designer, a_designer.binaries, a_designer.datas,
    name="Workflow2k",
)

# ── DevScope.exe ─────────────────────────────────────────────────────────────
a_devhelper = Analysis(
    [os.path.join(ROOT, "packaging", "entry_devhelper.py")],
    datas=datas + [web_tools],
    **_common,
)
pyz_devhelper = PYZ(a_devhelper.pure)
exe_devhelper = EXE(
    pyz_devhelper, a_devhelper.scripts, [],
    exclude_binaries=True, name="DevScope",
    console=False, disable_windowed_traceback=False,
    contents_directory="_devscope",   # distinct so both tools share one folder
)
coll_devhelper = COLLECT(
    exe_devhelper, a_devhelper.binaries, a_devhelper.datas,
    name="DevScope",
)
