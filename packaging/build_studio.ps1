<#
.SYNOPSIS
    Build Macro2k **Studio** (Designer + Runner, no Hub) into dist/Macro2k-Studio/.

    The lean sibling of build.ps1. Studio-only packaging bootstrap
    (packaging/entry_studio.py) and the same runtime payload, minus the Hub:
    web/hub is not bundled and workflow_hub is never analysed.

    dist/Macro2k-Studio/        <- the app folder (PyInstaller output + vendor)
        Macro2k.exe             -> Designer (no switch) / Runner (--runner)
        _macro2k/               private runtime files
        vendor/                 adb / scrcpy / frida

    No installer and no auto-update: this build is meant to be copied as a
    folder. Writable data (workflows/, data/, out/, logs/) lives next to the
    app when that folder is writable, else under %LOCALAPPDATA%\Macro2k.

.PARAMETER SkipVendor
    Skip copying vendor/ (quick code-only rebuild; keeps the existing vendor/).

.EXAMPLE
    pwsh packaging/build_studio.ps1
.EXAMPLE
    pwsh packaging/build_studio.ps1 -SkipVendor    # code-only rebuild
#>
[CmdletBinding()]
param(
    [switch]$SkipVendor
)

$ErrorActionPreference = "Stop"
$Root    = Split-Path -Parent $PSScriptRoot          # project root
$Spec    = Join-Path $PSScriptRoot "apps_studio.spec"
$Stage   = Join-Path $Root "build\_staging_studio"    # PyInstaller COLLECT output
$Work    = Join-Path $Root "build"
$OutDir  = Join-Path $Root "dist\Macro2k-Studio"      # final app folder

Write-Host "==> Project root: $Root" -ForegroundColor Cyan

# Version is the single source of truth in src/version.py.
$verFileText = Get-Content (Join-Path $Root "src\version.py") -Raw
$Version = ([regex]'__version__\s*=\s*"([^"]+)"').Match($verFileText).Groups[1].Value
if (-not $Version) { throw "Could not read __version__ from src/version.py" }
Write-Host "==> Version: $Version (Designer + Runner, no Hub)" -ForegroundColor Cyan

# 1. Ensure PyInstaller is available.
$havePI = $false
try { python -c "import PyInstaller" 2>$null; $havePI = ($LASTEXITCODE -eq 0) } catch {}
if (-not $havePI) {
    Write-Host "==> Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
}

# 1b. Ensure the app icon exists (packaging/app.ico drives the .exe icon).
#     Regenerated only when missing/stale so a normal build stays fast.
$IconPy  = Join-Path $PSScriptRoot "make_icon.py"
$IconIco = Join-Path $PSScriptRoot "app.ico"
$iconStale = -not (Test-Path $IconIco)
if (-not $iconStale) {
    $iconStale = (Get-Item $IconPy).LastWriteTimeUtc -gt (Get-Item $IconIco).LastWriteTimeUtc
}
if ($iconStale) {
    Write-Host "==> Generating app icon (packaging/app.ico)..." -ForegroundColor Cyan
    python $IconPy
    if ($LASTEXITCODE -ne 0) { throw "make_icon.py failed (is Pillow installed?)" }
}

# 2. Icon set guard — shared/icons.js must stay the only copy of icon geometry.
Write-Host "==> Checking icon set..." -ForegroundColor Cyan
python (Join-Path $PSScriptRoot "check_icons.py")
if ($LASTEXITCODE -ne 0) { throw "check_icons.py failed — see the report above" }

# 3. Build into the staging dir.
Write-Host "==> Running PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --distpath $Stage --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# 4. Promote staging/Macro2k -> dist/Macro2k-Studio.
Write-Host "==> Assembling output folder: $OutDir" -ForegroundColor Cyan
$keepVendor = (Test-Path (Join-Path $OutDir "vendor")) -and $SkipVendor
# These folders belong to the user, not to the PyInstaller payload.
# In particular, data/designer_settings.json stores the custom workflowsDir.
# Preserve them across every rebuild just as the full build does.
$userDirs = @("data", "workflows", "out", "logs")
if (Test-Path $OutDir) {
    Get-ChildItem $OutDir -Force | Where-Object {
        ($userDirs -notcontains $_.Name) -and
        -not ($keepVendor -and $_.Name -eq "vendor")
    } | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}
$src = Join-Path $Stage "Macro2k"
if (-not (Test-Path $src)) { throw "PyInstaller did not produce $src" }
robocopy $src $OutDir /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy Macro2k -> dist failed (code $LASTEXITCODE)" }

# 5. Copy vendor/.
if (-not $SkipVendor) {
    $vendorSrc = Join-Path $Root "vendor"
    $vendorDst = Join-Path $OutDir "vendor"
    Write-Host "==> Copying vendor/ -> $vendorDst" -ForegroundColor Cyan
    robocopy $vendorSrc $vendorDst /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy vendor failed (code $LASTEXITCODE)" }
}
$global:LASTEXITCODE = 0   # reset robocopy's non-zero "success" codes

# 6. Clean up staging.
Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "==> Studio folder done (Designer + Runner, no Hub)." -ForegroundColor Green
Write-Host "    $OutDir\Macro2k.exe          -> Designer"
Write-Host "    $OutDir\Macro2k.exe --runner  -> Runner"
Write-Host "    (vendor: $OutDir\vendor)"
