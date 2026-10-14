# ADB auto-game

Internal tool suite for Android (emulator/device) automation on Windows.

| App | Role | Run (source) |
|-----|------|----------------|
| **Macro2k Hub** | Dashboard: list / run / edit / create workflows | `python apps/workflow_hub.py` |
| **Macro2k Designer** | Node-graph workflow editor | `python apps/workflow_designer.py [flow.json]` |
| **Macro2k Runner** | Load JSON flow & run | `python apps/workflow_runner.py [flow.json]` |
| **DevScope** | Device inspector / crop templates | `python apps/devscope.py` |

Also: `run_hub.bat`, `run_designer.bat` (launchers stay at the repo root; they prefer `.venv`).

Frozen exe modes: `Macro2k.exe` (hub), `--designer [flow]`, `--runner [flow]`.

## Layout

```
apps/           Product apps + web UI (hub / wf / runner / scope) and the ADB CLI
  designer/     The Designer's Python API, one mixin per area (preview, library…)
  runner/       The Runner's Python API, likewise (outcome, state, controls…)
src/            Library: ADB, Win32, workflow engine, updater, utils
  workflow/     engine.py (load, run, graph walk) + catalog.py + nodes/ handlers
workflows/      Game projects: <Name>/*.json + templates/ + assets/
assets/         Bundled models (PP-OCRv5 Mobile)
docs/           Product notes and design specs
packaging/      PyInstaller, installer, app icon
vendor/         adb / scrcpy / frida / unity bridge
data/           Runtime settings (gitignored, machine-local)
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
# OCR runtime:   ONNX Runtime; the official PP-OCRv5 Mobile model is bundled
```

Use the project virtual environment instead of a shared Python installation.
The obsolete third-party `scrcpy-client` package pins `av<10` and conflicts with
Macro2k's direct PyAV capture implementation (`av>=10`); Macro2k does not use or
require that package.

OCR is recognition-only because workflow nodes already provide a cropped text
region. `assets/ocr/ppocr_v5_mobile/` contains the official PaddlePaddle ONNX
graph, dictionary, and manifest, so source runs and packaged Runners work
offline. The selector remains registry-driven for future recognition models.

Place binaries under `vendor/` as needed (`adb`, `scrcpy`, `frida`; some tools may be local-only — see `.gitignore`).

## Quality checks

The suite mixes unittest classes and pytest-style functions, so run it with
pytest (`unittest discover` would silently skip the pytest functions):

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
python -m ruff check .            # defects only — see ruff.toml
python -m compileall -q src apps packaging
```

JavaScript files can be syntax-checked with Node.js:

```powershell
Get-ChildItem apps/web -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }
```

Every JavaScript regression suite (Designer geometry, Hub layout, Runner
state, …):

```powershell
Get-ChildItem tests -Filter *.cjs | ForEach-Object { node --test $_.FullName }
```

### Looking at the UI

`tools/shoot_ui.py` opens the Hub, Runner, Designer and DevScope in headless
Edge against their **real** Python APIs (read-only: anything that would run a
workflow, write a file, touch a device or the network is refused) and saves a
screenshot of every scene — main views, dialogs, popovers, menus, a live run —
in both themes. It needs Playwright with the Edge channel, like
`tools/verify_runner_ui.py`.

```powershell
python tools/shoot_ui.py --out out/ui                      # everything, light + dark
python tools/shoot_ui.py --out out/ui --only designer --theme dark
python tools/shoot_ui.py --out out/ui --only hub --scale 2 # crisp crops
python tools/shoot_ui.py --out out/ui --flow workflows/BrownDust2/workflow.json
```

Colour changes are guarded by `tests/test_token_contrast.py`, which checks
every text/background token pair against WCAG AA in both themes.

In Designer, **F** fits the graph; **Shift+F** focuses selected nodes.
**F9** sets a breakpoint on the selected blocks (Shift+F9 clears all): a test
run holds *before* that block, then **F10** runs one block and **F8** continues
to the next breakpoint. Breakpoints are saved on the node; the Runner ignores
them.
Activities and Functions sit at the top of the left column, above the node
palette. **Arrange** spaces nodes automatically and can be undone with
**Ctrl+Z**. Selecting a node highlights its incoming and outgoing wires.

In the Runner, **Settings → Repeat** runs the sequence several rounds or
until stopped, with a rest between rounds. Every finished run is recorded in
`data/runner/<workflow>/history.jsonl`: the **History** tab lists them and
the Hub shows the newest one on each game's card.

## Build (Macro2k only)

```powershell
pwsh packaging/build.ps1
# code-only rebuild:
pwsh packaging/build.ps1 -SkipVendor
```

Output: `dist/Macro2k/Macro2k.exe` (+ shared `vendor/`).
DevScope is **source-only** in the default packaging.

## Docs

- Product / UI principles: [`docs/PRODUCT.md`](docs/PRODUCT.md)
- Packaging details: [`packaging/README.md`](packaging/README.md)
