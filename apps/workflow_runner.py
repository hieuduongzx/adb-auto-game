"""PyWebView runner GUI for JSON workflows.

A sibling of ``apps/workflow_designer.py`` (a *loaded JSON file* drives this
one instead of the graph editor). Press **Load JSON** to pick a flow exported
from the designer; its sequence/background activities then appear with the
same enable toggles, Start / Stop / Pause controls, and live log.

The actual execution is delegated to :class:`src.workflow.WorkflowEngine`, so a
flow behaves identically here and in the designer's *Run test*.

Run::

    python apps/workflow_runner.py
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

# --- bootstrap: make `src.*` importable when run from apps/ ---------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import webview

from src.core.adb import kill_adb_server
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    get_capture_backend,
    set_capture_backend,
    stop_scrcpy_sources,
)
from src.workflow import WorkflowEngine
from src.utils import (
    add_log_subscriber,
    bundle_dir,
    data_root,
    file_url,
    is_frozen,
    log_error,
    log_info,
    log_success,
    log_warning,
    push_webview_event,
    remove_log_subscriber,
    titled,
    webview_storage_path,
)

# In a frozen build, writable resources (data/) live under data_root() — next to
# the app when writable, else %LOCALAPPDATA% (read-only Program Files install).
if is_frozen():
    _PROJECT_ROOT = data_root()

# Bundled HTML: ``apps/web`` from source, ``<_MEIPASS>/web`` when frozen.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))


class WorkflowRunnerAPI:
    """Methods exposed to JavaScript via ``pywebview.api.*``."""

    def __init__(self) -> None:
        self.engine = WorkflowEngine()
        self.flow: Dict[str, Any] = {}
        self.flow_path: Optional[str] = None
        self._runner_config: Dict[str, Any] = {}
        self._runner_config_path: Optional[str] = None
        self._runner_config_lock = threading.RLock()

        self._window: Optional[webview.Window] = None
        self._closing = False
        self._log_buffer: List[Dict] = []
        self._pending_load: Optional[str] = None  # flow path to auto-load on attach

        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None

        # Mirror engine running/paused into the UI.
        self.engine.on("on_start", self._on_engine_start)
        self.engine.on("on_stop", self._on_engine_stop)
        self.engine.on("on_activity_start",
                       lambda act: self._push("activity_update",
                                              {"id": act.get("id"), "status": "running"}))
        self.engine.on("on_activity_complete",
                       lambda act, ok: self._push("activity_update",
                                                  {"id": act.get("id"),
                                                   "status": "completed" if ok else "failed"}))

    # ── Setup ────────────────────────────────────────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log)
        if self._pending_load:
            try:
                self._load_path(self._pending_load)
            except Exception as exc:
                log_error(f"Auto-load failed: {exc}")
            self._pending_load = None
        threading.Thread(target=self._device_worker, args=(True,), daemon=True).start()
        threading.Thread(target=self._device_poll, daemon=True).start()

    def _on_engine_start(self) -> None:
        self._push("running_state", {"running": True, "paused": False})

    def _on_engine_stop(self) -> None:
        self._push("running_state", {"running": False, "paused": False})

    # ── Log subscriber ───────────────────────────────────────────────────────

    def _on_log(self, level: str, message: str) -> None:
        bucket = {"info": "info", "success": "success",
                  "warning": "warning", "error": "error"}.get(level, "info")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {"ts": ts, "level": bucket, "msg": message}
        self._log_buffer.append(entry)
        if len(self._log_buffer) > 2000:
            self._log_buffer = self._log_buffer[-2000:]
        self._push("log", entry)

    def _push(self, event_type: str, data: dict) -> None:
        if self._window is None or self._closing:
            return
        try:
            push_webview_event(self._window, event_type, data)
        except Exception:
            pass

    # ── State ────────────────────────────────────────────────────────────────

    def _config_path_for_flow(self, flow: dict, flow_path: str) -> str:
        """Readable per-workflow config: data/runner/<workflow>/config.json."""
        raw = str(flow.get("name") or "").strip()
        if not raw:
            raw = os.path.splitext(os.path.basename(flow_path or "workflow"))[0]
        slug = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", raw)
        slug = re.sub(r"_+", "_", re.sub(r"\s+", "_", slug)).strip(" ._-")[:80] or "workflow"
        if slug.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            slug = "_" + slug
        return os.path.join(data_root(), "data", "runner", slug, "config.json")

    def _load_runner_config(self, flow: dict, flow_path: str) -> None:
        with self._runner_config_lock:
            self._runner_config_path = self._config_path_for_flow(flow, flow_path)
            try:
                with open(self._runner_config_path, encoding="utf-8") as fh:
                    cfg = json.load(fh) or {}
                self._runner_config = cfg if isinstance(cfg, dict) else {}
            except Exception:
                self._runner_config = {}

    def _save_runner_config(self) -> bool:
        with self._runner_config_lock:
            if not self._runner_config_path:
                return False
            cfg = self._runner_config
            cfg["version"] = 1
            cfg["workflow"] = str(self.flow.get("name") or "")
            tmp = ""
            try:
                folder = os.path.dirname(self._runner_config_path)
                os.makedirs(folder, exist_ok=True)
                fd, tmp = tempfile.mkstemp(
                    prefix="config.", suffix=".tmp", dir=folder,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(cfg, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, self._runner_config_path)
                return True
            except Exception as exc:
                if tmp:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                log_warning(f"Couldn't save Runner config: {exc}")
                return False

    def _apply_runner_config(self) -> None:
        """Overlay only values explicitly edited in Runner onto workflow data."""
        cfg = self._runner_config or {}
        acts = self.flow.get("activities") or []
        by_id = {str(a.get("id")): a for a in acts if a.get("id")}
        act_cfg = cfg.get("activities") or {}
        if not isinstance(act_cfg, dict):
            act_cfg = {}
        for act_id, saved in act_cfg.items():
            act = by_id.get(str(act_id))
            if not act or not isinstance(saved, dict):
                continue
            if "enabled" in saved:
                act["enabled"] = bool(saved["enabled"])
            if "pollInterval" in saved:
                try:
                    act["pollInterval"] = max(0.05, float(saved["pollInterval"]))
                except (TypeError, ValueError):
                    pass
            saved_vars = saved.get("vars") or {}
            for var in act.get("vars", []) or []:
                if var.get("name") in saved_vars:
                    var["value"] = saved_vars[var.get("name")]
        order = cfg.get("order") or []
        if not isinstance(order, list):
            order = []
        if order:
            rank = {str(value): i for i, value in enumerate(order)}
            acts.sort(key=lambda a: rank.get(str(a.get("id")), len(rank)))
        node_cfg = cfg.get("nodes") or {}
        if not isinstance(node_cfg, dict):
            node_cfg = {}
        for node_id, values in node_cfg.items():
            node = self._find_node(str(node_id))
            if not node or not isinstance(values, dict):
                continue
            params = node.setdefault("params", {})
            if "path" in values and "path" in params:
                params["path"] = str(values["path"] or "")
        speed = cfg.get("speedhack") or {}
        if isinstance(speed, dict) and speed:
            merged = dict(self.flow.get("speedhack") or {})
            if "enabled" in speed:
                merged["enabled"] = bool(speed["enabled"])
            if "speed" in speed:
                try:
                    merged["speed"] = float(speed["speed"])
                except (TypeError, ValueError):
                    pass
            self.flow["speedhack"] = merged
        if cfg.get("capture") in CAPTURE_BACKENDS:
            self.flow["capture"] = cfg["capture"]

    def _activity_runner_config(self, activity_id: str) -> dict:
        acts = self._runner_config.get("activities")
        if not isinstance(acts, dict):
            acts = {}
            self._runner_config["activities"] = acts
        saved = acts.get(str(activity_id))
        if not isinstance(saved, dict):
            saved = {}
            acts[str(activity_id)] = saved
        return saved

    def get_state(self) -> dict:
        return {
            "title": "Macro2k Runner",
            "name": self.flow.get("name", ""),
            "loaded": bool(self.flow),
            "activities": self._activities_payload(),
            "log": self._log_buffer[-300:],
            "running": self.engine.is_running(),
            "paused": self.engine.is_paused(),
            "speedhack": self.engine.speedhack_info(),
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
            "captureBackend": get_capture_backend(),
            "captureBackends": list(CAPTURE_BACKENDS),
            "controller": self._controller(),
            "win32": dict(self.flow.get("win32") or {}),
            "configPath": self._runner_config_path or "",
        }

    def _controller(self) -> str:
        raw = str((self.flow or {}).get("controller") or "adb").strip().lower()
        return "win32" if raw == "win32" else "adb"

    def set_capture_backend(self, backend: str) -> dict:
        selected = set_capture_backend(backend)
        if self.flow:
            with self._runner_config_lock:
                self._runner_config["capture"] = selected
                self._save_runner_config()
        self._push("capture_backend", {"backend": selected})
        return {"backend": selected, "backends": list(CAPTURE_BACKENDS)}

    def _find_node(self, node_id: str) -> Optional[dict]:
        """Find a node across activity and function graphs by its stable id."""
        owners = list(self.flow.get("activities", []) or []) + list(self.flow.get("functions", []) or [])
        for owner in owners:
            for node in ((owner.get("graph") or {}).get("nodes") or []):
                if node.get("id") == node_id:
                    return node
        return None

    def _runtime_settings_for_activity(self, activity: dict) -> List[dict]:
        """Generate runner controls for runtime-selectable node paths.

        Function calls are traversed too, so a Launch program inside a reusable
        function automatically appears on every activity that can invoke it.
        """
        functions = {f.get("id"): f for f in (self.flow.get("functions") or []) if f.get("id")}
        labels = {
            "win_launch": ("Launch program", "Program path (.exe)"),
            "launch_emulator": ("Launch emulator", "Install folder / console .exe"),
        }
        kinds = {"launch_emulator": "folder", "win_launch": "file"}
        found: List[dict] = []
        seen_nodes: set = set()
        seen_functions: set = set()

        def scan(graph: dict) -> None:
            for node in (graph or {}).get("nodes", []) or []:
                node_id = node.get("id")
                if not node_id or node_id in seen_nodes:
                    continue
                seen_nodes.add(node_id)
                params = node.get("params") or {}
                node_type = str(node.get("type") or "")
                # Every serialized `path` parameter gets a generated setting;
                # known node types only refine its label and picker kind.
                if "path" in params:
                    node_label, field_label = labels.get(node_type, (node_type or "Action", "Path"))
                    node_label = str(node.get("note") or node_label)
                    found.append({
                        "id": f"{node_id}:path", "nodeId": node_id, "param": "path",
                        "nodeLabel": node_label, "label": field_label,
                        "kind": kinds.get(node_type, "file"),
                        "value": str(params.get("path") or ""),
                    })
                if node_type == "call":
                    fn_id = str(params.get("fn") or "")
                    if fn_id and fn_id not in seen_functions and fn_id in functions:
                        seen_functions.add(fn_id)
                        scan(functions[fn_id].get("graph") or {})

        scan(activity.get("graph") or {})
        return found

    def _activities_payload(self) -> List[dict]:
        out = []
        for a in self.flow.get("activities", []) or []:
            graph = a.get("graph", {}) or {}
            out.append({
                "id": a.get("id"),
                "name": a.get("name") or a.get("id"),
                "type": a.get("type", "sequence"),
                "enabled": a.get("enabled", True),
                "pollInterval": a.get("pollInterval", 1.0),
                "maxRetries": a.get("maxRetries", 1),
                "nodeCount": len(graph.get("nodes", []) or []),
                "vars": [{"name": v.get("name"), "label": v.get("label", ""),
                          "type": v.get("type", "bool"), "value": v.get("value"),
                          "options": v.get("options") or []}
                         for v in (a.get("vars") or [])],
                "runtimeSettings": self._runtime_settings_for_activity(a),
            })
        return out

    # ── Load JSON ────────────────────────────────────────────────────────────

    def load_json(self) -> dict:
        """Open a file dialog, load the flow, and return the new state."""
        flows_dir = os.path.join(data_root(), "workflows")
        start_dir = flows_dir if os.path.isdir(flows_dir) else data_root()
        try:
            wins = webview.windows
            win = wins[0] if wins else None
            if win is None:
                return {"ok": False}
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                file_types=("JSON (*.json)", "All files (*.*)"),
            )
        except Exception as exc:
            log_error(f"Dialog error: {exc}")
            return {"ok": False}
        if not paths:
            return {"ok": False}
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return self._load_path(str(path))

    def _load_path(self, path: str) -> dict:
        try:
            flow = WorkflowEngine.load_file(path)
        except Exception as exc:
            log_error(f"Couldn't read workflow: {exc}")
            return {"ok": False}
        if self.engine.is_running():
            self.engine.stop()
        self.flow = flow
        self.flow_path = path
        self._load_runner_config(flow, path)
        self._apply_runner_config()
        self.engine.load(flow, flow_path=path)
        # engine.load applies flow["capture"] process-wide — sync the Source dropdown.
        backend = get_capture_backend()
        self._push("capture_backend", {"backend": backend})
        log_success(f"Loaded workflow: {flow.get('name', os.path.basename(path))}")
        ctrl = self._controller()
        state = {"ok": True, "name": flow.get("name", ""),
                 "activities": self._activities_payload(),
                 "speedhack": self.engine.speedhack_info(),
                 "captureBackend": backend,
                 "controller": ctrl,
                 "win32": dict(flow.get("win32") or {}),
                 "configPath": self._runner_config_path or ""}
        self._push("flow_loaded", state)
        return state

    # ── Controls ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        if not self.flow:
            log_warning("Load a workflow JSON first")
            return False
        serial = self._connected_serial or self._selected_serial
        if serial:
            try:
                self.engine.auto.adb.device_id = serial
                self.engine.auto.adb.select_device(serial)
            except Exception as exc:
                log_warning(f"Couldn't select device: {exc}")
        # Reset UI activity statuses.
        for a in self._activities_payload():
            self._push("activity_update", {"id": a["id"], "status": "pending"})
        return self.engine.start(background=True)

    def stop(self) -> bool:
        self.engine.stop()
        return True

    def pause(self) -> dict:
        if self.engine.is_paused():
            self.engine.resume()
        else:
            self.engine.pause()
        paused = self.engine.is_paused()
        self._push("running_state", {"running": self.engine.is_running(), "paused": paused})
        return {"paused": paused}

    def toggle_activity(self, activity_id: str, enabled: bool) -> bool:
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                a["enabled"] = bool(enabled)
                with self._runner_config_lock:
                    self._activity_runner_config(activity_id)["enabled"] = bool(enabled)
                    self._save_runner_config()
                # Background workers can be toggled live while running.
                if a.get("type") == "background" and self.engine.is_running():
                    if enabled:
                        self.engine.start_background(a)
                    else:
                        self.engine.stop_background(activity_id)
                return True
        return False

    def set_interval(self, activity_id: str, interval: float) -> bool:
        try:
            value = max(0.05, float(interval))
        except (TypeError, ValueError):
            return False
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                a["pollInterval"] = value
                with self._runner_config_lock:
                    self._activity_runner_config(activity_id)["pollInterval"] = value
                    self._save_runner_config()
                return True
        return False

    def set_activity_var(self, activity_id: str, name: str, value) -> bool:
        """Override an activity variable's value (used at run time)."""
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                for v in a.get("vars", []) or []:
                    if v.get("name") == name:
                        v["value"] = value
                        with self._runner_config_lock:
                            act_cfg = self._activity_runner_config(activity_id)
                            saved_vars = act_cfg.get("vars")
                            if not isinstance(saved_vars, dict):
                                saved_vars = {}
                                act_cfg["vars"] = saved_vars
                            saved_vars[str(name)] = value
                            self._save_runner_config()
                        return True
        return False

    def set_node_runtime_param(self, node_id: str, param: str, value) -> bool:
        """Update an auto-generated runtime setting in the loaded flow."""
        if self.engine.is_running() or param != "path":
            return False
        node = self._find_node(str(node_id or ""))
        if node is None:
            return False
        params = node.setdefault("params", {})
        if param not in params:
            return False
        params[param] = str(value or "").strip()
        with self._runner_config_lock:
            nodes = self._runner_config.get("nodes")
            if not isinstance(nodes, dict):
                nodes = {}
                self._runner_config["nodes"] = nodes
            saved = nodes.get(str(node_id))
            if not isinstance(saved, dict):
                saved = {}
                nodes[str(node_id)] = saved
            saved[param] = params[param]
            self._save_runner_config()
        return True

    def pick_node_runtime_path(self, node_id: str, param: str,
                               kind: str = "file", start: str = "") -> str:
        """Open the native file/folder picker for a generated path setting."""
        if self.engine.is_running() or param != "path" or self._window is None:
            return ""
        node = self._find_node(str(node_id or ""))
        if node is None or param not in (node.get("params") or {}):
            return ""
        start = str(start or "")
        start_dir = start if os.path.isdir(start) else os.path.dirname(start)
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = _PROJECT_ROOT
        try:
            if kind == "folder":
                paths = self._window.create_file_dialog(
                    webview.FOLDER_DIALOG, directory=start_dir)
            else:
                paths = self._window.create_file_dialog(
                    webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                    file_types=("Programs (*.exe;*.bat;*.cmd;*.com)", "All files (*.*)"),
                )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        value = str(path or "")
        return value if self.set_node_runtime_param(node_id, param, value) else ""

    def reorder_activities(self, ordered_ids: List[str]) -> bool:
        """Reorder ``flow['activities']`` to match the drag-and-drop order.

        ``ordered_ids`` lists every activity id in its new order. The list is
        rewritten *in place* so the engine (which shares the same dict) picks up
        the new sequence order on the next run. Ignored while a run is in
        progress to avoid mutating the list mid-iteration.
        """
        if self.engine.is_running():
            log_warning("Activities can't be reordered while running")
            return False
        acts = self.flow.get("activities") or []
        by_id = {a.get("id"): a for a in acts}
        new_order = [by_id[i] for i in ordered_ids if i in by_id]
        # Append any activity not mentioned (defensive), keeping its relative order.
        for a in acts:
            if a not in new_order:
                new_order.append(a)
        acts[:] = new_order
        with self._runner_config_lock:
            self._runner_config["order"] = [str(a.get("id")) for a in acts if a.get("id")]
            self._save_runner_config()
        return True

    # ── Speedhack (live scale slider) ─────────────────────────────────────────

    def set_speedhack(self, enabled: bool, speed: float = None,
                      package: str = None) -> dict:
        """Toggle the speedhack and/or update its speed/package.

        Applies live when a run is in progress, otherwise just stores the
        config so the next Start picks it up.
        """
        try:
            self.engine.configure_speedhack(
                enabled=bool(enabled),
                speed=speed,
                package=package,
            )
            with self._runner_config_lock:
                saved = self._runner_config.get("speedhack")
                if not isinstance(saved, dict):
                    saved = {}
                    self._runner_config["speedhack"] = saved
                saved["enabled"] = bool(enabled)
                if speed is not None:
                    saved["speed"] = float(speed)
                self._save_runner_config()
        except Exception as exc:
            log_error(f"Speed hack failed: {exc}")
        info = self.engine.speedhack_info()
        self._push("speedhack_update", info)
        return info

    def set_speed_scale(self, scale: float) -> dict:
        """Change the live time scale while a run is in progress."""
        try:
            value = float(scale)
            self.engine.set_speed_scale(value)
            with self._runner_config_lock:
                saved = self._runner_config.get("speedhack")
                if not isinstance(saved, dict):
                    saved = {}
                    self._runner_config["speedhack"] = saved
                saved["speed"] = value
                self._save_runner_config()
        except Exception as exc:
            log_error(f"Speed hack failed: {exc}")
        info = self.engine.speedhack_info()
        self._push("speedhack_update", info)
        return info

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        return True

    # ── Devices ───────────────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        threading.Thread(target=self._device_worker, args=(True,), daemon=True).start()

    def select_device(self, serial: str) -> bool:
        try:
            self._selected_serial = serial
            self.engine.auto.adb.device_id = serial
            threading.Thread(target=self._connect_device, args=(serial,), daemon=True).start()
            return True
        except Exception as e:
            log_error(f"Select device error: {e}")
            return False

    def _connect_device(self, serial: str) -> None:
        try:
            self.engine.auto.adb.select_device(serial)
            self.engine.auto.adb.quick_refresh()
            s = self.engine.auto.adb.get_status_summary()
            self._connected_serial = s.get("device_id") if s.get("connected") else None
            self._push("device_status", {
                "connected": bool(s.get("connected")),
                "serial": s.get("device_id"),
                "name": s.get("device_name") or serial,
            })
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _device_worker(self, force_scan: bool = False) -> None:
        adb = self.engine.auto.adb
        with self._device_lock:
            try:
                if force_scan:
                    try:
                        if not (adb.list_devices() or []):
                            adb.scan_all_devices()
                    except Exception:
                        pass
                devices = adb.list_devices() or []
                if devices and not self._selected_serial:
                    first = devices[0].get("serial")
                    if first:
                        self._selected_serial = first
                        adb.device_id = first
                        adb.select_device(first)
                elif devices and self._selected_serial:
                    if adb.device is None or adb.device_id != self._selected_serial:
                        adb.select_device(self._selected_serial)
                elif not devices:
                    try:
                        adb.check_adb_connection()
                    except Exception:
                        pass
                adb.quick_refresh()
                s = adb.get_status_summary()
                self._connected_serial = s.get("device_id") if s.get("connected") else None
                self._push("devices_update", {
                    "devices": devices,
                    "connected": bool(s.get("connected")),
                    "serial": s.get("device_id"),
                    "name": s.get("device_name") or s.get("device_id") or "",
                })
            except Exception:
                self._push("devices_update", {"devices": [], "connected": False,
                                              "serial": None, "name": ""})

    def _device_poll(self) -> None:
        while not self._closing:
            time.sleep(5)
            if not self._closing:
                self._device_worker(force_scan=False)

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        remove_log_subscriber(self._on_log)
        try:
            self.engine.stop()
        except Exception:
            pass
        stop_scrcpy_sources()
        kill_adb_server()   # stop the leftover adb.exe daemon (also unlocks vendor/adb)


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_runner_window(title: str = titled("Macro2k Runner"),
                                  auto_load: Optional[str] = None) -> webview.Window:
    api = WorkflowRunnerAPI()
    api._pending_load = auto_load
    html_path = os.path.join(_WEB_DIR, "runner", "index.html")
    url = file_url(html_path)
    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=440,
        height=860,
        resizable=True,
        min_size=(380, 620),
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    window.events.closed += lambda: api._close()
    return window


def run(auto_load: Optional[str] = None) -> None:
    create_workflow_runner_window(auto_load=auto_load)
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=webview_storage_path("runner"),
    )


if __name__ == "__main__":
    # Optional: a flow JSON path to auto-load (the designer's "Chạy GUI" passes one).
    auto = sys.argv[1] if len(sys.argv) > 1 else None
    run(auto)
