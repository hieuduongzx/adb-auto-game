"""Self-update for a standalone single-workflow Runner build.

Every Runner built by ``packaging/build_runner.py`` bundles a
``runner_build.json``: app name, display name, version, the GitHub repo that
hosts its updates, and its release tag prefix. Updates are GitHub Releases in
that repo tagged ``runner-<AppName>-v<version>`` with a ``.zip`` of the whole
Runner folder attached, so any number of games share one repo without touching
each other's — or the Hub installer's — releases.

Applying an update downloads the zip, extracts it to a temp folder and hands
over to a small ``.cmd`` that gives this process time to exit, copies the new
files over the install folder (keeping ``data/``, ``out/`` and ``logs/``) and
relaunches the exe. A token for a private repo may be supplied via
``$MACRO2K_UPDATE_TOKEN`` or ``$GITHUB_TOKEN``.
"""
from __future__ import annotations

import json
import os
import re
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


_META_RE = re.compile(r"<!--\s*macro2k-runner:\s*(\{.*?\})\s*-->", re.DOTALL)
_PUBLIC_FIELDS = ("version", "tag", "markdown", "page", "publishedAt", "autoShow")


def split_release_notes(body: str) -> Tuple[str, bool]:
    """Release body → ``(markdown, auto_show)``.

    The HTML comment is metadata, not part of the notes. A missing or
    malformed comment means automatic display stays off."""
    text = str(body or "")
    match = _META_RE.search(text)
    auto = False
    if match:
        try:
            data = json.loads(match.group(1))
            auto = isinstance(data, dict) and data.get("autoShow") is True
        except Exception:
            auto = False
        text = (text[:match.start()] + text[match.end():]).strip()
    return text.strip(), auto


def normalize_release(rel: dict, tag_prefix: str) -> Optional[dict]:
    """One GitHub release for this Runner, or None when it is not theirs."""
    if not isinstance(rel, dict) or rel.get("draft"):
        return None
    tag = str(rel.get("tag_name") or "")
    prefix = str(tag_prefix or "")
    if not prefix or not tag.startswith(prefix):
        return None
    version = tag[len(prefix):]
    if not parse_version(version):
        return None
    markdown, auto_show = split_release_notes(rel.get("body") or "")
    return {
        "version": version,
        "tag": tag,
        "markdown": markdown,
        "page": str(rel.get("html_url") or ""),
        "publishedAt": str(rel.get("published_at") or ""),
        "autoShow": auto_show,
    }


def normalize_releases(releases: list, tag_prefix: str) -> list:
    """Matching releases, newest version first. Drafts and other games are dropped."""
    rows = []
    for rel in releases or []:
        row = normalize_release(rel, tag_prefix)
        if row:
            rows.append(row)
    rows.sort(key=lambda row: parse_version(row["version"]), reverse=True)
    return rows


def _app_key(info: dict) -> str:
    raw = str((info or {}).get("appName") or "runner")
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._") or "runner"
    return cleaned[:80]


def changelog_dir(info: dict) -> str:
    from src.utils import data_root
    return os.path.join(data_root(), "data", "runner", _app_key(info))


def _read_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_json(path: str, data) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _public_record(record: dict) -> dict:
    out = {key: record.get(key) for key in _PUBLIC_FIELDS}
    out["version"] = str(out.get("version") or "")
    out["tag"] = str(out.get("tag") or "")
    out["markdown"] = str(out.get("markdown") or "")
    out["page"] = str(out.get("page") or "")
    out["publishedAt"] = str(out.get("publishedAt") or "")
    out["autoShow"] = out.get("autoShow") is True
    return out


def load_history(info: dict) -> list:
    data = _read_json(os.path.join(changelog_dir(info), "changelog-cache.json"))
    rows = data.get("history") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [_public_record(row) for row in rows if isinstance(row, dict) and row.get("version")]


def save_history(info: dict, rows: list) -> None:
    _write_json(os.path.join(changelog_dir(info), "changelog-cache.json"),
                {"history": [_public_record(row) for row in rows if isinstance(row, dict)]})


def refresh_history(info: dict) -> list:
    """Fetch this Runner's release notes. A failed fetch keeps the last cache."""
    cached = load_history(info)
    try:
        rows = normalize_releases(fetch_releases(str(info.get("repo") or "")),
                                  str(info.get("tagPrefix") or ""))
    except Exception as exc:
        log_error(f"[update] changelog refresh failed: {exc}")
        return cached
    try:
        save_history(info, rows)
    except Exception as exc:
        log_error(f"[update] changelog cache was not saved: {exc}")
    return rows


def write_pending(info: dict, record: dict) -> None:
    _write_json(os.path.join(changelog_dir(info), "pending-changelog.json"),
                _public_record(record))


def read_pending(info: dict) -> Optional[dict]:
    data = _read_json(os.path.join(changelog_dir(info), "pending-changelog.json"))
    if not isinstance(data, dict) or not data.get("version"):
        return None
    return _public_record(data)


def acknowledge_pending(info: dict, version: str) -> None:
    pending = read_pending(info)
    if pending and pending.get("version") == str(version or ""):
        try:
            os.remove(os.path.join(changelog_dir(info), "pending-changelog.json"))
        except OSError:
            pass


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
        markdown, auto_show = split_release_notes(rel.get("body") or "")
        if best is None or numbers > best["numbers"]:
            best = {
                "numbers": numbers, "version": version, "tag": tag,
                "url": asset.get("browser_download_url"), "size": int(asset.get("size") or 0),
                "notes": rel.get("body") or "", "page": rel.get("html_url") or "",
                "markdown": markdown, "autoShow": auto_show,
                "publishedAt": str(rel.get("published_at") or ""),
            }
    return best


def check(info: Optional[dict] = None, force: bool = False) -> dict:
    """Look for a newer release of this Runner. Never raises.

    Returns ``{available, current, version, url, page, notes, size, error,
    supported, repo}``. ``force`` skips the frozen-build requirement (tests)."""
    info = build_info() if info is None else info
    result = {
        "available": False, "current": str(info.get("version") or ""), "version": None,
        "url": None, "page": None, "notes": "", "markdown": "", "autoShow": False,
        "tag": "", "publishedAt": "", "size": 0, "error": None,
        "supported": bool(force or updates_supported(info)), "repo": str(info.get("repo") or ""),
    }
    if not result["supported"]:
        return result
    try:
        best = latest_release(result["repo"], str(info.get("tagPrefix") or ""))
        if best and best["numbers"] > parse_version(result["current"]):
            result.update(available=True, version=best["version"], url=best["url"],
                          page=best["page"], notes=best["notes"], size=best["size"],
                          markdown=best.get("markdown") or "", autoShow=bool(best.get("autoShow")),
                          tag=best.get("tag") or "", publishedAt=best.get("publishedAt") or "")
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
                        script_path: str, relaunch: bool = True,
                        version: str = "") -> str:
    """The hand-over ``.cmd``: let ``pid`` exit, copy ``src_dir`` over
    ``install_dir`` (keeping :data:`KEEP_DIRS`), relaunch ``exe``, clean up.

    Copy uses ``/E /IS /IT`` and deliberately **not** ``/MIR``: ``/MIR`` adds
    ``/PURGE``, which deletes files from the install before they're replaced, so
    a copy that fails part-way (locked file, denied rights) can leave a broken
    install — the app then exits and never comes back. ``/IS /IT`` force each
    source file over (otherwise robocopy skips a file whose destination looks
    newer, leaving the version file stale). Every step is appended to a log so a
    silent failure can be diagnosed."""
    keep = " ".join(f'"{os.path.join(install_dir, d)}"' for d in KEEP_DIRS)
    # System tools by full path: a PATH with Git's usr/bin first can pick up
    # unrelated Unix tools. `ping` is a bounded sleep because `timeout` refuses
    # to run in a process without a console. Do not poll tasklist through a pipe:
    # on some Windows builds find.exe inherits the pipe's write handle and waits
    # forever for EOF even though the Runner process has already exited.
    sys32 = r"%SystemRoot%\System32"
    log_file = os.path.join(tempfile.gettempdir(), "macro2k-runner-update.log")
    lines = [
        "@echo off",
        f'set "LOG={log_file}"',
        f'>>"%LOG%" echo [%date% %time%] update v{version or "?"}: src="{src_dir}" dst="{install_dir}" exe="{exe}" pid={pid}',
        # The parent calls os._exit immediately after starting this script. Give
        # Windows a moment to release the exe and its _internal DLLs; robocopy's
        # own /R retry handles any slower file release without an infinite loop.
        f'"{sys32}\\PING.EXE" -n 4 127.0.0.1 >nul',
        f'>>"%LOG%" echo [%date% %time%] copying after shutdown grace period',
        # /E copies (no purge); /IS /IT force every source file over the target.
        f'"{sys32}\\Robocopy.exe" "{src_dir}" "{install_dir}" /E /IS /IT /XD {keep} '
        f'/R:3 /W:1 /NFL /NDL /NJH /NJS /NP >>"%LOG%" 2>&1',
        "set RC=%ERRORLEVEL%",
        '>>"%LOG%" echo [%date% %time%] robocopy rc=%RC%',
    ]
    if relaunch:
        lines += [
            'if %RC% GEQ 8 (',
            f'  >>"%LOG%" echo [%date% %time%] COPY FAILED; keeping extracted update at "{src_dir}"',
            f'  if exist "{exe}" start "" /D "{install_dir}" "{exe}"',
            '  goto finish',
            ')',
            f'if exist "{exe}" (',
            f'  "{sys32}\\PING.EXE" -n 2 127.0.0.1 >nul',
            f'  start "" /D "{install_dir}" "{exe}"',
            f'  >>"%LOG%" echo [%date% %time%] updated to v{version or "?"} and relaunched',
            ") else (",
            f'  >>"%LOG%" echo [%date% %time%] EXE MISSING: {exe}',
            ")",
        ]
    # Only clean up the extracted files when the copy actually succeeded, so a
    # failed update can still be inspected / copied by hand.
    lines += [
        f'if %RC% LSS 8 rmdir /s /q "{src_dir}"',
        ':finish',
        '(goto) 2>nul & del "%~f0"',
    ]
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
                                     os.path.join(tmp, "apply-update.cmd"), version=version)
        try:
            write_pending(info, {
                "version": version,
                "tag": str(found.get("tag") or ""),
                "markdown": str(found.get("markdown") or ""),
                "page": str(found.get("page") or ""),
                "publishedAt": str(found.get("publishedAt") or ""),
                "autoShow": found.get("autoShow") is True,
            })
        except Exception as exc:
            log_error(f"[update] could not remember the changelog: {exc}")
        stage(100, "Restarting")
        log_info(f"[update] installing {version} and restarting…")
        if before_exit:
            before_exit()
        # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW. DETACHED_PROCESS conflicts
        # with CREATE_NO_WINDOW on some Windows versions and caused a visible
        # black console to flash during updates.
        subprocess.Popen([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", script],
                         creationflags=0x00000200 | 0x08000000, close_fds=True)
        os._exit(0)
    except Exception as exc:
        log_error(f"[update] apply failed: {exc}")
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        return {"applied": False, "error": str(exc), "upToDate": False}
