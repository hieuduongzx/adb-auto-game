<#
.SYNOPSIS
    Build Macro2k (Hub + Designer + Runner) into dist/Macro2k/, and optionally a
    Windows installer (Inno Setup) with a folder picker + GitHub auto-update.

    dist/Macro2k/               <- the app folder (PyInstaller output + vendor)
        Macro2k.exe
        _macro2k/               private runtime files
        vendor/                 adb / frida / tesseract

    dist/installer/             <- (with -Installer) the wizard installer
        Macro2k-Setup-<ver>.exe

    The installer lets the user Browse to any folder (per-user, or all-users /
    Program Files when elevated). Writable data (workflows/, data/, out/) lives
    next to the app when that folder is writable, else under %LOCALAPPDATA%\Macro2k
    (read-only Program Files installs) — either way it survives updates.
    Auto-update (src/updater.py) downloads the newest Setup.exe from GitHub
    Releases and re-runs it silently over the same folder.

.PARAMETER SkipVendor
    Skip copying vendor/ (quick code-only rebuild; keeps the existing vendor/).

.PARAMETER Installer
    After building, compile packaging/installer.iss into dist/installer/. Installs
    Inno Setup via winget if ISCC is missing.

.PARAMETER Upload
    After compiling, publish the installer to GitHub Releases (implies -Installer).
    Needs a token via -Token or $env:GITHUB_TOKEN; installs the gh CLI if missing.

.PARAMETER Token
    GitHub token for -Upload. Defaults to $env:GITHUB_TOKEN.

.EXAMPLE
    pwsh packaging/build.ps1                 # app folder only
.EXAMPLE
    pwsh packaging/build.ps1 -Installer      # + dist/installer/Macro2k-Setup-<ver>.exe
.EXAMPLE
    pwsh packaging/build.ps1 -Upload         # + publish to GitHub Releases
#>
[CmdletBinding()]
param(
    [switch]$SkipVendor,
    [switch]$Installer,
    [switch]$Upload,
    [string]$Token = $env:GITHUB_TOKEN
)

$ErrorActionPreference = "Stop"
$Root    = Split-Path -Parent $PSScriptRoot          # project root
$Spec    = Join-Path $PSScriptRoot "apps_build.spec"
$Iss     = Join-Path $PSScriptRoot "installer.iss"
$Stage   = Join-Path $Root "build\_staging"          # PyInstaller COLLECT output
$Work    = Join-Path $Root "build"
$OutDir  = Join-Path $Root "dist\Macro2k"            # final app folder
$InstDir = Join-Path $Root "dist\installer"          # installer output
if ($Upload) { $Installer = $true }

Write-Host "==> Project root: $Root" -ForegroundColor Cyan

# Version + update repo are the single source of truth in src/version.py.
$verFileText = Get-Content (Join-Path $Root "src\version.py") -Raw
$Version = ([regex]'__version__\s*=\s*"([^"]+)"').Match($verFileText).Groups[1].Value
$RepoUrl = ([regex]'"(https://github\.com/[^"]+)"').Match($verFileText).Groups[1].Value
if (-not $Version) { throw "Could not read __version__ from src/version.py" }
Write-Host "==> Version: $Version" -ForegroundColor Cyan

# 1. Ensure PyInstaller is available.
$havePI = $false
try { python -c "import PyInstaller" 2>$null; $havePI = ($LASTEXITCODE -eq 0) } catch {}
if (-not $havePI) {
    Write-Host "==> Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install --upgrade pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }
}

# 2. Build Macro2k into the staging dir.
Write-Host "==> Running PyInstaller..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean --distpath $Stage --workpath $Work $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

# 3. Promote staging/Macro2k -> dist/Macro2k.
Write-Host "==> Assembling output folder: $OutDir" -ForegroundColor Cyan
$keepVendor = (Test-Path (Join-Path $OutDir "vendor")) -and $SkipVendor
if (Test-Path $OutDir) {
    # Preserve an existing vendor/ on -SkipVendor; wipe everything else.
    Get-ChildItem $OutDir -Force | Where-Object {
        -not ($keepVendor -and $_.Name -eq "vendor")
    } | Remove-Item -Recurse -Force
} else {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}
$src = Join-Path $Stage "Macro2k"
if (-not (Test-Path $src)) { throw "PyInstaller did not produce $src" }
robocopy $src $OutDir /E /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy Macro2k -> dist failed (code $LASTEXITCODE)" }

# 4. Copy vendor/.
if (-not $SkipVendor) {
    $vendorSrc = Join-Path $Root "vendor"
    $vendorDst = Join-Path $OutDir "vendor"
    Write-Host "==> Copying vendor/ -> $vendorDst" -ForegroundColor Cyan
    robocopy $vendorSrc $vendorDst /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy vendor failed (code $LASTEXITCODE)" }
}
$global:LASTEXITCODE = 0   # reset robocopy's non-zero "success" codes

# 5. Clean up staging.
Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "==> App folder done." -ForegroundColor Green
Write-Host "    $OutDir\Macro2k.exe"
Write-Host "    (vendor: $OutDir\vendor)"

# ── 6. Installer (Inno Setup) ────────────────────────────────────────────────
if (-not $Installer) {
    Write-Host ""
    Write-Host "    (run with -Installer to also produce dist/installer/Setup.exe)" -ForegroundColor DarkGray
    return
}

function Resolve-ISCC {
    # NB: keep the @(...) around the whole pipeline — a single match otherwise
    # collapses to a scalar string and [0] would index its first character.
    $hit = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($hit) { return $hit }
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$ISCC = Resolve-ISCC
if (-not $ISCC) {
    Write-Host "==> Installing Inno Setup (winget)..." -ForegroundColor Yellow
    winget install --id JRSoftware.InnoSetup -e --silent `
        --accept-source-agreements --accept-package-agreements
    $ISCC = Resolve-ISCC
    if (-not $ISCC) { throw "Inno Setup installed but ISCC.exe not found — install it and re-run." }
}

New-Item -ItemType Directory -Force $InstDir | Out-Null
Write-Host "==> Compiling installer ($Version) ..." -ForegroundColor Cyan
& $ISCC "/DMyAppVersion=$Version" "/DMySourceDir=$OutDir" "/DMyOutputDir=$InstDir" $Iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed (code $LASTEXITCODE)" }

$SetupExe = Join-Path $InstDir "Macro2k-Setup-$Version.exe"
Write-Host ""
Write-Host "==> Installer done." -ForegroundColor Green
Write-Host "    $SetupExe"

# ── 7. Publish to GitHub Releases (gh) ───────────────────────────────────────
if ($Upload) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        Write-Host "==> Installing GitHub CLI (winget)..." -ForegroundColor Yellow
        winget install --id GitHub.cli -e --silent `
            --accept-source-agreements --accept-package-agreements
        $env:PATH = "$env:PATH;$env:ProgramFiles\GitHub CLI"
        if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
            throw "gh installed but not on PATH — reopen the shell and re-run."
        }
    }
    # Auth: an explicit token wins; otherwise fall back to an existing
    # `gh auth login` session so you don't have to mint a PAT.
    if ($Token) {
        $env:GH_TOKEN = $Token
    } else {
        gh auth status 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Not signed in. Run 'gh auth login' once, or pass -Token / set `$env:GITHUB_TOKEN."
        }
    }
    # owner/repo from the feed URL.
    $slug = ($RepoUrl -replace '^https://github\.com/', '') -replace '\.git$', ''
    $tag = "v$Version"
    Write-Host "==> Publishing $tag to $slug ..." -ForegroundColor Cyan
    # Create the release, or (if the tag already exists) just (re)upload the asset.
    gh release create $tag $SetupExe --repo $slug --title "Macro2k $Version" --notes "Macro2k $Version" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "    release exists — uploading asset with --clobber" -ForegroundColor DarkGray
        gh release upload $tag $SetupExe --repo $slug --clobber
        if ($LASTEXITCODE -ne 0) { throw "gh release upload failed (code $LASTEXITCODE)" }
    }
    Write-Host "==> Published $tag." -ForegroundColor Green
}
