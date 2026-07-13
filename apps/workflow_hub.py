"""Workflow2k Hub — navigation dashboard for workflows.

Lists every workflow under ``workflows/``, and launches the Runner (Run) or
Designer (Edit). **New workflow** scaffolds ``workflows/<Name>/workflow.json``
and opens the Designer on it.

This is the default entry of ``Workflow2k.exe`` (see
``packaging/entry_designer.py``). Run from source::

    python apps/workflow_hub.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

# --- bootstrap: make `src.*` importable when run from apps/ ---------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import webview

from src.utils import app_dir, bundle_dir, is_frozen, launch_tool

# In a frozen build, writable resources (workflows/, data/) live next to the .exe.
if is_frozen():
    _PROJECT_ROOT = app_dir()

_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
_WORKFLOWS_DIR = os.path.join(_PROJECT_ROOT, "workflows")
_TEMPLATES_DIRNAME = "templates"
# Internal handoff / scratch folder — never listed as a user workflow.
_SKIP_DIRS = {"_run", "__pycache__"}


def _sanitize_name(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", (raw or "").strip())
    return cleaned.strip("._-")


def _norm_controller(raw: str) -> str:
    return "win32" if str(raw or "").strip().lower() == "win32" else "adb"


def _norm_capture(raw: str) -> str:
    return "adb" if str(raw or "").strip().lower() == "adb" else "scrcpy"


def _blank_flow(
    name: str,
    controller: str = "adb",
    capture: str = "scrcpy",
) -> dict:
    """Minimal valid workflow matching the designer's *New* seed shape.

    *controller*: ``adb`` | ``win32``
    *capture*: ``scrcpy`` | ``adb`` (ADB frame source; kept for win32 too so a
    later switch back to ADB remembers the choice).
    """
    ctrl = _norm_controller(controller)
    cap = _norm_capture(capture)
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
            "inputMode": "background",
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
        "controller": controller,
        "capture": capture,
        "activityCount": activity_count,
        "modified": modified,
        "modifiedIso": modified_iso,
        "mtime": mtime,
    }


class WorkflowHubAPI:
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        self._window: Optional[webview.Window] = None

    def _attach(self, window: webview.Window) -> None:
        self._window = window

    def list_workflows(self) -> dict:
        """Return every workflow under ``workflows/`` (newest first)."""
        items: List[Dict[str, Any]] = []
        root = _WORKFLOWS_DIR
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
                items.append(_read_meta(path, name))
        items.sort(key=lambda w: (-(w.get("mtime") or 0), (w.get("name") or "").lower()))
        return {"dir": root, "workflows": items}

    def run_workflow(self, path: str) -> bool:
        """Launch the Runner GUI preloaded with *path*."""
        path = (path or "").strip()
        if not path or not os.path.isfile(path):
            return False
        try:
            launch_tool("runner", [path])
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
            return True
        except Exception:
            return False

    def delete_workflow(self, path: str) -> dict:
        """Delete a workflow folder (JSON + templates) under ``workflows/``.

        Only paths that resolve inside ``_WORKFLOWS_DIR`` are accepted.
        Deletes the whole project folder (e.g. ``workflows/GirlWars/``).

        Returns ``{ok: true, folder}`` or ``{ok: false, error}``.
        """
        path = (path or "").strip()
        if not path:
            return {"ok": False, "error": "No path"}
        try:
            abs_path = os.path.abspath(path)
            root = os.path.abspath(_WORKFLOWS_DIR)
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
    ) -> dict:
        """Scaffold ``workflows/<Name>/workflow.json`` (+ empty templates/).

        *controller*: ``adb`` | ``win32``
        *capture*: ``scrcpy`` | ``adb`` (ADB screen-capture backend)

        Returns ``{ok, path, name, controller, capture}`` or ``{ok: false, error}``.
        """
        clean = _sanitize_name(name)
        if not clean:
            return {"ok": False, "error": "Name is required"}
        if clean in _SKIP_DIRS or clean.startswith("_"):
            return {"ok": False, "error": f"Reserved name: {clean}"}

        folder = os.path.join(_WORKFLOWS_DIR, clean)
        path = os.path.join(folder, "workflow.json")
        if os.path.exists(path):
            return {"ok": False, "error": f"Already exists: {clean}/workflow.json"}
        if os.path.isdir(folder) and _find_workflow_json(folder):
            return {"ok": False, "error": f"Folder already has a workflow: {clean}"}

        display = (name or "").strip() or clean
        ctrl = _norm_controller(controller)
        cap = _norm_capture(capture)
        try:
            os.makedirs(os.path.join(folder, _TEMPLATES_DIRNAME), exist_ok=True)
            flow = _blank_flow(display, controller=ctrl, capture=cap)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(flow, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            return {
                "ok": True,
                "path": path,
                "name": display,
                "folder": clean,
                "controller": ctrl,
                "capture": cap,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def open_workflows_folder(self) -> bool:
        """Reveal the workflows directory in the OS file manager."""
        try:
            os.makedirs(_WORKFLOWS_DIR, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(_WORKFLOWS_DIR)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", _WORKFLOWS_DIR])
            return True
        except Exception:
            return False


# ── Entry points ────────────────────────────────────────────────────────────

# Portrait dashboard (taller than wide) — same family as the Runner panel.
# Keep this simple: no native WinForms max-size hooks (those hung the UI thread).
_HUB_SIZE = (500, 780)
_HUB_MIN = (420, 560)


def create_hub_window(title: str = "Workflow2k") -> webview.Window:
    api = WorkflowHubAPI()
    html_path = os.path.join(_WEB_DIR, "hub", "index.html")
    url = f"file:///{html_path.replace(os.sep, '/')}"
    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=_HUB_SIZE[0],
        height=_HUB_SIZE[1],
        resizable=True,
        fullscreen=False,
        maximized=False,
        min_size=_HUB_MIN,
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    return window


def run() -> None:
    # No DPI shim here — designer needs it for the canvas; on the hub it can
    # interact badly with WebView2 sizing. pywebview/WinForms already handle DPI.
    create_hub_window()
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    run()
