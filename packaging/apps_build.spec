# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Macro2k one-dir app.

Output (after ``build.ps1`` merges staging + vendor)::

    dist/Macro2k/
        Macro2k.exe      -> Hub (default) + Designer (--designer) + Runner (--runner)
        _macro2k/        -> private runtime files
        vendor/             -> adb / frida / tesseract (external, not bundled)

``vendor/`` is NOT bundled here (kept external/updatable). Web HTML assets ARE
bundled (``hub/`` + ``wf/`` + ``runner/`` — DevScope is not packaged). Neural OCR
backends (easyocr / paddle / torch) are excluded; only Tesseract.

Prefer ``build.ps1`` (handles staging + vendor). Raw build::

    pyinstaller --noconfirm --clean packaging/apps_build.spec
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = .../packaging
APPS = os.path.join(ROOT, "apps")

# --- app version → Windows .exe version resource -----------------------------
# Single source of truth is src/version.py; mirror it into the PE metadata so
# right-click → Properties → Details shows the version on the packaged .exe.
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from src.version import APP_NAME, __version__, version_tuple  # noqa: E402

_vt = (version_tuple() + (0, 0, 0, 0))[:4]  # pad to the 4 ints Windows wants
from PyInstaller.utils.win32.versioninfo import (  # noqa: E402
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct,
)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_vt, prodvers=_vt, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", APP_NAME),
            StringStruct("FileDescription", f"{APP_NAME} — desktop automation suite"),
            StringStruct("FileVersion", __version__),
            StringStruct("InternalName", APP_NAME),
            StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
            StringStruct("ProductName", APP_NAME),
            StringStruct("ProductVersion", __version__),
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

# pure-python-adb installs as the ``ppadb`` package; pull all submodules since
# clients/connections are imported dynamically.
hiddenimports += collect_submodules("ppadb")
hiddenimports += [
    "clr",            # pythonnet entry module
    "bottle",         # pywebview's local http server
    "proxy_tools",    # pywebview js-api proxy
    "pytesseract",    # OCR (calls the vendored tesseract.exe)
]

# --- bundled web assets (hub + designer + runner; no DevScope) ---------------
# Under apps/web: hub/, wf/, and runner/ are needed for Macro2k.
_web_src = os.path.join(ROOT, "apps", "web")
web_datas = [
    (os.path.join(_web_src, "hub"), os.path.join("web", "hub")),
    (os.path.join(_web_src, "wf"), os.path.join("web", "wf")),
    (os.path.join(_web_src, "runner"), os.path.join("web", "runner")),
]

# --- exclude the world we don't ship -----------------------------------------
excludes = [
    "PySide6", "shiboken6", "PyQt5", "PyQt6", "qtawesome",
    "torch", "torchvision", "torchaudio",
    "easyocr", "paddle", "paddleocr", "paddlepaddle",
    "scipy", "matplotlib", "pandas", "sympy", "sklearn", "skimage",
    "tkinter", "IPython", "notebook", "jupyter", "pytest",
]

_common = dict(
    pathex=[ROOT, APPS],
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=excludes,
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)

# ── Macro2k.exe (Hub + Designer + Runner) ────────────────────────────────
a_designer = Analysis(
    [os.path.join(ROOT, "packaging", "entry_designer.py")],
    datas=datas + web_datas,
    **_common,
)
pyz_designer = PYZ(a_designer.pure)
exe_designer = EXE(
    pyz_designer, a_designer.scripts, [],
    exclude_binaries=True, name="Macro2k",
    console=False, disable_windowed_traceback=False,
    contents_directory="_macro2k",
    version=version_info,
)
coll_designer = COLLECT(
    exe_designer, a_designer.binaries, a_designer.datas,
    name="Macro2k",
)
