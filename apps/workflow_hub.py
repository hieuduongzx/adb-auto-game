"""Macro2k Hub — navigation dashboard for workflows.

Lists every workflow under ``workflows/``, and launches the Runner (Run) or
Designer (Edit). **New workflow** scaffolds ``workflows/<Name>/workflow.json``
and opens the Designer on it.

This is the default entry of ``Macro2k.exe`` (see
``packaging/entry_designer.py``). Run from source::

    python apps/workflow_hub.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
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
    bundle_dir,
    data_root,
    file_url,
    is_frozen,
    launch_tool,
    titled,
    webview_storage_path,
)

# In a frozen build, writable resources (workflows/, data/) live under data_root()
# — next to the app when writable, else %LOCALAPPDATA% (read-only Program Files).
if is_frozen():
    _PROJECT_ROOT = data_root()

_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
_WORKFLOWS_DIR = os.path.join(_PROJECT_ROOT, "workflows")
_AUTOCLICKS_DIR = os.path.join(_PROJECT_ROOT, "autoclicks")
_TEMPLATES_DIRNAME = "templates"
_AUTOCLICK_SETTINGS = os.path.join(_PROJECT_ROOT, "data", "autoclick_settings.json")
# Internal handoff / scratch folder — never listed as a user workflow.
_SKIP_DIRS = {"_run", "__pycache__"}


def _sanitize_name(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", (raw or "").strip())
    return cleaned.strip("._-")


def _norm_controller(raw: str) -> str:
    return "win32" if str(raw or "").strip().lower() == "win32" else "adb"


def _norm_capture(raw: str) -> str:
    return "adb" if str(raw or "").strip().lower() == "adb" else "scrcpy"


def _norm_input_mode(raw: str) -> str:
    mode = str(raw or "").strip().lower()
    return mode if mode in {"background", "background_sync", "background_cursor", "foreground"} else "background"


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
        self._click_lock = threading.RLock()
        self._click_stop = threading.Event()
        self._click_thread: Optional[threading.Thread] = None
        self._hotkey_thread: Optional[threading.Thread] = None
        self._hotkey_thread_id = 0
        self._hotkeys_ok = False
        self._autoclick_view_active = threading.Event()
        self._click_config = self._load_click_config()
        self._click_state: Dict[str, Any] = {
            "running": False, "count": 0, "cycles": 0, "activePointId": "",
            "startedAt": 0.0, "elapsed": 0.0, "status": "Ready", "error": "",
        }

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        self._start_hotkeys()

    def app_version(self) -> str:
        """Version string for the Hub UI badge (see ``src/version.py``)."""
        return APP_VERSION

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

    # ── Auto Click ──────────────────────────────────────────────────────────
    @staticmethod
    def _default_click_config() -> Dict[str, Any]:
        return {
            "profileName": "Untitled sequence", "selectedPointId": "point-1",
            "points": [{
                "id": "point-1", "label": "Point 1", "enabled": True,
                "targetMode": "fixed", "x": 0, "y": 0,
                "button": "left", "clickType": "single",
            }],
            "intervalMs": 250, "startDelaySec": 0,
            "infinite": True, "count": 100,
        }

    @staticmethod
    def _copy_click_config(config: dict) -> dict:
        return json.loads(json.dumps(config, ensure_ascii=False))

    def _load_click_config(self) -> Dict[str, Any]:
        cfg = self._default_click_config()
        try:
            with open(_AUTOCLICK_SETTINGS, "r", encoding="utf-8") as fh:
                raw = json.load(fh) or {}
            if isinstance(raw, dict):
                cfg = raw
        except Exception:
            pass
        return self._normalise_click_config(cfg)

    @classmethod
    def _normalise_click_config(cls, raw: Optional[dict]) -> Dict[str, Any]:
        src = dict(raw or {})
        if isinstance(src.get("settings"), dict):
            src = {**src["settings"], "points": src.get("points", []),
                   "profileName": src.get("name") or src.get("profileName")}
        cfg = cls._default_click_config()
        cfg["profileName"] = str(src.get("profileName") or "Untitled sequence").strip()[:100]
        cfg["infinite"] = bool(src.get("infinite", True))
        for key, default, lo, hi in (
            ("intervalMs", 250, 10, 600000), ("startDelaySec", 0, 0, 3600),
            ("count", 100, 1, 1000000),
        ):
            try:
                val = int(float(src.get(key, default)))
            except (TypeError, ValueError):
                val = default
            cfg[key] = max(lo, min(hi, val))

        points_raw = src.get("points")
        if not isinstance(points_raw, list):
            points_raw = [{
                "id": "point-1", "label": "Point 1", "enabled": True,
                "targetMode": src.get("targetMode", "fixed"),
                "x": src.get("x", 0), "y": src.get("y", 0),
                "button": src.get("button", "left"),
                "clickType": src.get("clickType", "single"),
            }]
        points: List[Dict[str, Any]] = []
        used_ids = set()
        for index, item in enumerate(points_raw[:500]):
            if not isinstance(item, dict):
                continue
            point_id = re.sub(r"[^A-Za-z0-9_-]", "", str(item.get("id") or ""))[:40]
            if not point_id or point_id in used_ids:
                point_id = f"point-{index + 1}"
                while point_id in used_ids:
                    point_id += "x"
            used_ids.add(point_id)
            try:
                x = max(-100000, min(100000, int(float(item.get("x", 0)))))
                y = max(-100000, min(100000, int(float(item.get("y", 0)))))
            except (TypeError, ValueError):
                x, y = 0, 0
            points.append({
                "id": point_id,
                "label": str(item.get("label") or f"Point {index + 1}").strip()[:80] or f"Point {index + 1}",
                "enabled": bool(item.get("enabled", True)),
                "targetMode": "cursor" if item.get("targetMode") == "cursor" else "fixed",
                "x": x, "y": y,
                "button": item.get("button") if item.get("button") in {"left", "right", "middle"} else "left",
                "clickType": "double" if item.get("clickType") == "double" else "single",
            })
        cfg["points"] = points
        selected = str(src.get("selectedPointId") or "")
        cfg["selectedPointId"] = selected if selected in used_ids else (points[0]["id"] if points else "")
        return cfg

    def _save_click_config(self) -> None:
        try:
            os.makedirs(os.path.dirname(_AUTOCLICK_SETTINGS), exist_ok=True)
            with open(_AUTOCLICK_SETTINGS, "w", encoding="utf-8") as fh:
                json.dump(self._click_config, fh, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _push_click(self, event: str, data: Optional[dict] = None) -> None:
        win = self._window
        if win is None:
            return
        payload = json.dumps(data or {}, ensure_ascii=False)
        try:
            win.evaluate_js(f"window.__autoClickEvent && window.__autoClickEvent({json.dumps(event)}, {payload})")
        except Exception:
            pass

    @staticmethod
    def _cursor_pos() -> Optional[tuple]:
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return int(pt.x), int(pt.y)
        except Exception:
            pass
        return None

    def autoclick_state(self) -> dict:
        with self._click_lock:
            return {
                **self._click_state,
                "config": self._copy_click_config(self._click_config),
                "hotkeys": self._hotkeys_ok,
                "platform": sys.platform,
                "profilesDir": _AUTOCLICKS_DIR,
            }

    def autoclick_set_view_active(self, active: bool) -> bool:
        """Enable capture hotkeys only while the Auto Click view is open."""
        if active:
            self._autoclick_view_active.set()
        else:
            self._autoclick_view_active.clear()
        return True

    def autoclick_configure(self, config: dict) -> dict:
        with self._click_lock:
            if self._click_state["running"]:
                return {"ok": False, "error": "Stop Auto Click before changing settings."}
            self._click_config = self._normalise_click_config(config)
            self._save_click_config()
            return {"ok": True, "config": self._copy_click_config(self._click_config)}

    def autoclick_select_point(self, point_id: str) -> bool:
        with self._click_lock:
            if point_id not in {point["id"] for point in self._click_config["points"]}:
                return False
            self._click_config["selectedPointId"] = point_id
            self._save_click_config()
            return True

    def autoclick_add_point_at_cursor(self) -> dict:
        pos = self._cursor_pos()
        if pos is None:
            return {"ok": False, "error": "Cursor position is only available on Windows."}
        with self._click_lock:
            if self._click_state["running"]:
                return {"ok": False, "error": "Stop Auto Click before adding a point."}
            used = {point["id"] for point in self._click_config["points"]}
            point_id = f"point-{int(time.time() * 1000)}"
            while point_id in used:
                point_id += "x"
            point = {
                "id": point_id,
                "label": f"Point {len(self._click_config['points']) + 1}",
                "enabled": True, "targetMode": "fixed",
                "x": pos[0], "y": pos[1], "button": "left", "clickType": "single",
            }
            self._click_config["points"].append(point)
            self._click_config["selectedPointId"] = point_id
            self._save_click_config()
            result = {"ok": True, "point": self._copy_click_config(point)}
        self._push_click("point-added", result)
        return result

    def autoclick_capture_position(self, point_id: str = "") -> dict:
        pos = self._cursor_pos()
        if pos is None:
            return {"ok": False, "error": "Cursor position is only available on Windows."}
        with self._click_lock:
            if self._click_state["running"]:
                return {"ok": False, "error": "Stop Auto Click before capturing a position."}
            wanted = point_id or self._click_config.get("selectedPointId")
            point = next((p for p in self._click_config["points"] if p["id"] == wanted), None)
            if point is None and self._click_config["points"]:
                point = self._click_config["points"][0]
            if point is None:
                return {"ok": False, "error": "Add a point before capturing a position."}
            point["x"], point["y"] = pos
            self._click_config["selectedPointId"] = point["id"]
            self._save_click_config()
            result = {"ok": True, "pointId": point["id"], "x": pos[0], "y": pos[1]}
        self._push_click("position", result)
        return result

    @staticmethod
    def _profile_filename(name: str) -> str:
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(name or "").strip())
        clean = clean.rstrip(". ")[:80] or "Untitled sequence"
        return clean if clean.lower().endswith(".json") else clean + ".json"

    @staticmethod
    def _profile_path(filename: str) -> Optional[str]:
        raw = str(filename or "").strip()
        base = os.path.basename(raw)
        if not base or base != raw or not base.lower().endswith(".json"):
            return None
        path = os.path.abspath(os.path.join(_AUTOCLICKS_DIR, base))
        return path if os.path.dirname(path) == os.path.abspath(_AUTOCLICKS_DIR) else None

    def autoclick_list_profiles(self) -> dict:
        items: List[Dict[str, Any]] = []
        try:
            os.makedirs(_AUTOCLICKS_DIR, exist_ok=True)
            for filename in os.listdir(_AUTOCLICKS_DIR):
                if filename.startswith(".") or not filename.lower().endswith(".json"):
                    continue
                path = os.path.join(_AUTOCLICKS_DIR, filename)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        raw = json.load(fh)
                    config = self._normalise_click_config(raw if isinstance(raw, dict) else {})
                    items.append({
                        "filename": filename,
                        "name": str((raw or {}).get("name") or config["profileName"]),
                        "points": len(config["points"]), "modified": os.path.getmtime(path),
                    })
                except Exception:
                    items.append({"filename": filename, "name": os.path.splitext(filename)[0],
                                  "points": None, "invalid": True, "modified": os.path.getmtime(path)})
        except Exception as exc:
            return {"ok": False, "error": str(exc), "dir": _AUTOCLICKS_DIR, "profiles": []}
        items.sort(key=lambda item: (-(item.get("modified") or 0), item["name"].lower()))
        return {"ok": True, "dir": _AUTOCLICKS_DIR, "profiles": items}

    def autoclick_load_profile(self, filename: str) -> dict:
        path = self._profile_path(filename)
        if path is None or not os.path.isfile(path):
            return {"ok": False, "error": "Auto Click file not found."}
        with self._click_lock:
            if self._click_state["running"]:
                return {"ok": False, "error": "Stop Auto Click before loading a file."}
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                if not isinstance(raw, dict):
                    raise ValueError("The JSON root must be an object.")
                self._click_config = self._normalise_click_config(raw)
                self._save_click_config()
                return {"ok": True, "filename": os.path.basename(path),
                        "config": self._copy_click_config(self._click_config)}
            except Exception as exc:
                return {"ok": False, "error": f"Could not load file: {exc}"}

    def autoclick_save_profile(self, name: str, config: dict, filename: str = "", overwrite: bool = False) -> dict:
        with self._click_lock:
            if self._click_state["running"]:
                return {"ok": False, "error": "Stop Auto Click before saving."}
            clean_name = str(name or "").strip()[:100]
            if not clean_name:
                return {"ok": False, "error": "Sequence name is required."}
            target_name = filename or self._profile_filename(clean_name)
            path = self._profile_path(target_name)
            if path is None:
                return {"ok": False, "error": "Invalid filename."}
            if os.path.exists(path) and not overwrite:
                return {"ok": False, "exists": True, "filename": os.path.basename(path),
                        "error": "A sequence with this name already exists."}
            normal = self._normalise_click_config({**dict(config or {}), "profileName": clean_name})
            document = {
                "version": 1, "type": "macro2k-autoclick", "name": clean_name,
                "settings": {key: normal[key] for key in ("intervalMs", "startDelaySec", "infinite", "count")},
                "points": normal["points"],
            }
            try:
                os.makedirs(_AUTOCLICKS_DIR, exist_ok=True)
                temp = path + ".tmp"
                with open(temp, "w", encoding="utf-8") as fh:
                    json.dump(document, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                os.replace(temp, path)
                self._click_config = normal
                self._save_click_config()
                return {"ok": True, "filename": os.path.basename(path),
                        "config": self._copy_click_config(normal)}
            except Exception as exc:
                return {"ok": False, "error": f"Could not save file: {exc}"}

    def autoclick_open_folder(self) -> bool:
        try:
            os.makedirs(_AUTOCLICKS_DIR, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(_AUTOCLICKS_DIR)  # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["xdg-open", _AUTOCLICKS_DIR])
            return True
        except Exception:
            return False

    def autoclick_start(self, config: Optional[dict] = None) -> dict:
        if sys.platform != "win32":
            return {"ok": False, "error": "Auto Click currently requires Windows."}
        with self._click_lock:
            if self._click_state["running"]:
                return {"ok": True, **self.autoclick_state()}
            if config is not None:
                self._click_config = self._normalise_click_config(config)
                self._save_click_config()
            if not any(point["enabled"] for point in self._click_config["points"]):
                return {"ok": False, "error": "Add or enable at least one click point."}
            self._click_stop.clear()
            self._click_state.update({
                "running": True, "count": 0, "cycles": 0, "activePointId": "",
                "startedAt": time.time(), "elapsed": 0.0,
                "status": "Starting", "error": "",
            })
            self._click_thread = threading.Thread(target=self._click_loop, daemon=True)
            self._click_thread.start()
            state = self.autoclick_state()
        self._push_click("state", state)
        return {"ok": True, **state}

    def autoclick_stop(self) -> dict:
        self._click_stop.set()
        with self._click_lock:
            if self._click_state["running"]:
                self._click_state["status"] = "Stopping"
            state = self.autoclick_state()
        self._push_click("state", state)
        return {"ok": True, **state}

    @staticmethod
    def _mouse_click(button: str, double: bool) -> None:
        import ctypes
        flags = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }
        down, up = flags.get(button, flags["left"])
        user32 = ctypes.windll.user32
        for index in range(2 if double else 1):
            user32.mouse_event(down, 0, 0, 0, 0)
            user32.mouse_event(up, 0, 0, 0, 0)
            if index == 0 and double:
                time.sleep(0.05)

    def _click_loop(self) -> None:
        import ctypes
        with self._click_lock:
            cfg = self._copy_click_config(self._click_config)
        points = [point for point in cfg["points"] if point["enabled"]]
        completed = 0
        cycles = 0
        last_push = 0.0
        try:
            delay = cfg["startDelaySec"]
            if delay:
                with self._click_lock:
                    self._click_state["status"] = f"Starting in {delay}s"
                self._push_click("state", self.autoclick_state())
                if self._click_stop.wait(delay):
                    return
            with self._click_lock:
                self._click_state["status"] = "Clicking"
            self._push_click("state", self.autoclick_state())
            limit = None if cfg["infinite"] else cfg["count"]
            while not self._click_stop.is_set() and (limit is None or cycles < limit):
                cycle_complete = True
                for point_index, point in enumerate(points):
                    if self._click_stop.is_set():
                        cycle_complete = False
                        break
                    if point["targetMode"] == "fixed":
                        ctypes.windll.user32.SetCursorPos(point["x"], point["y"])
                    with self._click_lock:
                        self._click_state["activePointId"] = point["id"]
                    self._mouse_click(point["button"], point["clickType"] == "double")
                    completed += 1
                    now = time.monotonic()
                    with self._click_lock:
                        self._click_state["count"] = completed
                    if now - last_push >= 0.08:
                        self._push_click("tick", {"count": completed, "cycles": cycles,
                                                  "pointId": point["id"], "pointIndex": point_index})
                        last_push = now
                    final_action = (limit is not None and cycles + 1 >= limit and point_index == len(points) - 1)
                    if not final_action and self._click_stop.wait(cfg["intervalMs"] / 1000.0):
                        cycle_complete = False
                        break
                if cycle_complete:
                    cycles += 1
                    with self._click_lock:
                        self._click_state["cycles"] = cycles
                    self._push_click("tick", {"count": completed, "cycles": cycles, "pointId": ""})
        except Exception as exc:
            with self._click_lock:
                self._click_state["error"] = str(exc)
                self._click_state["status"] = "Error"
        finally:
            stopped = self._click_stop.is_set()
            with self._click_lock:
                self._click_state["running"] = False
                self._click_state["activePointId"] = ""
                self._click_state["elapsed"] = max(0.0, time.time() - self._click_state["startedAt"])
                if not self._click_state["error"]:
                    self._click_state["status"] = "Stopped" if stopped else "Completed"
                state = self.autoclick_state()
            self._push_click("state", state)

    def _toggle_click_hotkey(self) -> None:
        if self.autoclick_state()["running"]:
            self.autoclick_stop()
        else:
            self.autoclick_start()

    def _start_hotkeys(self) -> None:
        if sys.platform != "win32" or (self._hotkey_thread and self._hotkey_thread.is_alive()):
            return
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True)
        self._hotkey_thread.start()

    def _hotkey_loop(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._hotkey_thread_id = int(kernel32.GetCurrentThreadId())
            # MOD_NOREPEAT prevents held keys from rapidly toggling the clicker.
            ok6 = bool(user32.RegisterHotKey(None, 6001, 0x4000, 0x75))  # F6
            ok7 = bool(user32.RegisterHotKey(None, 6002, 0x4000, 0x76))  # F7
            ok8 = bool(user32.RegisterHotKey(None, 6003, 0x4000, 0x77))  # F8
            self._hotkeys_ok = ok6 and ok7 and ok8
            self._push_click("hotkeys", {"ok": self._hotkeys_ok})
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:  # WM_HOTKEY
                    if msg.wParam == 6001:
                        self._toggle_click_hotkey()
                    elif msg.wParam == 6002 and self._autoclick_view_active.is_set():
                        self.autoclick_capture_position()
                    elif msg.wParam == 6003 and self._autoclick_view_active.is_set():
                        self.autoclick_add_point_at_cursor()
            if ok6:
                user32.UnregisterHotKey(None, 6001)
            if ok7:
                user32.UnregisterHotKey(None, 6002)
            if ok8:
                user32.UnregisterHotKey(None, 6003)
        except Exception:
            self._hotkeys_ok = False
            self._push_click("hotkeys", {"ok": False})

    def shutdown(self) -> None:
        self._click_stop.set()
        if sys.platform == "win32" and self._hotkey_thread_id:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(self._hotkey_thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass

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
        input_mode: str = "background",
    ) -> dict:
        """Scaffold ``workflows/<Name>/workflow.json`` (+ empty templates/).

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

        folder = os.path.join(_WORKFLOWS_DIR, clean)
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
            flow = _blank_flow(display, controller=ctrl, capture=cap, input_mode=mode)
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
                "inputMode": mode,
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
        min_size=_HUB_MIN,
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    window.events.closed += api.shutdown
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
