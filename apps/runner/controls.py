"""Loading the workflow and the run controls: start, stop, toggles, settings."""
from __future__ import annotations

import math
import os
from typing import List, Optional

import webview

from src.core.adb.auto.scrcpy_capture import (
    get_capture_backend,
)
from src.utils import (
    log_error,
    log_info,
    log_success,
    log_warning,
)
from src.version import APP_VERSION
from src.workflow import WorkflowEngine

from runner.common import (
    _PROJECT_ROOT,
    RUNTIME_PATH_PARAMS,
    runner_title,
)


class ControlMixin:
    """Loading the workflow and the run controls: start, stop, toggles, settings."""

    # ── Workflow (handed in at launch) ───────────────────────────────────────

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
        req = self._requirements_payload()
        if req and not req.get("installed"):
            log_warning(f"This game needs extra files: copy everything in {req['folder']} "
                        "into the game folder (Settings → Game files)")
        ctrl = self._controller()
        state = {"ok": True, "name": flow.get("name", ""),
                 "activities": self._activities_payload(),
                 "speedhack": self.engine.speedhack_info(),
                 "rounds": self._rounds_payload(),
                 "schedule": self._schedule_payload(),
                 "captureBackend": backend,
                 "controller": ctrl,
                 "win32": dict(flow.get("win32") or {}),
                 "gamePathDefault": self._flow_game_path,
                 "emulator": dict(flow.get("emulator") or {}),
                 "emulatorDefault": self._flow_emulator,
                 "requirements": self._requirements_payload(),
                 "gamePath": self._game_path_status(),
                 "configPath": self._runner_config_path or "",
                 "icon": self._icon_url(),
                 "iconKey": self._icon_key()}
        self._push("flow_loaded", state)
        workflow_name = str(flow.get("name") or os.path.basename(path))
        self._set_window_title(workflow_name)
        log_success(f"Automation initialized successfully — {workflow_name}")
        # unity_bridge: show from the start whether the in-game plugin answers.
        self._push_bridge_status(force=True)
        # The controller just changed: start (or park) ADB device watching.
        self._kick_device_scan()
        return state

    def _set_window_title(self, workflow_name: str) -> None:
        """Title the window "<Workflow> Runner <version>" for the loaded game."""
        if not self._window:
            return
        version = str(self._runner_info.get("version") or APP_VERSION or "")
        try:
            self._window.set_title(runner_title(workflow_name, version))
        except Exception as exc:
            log_warning(f"Couldn't set the window title: {exc}")

    # ── Controls ─────────────────────────────────────────────────────────────

    def _select_run_device(self) -> None:
        """Point the engine at the device chosen in the footer before a run."""
        if not self._adb_workflow():
            return                      # Win32 drives a window, not a device
        serial = self._connected_serial or self._selected_serial
        self.engine.set_selected_device(serial)
        if serial:
            try:
                self.engine.auto.adb.device_id = serial
                self.engine.auto.adb.select_device(serial)
            except Exception as exc:
                log_warning(f"Couldn't select device: {exc}")

    def start(self) -> bool:
        return self._request_run(None)

    def run_activity(self, activity_id: str) -> bool:
        """Run a single activity on its own, whether or not it is enabled.

        A sequence activity runs once; a background activity loops until Stop."""
        return self._request_run([str(activity_id or "")])

    def resume_from(self, activity_id: str) -> bool:
        """Start a full run that picks up at *activity_id* — the "Resume from"
        on a failed run's result: the activities before it are skipped (this
        round only), everything from it on runs as usual."""
        return self._request_run(None, start_from=str(activity_id or "") or None)

    def _request_run(self, scope: Optional[List[str]], start_from: Optional[str] = None) -> bool:
        # pywebview dispatches API calls on separate threads. Reserve the entire
        # preflight/readiness interval, before engine.running becomes True.
        if not self._run_request_lock.acquire(blocking=False):
            return False
        try:
            if self._run_live():
                log_warning("Stop the current run before starting another")
                return False
            self._begin_run()
            if not self.flow:
                log_warning("No workflow loaded — open this Runner from the Macro2k Hub")
                return False
            if scope and not any(str(a.get("id")) == scope[0]
                                 for a in self.flow.get("activities", []) or []):
                return False
            if self._blocked_by_launch_paths(scope):
                return False
            self._select_run_device()
            self._run_scope = scope
            if scope is None:
                self._push_bridge_status(force=True)
                acts = self.flow.get("activities", []) or []
                self._resume_from = (start_from if any(str(a.get("id")) == start_from for a in acts)
                                     else None)
                if self._resume_from:
                    return self.engine.start(background=True, start_from=self._resume_from)
                return self.engine.start(background=True)
            return self.engine.start_activity(scope[0])
        finally:
            self._run_request_lock.release()

    def stop(self) -> bool:
        """Stop the run — recorded as a Stop, not a failure.

        The intent is set *before* the engine is asked to stop, because a
        cancelled activity comes back from the engine as ok=False exactly like
        a failed one; the flag is what lets the run end as "stopped"."""
        if self._run_live():
            self._stop_intent = True
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
                if (enabled and a.get("type") == "background" and self.engine.is_running()
                        and self.engine.background_stopping(activity_id)):
                    log_warning("Background is still stopping — wait for its current action")
                    return False
                with self._runner_config_lock:
                    if not self._persist_runner_config({("activities", str(activity_id), "enabled"): bool(enabled)}):
                        return False
                    a["enabled"] = bool(enabled)
                # Background workers can be toggled live while running.
                if a.get("type") == "background" and self.engine.is_running():
                    if enabled:
                        self.engine.start_background(a)
                    else:
                        self.engine.stop_background(activity_id)
                        self._act_status[str(activity_id)] = "stopped"
                        self._push("activity_update", {"id": activity_id, "status": "stopped"})
                state = "enabled" if enabled else "disabled"
                activity_name = str(a.get("name") or activity_id)
                log_info(f"Activity {state} — {activity_name}")
                return True
        return False

    def set_interval(self, activity_id: str, interval: float) -> bool:
        try:
            value = float(interval)
            if not math.isfinite(value):
                return False
            value = max(0.05, value)
        except (TypeError, ValueError):
            return False
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                with self._runner_config_lock:
                    if not self._persist_runner_config({("activities", str(activity_id), "pollInterval"): value}):
                        return False
                    a["pollInterval"] = value
                return True
        return False

    def set_activity_retries(self, activity_id: str, value) -> dict:
        """Runner-only retry count for one activity.

        This is a Runner setting: it overrides ``maxRetries`` in memory for the
        run and is saved to this Runner's own config — the workflow file is never
        touched. Returns ``{"ok", "retries"}``."""
        try:
            retries = max(1, int(float(value)))
        except (TypeError, ValueError, OverflowError):
            return {"ok": False, "retries": 1}
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                with self._runner_config_lock:
                    if not self._persist_runner_config({("activities", str(activity_id), "retries"): retries}):
                        return {"ok": False, "retries": a.get("maxRetries", 1)}
                    a["maxRetries"] = retries
                return {"ok": True, "retries": retries}
        return {"ok": False, "retries": 1}

    def set_activity_time_limit(self, activity_id: str, minutes) -> dict:
        """Runner-only time limit (minutes, 0 = none) for one activity — the
        watchdog that fails a stuck activity so the run goes on. Saved to this
        Runner's config like the attempts; the workflow file is never touched."""
        try:
            value = max(0.0, float(minutes))
            if not math.isfinite(value):
                raise ValueError
        except (TypeError, ValueError):
            return {"ok": False, "timeLimit": 0}
        value = round(value, 2)
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                with self._runner_config_lock:
                    if not self._persist_runner_config(
                            {("activities", str(activity_id), "timeLimit"): value}):
                        return {"ok": False, "timeLimit": a.get("timeLimit", 0)}
                    a["timeLimit"] = value
                return {"ok": True, "timeLimit": value}
        return {"ok": False, "timeLimit": 0}

    def _each_activity_var(self, variables, prefix: str = ""):
        """Yield ``(dotted name, var)`` for a variable tree.

        Select options contribute ``parent.<option>.<child>``, the same key the
        engine seeds and the Runner settings panel edits.
        """
        for var in variables or []:
            if not isinstance(var, dict):
                continue
            name = str(var.get("name") or "").strip()
            if not name:
                continue
            full = f"{prefix}.{name}" if prefix else name
            yield full, var
            yield from self._each_activity_var(var.get("children") or [], full)
            option_children = var.get("optionChildren") or {}
            if isinstance(option_children, dict):
                for option, kids in option_children.items():
                    opt = str(option).strip()
                    if opt and isinstance(kids, list):
                        yield from self._each_activity_var(kids, f"{full}.{opt}")

    def _var_payload(self, v: dict) -> dict:
        item = {"name": v.get("name"), "label": v.get("label", ""),
                "type": v.get("type", "bool"), "value": v.get("value"),
                "options": v.get("options") or [],
                "display": v.get("display", "dropdown"),
                "multiple": v.get("display") == "toggle-group" and bool(v.get("multiple"))}
        children = [self._var_payload(c) for c in (v.get("children") or []) if isinstance(c, dict)]
        if children:
            item["children"] = children
        option_children = v.get("optionChildren") or {}
        if isinstance(option_children, dict):
            packed = {}
            for option, kids in option_children.items():
                if isinstance(kids, list) and kids:
                    packed[str(option)] = [self._var_payload(c) for c in kids if isinstance(c, dict)]
            if packed:
                item["optionChildren"] = packed
        return item

    def set_activity_var(self, activity_id: str, name: str, value) -> bool:
        """Override an activity variable's value (used at run time)."""
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                for full, v in self._each_activity_var(a.get("vars") or []):
                    if full == name:
                        if v.get("type") == "select":
                            options = v.get("options") or []
                            if v.get("display") == "toggle-group" and v.get("multiple"):
                                if not isinstance(value, list) or any(o not in options for o in value):
                                    return False
                                value = [o for o in options if o in value]
                            elif isinstance(value, list) or value not in options:
                                return False
                        with self._runner_config_lock:
                            if not self._persist_runner_config({("activities", str(activity_id), "vars", str(full)): value}):
                                return False
                            v["value"] = value
                        return True
        return False

    def set_node_runtime_param(self, node_id: str, param: str, value) -> bool:
        """Update an auto-generated runtime setting in the loaded flow."""
        if self.engine.is_running() or param not in RUNTIME_PATH_PARAMS:
            return False
        node = self._find_node(str(node_id or ""))
        if node is None:
            return False
        params = node.setdefault("params", {})
        if param not in params:
            return False
        with self._runner_config_lock:
            value = str(value or "").strip()
            if not self._persist_runner_config({("nodes", str(node_id), param): value}):
                return False
            params[param] = value
        return True

    def pick_node_runtime_path(self, node_id: str, param: str,
                               kind: str = "file", start: str = "") -> str:
        """Open the native file/folder picker for a generated path setting."""
        if self.engine.is_running() or param not in RUNTIME_PATH_PARAMS or self._window is None:
            return ""
        node = self._find_node(str(node_id or ""))
        if node is None or param not in (node.get("params") or {}):
            return ""
        types = (("Android package (*.apk)", "All files (*.*)") if param == "apk"
                 else ("Programs (*.exe;*.bat;*.cmd;*.com)", "All files (*.*)"))
        value = self._ask_path(kind, start, types)
        if not value:
            return ""
        return value if self.set_node_runtime_param(node_id, param, value) else ""

    def _ask_path(self, kind: str, start: str, types: tuple) -> str:
        """Native file/folder picker opened near ``start``; "" when cancelled."""
        if self._window is None:
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
                    file_types=types,
                )
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return str(path or "")
