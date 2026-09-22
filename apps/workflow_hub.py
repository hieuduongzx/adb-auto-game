"""Macro2k Hub — game library launcher.

Shows every game project under ``workflows/`` as a cover card
(``workflows/<Name>/assets/cover.png``) and launches the Runner (Run) or
Designer (Edit). **New game** scaffolds ``workflows/<Name>/workflow.json`` and
opens the Designer on it.

This is the default entry of ``Macro2k.exe`` (see
``packaging/entry_designer.py``). Run from source::

    python apps/workflow_hub.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# --- bootstrap: make `src.*` importable when run from apps/ ---------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import webview

from src.utils import (
    APP_VERSION,
    app_dir,
    bundle_dir,
    data_root,
    file_url,
    is_frozen,
    launch_tool,
    load_ui_settings,
    sanitize_name as _sanitize_name,
    save_ui_settings,
    source_python,
    theme_background,
    titled,
    webview_storage_path,
)

# In a frozen build, writable resources (workflows/, data/) live under data_root()
# — next to the app when writable, else %LOCALAPPDATA% (read-only Program Files).
if is_frozen():
    _PROJECT_ROOT = data_root()

def _is_source_root(path: str) -> bool:
    """Whether *path* contains the source toolchain required to build a Runner."""
    return all(os.path.isfile(os.path.join(path, rel)) for rel in (
        os.path.join("packaging", "build_runner.py"),
        os.path.join("packaging", "runner_build.spec"),
        os.path.join("packaging", "entry_runner_single.py"),
    ))


def _find_source_root() -> str:
    """Find the checkout behind a development ``dist/Macro2k`` build.

    ``dist/Macro2k/Macro2k.exe`` is two directories below the checkout. An
    installed release has no checkout and therefore cannot build a Runner;
    return an empty string so ``build_info`` can explain that explicitly.
    ``MACRO2K_SOURCE_ROOT`` supports non-standard layouts.
    """
    if not is_frozen():
        return _PROJECT_ROOT
    exe_dir = app_dir()
    candidates = [
        os.environ.get("MACRO2K_SOURCE_ROOT", ""),
        os.path.abspath(os.path.join(exe_dir, os.pardir, os.pardir)),
        os.getcwd(),
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate) if candidate else ""
        if candidate and _is_source_root(candidate):
            return candidate
    return ""


def _build_python() -> str:
    """Python from the source checkout, or a real interpreter on PATH."""
    parts = ("Scripts", "python.exe") if sys.platform == "win32" else ("bin", "python")
    if _SOURCE_ROOT:
        project_python = os.path.join(_SOURCE_ROOT, ".venv", *parts)
        if os.path.isfile(project_python):
            return project_python
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            return found
    return source_python()


_SOURCE_ROOT = _find_source_root()

_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
_DEFAULT_WORKFLOWS_DIR = os.path.join(_PROJECT_ROOT, "workflows")


def _workflows_dir() -> str:
    """Folder the library lists and creates games in.

    A custom path from Hub settings wins when it still exists; otherwise the
    default ``workflows/`` next to the app.
    """
    custom = str((load_ui_settings() or {}).get("workflowsDir") or "").strip()
    if custom and os.path.isdir(custom):
        return os.path.abspath(custom)
    return _DEFAULT_WORKFLOWS_DIR
_TEMPLATES_DIRNAME = "templates"
# Cover art and icon looked up in <project>/assets/, first match wins.
_COVER_NAMES = ("cover.png", "cover.jpg", "cover.jpeg", "cover.webp")
_ICON_NAMES = ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.ico")
# Internal handoff / scratch folder — never listed as a user workflow.
_SKIP_DIRS = {"_run", "__pycache__"}


def _norm_controller(raw: str) -> str:
    return "win32" if str(raw or "").strip().lower() == "win32" else "adb"


def _norm_capture(raw: str) -> str:
    return "adb" if str(raw or "").strip().lower() == "adb" else "scrcpy"


_WIN_INPUT_MODES: Optional[tuple] = None


def _win_input_modes() -> tuple:
    """Every Win32 input transport the controller accepts.

    Read from ``src/core/win32/automation.py`` so the Hub can never silently
    downgrade a mode the engine supports (it used to coerce ``anchored_touch``
    and ``unity_bridge`` back to ``background`` on create)."""
    global _WIN_INPUT_MODES
    if _WIN_INPUT_MODES is None:
        try:
            from src.core.win32.automation import _INPUT_MODES
            _WIN_INPUT_MODES = tuple(_INPUT_MODES)
        except Exception:
            _WIN_INPUT_MODES = ("background", "background_sync", "background_cursor",
                                "background_window", "anchored_touch", "unity_bridge",
                                "foreground")
    return _WIN_INPUT_MODES


def _norm_input_mode(raw: str) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in _win_input_modes() else "background"


def _blank_flow(
    name: str,
    controller: str = "adb",
    capture: str = "scrcpy",
    input_mode: str = "background",
) -> dict:
    """Minimal valid workflow matching the designer's *New* seed shape.

    *controller*: ``adb`` | ``win32``
    *capture*: ``scrcpy`` | ``adb`` (ADB frame source; kept for win32 too so a
    later switch back to ADB remembers the choice).
    *input_mode*: Win32 ``background`` | ``background_sync`` |
    ``background_cursor`` | ``foreground``.
    """
    ctrl = _norm_controller(controller)
    cap = _norm_capture(capture)
    mode = _norm_input_mode(input_mode)
    return {
        "name": name,
        "version": 2,
        "templatesDir": _TEMPLATES_DIRNAME,
        "controller": ctrl,
        "capture": cap,
        "package": "",
        "win32": {
            "window": "",
            "matchBy": "title",
            "inputMode": mode,
        },
        "speedhack": {
            "enabled": False,
            "speed": 2,
            # Frida speed-hack is ADB-only; always start disabled for win32.
            "package": "",
        },
        "globals": [],
        "functions": [],
        "activities": [
            {
                "id": "sequence_1",
                "name": "Activity 1",
                "type": "sequence",
                "enabled": True,
                "vars": [],
                "graph": {
                    "nodes": [
                        {"id": "nstart", "type": "start", "x": 60, "y": 70, "params": {}},
                    ],
                    "edges": [],
                    "groups": [],
                },
                "maxRetries": 1,
            }
        ],
    }


def _find_workflow_json(folder: str) -> Optional[str]:
    """Pick the primary JSON in a workflow folder.

    Preference order:
      1. ``workflow.json``
      2. ``<folder-name>.json``
      3. first ``*.json`` (alphabetically)
    """
    if not os.path.isdir(folder):
        return None
    names = [n for n in os.listdir(folder) if n.lower().endswith(".json")]
    if not names:
        return None
    lower = {n.lower(): n for n in names}
    if "workflow.json" in lower:
        return os.path.join(folder, lower["workflow.json"])
    base = os.path.basename(folder)
    cand = f"{base}.json"
    if cand.lower() in lower:
        return os.path.join(folder, lower[cand.lower()])
    names.sort(key=str.lower)
    return os.path.join(folder, names[0])


def _find_cover(folder: str) -> str:
    return _find_asset(folder, _COVER_NAMES)


def _find_icon(folder: str) -> str:
    return _find_asset(folder, _ICON_NAMES)


def _find_asset(folder: str, names: tuple) -> str:
    """``file://`` URL of the first ``<folder>/assets/<name>`` that exists, or "".

    The file's mtime rides as a query string so a replaced image shows up on
    the next refresh instead of the WebView's cached copy."""
    assets = os.path.join(folder, "assets")
    for name in names:
        path = os.path.join(assets, name)
        if os.path.isfile(path):
            try:
                stamp = int(os.path.getmtime(path))
            except OSError:
                stamp = 0
            return f"{file_url(path)}?v={stamp}"
    return ""


_REPO_RE = re.compile(r"[\w.-]+/[\w.-]+")
_BUILD_LOG_LIMIT = 4000


def _repo_slug(url_or_slug: str) -> str:
    """``https://github.com/owner/name(.git)`` or ``owner/name`` → ``owner/name``."""
    text = re.sub(r"^https?://github\.com/", "", str(url_or_slug or "").strip()).strip("/")
    return text[:-4] if text.endswith(".git") else text


def _remember_update_repo(flow_path: str, repo: str) -> None:
    """Store ``runnerUpdate.repo`` in the workflow JSON as soon as a build starts.

    build_runner.py records it too, but only after a successful build — so a
    repo changed in the Build dialog was forgotten whenever the build or its
    publish failed. Best effort: that later save still runs on success."""
    try:
        with open(flow_path, "r", encoding="utf-8") as fh:
            flow = json.load(fh) or {}
        update = flow.get("runnerUpdate") if isinstance(flow.get("runnerUpdate"), dict) else {}
        if update.get("repo") == repo:
            return
        update["repo"] = repo
        flow["runnerUpdate"] = update
        with open(flow_path, "w", encoding="utf-8") as fh:
            json.dump(flow, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except Exception:
        pass


def _bump_patch(version: str) -> str:
    """``1.2.3`` → ``1.2.4`` (padded to three parts)."""
    nums = [int(p) for p in re.findall(r"\d+", version or "")][:3]
    nums += [0] * (3 - len(nums))
    nums[2] += 1
    return ".".join(str(n) for n in nums)


_build_module: Any = None


def _pyinstaller_installed(python: str) -> bool:
    """Whether ``python`` can import PyInstaller.

    Checked in a subprocess because a frozen build's own interpreter is the
    app executable, and the build runs under the system Python instead.
    """
    try:
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        proc = subprocess.run(
            [python, "-c", "import PyInstaller"],
            capture_output=True, timeout=30, creationflags=flags,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _load_build_module() -> Any:
    """``packaging/build_runner.py`` as a module (for its vendor/name rules), or None."""
    global _build_module
    if _build_module is None:
        script = os.path.join(_SOURCE_ROOT, "packaging", "build_runner.py")
        if not os.path.isfile(script):
            return None
        spec = importlib.util.spec_from_file_location("macro2k_build_runner", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        _build_module = module
    return _build_module


def _read_meta(path: str, folder_name: str) -> Dict[str, Any]:
    name = folder_name
    controller = "adb"
    capture = "scrcpy"
    activity_count = 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        if isinstance(data, dict):
            raw_name = (data.get("name") or "").strip()
            if raw_name:
                name = raw_name
            controller = _norm_controller(data.get("controller"))
            raw_cap = data.get("capture")
            if raw_cap is None:
                raw_cap = data.get("captureBackend", data.get("capture_backend", ""))
            capture = _norm_capture(raw_cap)
            acts = data.get("activities") or []
            if isinstance(acts, list):
                activity_count = len(acts)
    except Exception:
        pass

    mtime = 0.0
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        pass
    modified = ""
    modified_iso = ""
    if mtime:
        try:
            dt = datetime.fromtimestamp(mtime)
            modified = dt.strftime("%Y-%m-%d %H:%M")
            modified_iso = dt.isoformat(timespec="seconds")
        except Exception:
            modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))

    file_name = os.path.basename(path)
    rel = os.path.join(folder_name, file_name).replace("\\", "/")
    return {
        "name": name,
        "folder": folder_name,
        "file": file_name,
        "relPath": rel,
        "path": path,
        "cover": _find_cover(os.path.dirname(path)),
        "icon": _find_icon(os.path.dirname(path)),
        "controller": controller,
        "capture": capture,
        "activityCount": activity_count,
        "modified": modified,
        "modifiedIso": modified_iso,
        "mtime": mtime,
    }


# ── Recent interaction ───────────────────────────────────────────────────────
# A per-game "last touched from the Hub" timestamp, bumped when a game is run,
# edited, or built. Kept under data/ so it survives restarts; the library orders
# by the newest of this and the workflow file's own mtime (which the Designer
# and the build both move).
_RECENT_PATH = os.path.join(data_root(), "data", "recent_games.json")
_RECENT_LOCK = threading.Lock()


def _norm_game_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path or "")))
    except Exception:
        return str(path or "")


def _load_recent() -> Dict[str, float]:
    try:
        with open(_RECENT_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
        if isinstance(data, dict):
            return {str(k): float(v) for k, v in data.items() if v is not None}
    except Exception:
        pass
    return {}


def _touch_recent(path: str) -> None:
    """Record that *path* was just interacted with (run / edit / build)."""
    key = _norm_game_path(path)
    if not key:
        return
    with _RECENT_LOCK:
        data = _load_recent()
        data[key] = time.time()
        cutoff = time.time() - 180 * 86400        # forget games untouched for ~6 months
        data = {k: v for k, v in data.items() if v >= cutoff}
        try:
            os.makedirs(os.path.dirname(_RECENT_PATH), exist_ok=True)
            tmp = _RECENT_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, _RECENT_PATH)
        except Exception:
            pass


class WorkflowHubAPI:
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        self._window: Optional[webview.Window] = None
        # One standalone-Runner build at a time: its state, full log, and the
        # lines not yet pushed to the page (batched so PyInstaller's chatter
        # doesn't turn into thousands of evaluate_js calls).
        self._build_lock = threading.Lock()
        self._build: Optional[Dict[str, Any]] = None
        self._build_log: List[str] = []
        self._build_pending: List[str] = []
        self._build_pushed_at = 0.0
        self._build_proc: Optional[subprocess.Popen] = None

    def _attach(self, window: webview.Window) -> None:
        self._window = window

    def app_version(self) -> str:
        """Version string for the Hub UI badge (see ``src/version.py``)."""
        return APP_VERSION

    # ── Shared UI settings ───────────────────────────────────────────────────
    # Backed by the same file the Designer writes, so a theme or density picked
    # in any window is what every other window opens with. ``web/shared/
    # theme.js`` calls both of these.
    def get_settings(self) -> dict:
        return load_ui_settings()

    def save_settings(self, settings: dict) -> bool:
        return save_ui_settings(settings)

    # ── Auto-update (Velopack) ───────────────────────────────────────────────
    def update_check(self) -> dict:
        """Check the release feed for a newer version (blocking network call;
        pywebview runs each api call off the UI thread). Returns the dict from
        :func:`src.updater.check`."""
        from src.updater import check
        return check()

    def update_apply(self) -> dict:
        """Download + install the latest release, then restart into it. On
        success the process is relaunched and this never returns. Download
        progress is pushed to the Hub UI via ``window.__updateProgress(pct)``."""
        from src.updater import apply_latest

        def _push(pct: int) -> None:
            w = self._window
            if w is None:
                return
            try:
                w.evaluate_js(f"window.__updateProgress && window.__updateProgress({int(pct)})")
            except Exception:
                pass

        return apply_latest(_push)

    # ── Game library ─────────────────────────────────────────────────────────
    def list_workflows(self) -> dict:
        """Return every game project under ``workflows/``, newest interaction first.

        A game's place is its last interaction — run, edit, or build — so the
        ones you touched most recently sit at the top. Falls back to the
        workflow file's own mtime (Designer saves and builds move it), then the
        display name for stability."""
        items: List[Dict[str, Any]] = []
        recent = _load_recent()
        root = _workflows_dir()
        if os.path.isdir(root):
            try:
                entries = sorted(os.listdir(root), key=str.lower)
            except Exception:
                entries = []
            for name in entries:
                if name.startswith(".") or name in _SKIP_DIRS:
                    continue
                folder = os.path.join(root, name)
                if not os.path.isdir(folder):
                    continue
                path = _find_workflow_json(folder)
                if not path:
                    continue
                meta = _read_meta(path, name)
                used = recent.get(_norm_game_path(path), 0.0)
                meta["lastUsed"] = used
                meta["recency"] = max(used, float(meta.get("mtime") or 0.0))
                items.append(meta)
        items.sort(key=lambda w: (-(w.get("recency") or 0.0),
                                  (w.get("name") or "").lower(),
                                  w.get("folder") or ""))
        return {"dir": root, "workflows": items}

    def run_workflow(self, path: str) -> bool:
        """Launch the Runner GUI preloaded with *path*."""
        path = (path or "").strip()
        if not path or not os.path.isfile(path):
            return False
        try:
            launch_tool("runner", [path])
            _touch_recent(path)
            return True
        except Exception:
            return False

    def edit_workflow(self, path: str) -> bool:
        """Launch the Designer with *path* open."""
        path = (path or "").strip()
        if not path or not os.path.isfile(path):
            return False
        try:
            launch_tool("designer", [path])
            _touch_recent(path)
            return True
        except Exception:
            return False

    # ── Build a standalone Runner .exe ───────────────────────────────────────
    def build_info(self, path: str) -> dict:
        """What building this game would produce, or why it can't be built.

        Feeds the Hub's Build dialog: exe name, output folder, the vendor tools
        the workflow needs, and the version to stamp (``buildVersion``)."""
        path = (path or "").strip()
        if not path or not os.path.isfile(path):
            return {"ok": False, "error": "Workflow file not found"}
        if not _SOURCE_ROOT:
            return {"ok": False, "error": "Source checkout not found. Run this build from dist/Macro2k, "
                                          "or set MACRO2K_SOURCE_ROOT."}
        module = _load_build_module()
        if module is None:
            return {"ok": False, "error": "packaging/build_runner.py is missing from the source checkout"}
        python = _build_python()
        if not _pyinstaller_installed(python):
            return {"ok": False, "error": f"PyInstaller is not installed for {python}. "
                                          "Run: python -m pip install pyinstaller"}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                flow = json.load(fh) or {}
        except Exception as exc:
            return {"ok": False, "error": f"Couldn't read workflow: {exc}"}
        folder = os.path.dirname(os.path.abspath(path))
        name = str(flow.get("name") or os.path.basename(folder))
        app_name = module._sanitize(name)
        out_folder = os.path.join(_SOURCE_ROOT, "dist", f"{app_name}-Runner")
        from src import runner_update
        from src.version import UPDATE_REPO_URL
        update = flow.get("runnerUpdate") if isinstance(flow.get("runnerUpdate"), dict) else {}
        repo = _repo_slug(update.get("repo") or UPDATE_REPO_URL)
        last = str(update.get("lastVersion") or "")
        prefix = module.tag_prefix(app_name)
        # Newest version already on GitHub, so the dialog can suggest past it.
        published = ""
        try:
            best = runner_update.latest_release(repo, prefix, runner_update.fetch_releases(repo, timeout=6))
            published = best["version"] if best else ""
        except Exception:
            pass
        newest = max((v for v in (last, published) if v), key=runner_update.parse_version, default="")
        has_gh = shutil.which("gh") is not None
        icon_preview = ""
        try:
            icon_preview = module.icon_preview_data_uri(folder, name, 64)
        except Exception:
            pass  # no Pillow in this Python — the build falls back as well
        return {
            "ok": True,
            "path": path,
            "name": name,
            "exeName": f"{app_name}.exe",
            "folder": out_folder,
            "exists": os.path.isdir(out_folder),
            "version": _bump_patch(newest) if newest else str(flow.get("buildVersion") or "1.0.0"),
            "lastVersion": last,
            "published": published,
            "repo": repo,
            "tagPrefix": prefix,
            "canPublish": has_gh,
            "publishNote": "" if has_gh else "Install the GitHub CLI (gh) to publish updates",
            "iconPreview": icon_preview,
            "iconSource": module.describe_icon_source(folder),
            "vendor": sorted(module.compute_vendor_needs(flow)),
            # workflows/<Name>/vendor/ → requirements/ beside the exe.
            "requirements": module.find_requirements(folder),
        }

    def build_runner(self, path: str, version: str = "", publish: bool = False,
                     repo: str = "", changelog: str = "", auto_show: bool = False,
                     dry_run: bool = False) -> dict:
        """Start building ``dist/<Name>-Runner/<Name>.exe`` in the background,
        optionally publishing it as this Runner's next GitHub Release.

        Progress, log lines and the result arrive through ``window.__buildEvent``;
        ``dry_run`` zips but skips the upload (tests)."""
        info = self.build_info(path)
        if not info.get("ok"):
            return info
        from src import runner_update
        version = str(version or info["version"]).strip()
        if not re.fullmatch(r"\d+(\.\d+){0,3}", version):
            return {"ok": False, "error": "Version must look like 1.0.0"}
        publish = bool(publish)
        repo = _repo_slug(repo or info["repo"])
        if not isinstance(changelog, str):
            return {"ok": False, "error": "Changelog must be text"}
        if len(changelog.encode("utf-8")) > 125_000:
            return {"ok": False, "error": "Changelog is too long (125 KB maximum)"}
        changelog = changelog if changelog.strip() else ""
        auto_show = bool(auto_show) if changelog else False
        if publish or dry_run:
            if not _REPO_RE.fullmatch(repo):
                return {"ok": False, "error": "Update repo must look like owner/name"}
            if publish and not info.get("canPublish"):
                return {"ok": False, "error": info.get("publishNote") or "Publishing needs the GitHub CLI"}
            published = info.get("published") or ""
            if published and runner_update.parse_version(version) <= runner_update.parse_version(published):
                return {"ok": False, "error": f"v{published} is already published — use a newer version"}
        if _REPO_RE.fullmatch(repo):
            _remember_update_repo(info["path"], repo)
        with self._build_lock:
            if self._build is not None and self._build.get("state") in ("running", "cancelling"):
                return {"ok": False, "error": f"Already building {self._build.get('name')}"}
            self._build = {
                "path": info["path"], "name": info["name"], "version": version,
                "publish": publish or dry_run, "repo": repo, "state": "running",
                "progress": 0, "stage": "Starting", "startedAt": time.time(), "endedAt": 0,
                "folder": info["folder"], "exe": "", "releaseUrl": "", "error": "",
                "requirements": "",
            }
            self._build_log = []
            self._build_pending = []
            state = dict(self._build)
        threading.Thread(
            target=self._build_worker,
            args=(info, version, publish, repo, dry_run, changelog, auto_show),
            daemon=True,
        ).start()
        return {"ok": True, **state}

    def build_state(self) -> dict:
        """The current or last build plus its full log, for a reloaded Hub page."""
        with self._build_lock:
            if not self._build:
                return {}
            return {**self._build, "log": list(self._build_log)}

    def cancel_build(self) -> bool:
        """Kill the running build (PyInstaller included)."""
        with self._build_lock:
            proc = self._build_proc
            if proc is None or not self._build or self._build.get("state") != "running":
                return False
            self._build.update(state="cancelling", stage="Cancelling")
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, creationflags=0x08000000)
            else:
                proc.kill()
        except Exception:
            pass
        self._update_build(force=True)
        return True

    def _update_build(self, lines: Optional[List[str]] = None, force: bool = False,
                      **changes: Any) -> None:
        """Apply state changes / new log lines and push them to the page.

        Log lines are batched: a push happens on any state change, when forced,
        or at most every 150 ms."""
        with self._build_lock:
            if self._build is None:
                return
            self._build.update(changes)
            if lines:
                self._build_log.extend(lines)
                if len(self._build_log) > _BUILD_LOG_LIMIT:
                    del self._build_log[:-_BUILD_LOG_LIMIT]
                self._build_pending.extend(lines)
            now = time.monotonic()
            if not (force or changes) and now - self._build_pushed_at < 0.15:
                return
            pending, self._build_pending = self._build_pending, []
            self._build_pushed_at = now
            payload = {**self._build, "lines": pending}
        win = self._window
        if win is None:
            return
        try:
            win.evaluate_js(f"window.__buildEvent && window.__buildEvent({json.dumps(payload)})")
        except Exception:
            pass

    def _build_worker(self, info: Dict[str, Any], version: str, publish: bool,
                      repo: str, dry_run: bool, changelog: str = "",
                      auto_show: bool = False) -> None:
        script = os.path.join(_SOURCE_ROOT, "packaging", "build_runner.py")
        folder = os.path.dirname(os.path.abspath(info["path"]))
        cmd = [_build_python(), "-u", script, "--workflow", folder, "--version", version,
               "--repo", repo, "--verbose", "--save-version",
               "--flow-path", info["path"]]
        notes_path = ""
        if (publish or dry_run) and changelog:
            fd, notes_path = tempfile.mkstemp(suffix=".md", prefix="m2k-notes-")
            os.close(fd)
            with open(notes_path, "w", encoding="utf-8") as fh:
                fh.write(changelog)
            cmd.extend(["--notes-file", notes_path])
            if auto_show:
                cmd.append("--auto-show")
        if publish:
            cmd.append("--publish")
        elif dry_run:
            cmd.append("--publish-dry-run")
        # build_runner prints non-ASCII (…, −); a cp1252 pipe would crash it.
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        exe_path = release_url = error = requirements = ""
        code = -1
        try:
            proc = subprocess.Popen(
                cmd, cwd=_SOURCE_ROOT, env=env, creationflags=flags,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            with self._build_lock:
                self._build_proc = proc
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if not line.strip():
                    continue
                if line.startswith(">> PROGRESS "):
                    pct, _, stage = line[len(">> PROGRESS "):].partition(" ")
                    if pct.isdigit():
                        self._update_build(progress=int(pct), stage=stage)
                    continue
                if line.startswith(">>"):
                    message = line[2:].strip()
                    if message.startswith("DONE:"):
                        exe_path = message[len("DONE:"):].strip()
                    elif message.startswith("RELEASE:"):
                        release_url = message[len("RELEASE:"):].strip()
                    elif message.startswith("REQUIREMENTS:"):
                        requirements = message[len("REQUIREMENTS:"):].strip()
                    elif message.startswith("BUILD FAILED:"):
                        error = message[len("BUILD FAILED:"):].strip()
                    # Milestones keep their ">> " so the log can set them apart.
                    self._update_build(lines=[f">> {message}"])
                else:
                    self._update_build(lines=[line[3:] if line.startswith(".. ") else line])
            code = proc.wait()
        except Exception as exc:
            error = str(exc)
        finally:
            if notes_path:
                try:
                    os.remove(notes_path)
                except OSError:
                    pass
        with self._build_lock:
            self._build_proc = None
            cancelled = bool(self._build and self._build.get("state") == "cancelling")
        ended = time.time()
        if cancelled:
            self._update_build(force=True, state="cancelled", stage="Cancelled", endedAt=ended)
        elif code == 0 and exe_path:
            _touch_recent(info.get("path") or "")
            self._update_build(force=True, state="done", progress=100,
                               stage="Published" if release_url else "Built",
                               exe=exe_path, folder=os.path.dirname(exe_path),
                               releaseUrl=release_url, requirements=requirements,
                               endedAt=ended)
        else:
            self._update_build(force=True, state="failed", stage="Failed", endedAt=ended,
                               error=error or f"build_runner exited with code {code}")

    def open_url(self, url: str) -> bool:
        """Open a GitHub page (a published release) in the default browser."""
        url = str(url or "")
        if not url.startswith("https://github.com/"):
            return False
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception:
            return False

    def open_folder(self, path: str) -> bool:
        """Reveal a build output folder in Explorer."""
        path = os.path.abspath(str(path or ""))
        if not os.path.isdir(path):
            return False
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    def delete_workflow(self, path: str) -> dict:
        """Delete a workflow folder (JSON + templates + assets) under ``workflows/``.

        Only paths that resolve inside the configured workflows folder are accepted.
        Deletes the whole project folder (e.g. ``workflows/GirlWars/``).

        Returns ``{ok: true, folder}`` or ``{ok: false, error}``.
        """
        path = (path or "").strip()
        if not path:
            return {"ok": False, "error": "No path"}
        try:
            abs_path = os.path.abspath(path)
            root = os.path.abspath(_workflows_dir())
            # Must live under workflows/ (and not be the root itself).
            try:
                common = os.path.commonpath([root, abs_path])
            except ValueError:
                return {"ok": False, "error": "Invalid path"}
            if common != root:
                return {"ok": False, "error": "Path outside workflows/"}
            if not os.path.isfile(abs_path):
                return {"ok": False, "error": "Workflow file not found"}

            folder = os.path.dirname(abs_path)
            # Only delete one level under workflows/ — never nested or root.
            if os.path.dirname(folder) != root:
                return {"ok": False, "error": "Not a workflow project folder"}
            folder_name = os.path.basename(folder)
            if folder_name in _SKIP_DIRS or folder_name.startswith("."):
                return {"ok": False, "error": f"Protected folder: {folder_name}"}

            shutil.rmtree(folder)
            return {"ok": True, "folder": folder_name, "path": abs_path}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def create_workflow(
        self,
        name: str = "",
        controller: str = "adb",
        capture: str = "scrcpy",
        input_mode: str = "background",
    ) -> dict:
        """Scaffold ``workflows/<Name>/workflow.json`` (+ empty templates/ and assets/).

        *controller*: ``adb`` | ``win32``
        *capture*: ``scrcpy`` | ``adb`` (ADB screen-capture backend)
        *input_mode*: Win32 input delivery mode (ignored by ADB workflows)

        Returns ``{ok, path, name, controller, capture}`` or ``{ok: false, error}``.
        """
        clean = _sanitize_name(name)
        if not clean:
            return {"ok": False, "error": "Name is required"}
        if clean in _SKIP_DIRS or clean.startswith("_"):
            return {"ok": False, "error": f"Reserved name: {clean}"}

        folder = os.path.join(_workflows_dir(), clean)
        path = os.path.join(folder, "workflow.json")
        if os.path.exists(path):
            return {"ok": False, "error": f"Already exists: {clean}/workflow.json"}
        if os.path.isdir(folder) and _find_workflow_json(folder):
            return {"ok": False, "error": f"Folder already has a workflow: {clean}"}

        display = (name or "").strip() or clean
        ctrl = _norm_controller(controller)
        cap = _norm_capture(capture)
        mode = _norm_input_mode(input_mode)
        try:
            os.makedirs(os.path.join(folder, _TEMPLATES_DIRNAME), exist_ok=True)
            # Where the Hub looks for the cover art (assets/cover.png).
            os.makedirs(os.path.join(folder, "assets"), exist_ok=True)
            flow = _blank_flow(display, controller=ctrl, capture=cap, input_mode=mode)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(flow, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            _touch_recent(path)
            return {
                "ok": True,
                "path": path,
                "name": display,
                "folder": clean,
                "controller": ctrl,
                "capture": cap,
                "inputMode": mode,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def get_workflows_dir(self) -> dict:
        """Current library folder and whether it is the built-in default."""
        current = _workflows_dir()
        return {"dir": current, "custom": os.path.abspath(current) != os.path.abspath(_DEFAULT_WORKFLOWS_DIR)}

    def pick_workflows_dir(self) -> dict:
        """Folder picker for the library. Returns the chosen path, or "" if cancelled."""
        win = self._window
        if win is None:
            return {"ok": False, "error": "Window is not ready"}
        start = _workflows_dir()
        start_dir = start if os.path.isdir(start) else ""
        try:
            paths = win.create_file_dialog(webview.FOLDER_DIALOG, directory=start_dir)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not paths:
            return {"ok": False, "cancelled": True, "dir": ""}
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return {"ok": True, "dir": str(path)}

    def set_workflows_dir(self, path: str) -> dict:
        """Point the library at ``path``. An empty path restores the default folder."""
        raw = str(path or "").strip()
        if not raw:
            save_ui_settings({"workflowsDir": None})
            return {"ok": True, "dir": _workflows_dir()}
        folder = os.path.abspath(raw)
        if not os.path.isdir(folder):
            return {"ok": False, "error": "Folder does not exist"}
        if not save_ui_settings({"workflowsDir": folder}):
            return {"ok": False, "error": "Couldn't save the folder"}
        return {"ok": True, "dir": folder}

# ── Entry points ────────────────────────────────────────────────────────────

# Landscape library: five cover cards per row with two rows in view. The window
# is resizable; hub.css sizes the cards from the window so two rows always fit.
# Keep this simple: no native WinForms max-size hooks (those hung the UI thread).
_HUB_SIZE = (1280, 820)
_HUB_MIN_SIZE = (1040, 700)


def create_hub_window(title: str = titled()) -> webview.Window:
    api = WorkflowHubAPI()
    html_path = os.path.join(_WEB_DIR, "hub", "index.html")
    url = file_url(html_path)
    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=_HUB_SIZE[0],
        height=_HUB_SIZE[1],
        resizable=True,
        fullscreen=False,
        maximized=False,
        min_size=_HUB_MIN_SIZE,
        background_color=theme_background(),
    )
    window.events.loaded += lambda: api._attach(window)
    return window


def run() -> None:
    # No DPI shim here — designer needs it for the canvas; on the hub it can
    # interact badly with WebView2 sizing. pywebview/WinForms already handle DPI.
    create_hub_window()
    # Per-app WebView2 profile — Designer/Runner launch as sibling processes.
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=webview_storage_path("hub"),
    )


if __name__ == "__main__":
    run()
