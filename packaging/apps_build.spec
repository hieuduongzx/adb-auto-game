# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Workflow2k one-dir app.

Output (after ``build.ps1`` merges staging + vendor)::

    dist/Workflow2k/
        Workflow2k.exe      -> Hub (default) + Designer (--designer) + Runner (--runner)
        _workflow2k/        -> private runtime files
        vendor/             -> adb / frida / tesseract (external, not bundled)

``vendor/`` is NOT bundled here (kept external/updatable). Web HTML assets ARE
bundled (``hub/`` + ``wf/`` + ``runner/`` — DevScope is not packaged). Neural OCR
backends (easyocr / paddle / torch) are excluded; only Tesseract.

Prefer ``build.ps1`` (handles staging + vendor). Raw build::

    pyinstaller --noconfirm --clean packaging/apps_build.spec
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.dirname(SPECPATH)  # SPECPATH = .../packaging
APPS = os.path.join(ROOT, "apps")

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
# Under apps/web: hub/, wf/, and runner/ are needed for Workflow2k.
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

# ── Workflow2k.exe (Hub + Designer + Runner) ────────────────────────────────
a_designer = Analysis(
    [os.path.join(ROOT, "packaging", "entry_designer.py")],
    datas=datas + web_datas,
    **_common,
)
pyz_designer = PYZ(a_designer.pure)
exe_designer = EXE(
    pyz_designer, a_designer.scripts, [],
    exclude_binaries=True, name="Workflow2k",
    console=False, disable_windowed_traceback=False,
    contents_directory="_workflow2k",
)
coll_designer = COLLECT(
    exe_designer, a_designer.binaries, a_designer.datas,
    name="Workflow2k",
)
