"""Auto-update via GitHub Releases + the Inno Setup installer.

Model: the app asks the GitHub Releases API for the latest published release,
compares its tag (``vX.Y.Z``) with the running version, and — if newer —
downloads that release's ``…-Setup.exe`` and runs it. The Inno Setup installer
reinstalls over the current location (elevating via UAC if it lives under
Program Files) and relaunches the app. No admin rights are needed to *check* or
*download*; only running the installer may prompt for elevation.

The feed repo is :data:`src.version.UPDATE_REPO_URL`. A token (for a private
repo / higher rate limit) may be supplied via ``$MACRO2K_UPDATE_TOKEN`` or
``$GITHUB_TOKEN``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from typing import Optional, Tuple

from src.utils import app_dir, is_frozen, is_portable_build, log_error, log_info
from src.version import APP_NAME, APP_VERSION, UPDATE_REPO_URL, version_tuple

_API = "https://api.github.com"


def _owner_repo() -> Optional[Tuple[str, str]]:
    """``https://github.com/owner/repo`` → ``("owner", "repo")``."""
    try:
        parts = UPDATE_REPO_URL.rstrip("/").split("/")
        return parts[-2], parts[-1]
    except Exception:
        return None


def _token() -> Optional[str]:
    return os.environ.get("MACRO2K_UPDATE_TOKEN") or os.environ.get("GITHUB_TOKEN")


def updates_supported() -> bool:
    """Self-update only makes sense for an installed frozen build (not from
    source, not a portable folder the user manages by hand)."""
    return is_frozen() and not is_portable_build()


def _parse_version(tag: str) -> Tuple[int, ...]:
    """``"v1.2.3"`` / ``"1.2.3"`` → ``(1, 2, 3)`` (non-numeric parts stop it)."""
    nums = []
    for part in tag.lstrip("vV").replace("-", ".").split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums)


def _fetch_latest() -> dict:
    """GET the latest release JSON from the GitHub API (raises on failure)."""
    orp = _owner_repo()
    if not orp:
        raise RuntimeError("bad UPDATE_REPO_URL")
    url = f"{_API}/repos/{orp[0]}/{orp[1]}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _setup_asset(release: dict) -> Optional[dict]:
    """Pick the installer asset — the first ``.exe`` whose name mentions
    'setup' (falling back to any ``.exe``)."""
    assets = release.get("assets") or []
    exes = [a for a in assets if str(a.get("name", "")).lower().endswith(".exe")]
    for a in exes:
        if "setup" in str(a.get("name", "")).lower():
            return a
    return exes[0] if exes else None


def check() -> dict:
    """Look for a newer published release.

    Returns ``{"available", "version", "current", "error", "supported", "url"}``.
    Never raises — network / API errors land in ``error``.
    """
    result = {
        "available": False, "version": None, "current": APP_VERSION,
        "error": None, "supported": updates_supported(), "url": None,
    }
    if not result["supported"]:
        return result
    try:
        rel = _fetch_latest()
        tag = rel.get("tag_name") or rel.get("name") or ""
        latest = _parse_version(tag)
        if latest and latest > version_tuple():
            asset = _setup_asset(rel)
            if asset:
                result["available"] = True
                result["version"] = tag.lstrip("vV")
                result["url"] = asset.get("browser_download_url")
    except Exception as e:
        result["error"] = str(e)
        log_error(f"[update] check failed: {e}")
    return result


def _download(url: str, dest: str, on_progress=None) -> None:
    """Download ``url`` → ``dest``. If given, ``on_progress(pct)`` is called as
    bytes arrive with an integer 0..100 (or -1 when the server omits a length,
    i.e. progress is indeterminate). Fires only when the percentage changes."""
    req = urllib.request.Request(url, headers={
        "Accept": "application/octet-stream",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    })
    tok = _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done, last = 0, None
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                pct = int(done * 100 / total) if total else -1
                if pct != last:
                    last = pct
                    try:
                        on_progress(pct)
                    except Exception:
                        pass


def apply_latest(on_progress=None) -> dict:
    """Download the newest installer and run it, then quit so files can be
    replaced. On success this DOES NOT RETURN (the process exits and the
    installer relaunches the app). Returns ``{"applied", "error"}`` otherwise.

    ``on_progress(pct)`` (optional) is called with the download percentage
    (0..100, or -1 when indeterminate) and, once downloaded, ``100`` right
    before the installer launches."""
    if not updates_supported():
        return {"applied": False, "error": "updates not supported in this build"}
    info = check()
    if info.get("error"):
        return {"applied": False, "error": info["error"]}
    if not info.get("available") or not info.get("url"):
        return {"applied": False, "error": None}

    try:
        version = info["version"]
        setup = os.path.join(tempfile.gettempdir(), f"{APP_NAME}-Setup-{version}.exe")
        log_info(f"[update] downloading {version} → {setup}")
        _download(info["url"], setup, on_progress)

        install_dir = os.path.dirname(os.path.abspath(sys.executable))
        exe = os.path.abspath(sys.executable)
        # A tiny wrapper waits for this process to exit (releasing the .exe lock),
        # runs the installer silently into the SAME directory, then relaunches.
        wrapper = os.path.join(tempfile.gettempdir(), f"{APP_NAME}-update.cmd")
        with open(wrapper, "w", encoding="utf-8") as f:
            f.write(
                "@echo off\r\n"
                "timeout /t 2 /nobreak >nul\r\n"
                f'"{setup}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="{install_dir}"\r\n'
                f'start "" "{exe}"\r\n'
                'del "%~f0"\r\n'
            )
        if on_progress:
            try:
                on_progress(100)   # download done → UI flips to "Installing…"
            except Exception:
                pass
        log_info(f"[update] launching installer for {version} and quitting…")
        DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd", "/c", wrapper], creationflags=DETACHED, close_fds=True)
        # Quit hard so the running .exe unlocks for the installer.
        os._exit(0)
    except Exception as e:
        log_error(f"[update] apply failed: {e}")
        return {"applied": False, "error": str(e)}
