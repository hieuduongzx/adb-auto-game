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
    vendor/                      adb / frida / tesseract
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

## How auto-update works

[`src/updater.py`](../src/updater.py) polls the GitHub Releases API of
`UPDATE_REPO_URL`, compares the latest tag with the running version, and — if
newer — downloads that release's `Setup.exe` and runs it silently into the same
install folder (elevating via UAC only if under Program Files). No admin is
needed to check or download. The repo must be **public** (or clients need a
token via `MACRO2K_UPDATE_TOKEN` / `GITHUB_TOKEN`).

## Where user data lives

`data_root()` ([`src/utils/__init__.py`](../src/utils/__init__.py)) keeps
`workflows/`, `data/`, `out/`, `autoclicks/` **next to the app** when that folder
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
