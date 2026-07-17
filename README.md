# ADB auto-game

Internal tool suite for Android (emulator/device) automation on Windows.

| App | Role | Run (source) |
|-----|------|----------------|
| **Macro2k Hub** | Dashboard: list / run / edit / create workflows | `python apps/workflow_hub.py` |
| **Macro2k Designer** | Node-graph workflow editor | `python apps/workflow_designer.py [flow.json]` |
| **Macro2k Runner** | Load JSON flow & run | `python apps/workflow_runner.py [flow.json]` |
| **DevScope** | Device inspector / crop templates | `python apps/devscope.py` |

Also: `run_hub.bat`, `run_designer.bat` / `run_designer_admin.bat` (Admin needed when the game window is elevated).

Frozen exe modes: `Macro2k.exe` (hub), `--designer [flow]`, `--runner [flow]`.

## Layout

```
apps/           Product apps + web UI (hub / wf / runner / scope)
src/            Library: ADB core, OCR, Win32, workflow engine, utils
workflows/      User flows: <Name>/*.json + templates/
autoclicks/     Saved Auto Click sequences (*.json)
data/           Runtime settings (gitignored machine-local files)
packaging/      PyInstaller → dist/Macro2k/
vendor/         adb / scrcpy / frida / tesseract binaries
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
# Optional OCR:  pip install easyocr
#                 pip install paddlepaddle paddleocr
```

Use the project virtual environment instead of a shared Python installation.
The obsolete third-party `scrcpy-client` package pins `av<10` and conflicts with
Macro2k's direct PyAV capture implementation (`av>=10`); Macro2k does not use or
require that package.

Place binaries under `vendor/` as needed (`adb`, `scrcpy`, `tesseract`; `frida` / `scrcpy` may be local-only — see `.gitignore`).

## Quality checks

The regression suite uses the standard library, so it does not require an
extra test runner:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q src apps packaging
```

JavaScript files can be syntax-checked with Node.js:

```powershell
Get-ChildItem apps/web -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

## Build (Macro2k only)

```powershell
pwsh packaging/build.ps1
# code-only rebuild:
pwsh packaging/build.ps1 -SkipVendor
```

Output: `dist/Macro2k/Macro2k.exe` (+ shared `vendor/`).
DevScope is **source-only** in the default packaging.

## Docs

- Product / UI principles: [`PRODUCT.md`](PRODUCT.md)
- Packaging details: [`packaging/README.md`](packaging/README.md)
