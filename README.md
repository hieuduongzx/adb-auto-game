# ADB auto-game

Internal tool suite for Android (emulator/device) automation on Windows.

| App | Role | Run (source) |
|-----|------|----------------|
| **Workflow2k Hub** | Dashboard: list / run / edit / create workflows | `python apps/workflow_hub.py` |
| **Workflow2k Designer** | Node-graph workflow editor | `python apps/workflow_designer.py [flow.json]` |
| **Workflow2k Runner** | Load JSON flow & run | `python apps/workflow_runner.py [flow.json]` |
| **DevScope** | Device inspector / crop templates | `python apps/devscope.py` |

Also: `run_hub.bat`, `run_designer.bat` / `run_designer_admin.bat` (Admin needed when the game window is elevated).

Frozen exe modes: `Workflow2k.exe` (hub), `--designer [flow]`, `--runner [flow]`.

## Layout

```
apps/           Product apps + web UI (hub / wf / runner / scope)
src/            Library: ADB core, OCR, Win32, workflow engine, utils
workflows/      User flows: <Name>/*.json + templates/
data/           Runtime settings (gitignored machine-local files)
packaging/      PyInstaller → dist/Workflow2k/
vendor/         adb / scrcpy / frida / tesseract binaries
```

## Setup

```powershell
pip install -r requirements.txt
# Optional OCR:  pip install easyocr
#                 pip install paddlepaddle paddleocr
```

Place binaries under `vendor/` as needed (`adb`, `scrcpy`, `tesseract`; `frida` / `scrcpy` may be local-only — see `.gitignore`).

## Build (Workflow2k only)

```powershell
pwsh packaging/build.ps1
# code-only rebuild:
pwsh packaging/build.ps1 -SkipVendor
```

Output: `dist/Workflow2k/Workflow2k.exe` (+ shared `vendor/`).  
DevScope is **source-only** in the default packaging.

## Docs

- Product / UI principles: [`PRODUCT.md`](PRODUCT.md)
- Packaging details: [`packaging/README.md`](packaging/README.md)
