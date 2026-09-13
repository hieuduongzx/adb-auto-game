"""Self-update for a standalone single-workflow Runner build.

Every Runner built by ``packaging/build_runner.py`` bundles a
``runner_build.json``: app name, display name, version, the GitHub repo that
hosts its updates, and its release tag prefix. Updates are GitHub Releases in
that repo tagged ``runner-<AppName>-v<version>`` with a ``.zip`` of the whole
Runner folder attached, so any number of games share one repo without touching
each other's — or the Hub installer's — releases.

Applying an update downloads the zip, extracts it to a temp folder and hands
over to a small ``.cmd`` that waits for this process to exit, mirrors the new
files over the install folder (keeping ``data/``, ``out/`` and ``logs/``) and
relaunches the exe. A token for a private repo may be supplied via
``$MACRO2K_UPDATE_TOKEN`` or ``$GITHUB_TOKEN``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from typing import Callable, Optional, Tuple

from src.utils import app_dir, bundle_dir, is_frozen, log_error, log_info

_API = "https://api.github.com"
BUILD_INFO_NAME = "runner_build.json"
# Written by the running Runner; an update never overwrites or deletes them.
KEEP_DIRS = ("data", "out", "logs")


def parse_version(text: str) -> Tuple[int, ...]:
    """``"v1.2.3"`` / ``"1.2.3"`` → ``(1, 2, 3)`` (a non-numeric part stops it)."""
    nums = []
    for part in str(text or "").lstrip("vV").replace("-", ".").split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums)


def build_info() -> dict:
    """``runner_build.json`` bundled into this Runner, or ``{}`` (source / suite)."""
    try:
        with open(os.path.join(bundle_dir(), BUILD_INFO_NAME), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def updates_supported(info: dict) -> bool:
    """Only a frozen Runner that knows its repo and tag prefix can update itself."""
    return is_frozen() and bool(info.get("repo")) and bool(info.get("tagPrefix"))


def _request(url: str, accept: str) -> urllib.request.Request:
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        "User-Agent": "Macro2k-Runner",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    token = os.environ.get("MACRO2K_UPDATE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return req


def fetch_releases(repo: str, timeout: float = 15) -> list:
    """The repo's most recent releases (GitHub API, newest first)."""
    url = f"{_API}/repos/{repo}/releases?per_page=100"
    with urllib.request.urlopen(_request(url, "application/vnd.github+json"), timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data if isinstance(data, list) else []


def latest_release(repo: str, tag_prefix: str, releases: Optional[list] = None) -> Optional[dict]:
    """Newest published release tagged ``<tag_prefix><version>`` with a .zip asset."""
    best: Optional[dict] = None
    for rel in releases if releases is not None else fetch_releases(repo):
        if rel.get("draft"):
            continue
        tag = str(rel.get("tag_name") or "")
        if not tag.startswith(tag_prefix):
            continue
        version = tag[len(tag_prefix):]
        numbers = parse_version(version)
        if not numbers:
            continue
        asset = next((a for a in rel.get("assets") or []
                      if str(a.get("name", "")).lower().endswith(".zip")), None)
        if asset is None:
            continue
        if best is None or numbers > best["numbers"]:
            best = {
                "numbers": numbers, "version": version, "tag": tag,
                "url": asset.get("browser_download_url"), "size": int(asset.get("size") or 0),
                "notes": rel.get("body") or "", "page": rel.get("html_url") or "",
            }
    return best


def check(info: Optional[dict] = None, force: bool = False) -> dict:
    """Look for a newer release of this Runner. Never raises.

    Returns ``{available, current, version, url, page, notes, size, error,
    supported, repo}``. ``force`` skips the frozen-build requirement (tests)."""
    info = build_info() if info is None else info
    result = {
        "available": False, "current": str(info.get("version") or ""), "version": None,
        "url": None, "page": None, "notes": "", "size": 0, "error": None,
        "supported": bool(force or updates_supported(info)), "repo": str(info.get("repo") or ""),
    }
    if not result["supported"]:
        return result
    try:
        best = latest_release(result["repo"], str(info.get("tagPrefix") or ""))
        if best and best["numbers"] > parse_version(result["current"]):
            result.update(available=True, version=best["version"], url=best["url"],
                          page=best["page"], notes=best["notes"], size=best["size"])
    except Exception as exc:
        result["error"] = str(exc)
        log_error(f"[update] check failed: {exc}")
    return result


def download(url: str, dest: str, on_progress: Optional[Callable[[int], None]] = None) -> None:
    """Download ``url`` → ``dest``; ``on_progress(pct)`` gets 0..100, or -1 when
    the server sends no length. Fires only when the percentage changes."""
    with urllib.request.urlopen(_request(url, "application/octet-stream"), timeout=120) as resp, \
            open(dest, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done, last = 0, None
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if on_progress:
                pct = int(done * 100 / total) if total else -1
                if pct != last:
                    last = pct
                    try:
                        on_progress(pct)
                    except Exception:
                        pass


def _safe_extract(zip_path: str, dest: str) -> None:
    """Extract, refusing any member that would land outside ``dest``."""
    root = os.path.abspath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = os.path.abspath(os.path.join(root, member))
            if os.path.commonpath([root, target]) != root:
                raise RuntimeError(f"Unsafe path in update package: {member}")
        zf.extractall(root)


def write_update_script(src_dir: str, install_dir: str, exe: str, pid: int,
                        script_path: str, relaunch: bool = True) -> str:
    """The hand-over ``.cmd``: wait for ``pid`` to exit, mirror ``src_dir`` over
    ``install_dir`` (keeping :data:`KEEP_DIRS`), relaunch ``exe``, clean up."""
    keep = " ".join(f'"{os.path.join(install_dir, d)}"' for d in KEEP_DIRS)
    # System tools by full path: a PATH with Git's usr/bin first would pick up
    # the Unix `find`. `ping` is the sleep because `timeout` refuses to run in a
    # detached process (no console to read from).
    sys32 = r"%SystemRoot%\System32"
    lines = [
        "@echo off",
        ":wait",
        f'"{sys32}\\tasklist.exe" /FI "PID eq {pid}" /NH 2>nul | "{sys32}\\find.exe" " {pid} " >nul && '
        f'("{sys32}\\PING.EXE" -n 2 127.0.0.1 >nul & goto wait)',
        f'"{sys32}\\Robocopy.exe" "{src_dir}" "{install_dir}" /MIR /XD {keep} /R:10 /W:1 '
        f"/NFL /NDL /NJH /NJS /NP >nul",
    ]
    if relaunch:
        lines.append(f'start "" "{exe}"')
    # "(goto) & del" deletes the running script without cmd complaining after.
    lines += [f'rmdir /s /q "{src_dir}"', '(goto) 2>nul & del "%~f0"']
    with open(script_path, "w", encoding="utf-8") as fh:
        fh.write("\r\n".join(lines) + "\r\n")
    return script_path


def apply(info: Optional[dict] = None,
          on_progress: Optional[Callable[[int, str], None]] = None,
          before_exit: Optional[Callable[[], None]] = None) -> dict:
    """Download and install the newest release, then quit and relaunch.

    On success this DOES NOT RETURN. Otherwise returns ``{applied: False,
    error, upToDate}``. ``on_progress(pct, stage)`` reports download progress
    (pct -1 = indeterminate) and the Extracting / Restarting stages."""
    info = build_info() if info is None else info
    if not updates_supported(info):
        return {"applied": False, "error": "This Runner has no update source", "upToDate": False}
    found = check(info)
    if found.get("error"):
        return {"applied": False, "error": found["error"], "upToDate": False}
    if not found.get("available") or not found.get("url"):
        return {"applied": False, "error": None, "upToDate": True}

    def stage(pct: int, label: str) -> None:
        if on_progress:
            try:
                on_progress(pct, label)
            except Exception:
                pass

    tmp = ""
    try:
        version = found["version"]
        tmp = tempfile.mkdtemp(prefix=f"{info.get('appName') or 'Runner'}-update-")
        zip_path = os.path.join(tmp, "update.zip")
        log_info(f"[update] downloading {version}")
        download(found["url"], zip_path, lambda pct: stage(pct, "Downloading"))

        stage(100, "Extracting")
        new_dir = os.path.join(tmp, "files")
        _safe_extract(zip_path, new_dir)
        os.remove(zip_path)
        exe = os.path.abspath(sys.executable)
        if not os.path.isfile(os.path.join(new_dir, os.path.basename(exe))):
            raise RuntimeError(f"The update package has no {os.path.basename(exe)}")

        script = write_update_script(new_dir, app_dir(), exe, os.getpid(),
                                     os.path.join(tmp, "apply-update.cmd"))
        stage(100, "Restarting")
        log_info(f"[update] installing {version} and restarting…")
        if before_exit:
            before_exit()
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        subprocess.Popen(["cmd", "/c", script], creationflags=0x00000008 | 0x00000200 | 0x08000000,
                         close_fds=True)
        os._exit(0)
    except Exception as exc:
        log_error(f"[update] apply failed: {exc}")
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        return {"applied": False, "error": str(exc), "upToDate": False}
