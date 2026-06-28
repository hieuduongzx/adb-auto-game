<#
.SYNOPSIS
    Build the two ADB auto-game tools into ONE shared folder with a single
    shared vendor/.

    dist/Workflow2k/
        Workflow2k.exe      Workflow Designer (+ Runner via --runner)
        DevScope.exe        Dev / device inspector tool
        _workflow2k/        Workflow2k's private runtime files
        _devscope/          DevScope's private runtime files
        vendor/             shared adb / frida / tesseract (one copy)

    Both .exe resolve their writable root (vendor/, data/, out/) to the folder
    they sit in, so a single vendor/ next to them serves both.

.PARAMETER SkipVendor
    Skip copying vendor/ (quick code-only rebuild; keeps the existing vendor/).

.EXAMPLE
    pwsh packaging/build.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipVendor
)

$ErrorActionPreference = "Stop"
$Root    = Split-Path -Parent $PSScriptRoot          # project root
$Spec    = Join-Path $PSScriptRoot "tools_build.spec"
$Stage   = Join-Path $Root "build\_staging"          # PyInstaller COLLECT output
$Work    = Join-Path $Root "build"
$OutDir  = Join-Path $Root "dist\Workflow2k"         # final shared folder

Write-Host "==> Project root: $Root" -ForegroundColor Cyan

# 1. Ensure PyInstaller is available.
$havePI = $false
try { python -c "import PyInstaller" 2>$null; $havePI = ($LASTEXITCODE -eq 0) } catch {}
if (-not $havePI) {
    Write-Host "==> Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
}

# 2. Build both tools into the staging dir.
Write-Host "==> Running PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --distpath $Stage --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# 3. Merge both tool folders into one shared output folder.
#    Each tool has a distinct contents_directory (_workflow2k / _devscope) and a
#    distinct .exe name, so merging never collides.
Write-Host "==> Assembling shared folder: $OutDir" -ForegroundColor Cyan
$keepVendor = (Test-Path (Join-Path $OutDir "vendor")) -and $SkipVendor
if (Test-Path $OutDir) {
    # Preserve an existing vendor/ on -SkipVendor; wipe everything else.
    Get-ChildItem $OutDir -Force | Where-Object {
        -not ($keepVendor -and $_.Name -eq "vendor")
    } | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}
foreach ($tool in @("Workflow2k", "DevScope")) {
    $src = Join-Path $Stage $tool
    robocopy $src $OutDir /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $tool -> shared folder failed (code $LASTEXITCODE)" }
}

# 4. Copy the single shared vendor/.
if (-not $SkipVendor) {
    $vendorSrc = Join-Path $Root "vendor"
    $vendorDst = Join-Path $OutDir "vendor"
    Write-Host "==> Copying shared vendor/ -> $vendorDst" -ForegroundColor Cyan
    robocopy $vendorSrc $vendorDst /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy vendor failed (code $LASTEXITCODE)" }
}
$global:LASTEXITCODE = 0   # reset robocopy's non-zero "success" codes

# 5. Clean up staging.
Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "==> Done." -ForegroundColor Green
Write-Host "    $OutDir\Workflow2k.exe"
Write-Host "    $OutDir\DevScope.exe"
Write-Host "    (shared $OutDir\vendor)"
