"""PyWebView runner GUI for JSON workflows.

A sibling of ``src/gui/pywebview_gui.py`` (the game-automation GUI) but driven by
a *loaded JSON file* instead of a hard-coded ``BaseGameAutomation`` subclass.
Press **Load JSON** to pick a flow exported from the Workflow tab in
``tools/dev_helper.py``; its sequence/background activities then appear with the
same enable toggles, Start / Stop / Pause controls, and live log.

The actual execution is delegated to :class:`src.workflow.WorkflowEngine`, so a
flow behaves identically here and in the designer's *Run test*.

Run::

    python tools/workflow_runner.py
"""
from __future__ import annotations

import datetime
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

import webview

from src.workflow import WorkflowEngine
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web", "workflow")


class WorkflowRunnerAPI:
    """Methods exposed to JavaScript via ``pywebview.api.*``."""

    def __init__(self) -> None:
        self.engine = WorkflowEngine()
        self.flow: Dict[str, Any] = {}
        self.flow_path: Optional[str] = None

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
                log_error(f"Auto-load lỗi: {exc}")
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
            payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
            safe = payload.replace("\\", "\\\\").replace("`", "\\`")
            self._window.evaluate_js(f"window.__recv(`{safe}`)")
        except Exception:
            pass

    # ── State ────────────────────────────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            "title": "Workflow Runner",
            "name": self.flow.get("name", ""),
            "loaded": bool(self.flow),
            "activities": self._activities_payload(),
            "log": self._log_buffer[-300:],
            "running": self.engine.is_running(),
            "paused": self.engine.is_paused(),
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
        }

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
            })
        return out

    # ── Load JSON ────────────────────────────────────────────────────────────

    def load_json(self) -> dict:
        """Open a file dialog, load the flow, and return the new state."""
        flows_dir = os.path.join(os.getcwd(), "data", "flows")
        start_dir = flows_dir if os.path.isdir(flows_dir) else os.getcwd()
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
            log_error(f"Không đọc được flow: {exc}")
            return {"ok": False}
        if self.engine.is_running():
            self.engine.stop()
        self.flow = flow
        self.flow_path = path
        self.engine.load(flow, flow_path=path)
        log_success(f"Đã tải workflow: {flow.get('name', os.path.basename(path))}")
        state = {"ok": True, "name": flow.get("name", ""),
                 "activities": self._activities_payload()}
        self._push("flow_loaded", state)
        return state

    # ── Controls ─────────────────────────────────────────────────────────────

    def start(self) -> bool:
        if not self.flow:
            log_warning("Hãy tải một file JSON trước")
            return False
        serial = self._connected_serial or self._selected_serial
        if serial:
            try:
                self.engine.auto.adb.device_id = serial
                self.engine.auto.adb.select_device(serial)
            except Exception as exc:
                log_warning(f"Chọn thiết bị lỗi: {exc}")
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
                # Background workers can be toggled live while running.
                if a.get("type") == "background" and self.engine.is_running():
                    if enabled:
                        self.engine.start_background(a)
                    else:
                        self.engine.stop_background(activity_id)
                return True
        return False

    def set_interval(self, activity_id: str, interval: float) -> bool:
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                a["pollInterval"] = max(0.05, float(interval))
                return True
        return False

    def set_activity_var(self, activity_id: str, name: str, value) -> bool:
        """Override an activity variable's value (used at run time)."""
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                for v in a.get("vars", []) or []:
                    if v.get("name") == name:
                        v["value"] = value
                        return True
        return False

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        return True

    # ── Devices (same shape as pywebview_gui) ──────────────────────────────────

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


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_runner_window(title: str = "Workflow Runner",
                                  auto_load: Optional[str] = None) -> webview.Window:
    api = WorkflowRunnerAPI()
    api._pending_load = auto_load
    html_path = os.path.join(_WEB_DIR, "index.html")
    url = f"file:///{html_path.replace(os.sep, '/')}"
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
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    run()
