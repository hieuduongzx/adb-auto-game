"""PyWebView-based Workflow Designer for ADB auto-game.

A standalone tool (split out of ``tools/dev_helper.py``) for building automation
**workflows** as node graphs and test-running them. Drag nodes from the palette,
wire them (loose-connect / Ctrl-stack), group them into sequence/background
activities and reusable functions, then export to JSON or hit **Chạy thử** to run
against a connected device.

The actual execution is delegated to :class:`src.workflow.WorkflowEngine`, so a
flow behaves identically here and in the standalone runner GUI.

Run::

    python tools/workflow_designer.py

Flows save to ``data/flows/`` by default.
"""
from __future__ import annotations

import base64
import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
from typing import Dict, List, Optional

import cv2
import numpy as np

# --- bootstrap: make `src.*` importable when run from tools/ -------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import webview

from src.core.adb import ADBController, DeviceScanner
from src.workflow import NODE_TYPES, WorkflowEngine
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")
_FLOWS_DIR = os.path.join(_PROJECT_ROOT, "data", "flows")
_SETTINGS_PATH = os.path.join(_PROJECT_ROOT, "data", "designer_settings.json")


def _sanitize_name(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", raw.strip())
    return cleaned.strip("._-")


class WorkflowDesignerAPI:
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()

        self._engine: Optional[WorkflowEngine] = None
        self._wf_path: Optional[str] = None
        self._last_dir: Optional[str] = None

        self._window: Optional[webview.Window] = None
        self._closing = False
        self._log_buffer: List[Dict] = []

        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None

    # ── Setup ────────────────────────────────────────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log)
        threading.Thread(target=self._device_worker, daemon=True).start()
        threading.Thread(target=self._device_poll, daemon=True).start()

    # ── Log + push ───────────────────────────────────────────────────────────

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

    def get_state(self) -> dict:
        return {
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
            "log": self._log_buffer[-300:],
        }

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        log_info("Đã xoá nhật ký")
        return True

    # ── Persisted UI settings (snap, global preview, …) ───────────────────────

    def get_settings(self) -> dict:
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def save_settings(self, settings: dict) -> bool:
        try:
            os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
            with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(settings or {}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            log_warning(f"Lưu cài đặt thất bại: {exc}")
            return False

    # ── Device ops ───────────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        threading.Thread(target=self._device_worker, daemon=True).start()

    def select_device(self, serial: str) -> bool:
        try:
            self._selected_serial = serial or None
            threading.Thread(target=self._connect_device, args=(serial,), daemon=True).start()
            return True
        except Exception as e:
            log_error(f"Select device error: {e}")
            return False

    def scan_ports(self) -> None:
        threading.Thread(target=self._scan_ports_worker, daemon=True).start()

    def restart_adb(self) -> None:
        threading.Thread(target=self._restart_adb_worker, daemon=True).start()

    def _connect_device(self, serial: str) -> None:
        try:
            if not serial:
                self._connected_serial = None
                self._push("device_status", {"connected": False})
                return
            self.controller.select_device(serial)
            self.controller.quick_refresh()
            s = self.controller.get_status_summary()
            self._connected_serial = s.get("device_id") if s.get("connected") else None
            self._push("device_status", {
                "connected": bool(s.get("connected")),
                "serial": s.get("device_id"),
                "name": s.get("device_name") or serial,
            })
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _device_worker(self) -> None:
        with self._device_lock:
            try:
                self.scanner.ensure_adb_server_running()
                devices = self.controller.client.devices()
                items = []
                for d in devices:
                    try:
                        model = (d.shell("getprop ro.product.model") or "").strip()
                    except Exception:
                        model = ""
                    items.append({"serial": d.serial, "name": model or d.serial})
                if items and not self._selected_serial:
                    first = items[0].get("serial")
                    if first:
                        self._selected_serial = first
                        self.controller.select_device(first)
                elif items and self._selected_serial:
                    if (self.controller.device is None
                            or self.controller.device_id != self._selected_serial):
                        self.controller.select_device(self._selected_serial)
                self._push("devices_update", {"devices": items})
                if items:
                    s = self.controller.get_status_summary()
                    self._connected_serial = s.get("device_id") if s.get("connected") else None
                    self._push("device_status", {
                        "connected": bool(s.get("connected")),
                        "serial": s.get("device_id"),
                        "name": s.get("device_name") or "",
                    })
            except Exception:
                self._push("devices_update", {"devices": []})

    def _device_poll(self) -> None:
        while not self._closing:
            time.sleep(5)
            if not self._closing:
                self._device_worker()

    def _scan_ports_worker(self) -> None:
        log_info("Port scanning all known emulator ranges...")
        try:
            found = self.scanner.scan_all(stop_on_first=False)
        except Exception as exc:
            log_error(f"Scan failed: {exc}")
            return
        log_success(f"Found {len(found)} device(s)") if found else log_warning("No devices found")
        self._device_worker()

    def _restart_adb_worker(self) -> None:
        log_info("Restarting ADB server...")
        if self.scanner.restart_adb_server():
            log_success("ADB server restarted")
        else:
            log_error("Failed to restart ADB server")
        self._device_worker()

    # ── Dialog directory memory ────────────────────────────────────────────────

    def _start_dir(self, fallback: str) -> str:
        if self._last_dir and os.path.isdir(self._last_dir):
            return self._last_dir
        return fallback

    def _remember_dir(self, path: str) -> None:
        try:
            d = os.path.dirname(str(path))
            if d and os.path.isdir(d):
                self._last_dir = d
        except Exception:
            pass

    def _win(self):
        wins = webview.windows
        return wins[0] if wins else None

    # ── Image preview ──────────────────────────────────────────────────────────

    def _resolve_template(self, raw: str) -> str:
        """Resolve a (possibly relative) template path for previewing."""
        raw = (raw or "").strip().replace("\\", "/")
        if not raw:
            return ""
        if os.path.isabs(raw) and os.path.exists(raw):
            return raw
        cands = [raw, os.path.join(_PROJECT_ROOT, raw),
                 os.path.join(_PROJECT_ROOT, "out", raw)]
        if self._wf_path:
            cands.insert(0, os.path.join(os.path.dirname(self._wf_path), raw))
        for c in cands:
            if os.path.exists(c):
                return c
        return raw

    def image_thumbnail(self, path: str, max_w: int = 230) -> str:
        """Return a JPEG data-URL thumbnail for a template path (or "")."""
        p = self._resolve_template(path)
        if not p or not os.path.exists(p):
            return ""
        try:
            data = np.fromfile(p, dtype=np.uint8)   # unicode-path safe
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None:
                return ""
            h, w = img.shape[:2]
            if w > max_w:
                img = cv2.resize(img, (max_w, max(1, int(h * max_w / w))),
                                 interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if not ok:
                return ""
            return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception:
            return ""

    # ── Template picker (for image nodes) ──────────────────────────────────────

    def pick_template(self) -> str:
        win = self._win()
        if win is None:
            return ""
        out_dir = os.path.join(_PROJECT_ROOT, "out")
        start_dir = self._start_dir(out_dir if os.path.isdir(out_dir) else _PROJECT_ROOT)
        try:
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                file_types=("Images (*.png;*.jpg;*.jpeg;*.bmp)", "All files (*.*)"),
            )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        self._remember_dir(path)
        return str(path)

    # ── Workflow file ops ──────────────────────────────────────────────────────

    def workflow_node_types(self) -> dict:
        return {k: {"label": v["label"], "kind": v["kind"], "outs": v["outs"]}
                for k, v in NODE_TYPES.items()}

    def workflow_new(self) -> bool:
        """Forget the currently open file so 'Lưu' prompts for a new path."""
        self._wf_path = None
        return True

    def workflow_export(self, flow_json: str, name: str = "") -> bool:
        os.makedirs(_FLOWS_DIR, exist_ok=True)
        default = f"{_sanitize_name(name) or 'flow'}.json"
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=self._start_dir(_FLOWS_DIR),
                    save_filename=default,
                    file_types=("JSON (*.json)", "All files (*.*)"),
                )
                if not paths:
                    log_info("Lưu workflow bị huỷ")
                    return False
                path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception as exc:
            log_warning(f"Dialog error: {exc} — lưu vào data/flows/")
        if not path:
            path = os.path.join(_FLOWS_DIR, default)
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(flow_json)
            self._wf_path = path
            self._remember_dir(path)
            log_success(f"Đã lưu workflow: {path}")
            return True
        except Exception as exc:
            log_error(f"Lưu workflow thất bại: {exc}")
            return False

    def workflow_save(self, flow_json: str, name: str = "") -> dict:
        if self._wf_path:
            try:
                with open(self._wf_path, "w", encoding="utf-8") as fh:
                    fh.write(flow_json)
                log_success(f"Đã lưu: {self._wf_path}")
                return {"ok": True, "path": self._wf_path}
            except Exception as exc:
                log_error(f"Lưu thất bại: {exc}")
                return {"ok": False, "path": self._wf_path}
        ok = self.workflow_export(flow_json, name)
        return {"ok": bool(ok), "path": self._wf_path}

    def workflow_import(self) -> str:
        win = self._win()
        if win is None:
            return ""
        start_dir = self._start_dir(_FLOWS_DIR if os.path.isdir(_FLOWS_DIR) else _PROJECT_ROOT)
        try:
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG, directory=start_dir, allow_multiple=False,
                file_types=("JSON (*.json)", "All files (*.*)"),
            )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        try:
            with open(str(path), "r", encoding="utf-8") as fh:
                text = fh.read()
            self._wf_path = str(path)
            self._remember_dir(path)
            log_info(f"Đã mở workflow: {path}")
            return text
        except Exception as exc:
            log_error(f"Mở workflow thất bại: {exc}")
            return ""

    # ── Test run ────────────────────────────────────────────────────────────────

    def workflow_run(self, flow_json: str) -> bool:
        if self.controller.device is None:
            log_error("Chưa chọn thiết bị để chạy workflow")
            return False
        try:
            flow = json.loads(flow_json)
        except Exception as exc:
            log_error(f"JSON workflow không hợp lệ: {exc}")
            return False
        if self._engine and self._engine.is_running():
            log_warning("Workflow đang chạy")
            return False
        if self._engine is None:
            self._engine = WorkflowEngine()
        serial = self._connected_serial or self._selected_serial
        try:
            if serial:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Không thể chọn thiết bị cho engine: {exc}")
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        self._engine.load(flow, flow_path=anchor)
        self._engine.callbacks["on_stop"] = [lambda: self._push("workflow_state", {"running": False})]
        self._engine.callbacks["on_node"] = [lambda nid: self._push("node_active", {"id": nid})]
        ok = self._engine.start(background=True)
        self._push("workflow_state", {"running": ok})
        if ok:
            log_success("Workflow bắt đầu chạy")
        return ok

    def workflow_stop(self) -> bool:
        if self._engine:
            self._engine.stop()
        self._push("workflow_state", {"running": False})
        return True

    def workflow_running(self) -> bool:
        return bool(self._engine and self._engine.is_running())

    def open_runner(self, flow_json: str) -> bool:
        """Launch the Runner GUI (separate process) preloaded with this flow."""
        try:
            os.makedirs(_FLOWS_DIR, exist_ok=True)
            tmp = os.path.join(_FLOWS_DIR, "_designer_run.json")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(flow_json)
            runner = os.path.join(os.path.dirname(__file__), "workflow_runner.py")
            subprocess.Popen([sys.executable, runner, tmp])
            log_success("Đã mở Runner GUI với workflow hiện tại")
            return True
        except Exception as exc:
            log_error(f"Mở Runner thất bại: {exc}")
            return False

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        if self._engine and self._engine.is_running():
            try:
                self._engine.stop()
            except Exception:
                pass
        remove_log_subscriber(self._on_log)


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_designer_window(title: str = "ADB Auto-Game - Workflow Designer") -> webview.Window:
    api = WorkflowDesignerAPI()
    html_path = os.path.join(_WEB_DIR, "workflow_designer.html")
    url = f"file:///{html_path.replace(os.sep, '/')}"
    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=1320,
        height=840,
        resizable=True,
        min_size=(1040, 680),
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    window.events.closed += lambda: api._close()
    return window


def run() -> None:
    create_workflow_designer_window()
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    run()
