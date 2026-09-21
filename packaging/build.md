# Build & Release — Macro2k

Command reference for building the app, the installer, and publishing updates.
The single source of truth for the version is [`src/version.py`](../src/version.py)
(`__version__`), and for the update feed the same file's `UPDATE_REPO_URL`.

All commands run from the **project root** in PowerShell.

## Quick reference

| Goal | Command |
|------|---------|
| App folder only | `pwsh packaging/build.ps1` |
| Quick code rebuild (keep vendor/) | `pwsh packaging/build.ps1 -SkipVendor` |
| + Installer (`Setup.exe`) | `pwsh packaging/build.ps1 -Installer` |
| + Publish to GitHub Releases | `pwsh packaging/build.ps1 -Upload` |

`-Upload` implies `-Installer`. `-Installer` implies a full build.

## Outputs

```
dist/Macro2k/                    the app folder (PyInstaller output + vendor/)
    Macro2k.exe                  Hub (default) · --designer · --runner
    _macro2k/                    private runtime files
    vendor/                      adb / frida
dist/installer/
    Macro2k-Setup-<ver>.exe      the wizard installer (Browse-to-folder)
```

## 1. Build the app

```powershell
pwsh packaging/build.ps1            # full build (re-copies vendor/, ~slow)
pwsh packaging/build.ps1 -SkipVendor   # code-only rebuild, reuse existing vendor/
```

Prerequisite: `pip install -r requirements.txt`. PyInstaller is auto-installed if
missing.

The build bundles recognition-only PP-OCRv5 Mobile from
`assets/ocr/ppocr_v5_mobile/` plus ONNX Runtime CPU. It does not download a
model on first launch and does not ship Paddle, PaddleOCR, PaddleX, Tesseract,
or EasyOCR. Standalone Runner builds reject an incomplete OCR payload and an
application payload larger than 250 MiB; game-specific `requirements/` files
are reported separately and do not count toward that limit.

## 1b. App icon

`packaging/app.ico` is the icon for `Macro2k.exe`, the single-workflow Runner
exes, and `Setup.exe`. `build.ps1` regenerates it automatically when it is
missing or older than the generator, so a normal build needs no extra step.

Regenerate by hand after editing the artwork:

```powershell
python packaging/make_icon.py     # -> packaging/app.ico + app.png
```

[`make_icon.py`](make_icon.py) draws the Hub's brand mark — the shared
`grid-2x2-plus` glyph — on a dark rounded tile and renders each size
independently (16 … 256) so the small frames stay readable. It fills the tiles
and stains the plus `--accent`, where the in-app mark is a one-colour outline:
same geometry, two treatments, because a hairline outline vanishes on a dark
taskbar at 16 px. Only Pillow is required.

## 1c. Icon-set guard

`apps/web/shared/icons.js` is the only copy of any icon geometry in the suite.
[`check_icons.py`](check_icons.py) enforces it and runs automatically in both
`build.ps1` and `build_runner.py`:

```powershell
python packaging/check_icons.py           # ICONS_OK, or a report and exit 1
python packaging/check_icons.py --list    # also show ratchet progress
```

It checks three things: every `uiIco("name")` / `data-ico="name"` names an icon
that exists (an unknown name renders *nothing*, silently); no app inlines its own
`<svg>`; and the ladder in `shared/icons.css` still lands each step's rendered
stroke in the 1.0–1.8 px band. The Hub and Runner must stay at zero inline
`<svg>`; the Designer and DevScope are ratcheted down file by file — lower a
file's number in `LEGACY` when it shrinks, and delete the entry at zero.

## 2. Build the installer

```powershell
pwsh packaging/build.ps1 -Installer
```

- Compiles [`installer.iss`](installer.iss) with Inno Setup (`ISCC.exe`).
- Inno Setup is auto-installed via `winget` if missing.
- The installer is a normal wizard with a **Browse** folder picker: install
  per-user (no admin) or all-users / `C:\Program Files` (elevates via UAC).

Install silently (e.g. for scripting):

```powershell
dist\installer\Macro2k-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER
dist\installer\Macro2k-Setup-1.0.0.exe /VERYSILENT /DIR="D:\Macro2k"   # pick a folder
```

## 3. Publish a release to GitHub (enables auto-update)

**First time only — sign in to GitHub:**

```powershell
gh auth login          # GitHub.com → HTTPS → Login with a web browser
```

`gh` (GitHub CLI) is auto-installed via `winget` if missing.

**Then publish:**

```powershell
pwsh packaging/build.ps1 -Upload
```

This builds, compiles the installer, and creates GitHub Release `v<ver>` with
`Macro2k-Setup-<ver>.exe` attached. If the release/tag already exists it just
re-uploads the asset (`--clobber`).

Alternatively pass a token instead of `gh auth login`:

```powershell
$env:GITHUB_TOKEN = "ghp_..."     # a PAT with 'repo' scope
pwsh packaging/build.ps1 -Upload
```

## 4. Release a new version

1. Bump the version in [`src/version.py`](../src/version.py):
   ```python
   __version__ = "1.0.1"
   ```
2. Publish:
   ```powershell
   pwsh packaging/build.ps1 -Upload
   ```
3. Installed apps see **"Update to v1.0.1"** in the Hub → one click downloads the
   new `Setup.exe` and reinstalls over the same folder, then relaunches.

The version flows automatically to: window titles, the Hub version badge, the
`.exe` file metadata, the installer filename, and the GitHub release tag.

## 5. Standalone Runner — game requirements

A single-workflow Runner (Hub **Build**, Designer **Build EXE**, or
`python packaging/build_runner.py --workflow workflows/<Name>`) ships whatever is
in `workflows/<Name>/vendor/` — files the player must put into the **game's own
install folder** (a third-party mod's files, configs…; the Unity Bridge itself
needs none of this — it injects into the running game, see
`vendor/unity_bridge/README.md`):

```
dist/<Name>-Runner/
    <Name>.exe
    requirements/        a copy of workflows/<Name>/vendor/ (not bundled into the exe)
    REQUIREMENTS.txt     install steps for players (Vietnamese + English)
```

No `vendor/` folder (or an empty one) → neither is produced. The Hub's Build
dialog lists the file count and the finished build panel has **Open
requirements**. The built Runner warns on load until the files are found in the
game folder, and Settings → **Game files** can copy them next to the Game path's
`.exe`.

## 6. Standalone Runner — bundled workflow.json + templates are obfuscated

`build_runner.py` encrypts the bundled `workflow.json` and every image under its
`templates/` folder in place, after PyInstaller finishes
(`_internal/workflow/...`) — so a player who opens the installed Runner folder
can't casually read the automation logic in a text editor or browse the
match-template screenshots in an image viewer. `assets/icon.png`/`cover.*` (and
anything else in the workflow folder) are left alone — those are shown to the
player in the app UI itself. See `src/utils/asset_crypto.py` for the format and
its (explicitly stated) limits — it's obfuscation, not real security: the key
ships inside the Runner, so it only stops casual browsing, never a determined
extraction. `WorkflowEngine.load_file` and `TemplateMatcher.load` auto-detect
and decrypt transparently; a workflow saved by the Designer, or a Runner run
from source, is plain and unaffected.

## How auto-update works

[`src/updater.py`](../src/updater.py) polls the GitHub Releases API of
`UPDATE_REPO_URL`, compares the latest tag with the running version, and — if
newer — downloads that release's `Setup.exe` and runs it silently into the same
install folder (elevating via UAC only if under Program Files). No admin is
needed to check or download. The repo must be **public** (or clients need a
token via `MACRO2K_UPDATE_TOKEN` / `GITHUB_TOKEN`).

## Where user data lives

`data_root()` ([`src/utils/__init__.py`](../src/utils/__init__.py)) keeps
`workflows/`, `data/`, `out/` **next to the app** when that folder
is writable (per-user or custom install, or a portable copy), and falls back to
`%LOCALAPPDATA%\Macro2k` only for a read-only `C:\Program Files` install. Either
way, user data survives updates. Drop a `portable.txt` next to `Macro2k.exe` to
force data-beside-the-app regardless.

## Troubleshooting

- **`ISCC.exe not found`** — Inno Setup didn't install; install it manually from
  <https://jrsoftware.org/isdl.php> and re-run.
- **`gh` not found after install** — reopen the terminal so the new PATH loads.
- **`-Upload` says "Not signed in"** — run `gh auth login`, or set
  `$env:GITHUB_TOKEN`.
- **File locked / "Access denied" during build** — a running `Macro2k.exe` holds
  the file; close it (`Get-Process Macro2k | Stop-Process -Force`) and re-run.
- **A *downloaded* Runner dies with `Failed to resolve Python.Runtime.Loader.
  Initialize`** — Windows' *Mark-of-the-Web*. Files Explorer extracts from a
  downloaded `.zip` keep a `Zone.Identifier` stream, and the .NET Framework
  refuses to load a marked assembly — which is what Python.NET (pywebview's
  Windows backend) is. It hits everyone who downloads the build and nobody who
  built it, because the builder's copies were never downloaded. Current builds
  clear the mark at startup (`unblock_bundled_files()` in
  [`src/utils/__init__.py`](../src/utils/__init__.py), called from the frozen
  entry points before `webview.start()`), so nothing has to be done — a build
  made before that fix can be rescued by right-clicking the `.zip` →
  *Properties* → **Unblock** *before* extracting, extracting with 7-Zip
  instead, or running `Get-ChildItem <folder> -Recurse | Unblock-File` on the
  extracted folder.
