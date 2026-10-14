"""Test runs, debug runs, single-block tests and Start game."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import List, Optional

from src.workflow import WorkflowEngine
from src.utils import (
    log_error,
    log_info,
    log_success,
    log_warning,
)
from designer.common import (
    _PROJECT_ROOT,
    _START_GAME_ADB_WAIT,
)


class RunMixin:
    """Test runs, debug runs, single-block tests and Start game."""

    # ── Test run ────────────────────────────────────────────────────────────────

    @staticmethod
    def _flow_is_win32(flow: Optional[dict]) -> bool:
        return str((flow or {}).get("controller") or "adb").strip().lower() == "win32"

    @staticmethod
    def _flow_has_launch_emulator(flow: Optional[dict]) -> bool:
        """A flow with a launch_emulator / if_emulator / wait_emulator node may
        start with no device — those nodes boot/find the emulator and the engine
        attaches to its ADB afterwards."""
        for coll in ("activities", "functions"):
            for item in (flow or {}).get(coll) or []:
                for n in ((item.get("graph") or {}).get("nodes") or []):
                    if n.get("type") in ("launch_emulator", "if_emulator", "wait_emulator"):
                        return True
        return False

    def workflow_run(self, flow_json: str) -> bool:
        try:
            flow = json.loads(flow_json)
        except Exception as exc:
            log_error(f"Invalid workflow JSON: {exc}")
            return False
        # Overlay design-test values (local_vars.json) for this test run.
        self._apply_local_vars(flow)
        # Win32 flows target a native window — no ADB device needed; the engine
        # attaches to the window itself in _ensure_ready_win32().
        is_win32 = self._flow_is_win32(flow)
        if not is_win32 and self.controller.device is None:
            if self._flow_has_launch_emulator(flow):
                log_info("No device yet — the Launch emulator node will boot one and connect")
            else:
                log_error("No device selected to run the workflow")
                return False
        if self._engine and self._engine.is_running():
            log_warning("Workflow is already running")
            return False
        if self._engine is None:
            self._engine = WorkflowEngine()
        serial = self._connected_serial or self._selected_serial
        self._engine.set_selected_device(serial)
        try:
            if serial and not is_win32:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Couldn't select a device for the engine: {exc}")
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        self._engine.load(flow, flow_path=anchor)
        self._engine.failure_screenshot_dir = os.path.join(_PROJECT_ROOT, "out", "workflow_failures")
        # Test runs stop at breakpoints; the Runner's engine never does.
        self._engine.honor_breakpoints = True
        self._bind_workflow_callbacks()
        # Test runs never auto-apply speedhack — that's a separate ▶ action.
        ok = self._engine.start(background=True, with_speedhack=False)
        self._push("workflow_state", {"running": ok})
        if ok:
            # Seed the panel with global vars immediately (activity vars arrive
            # via on_var when each activity starts).
            self._push("vars_snapshot", {"vars": self._engine.globals_snapshot()})
            log_success("Workflow started")
        return ok

    def workflow_stop(self) -> bool:
        if self._engine:
            self._engine.stop()
        self._push("workflow_state", {"running": False})
        return True

    # ── Start game ───────────────────────────────────────────────────────────
    # The toolbar 🚀 action: boot whatever Project settings point at, without
    # running the workflow graph. Win32 → launch the project game .exe and
    # attach the preview window; ADB → boot the configured emulator instance,
    # connect its ADB, then launch the project package.

    def start_game(self, flow_json: str) -> dict:
        try:
            flow = json.loads(flow_json)
        except Exception as exc:
            log_error(f"Invalid workflow JSON: {exc}")
            return {"ok": False, "error": str(exc)}
        if self._engine is not None and self._engine.is_running():
            msg = "A workflow test run is in progress — stop it first"
            log_warning(msg)
            return {"ok": False, "error": msg}
        if self._game_launching:
            msg = "The game is already starting"
            log_warning(msg)
            return {"ok": False, "error": msg}
        self._game_launching = True
        self._push("game_launch", {"starting": True})
        threading.Thread(target=self._start_game_worker, args=(flow,), daemon=True).start()
        return {"ok": True}

    def _start_game_worker(self, flow: dict) -> None:
        ok = False
        try:
            ok = (self._start_game_win32(flow) if self._flow_is_win32(flow)
                  else self._start_game_adb(flow))
        except Exception as exc:
            log_error(f"Start game failed: {exc}")
        self._game_launching = False
        self._push("game_launch", {"starting": False, "ok": ok})

    def _start_game_win32(self, flow: dict) -> bool:
        """Launch the project game .exe and attach the Preview controller."""
        cfg = flow.get("win32") if isinstance(flow, dict) else {}
        cfg = cfg if isinstance(cfg, dict) else {}
        path = str(cfg.get("path") or "").strip()
        if not path:
            log_error("No game path — set Game path (.exe) in Project settings")
            return False
        if not os.path.isfile(path):
            log_error(f"Game not found at '{path}' — check Game path in Project settings")
            return False
        try:
            from src.core.win32 import Win32Controller
            if self._win32 is None:
                self._win32 = Win32Controller(cfg)
            else:
                self._win32.configure(cfg)
            ctrl = self._win32
        except Exception as exc:
            log_error(f"Win32 controller error: {exc}")
            return False
        log_info(f"▶ Starting game: {path}")
        if not ctrl.launch_app(path):
            return False
        # Attach: poll the configured window pattern while the game opens — a
        # "pid" target is stale by definition after a fresh launch, so it (and
        # an empty target) binds the window the launched process just opened.
        # attach() runs the exe-name fallback + bridge check on a pattern hit.
        pattern, by, _mode = ctrl._match
        use_pattern = bool(pattern) and by != "pid"
        pid = getattr(ctrl, "last_launch_pid", None)
        end = time.time() + 20.0
        hwnd = None
        while time.time() < end and not self._closing:
            hwnd = (ctrl._find_hwnd(pattern, by) if use_pattern
                    else ctrl.find_window_by_pid(pid))
            if hwnd:
                break
            time.sleep(0.5)
        if hwnd and use_pattern:
            ctrl.attach()  # re-binds + logs the window title
        elif hwnd:
            ctrl.hwnd = hwnd
            try:
                title = ctrl._w[1].GetWindowText(hwnd) or ""
            except Exception:
                title = ""
            log_success(f"🪟 Window '{title or 'game'}' opened and attached")
        elif pattern:
            ctrl.attach()  # one noisy attempt: warning + exe-name fallback
            if not ctrl.device:
                log_warning("The game may still be loading — Preview attaches when its window appears")
        else:
            log_success("Game started — set a Target window in Project settings so Preview can capture it")
        # unity_bridge input needs the plugin DLL inside the new process — a
        # plain launch leaves it out and every in-game tap silently no-ops.
        # Inject once the window is up; the retry loop gives the runtime a
        # moment to finish init. A failure warns but the launch still counts.
        if ctrl.device and _mode == "unity_bridge":
            try:
                from src.core.win32 import unity_bridge
                port = int(cfg.get("bridgePort") or unity_bridge.DEFAULT_PORT)
                res = {}
                for _try in range(4):
                    res = unity_bridge.ensure_injected(path, port, pid)
                    if res.get("ok"):
                        log_success("Unity Bridge injected — in-game input is live")
                        break
                    if _try < 3:
                        time.sleep(2.0)
                if not res.get("ok"):
                    log_warning(
                        f"Unity Bridge not injected: {res.get('error') or 'unknown'} "
                        "— Project settings → Unity Bridge can deploy it")
            except Exception as exc:
                log_warning(f"Unity Bridge inject failed: {exc}")
        return True

    def _start_game_adb(self, flow: dict) -> bool:
        """Boot the project's emulator instance, connect it, launch the package."""
        emu = flow.get("emulator") if isinstance(flow, dict) else {}
        emu = emu if isinstance(emu, dict) else {}
        package = str((flow or {}).get("package") or "").strip()
        kind = str(emu.get("kind") or "ldplayer").strip().lower() or "ldplayer"
        try:
            index = max(0, int(float(emu.get("index", 0) or 0)))
        except (TypeError, ValueError):
            index = 0
        path = str(emu.get("path") or "").strip()

        if self._engine is None:
            self._engine = WorkflowEngine()
        eng = self._engine
        # Reuse the engine's family/port tables + console helpers; load() gives
        # it the project's emulator/package config so _emu_cfg resolves like a
        # test run. Clear _stop/_pause so a stopped run can't cut the wait short.
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        eng.load(flow, flow_path=anchor)
        eng._stop.clear()
        eng._pause.set()

        # The port is derivable for every family in EMULATOR_CONSOLES
        # (port0 + index*step); when the console can report the real port the
        # resolver refines it while waiting (MuMu Global deviates).
        p = {"path": path, "index": index}
        port = eng._emulator_adb_port(p, kind, index)
        host = f"127.0.0.1:{port}" if port else None

        if host and eng._emulator_adb_ready(host):
            log_info(f"Emulator {kind} #{index} already running ({host})")
        else:
            argv = eng._emulator_launch_argv(p, kind, index)
            if not argv:
                log_error(
                    f"Could not build the launch command for '{kind}' — set the "
                    "emulator Install folder in Project settings")
                return False
            try:
                log_info(f"▶ Starting emulator: {' '.join(argv)}")
                subprocess.Popen(
                    argv,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                )
            except Exception as exc:
                log_error(f"Couldn't start the emulator: {exc}")
                return False
            host = eng._wait_emulator_adb(
                port, _START_GAME_ADB_WAIT,
                resolver=lambda: eng._emulator_adb_port(p, kind, index))
            if not host:
                log_error(
                    f"Emulator {kind} #{index} didn't come up in "
                    f"{_START_GAME_ADB_WAIT:.0f}s — try Start game again once it boots")
                return False
        try:
            port = int(host.rsplit(":", 1)[1])
        except (IndexError, ValueError):
            pass

        # Same bookkeeping a launch_emulator node does, so if_emulator's
        # "last used" target finds this instance on the next run.
        eng._save_emulator_state({
            "emulator": kind,
            "index": index,
            "instance": "",
            "path": path,
            "port": port,
            "serial": host,
            "launched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

        # Hand the booted instance to the designer — the picker, Preview and the
        # next test run all point at it.
        self.select_device(host)
        end = time.time() + 20.0
        while time.time() < end and not self._closing:
            if self.controller.device is not None and self.controller.device_id == host:
                break
            time.sleep(0.5)
        if not (self.controller.device is not None and self.controller.device_id == host):
            log_warning(
                f"Emulator is up on {host} but the designer couldn't attach — "
                "select it in the device picker")

        if not package:
            log_success("Emulator ready — no Package name in Project settings, nothing to launch")
            return True
        log_info(f"▶ Launching {package}…")
        try:
            if not self.controller.launch_app(package):
                return False
        except Exception as exc:
            log_error(f"Couldn't launch {package}: {exc}")
            return False
        log_success(f"Game launched: {package} on {host}")
        # Refresh the picker now so the new serial shows as connected without
        # waiting for the next 5s poll.
        self._device_worker()
        return True

    def _bind_workflow_callbacks(self) -> None:
        if self._engine is None:
            return
        # Designer test runs capture a screenshot on every action's FINAL failure
        # (no per-node opt-in) so the inspector can show what the screen looked
        # like when the block failed.
        self._engine.capture_failures_always = True
        # Live match boxes on Preview during test run / Test-one-block.
        self._engine.report_matches = True
        self._engine.callbacks["on_stop"] = [lambda: self._push("workflow_state", {"running": False})]
        self._engine.callbacks["on_node"] = [lambda nid: self._push("node_active", {"id": nid})]
        self._engine.callbacks["on_breakpoint"] = [lambda nid: self._push("breakpoint_hit", {"id": nid})]
        self._engine.callbacks["on_node_done"] = [
            lambda nid, st, port: self._push("node_result", {
                "id": nid, "status": st, "port": port})]
        # Live pre-block delay countdown chip next to the active node.
        self._engine.callbacks["on_node_delay"] = [
            lambda nid, phase, secs: self._push(
                "node_delay", {"id": nid, "phase": phase, "seconds": secs})]
        self._engine.callbacks["on_var"] = [
            lambda name, value: self._push("var_update", {"name": name, "value": value})]
        self._engine.callbacks["on_activity_start"] = [
            lambda act: self._push("activity_active", {"id": act.get("id")})]
        self._engine.callbacks["on_activity_complete"] = [
            lambda act, ok: self._push("activity_result",
                                       {"id": act.get("id"), "status": "ok" if ok else "fail"})]
        # Where a failed activity actually died, so the panel can offer a
        # one-click jump back to that block after the run.
        self._engine.callbacks["on_activity_crash"] = [
            lambda act, crash: self._push("activity_crash",
                                          {"id": act.get("id"), "crash": crash or None})]
        self._engine.callbacks["on_fail_shot"] = [
            lambda nid, path: self._push("node_fail_shot", {"id": nid, "path": path})]
        self._engine.callbacks["on_match"] = [self._on_engine_match]

    def _on_engine_match(self, data) -> None:
        """Push match rects to Preview and freeze the frame the engine just used.

        ``data`` is the dict from WorkflowEngine.on_match (rects with conf/ok,
        optional search region, template label). Converts dict rects to the
        compact ``[x,y,w,h,conf,ok,label]`` arrays the canvas overlay expects.
        """
        data = data or {}
        out: List[list] = []
        for r in (data.get("rects") or []):
            if isinstance(r, dict):
                out.append([
                    float(r.get("x", 0)), float(r.get("y", 0)),
                    float(r.get("w", 0)), float(r.get("h", 0)),
                    float(r.get("conf", 0) or 0),
                    1 if r.get("ok") else 0,
                    str(r.get("label") or ""),
                ])
            elif isinstance(r, (list, tuple)) and len(r) >= 4:
                out.append(list(r))
        region = data.get("region")
        if region is not None and not isinstance(region, list):
            try:
                region = list(region)
            except Exception:
                region = None
        self._overlay = [(r[0], r[1], r[2], r[3], r[4]) for r in out]
        self._push("overlay", {
            "rects": out,
            "ok": bool(data.get("ok")),
            "label": data.get("label") or data.get("template") or "",
            "threshold": data.get("threshold"),
            "conf": data.get("conf"),
            "region": region,
        })
        # Push the engine's latest screen so Preview shows the frame the match
        # was computed on (even if the tab wasn't auto-refreshing).
        try:
            if self._engine is not None:
                screen = self._engine.auto.get_latest_screen()
                if screen is not None:
                    self._screen = screen
                    h, w = screen.shape[:2]
                    self._screen_w, self._screen_h = int(w), int(h)
                    self._push_frame(screen)
        except Exception:
            pass

    def open_path(self, path: str) -> bool:
        """Open a file/folder with the OS default app (fail-shot viewer)."""
        try:
            if path and os.path.exists(path):
                os.startfile(path)  # noqa: S606 — local tool, user-initiated
                return True
        except Exception as exc:
            log_warning(f"Couldn't open: {exc}")
        return False

    def workflow_run_from_node(self, flow_json: str, edit_kind: str, edit_id: str, node_id: str, step: bool = False) -> bool:
        try:
            flow = json.loads(flow_json)
        except Exception as exc:
            log_error(f"Invalid workflow JSON: {exc}")
            return False
        self._apply_local_vars(flow)
        is_win32 = self._flow_is_win32(flow)
        if not is_win32 and self.controller.device is None:
            if self._flow_has_launch_emulator(flow):
                log_info("No device yet — the Launch emulator node will boot one and connect")
            else:
                log_error("No device selected to run the workflow")
                return False
        if self._engine is None:
            self._engine = WorkflowEngine()
        if self._engine.is_running():
            log_warning("Workflow is already running")
            return False
        serial = self._connected_serial or self._selected_serial
        self._engine.set_selected_device(serial)
        try:
            if serial and not is_win32:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Couldn't select a device for the engine: {exc}")
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        self._engine.load(flow, flow_path=anchor)
        self._engine.failure_screenshot_dir = os.path.join(_PROJECT_ROOT, "out", "workflow_failures")
        # Test runs stop at breakpoints; the Runner's engine never does.
        self._engine.honor_breakpoints = True
        self._bind_workflow_callbacks()
        graph = None
        seed_act = {"vars": []}
        if edit_kind == "function":
            fn = next((f for f in flow.get("functions", []) or [] if f.get("id") == edit_id), None)
            graph = (fn or {}).get("graph")
            # Names the log prefix for this debug run.
            seed_act = {"vars": [], "name": (fn or {}).get("name") or "Function"}
        else:
            act = next((a for a in flow.get("activities", []) or [] if a.get("id") == edit_id), None)
            graph = (act or {}).get("graph")
            seed_act = act or seed_act
            if act:
                self._push("activity_active", {"id": act.get("id")})
        if not graph:
            log_error("No graph found to run")
            return False
        ok = self._engine.start_graph(graph, node_id, seed_act=seed_act, step=bool(step))
        self._push("workflow_state", {"running": ok})
        if ok:
            self._push("vars_snapshot", {"vars": self._engine.globals_snapshot()})
            log_success("Workflow debug run started")
        return ok

    def workflow_debug_step(self) -> bool:
        if self._engine:
            self._engine.debug_next()
            return True
        return False

    def workflow_debug_continue(self) -> bool:
        """Resume a run held at a breakpoint (or stepping) until the next one."""
        if self._engine:
            self._engine.debug_continue()
            return True
        return False

    def workflow_run_node(self, node_json: str, flow_json: str = "") -> dict:
        """Run a single node in isolation (no graph walk) — Test block.

        ``flow_json`` is the current serialized workflow so template paths resolve
        against the same templates dir. Emits on_node / on_node_done / on_match
        so the canvas paints the block and Preview draws match boxes.

        Returns ``{ok, status, port}`` (dict — not bare bool — so the UI can
        show the taken branch without waiting for a late event).
        """
        try:
            node = json.loads(node_json)
            flow = json.loads(flow_json) if flow_json else None
        except Exception as exc:
            log_error(f"Invalid JSON: {exc}")
            return {"ok": False, "status": "error", "port": None}
        if flow:
            self._apply_local_vars(flow)
        is_win32 = self._flow_is_win32(flow)
        if (not is_win32 and self.controller.device is None
                and node.get("type") not in ("launch_emulator", "if_emulator", "wait_emulator")):
            log_error("No device selected to run the block")
            return {"ok": False, "status": "error", "port": None}
        if self._engine is None:
            self._engine = WorkflowEngine()
        if self._engine.is_running():
            log_warning("Workflow is already running")
            return {"ok": False, "status": "busy", "port": None}
        serial = self._connected_serial or self._selected_serial
        self._engine.set_selected_device(serial)
        try:
            if serial and not is_win32:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Couldn't select a device for the engine: {exc}")
        # Load the current flow (templates base + functions) so the node runs
        # against the same assets as a full run. Anchor to the open file if any.
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        try:
            if flow:
                self._engine.load(flow, flow_path=anchor)
            else:
                log_warning("No flow to load for the block")
        except Exception as exc:
            log_warning(f"Couldn't load the flow for the block: {exc}")
        # Re-bind the same GUI callbacks a full test run uses.
        self._engine.failure_screenshot_dir = os.path.join(_PROJECT_ROOT, "out", "workflow_failures")
        # Test runs stop at breakpoints; the Runner's engine never does.
        self._engine.honor_breakpoints = True
        self._bind_workflow_callbacks()
        try:
            result = self._engine.run_single_node(node) or {}
        except Exception as exc:
            log_error(f"Block run error: {exc}")
            return {"ok": False, "status": "error", "port": None}
        status = result.get("status") or "ok"
        return {
            "ok": status not in ("error", "busy"),
            "status": status,
            "port": result.get("port"),
        }
