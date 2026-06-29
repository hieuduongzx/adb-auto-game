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
import shutil
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
from src.game_core.frida_speedhack import FridaSpeedhackManager
from src.workflow import NODE_TYPES, WorkflowEngine
from src.utils import (
    add_log_subscriber,
    app_dir,
    bundle_dir,
    is_frozen,
    launch_tool,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)

# In a frozen build, writable resources (data/) live next to the .exe.
if is_frozen():
    _PROJECT_ROOT = app_dir()

# Bundled HTML: ``tools/web`` from source, ``<_MEIPASS>/web`` when frozen.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
# Default home for saved workflows. Each workflow lives in its own subfolder
# ``workflows/<name>/<name>.json`` (with its ``templates/`` bundle alongside),
# next to the .exe in a frozen build or in the repo root from source.
_WORKFLOWS_DIR = os.path.join(_PROJECT_ROOT, "workflows")
# Transient flow written for the "Chạy GUI" handoff to the runner.
_RUN_TMP_DIR = os.path.join(_WORKFLOWS_DIR, "_run")
_SETTINGS_PATH = os.path.join(_PROJECT_ROOT, "data", "designer_settings.json")

# Convention: a saved workflow.json is paired with a sibling assets folder of
# this name, so the pair (json + folder) is a self-contained, movable bundle —
# the unit we later package into an .exe. Image nodes reference their templates
# relative to the json as ``<_TEMPLATES_DIRNAME>/<file>``.
_TEMPLATES_DIRNAME = "templates"
# Node params whose value is a template image path (kept in sync with the
# ``t:"tpl"`` fields in workflow_designer.html — all use the key "template").
_TEMPLATE_PARAM_KEYS = ("template",)
# Node params whose value is a *list* of template paths (``t:"tpls"`` fields —
# the "…_any" multi-image OR nodes; key "templates").
_TEMPLATE_LIST_PARAM_KEYS = ("templates",)


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

        # Standalone speed hack — fully decoupled from the test run. The designer's
        # "Run test" never injects Frida; speedhack is its own manual ▶ action, so
        # it owns its own manager/retry-thread rather than riding the engine run.
        self._sh_mgr: Optional[FridaSpeedhackManager] = None
        self._sh_stop: Optional[threading.Event] = None

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
        # Merge into the existing file so writing UI prefs (snap, previewAll…) from
        # JS doesn't wipe keys the backend owns, like ``lastWorkflow``.
        try:
            merged = self.get_settings()
            merged.update(settings or {})
            os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
            with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            return True
        except Exception as exc:
            log_warning(f"Lưu cài đặt thất bại: {exc}")
            return False

    def _remember_last_workflow(self, path: Optional[str]) -> None:
        """Persist (or clear) the path to reopen on the next launch."""
        try:
            s = self.get_settings()
            if path:
                s["lastWorkflow"] = str(path)
            else:
                s.pop("lastWorkflow", None)
            os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
            with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_last_workflow(self) -> dict:
        """Return the previously-open workflow so the designer can reopen it.

        ``{ok, path, name, text}`` when a remembered file still exists, else ``{}``.
        """
        path = (self.get_settings() or {}).get("lastWorkflow")
        if not path or not os.path.isfile(str(path)):
            return {}
        try:
            with open(str(path), "r", encoding="utf-8") as fh:
                text = fh.read()
            name = ""
            try:
                name = (json.loads(text) or {}).get("name", "")
            except Exception:
                pass
            self._wf_path = str(path)
            self._remember_dir(path)
            return {"ok": True, "path": str(path), "name": name, "text": text}
        except Exception:
            return {}

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
                items = self.scanner.unique_devices(devices)
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

    # ── Template bundling (portable game folder) ───────────────────────────────

    @staticmethod
    def _iter_graphs(flow: dict):
        """Yield every node-graph in a flow (each activity + each function)."""
        for act in flow.get("activities") or []:
            g = act.get("graph")
            if isinstance(g, dict):
                yield g
        for fn in flow.get("functions") or []:
            g = fn.get("graph")
            if isinstance(g, dict):
                yield g

    def _resolve_existing(self, raw: str, save_dir: str) -> Optional[str]:
        """Absolute path of an existing template, or ``None`` if not found.

        Tries the save folder (already-bundled / in-place save), the currently
        open flow's folder, then the project's usual asset roots.
        """
        raw = (raw or "").strip().replace("\\", "/")
        if not raw:
            return None
        if os.path.isabs(raw):
            return raw if os.path.isfile(raw) else None
        anchors: List[str] = []
        if save_dir:
            anchors.append(save_dir)
        if self._wf_path:
            anchors.append(os.path.dirname(self._wf_path))
        anchors += [_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "out"), os.getcwd()]
        for a in anchors:
            cand = os.path.join(a, raw)
            if os.path.isfile(cand):
                return cand
        return None

    def _materialize_templates(self, flow: dict, save_dir: str) -> int:
        """Copy every template used by ``flow`` into ``save_dir/templates`` and
        rewrite each node's path to the relative ``templates/<file>`` form.

        Returns the number of distinct images bundled. Mutates ``flow`` in place.
        """
        tdir_name = (flow.get("templatesDir") or _TEMPLATES_DIRNAME).strip().strip("/\\")
        tdir_name = tdir_name or _TEMPLATES_DIRNAME
        flow["templatesDir"] = tdir_name
        dest_dir = os.path.join(save_dir, tdir_name)

        copied: Dict[str, str] = {}   # normalized source abs path -> "templates/<file>"
        taken: set = set()            # lower-cased basenames already claimed

        def relocate(raw: str) -> str:
            src = self._resolve_existing(raw, save_dir)
            if not src:
                return raw  # leave unknown/empty paths untouched
            key = os.path.normcase(os.path.abspath(src))
            if key in copied:
                return copied[key]
            stem, ext = os.path.splitext(os.path.basename(src))
            name, n = f"{stem}{ext}", 1
            while name.lower() in taken:   # different source, same basename
                name = f"{stem}_{n}{ext}"
                n += 1
            taken.add(name.lower())
            dest = os.path.join(dest_dir, name)
            if os.path.normcase(os.path.abspath(dest)) != key:
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(src, dest)
            rel = f"{tdir_name}/{name}"
            copied[key] = rel
            return rel

        for graph in self._iter_graphs(flow):
            for node in graph.get("nodes") or []:
                params = node.get("params")
                if not isinstance(params, dict):
                    continue
                for pk in _TEMPLATE_PARAM_KEYS:
                    if params.get(pk):
                        params[pk] = relocate(params[pk])
                for pk in _TEMPLATE_LIST_PARAM_KEYS:
                    vals = params.get(pk)
                    if isinstance(vals, list):
                        params[pk] = [relocate(v) if v else v for v in vals]
        return len(copied)

    def _write_flow(self, flow_json: str, path: str) -> None:
        """Write a flow to ``path``, bundling its templates into a sibling folder.

        Falls back to writing the raw JSON unchanged if it can't be parsed or
        the images can't be copied, so a save never silently fails.
        """
        text = flow_json
        try:
            flow = json.loads(flow_json)
            n = self._materialize_templates(flow, os.path.dirname(os.path.abspath(path)))
            text = json.dumps(flow, ensure_ascii=False, indent=2)
            if n:
                log_info(f"Đã đóng gói {n} ảnh template vào ./{_TEMPLATES_DIRNAME}/")
        except Exception as exc:
            log_warning(f"Không thể đóng gói ảnh template: {exc} — lưu JSON gốc")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    # ── Workflow file ops ──────────────────────────────────────────────────────

    def workflow_node_types(self) -> dict:
        return {k: {"label": v["label"], "kind": v["kind"], "outs": v["outs"]}
                for k, v in NODE_TYPES.items()}

    def workflow_new(self) -> bool:
        """Forget the open file so the next 'Lưu' saves to the default folder
        (``workflows/<name>/<name>.json``)."""
        self._wf_path = None
        self._remember_last_workflow(None)   # a fresh doc shouldn't reopen the old one
        return True

    def _default_flow_path(self, name: str) -> str:
        """Default save target: ``<workflows>/<name>/<name>.json``.

        Used whenever the user doesn't pick an explicit location. Each workflow
        gets its own folder so ``_write_flow`` can bundle a sibling
        ``templates/`` folder, keeping the pair portable.
        """
        clean = _sanitize_name(name) or "workflow"
        folder = os.path.join(_WORKFLOWS_DIR, clean)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, f"{clean}.json")

    def workflow_export(self, flow_json: str, name: str = "") -> bool:
        os.makedirs(_WORKFLOWS_DIR, exist_ok=True)
        default = f"{_sanitize_name(name) or 'workflow'}.json"
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=self._start_dir(_WORKFLOWS_DIR),
                    save_filename=default,
                    file_types=("JSON (*.json)", "All files (*.*)"),
                )
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
        if not path:
            # No location chosen → default per-workflow folder next to the app.
            path = self._default_flow_path(name)
            log_info(f"Lưu mặc định vào workflows/{_sanitize_name(name) or 'workflow'}/")
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self._write_flow(flow_json, path)
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            log_success(f"Đã lưu workflow: {path}")
            return True
        except Exception as exc:
            log_error(f"Lưu workflow thất bại: {exc}")
            return False

    def workflow_save(self, flow_json: str, name: str = "") -> dict:
        # Save to the open file if there is one; otherwise drop the workflow
        # into its default folder (workflows/<name>/<name>.json) with no dialog.
        path = self._wf_path or self._default_flow_path(name)
        try:
            self._write_flow(flow_json, path)
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            log_success(f"Đã lưu: {path}")
            return {"ok": True, "path": path}
        except Exception as exc:
            log_error(f"Lưu thất bại: {exc}")
            return {"ok": False, "path": self._wf_path}

    def workflow_import(self) -> str:
        win = self._win()
        if win is None:
            return ""
        start_dir = self._start_dir(_WORKFLOWS_DIR if os.path.isdir(_WORKFLOWS_DIR) else _PROJECT_ROOT)
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
            self._remember_last_workflow(str(path))
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
        self._engine.callbacks["on_node_done"] = [
            lambda nid, st, port: self._push("node_result", {"id": nid, "status": st, "port": port})]
        self._engine.callbacks["on_var"] = [
            lambda name, value: self._push("var_update", {"name": name, "value": value})]
        # Test runs never auto-apply speedhack — that's a separate ▶ action.
        ok = self._engine.start(background=True, with_speedhack=False)
        self._push("workflow_state", {"running": ok})
        if ok:
            # Seed the panel with global vars immediately (activity vars arrive
            # via on_var when each activity starts).
            self._push("vars_snapshot", {"vars": dict(self._engine._globals)})
            log_success("Workflow bắt đầu chạy")
        return ok

    def workflow_stop(self) -> bool:
        if self._engine:
            self._engine.stop()
        self._push("workflow_state", {"running": False})
        return True

    def workflow_running(self) -> bool:
        return bool(self._engine and self._engine.is_running())

    def workflow_run_node(self, node_json: str, flow_json: str = "") -> bool:
        """Run a single node in isolation (no graph walk) — context-menu action.

        ``flow_json`` is the current serialized workflow so template paths resolve
        against the same templates dir. The engine fires the node on the calling
        thread and emits the same on_node / on_node_done callbacks a real run does,
        so the canvas paints the block amber→green/red.
        """
        if self.controller.device is None:
            log_error("Chưa chọn thiết bị để chạy block")
            return False
        try:
            node = json.loads(node_json)
            flow = json.loads(flow_json) if flow_json else None
        except Exception as exc:
            log_error(f"JSON không hợp lệ: {exc}")
            return False
        if self._engine is None:
            self._engine = WorkflowEngine()
        if self._engine.is_running():
            log_warning("Workflow đang chạy")
            return False
        serial = self._connected_serial or self._selected_serial
        try:
            if serial:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Không thể chọn thiết bị cho engine: {exc}")
        # Load the current flow (templates base + functions) so the node runs
        # against the same assets as a full run. Anchor to the open file if any.
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        try:
            if flow:
                self._engine.load(flow, flow_path=anchor)
            else:
                log_warning("Không có flow để nạp cho block")
        except Exception as exc:
            log_warning(f"Không nạp được flow cho block: {exc}")
        # Re-bind the same GUI callbacks a full test run uses.
        self._engine.callbacks["on_node"] = [lambda nid: self._push("node_active", {"id": nid})]
        self._engine.callbacks["on_node_done"] = [
            lambda nid, st, port: self._push("node_result", {"id": nid, "status": st, "port": port})]
        try:
            self._engine.run_single_node(node)
        except Exception as exc:
            log_error(f"Chạy block lỗi: {exc}")
            return False
        return True

    # ── Standalone speed hack (manual ▶, independent of the test run) ──────────

    def _sh_push(self, active: bool, running: bool) -> None:
        self._push("speedhack_state", {"active": active, "running": running})

    def speedhack_start(self, speed=2.0, package: str = "") -> bool:
        """Start (or live-adjust) the speed hack on its own — no workflow needed."""
        try:
            scale = float(speed)
        except (TypeError, ValueError):
            scale = 2.0
        if self.controller.device is None:
            log_error("[speedhack] chưa chọn thiết bị")
            return False
        if scale <= 0 or scale == 1.0:
            log_warning("[speedhack] tốc độ phải khác 1.0 để tăng tốc")
            return False
        # Already running → just push the new scale live (no re-inject, no package).
        if self._sh_mgr is not None:
            ok = self._sh_mgr.set_scale(scale)
            self._sh_push(bool(self._sh_mgr.active), True)
            return ok
        pkg = (package or "").strip()
        if not pkg:
            log_error("[speedhack] cần nhập package game để bật speed hack")
            return False
        mgr = FridaSpeedhackManager(package=pkg)
        mgr.adb_controller = self.controller
        if not mgr.available:
            log_warning("[speedhack] không tìm thấy frida-inject trong vendor/frida/")
            return False
        self._sh_mgr = mgr
        self._sh_stop = threading.Event()
        self._sh_push(False, True)
        threading.Thread(target=self._sh_loop, args=(scale,), daemon=True).start()
        return True

    def _sh_loop(self, scale: float) -> None:
        """Inject in the background, retrying until the game process exists."""
        stop_ev = self._sh_stop
        mgr = self._sh_mgr
        if mgr is None:
            return
        log_info(f"[speedhack] sẽ tăng tốc '{mgr.package}' x{scale} khi game chạy…")
        while mgr is not None and stop_ev is not None and not stop_ev.is_set():
            if mgr.active:
                return
            try:
                if mgr.set_scale(scale):
                    log_success(f"[speedhack] đã bật x{scale}")
                    self._sh_push(True, True)
                    return
            except Exception as e:
                log_warning(f"[speedhack] thử lại: {e}")
            for _ in range(50):  # ~5s, stay responsive to stop
                if stop_ev.is_set():
                    return
                time.sleep(0.1)

    def speedhack_stop(self) -> bool:
        ev = self._sh_stop
        if ev is not None:
            ev.set()
        self._sh_stop = None
        mgr = self._sh_mgr
        self._sh_mgr = None
        if mgr is not None:
            try:
                mgr.detach()
            except Exception as e:
                log_warning(f"[speedhack] lỗi khi tắt: {e}")
        self._sh_push(False, False)
        return True

    def speedhack_running(self) -> bool:
        return self._sh_mgr is not None

    def _workflow_templates_dir(self, flow_json: str = "") -> Optional[str]:
        """Best-effort path to the current workflow's ``templates/`` folder.

        Captures from DevScope should land where the workflow will bundle its
        images, so they're picked up by ``_write_flow`` on save. Uses the open
        file's folder when saved; otherwise the default ``workflows/<name>/``.
        Returns ``None`` if it can't be resolved.
        """
        name, tdir = "", _TEMPLATES_DIRNAME
        try:
            if flow_json:
                flow = json.loads(flow_json)
                name = flow.get("name") or ""
                tdir = (flow.get("templatesDir") or _TEMPLATES_DIRNAME).strip().strip("/\\") \
                    or _TEMPLATES_DIRNAME
        except Exception:
            pass
        try:
            if self._wf_path:
                base = os.path.dirname(os.path.abspath(self._wf_path))
            else:
                base = os.path.dirname(self._default_flow_path(name))
            dest = os.path.join(base, tdir)
            os.makedirs(dest, exist_ok=True)
            return dest
        except Exception as exc:
            log_warning(f"Không xác định được thư mục templates: {exc}")
            return None

    def open_dev_helper(self, flow_json: str = "") -> bool:
        """Launch the Dev Helper tool, pointing its output at this workflow's
        ``templates/`` folder so region crops / screenshots save alongside it."""
        try:
            out_dir = self._workflow_templates_dir(flow_json)
            launch_tool("devhelper", [out_dir] if out_dir else None)
            if out_dir:
                log_success(f"Đã mở DevScope · ảnh lưu vào: {out_dir}")
            else:
                log_success("Đã mở DevScope")
            return True
        except Exception as exc:
            log_error(f"Mở DevScope thất bại: {exc}")
            return False

    def open_runner(self, flow_json: str) -> bool:
        """Launch the Runner GUI (separate process) preloaded with this flow.

        The runner resolves template images relative to the file it loads, so we
        can't just dump the raw JSON next to it — its ``templates/<file>`` paths
        point at the *original* bundle folder, not ``data/flows/``. ``_write_flow``
        re-bundles the templates into a sibling ``templates/`` folder (pulling
        from the original ``self._wf_path`` bundle / absolute picker paths) and
        rewrites the paths, so the temp run file is self-contained and the runner
        finds every image.
        """
        try:
            os.makedirs(_RUN_TMP_DIR, exist_ok=True)
            tmp = os.path.join(_RUN_TMP_DIR, "_designer_run.json")
            self._write_flow(flow_json, tmp)
            launch_tool("runner", [tmp])
            log_success("Đã mở Runner GUI với workflow hiện tại")
            return True
        except Exception as exc:
            log_error(f"Mở Runner thất bại: {exc}")
            return False

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        # Remember whatever file is open so the next launch reopens it.
        self._remember_last_workflow(self._wf_path)
        if self._engine and self._engine.is_running():
            try:
                self._engine.stop()
            except Exception:
                pass
        if self._sh_mgr is not None:
            try:
                self.speedhack_stop()
            except Exception:
                pass
        remove_log_subscriber(self._on_log)


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_designer_window(title: str = "Workflow2k") -> webview.Window:
    api = WorkflowDesignerAPI()
    html_path = os.path.join(_WEB_DIR, "wf", "index.html")
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
