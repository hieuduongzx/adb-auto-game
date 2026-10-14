"""Execute JSON workflows against a connected device.

The engine wraps an :class:`~src.core.adb.auto.ADBGameAutomation` instance and
runs the **node graph** of each activity. It is shared by two front-ends:

* the **Run test** button in Macro2k Designer (design-time preview), and
* the standalone **runner GUI** (``apps/workflow_runner.py``).

Both feed it the exact same JSON, so a flow that runs in the designer runs
unchanged in the runner.

Each activity holds a directed **node graph** (``nodes`` + ``edges``). Execution
starts at the ``start`` node and follows output ports edge-by-edge:

* an **action** node (tap, swipe, …) runs, then follows its ``out`` port;
* an **if_image** node follows ``true`` or ``false`` depending on the match;
* a **loop** node follows ``body`` ``count`` times (wire the body back to the
  loop node to iterate), then ``done``;
* reaching an ``end`` node — or a port with no edge — ends the activity.

There are two activity modes:

* ``sequence``   — run the graph once (with ``maxRetries``), in order;
* ``background`` — run the graph in its own thread every ``pollInterval`` s.

JSON shape::

    {
      "name": "My Flow", "version": 2, "templatesDir": "out",
      "activities": [
        {
          "id": "daily", "name": "Daily", "type": "sequence",
          "enabled": true, "maxRetries": 1,
          "graph": {
            "nodes": [
              {"id": "n1", "type": "start", "x": 40,  "y": 40,  "params": {}},
              {"id": "n2", "type": "tap",   "x": 240, "y": 40,  "params": {"x": 100, "y": 200}},
              {"id": "n3", "type": "end",   "x": 440, "y": 40,  "params": {}}
            ],
            "edges": [
              {"from": "n1", "fromPort": "out", "to": "n2"},
              {"from": "n2", "fromPort": "out", "to": "n3"}
            ]
          }
        }
      ]
    }
"""
from __future__ import annotations

import json
from functools import wraps
import math
import os
import random
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

from src.utils import (
    LOG_KIND_ACTIVITY,
    LOG_KIND_RUN,
    LOG_KIND_USER,
    get_log_activity,
    log_activity,
    set_log_activity,
    set_log_node,
)
from src.workflow.catalog import MAX_CALL_DEPTH, MAX_STEPS, NODE_TYPES, SWITCH_CASE_TYPES
from src.core import ADBGameAutomation
from src.workflow.nodes import (
    ActionNodes,
    ConditionNodes,
    EmulatorNodes,
    SpeedhackSupport,
    VisionHelpers,
    Win32Nodes,
)
# Re-exported: callers and tests reach these through ``engine``.
from src.workflow.nodes.emulator import (  # noqa: F401
    EMU_INDEX_MAX,
    EMU_PLAYER_EXES,
    EMU_SELECTED,
    EMULATOR_CONSOLES,
    _emulator_family_from_exe,
    _emulator_port_candidates,
    _enum_player_windows,
    _find_emulator_window,
    _pick_player_window,
    _split_emulator_serial,
    _tcp_listener_pids,
)
from src.workflow.logs import log_error, log_info, log_success, log_warning

if TYPE_CHECKING:
    from src.core.frida_speedhack import FridaSpeedhackManager


def _serialize_run_start(method):
    """Reserve readiness and worker creation across every run entry point."""
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if not self._run_start_lock.acquire(blocking=False):
            return False
        try:
            return method(self, *args, **kwargs)
        finally:
            self._run_start_lock.release()
    return guarded


class WorkflowEngine(VisionHelpers, ConditionNodes, ActionNodes, EmulatorNodes,
                     Win32Nodes, SpeedhackSupport):
    """Run a JSON workflow, honouring pause/stop and the sequence/background split."""

    def __init__(
        self,
        automation: Optional[ADBGameAutomation] = None,
        ocr_backend: Optional[str] = None,
    ) -> None:
        self.auto = automation or ADBGameAutomation(ocr_backend=ocr_backend)
        # Match images exactly like the Dev Helper tester: single scale (1.0) at the
        # given threshold. Templates are QuickCropped on the same device at native
        # resolution, so the auto-orientation scale-sweep (0.8–1.2) + portrait
        # threshold-loosening only produces shifted / false matches here — the very
        # reason a tap that's correct in the tester lands wrong in a run.
        self.auto.auto_orientation_detection = False

        self.flow: Dict[str, Any] = {}
        self.flow_path: Optional[str] = None
        self.templates_base: str = ""
        # Shared emulator choice for ADB projects (flow["emulator"] = {kind,path}).
        # Emulator nodes set to "Project emulator setting" read kind + install
        # folder here instead of carrying their own copy.
        self._emu_cfg: Dict[str, Any] = {}
        # Global workflow variables — declared once at the flow top level
        # (``globals``) and seeded into EVERY activity/thread before its own
        # activity-local vars. Lets a counter or flag set in one place be seen
        # by every block in the workflow. Runtime writes to a global name keep
        # the shared dict in sync so other threads read the latest value.
        self._globals: Dict[str, Any] = {}
        # Target Android package for this flow (top-level ``package`` key).
        # Independent of speedhack; used as the default inject target and a
        # project-level app id. Legacy files may still nest it under speedhack.
        self.package: str = ""
        # Speedhack: a Frida clock_gettime time-scale, configured per-flow under
        # the top-level ``speedhack`` key ({enabled, speed}). The engine owns the
        # manager so both the designer's "Run test" and the runner GUI get it for
        # free. Package comes from ``self.package``. See frida_speedhack.py.
        self.speedhack_cfg: Dict[str, Any] = {}
        self._speedhack: Optional[FridaSpeedhackManager] = None
        self._speedhack_stop: Optional[threading.Event] = None
        self._speed_scale: float = 1.0
        # Reusable subroutines, keyed by id. Each value is a function dict with
        # its own ``graph`` (nodes + edges); a ``call`` node runs one inline.
        self._functions: Dict[str, Dict[str, Any]] = {}
        # Per-thread execution context. The sequence thread, every parallel branch
        # and every background activity each run a graph CONCURRENTLY; if they
        # shared one vars dict / last-found-position they would clobber each other
        # (a background popup-watcher resetting the main farm's variables, etc.).
        # Backing _vars/_last_pos/_break_loop with thread-local storage isolates
        # them automatically — see the properties below. A ``call`` runs on the
        # caller's thread, so a function correctly shares its caller's context.
        self._ctx = threading.local()
        self._debug_step = False
        self._debug_gate = threading.Event()
        self._debug_gate.set()
        self.failure_screenshot_dir: Optional[str] = None
        # The ADB serial the host app's device picker currently has selected —
        # what the emulator nodes' "selected" target resolves against. Pushed in
        # by the Designer/Runner (set_selected_device); empty in a bare engine.
        self.selected_serial: str = ""
        # When True (the designer's test runs), a failure screenshot is captured
        # for EVERY final action failure — not just nodes that opted in via
        # screenshotOnFail — so the designer can show "what the screen looked
        # like when this block failed" without per-node setup.
        self.capture_failures_always = False
        # When True (designer only), image/color/OCR matches emit ``on_match``
        # with rects + confidence so the Preview tab can draw a live overlay.
        # Off in the standalone runner — no UI to paint and no need for the
        # best-score-below-threshold extra match work on every miss.
        self.report_matches = False
        # Designer test runs pause *before* any block flagged ``breakpoint``
        # (see _hit_breakpoint). Off by default, so the Runner never does.
        self.honor_breakpoints = False
        # Passes a full Start makes over the sequence (configure_rounds):
        # 1 = once, N = N times, 0 = until stopped; rest = seconds between.
        self.rounds = 1
        self.round_rest = 0.0

        self.running = False
        self._run_start_lock = threading.Lock()
        # Last block an activity died on, shared across branch threads — see
        # _note_crash. Reset at the start of every activity.
        self._crash: Optional[Dict[str, Any]] = None
        self._crash_lock = threading.Lock()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # not paused

        self._seq_thread: Optional[threading.Thread] = None
        self._bg_threads: Dict[str, threading.Thread] = {}
        self._bg_stop: Dict[str, threading.Event] = {}
        self._bg_lock = threading.RLock()
        self._retired_bg_threads: Dict[str, threading.Thread] = {}
        self._sequence_stops: Dict[str, threading.Event] = {}
        self._sequence_stops_lock = threading.Lock()

        # GUI hooks; all optional.
        self.callbacks: Dict[str, List[Callable]] = {
            "on_start": [], "on_stop": [],
            "on_activity_start": [], "on_activity_complete": [],
            "on_node": [],  # fired with the node id about to execute (None = idle)
            # fired after a node runs: (node_id, status, port). status is "ok" or
            # "fail" (an action whose handler returned False); port is the output
            # actually taken (a condition's "true"/"false", a loop's "body"/"done",
            # else "out"). Lets the designer paint the executed path + branch taken.
            "on_node_done": [],
            # fired when a per-node delay starts or ends:
            # (node_id, phase, seconds). phase is "before" | "after" while waiting,
            # or None when the wait finishes / is cancelled. seconds is the full
            # wait length on start (0 on end). Designer shows a live countdown.
            "on_node_delay": [],
            # fired whenever a variable changes: (name, value). Lets the designer
            # show a live "current variables" panel during a test run.
            "on_var": [],
            # fired after a failure screenshot is written: (node_id, path). The
            # designer shows it in the inspector when the failed node is selected.
            "on_fail_shot": [],
            # fired after a template/color/OCR probe: one dict with rects
            # [{x,y,w,h,conf,ok,label}, …], threshold, template name, optional
            # search region. Designer paints these on the Preview canvas.
            "on_match": [],
            # fired once when an activity ends in failure: (activity, crash).
            # ``crash`` is the _crash dict below — the block the run actually
            # died on — or None when the activity failed with no identifiable
            # block (e.g. an empty graph). Lets the designer keep a "last crash
            # point" marker you can jump straight back to.
            "on_activity_crash": [],
            # fired by a repeating full Start: one dict {round, total (0 = until
            # stopped), phase "running" | "resting", restUntil (epoch, resting
            # only)}. Not fired for a single pass, the default.
            "on_round": [],
            # fired when a run holds at a breakpoint block: (node_id). The run
            # is then in step mode — debug_next() / debug_continue() resume it.
            "on_breakpoint": [],
        }

        # Dispatch table for action nodes: type -> handler(node, params) -> bool.
        self._actions: Dict[str, Callable[[Dict, Dict], bool]] = {
            "tap": self._a_tap,
            "multi_tap": self._a_multi_tap,
            "sequence_tap": self._a_sequence_tap,
            "sequence_tap_image": self._a_sequence_tap_image,
            "stop_sequence": self._a_stop_sequence,
            "double_tap": self._a_double_tap,
            "tap_random": self._a_tap_random,
            "long_press": self._a_long_press,
            "swipe": self._a_swipe,
            "swipe_dir": self._a_swipe_dir,
            "wait": self._a_wait,
            "wait_random": self._a_wait_random,
            "send_text": self._a_send_text,
            "key": self._a_key,
            "back": self._a_back,
            "home": self._a_home,
            "launch_app": self._a_launch_app,
            "screenshot": self._a_screenshot,
            "log": self._a_log,
            "set_var": self._a_set_var,
            "calc_var": self._a_calc_var,
            "read_var": self._a_read_var,
            "parse_var": self._a_parse_var,
            "break":      self._a_break,
            "format_var": self._a_format_var,
            "notify":     self._a_notify,
            "get_time":     self._a_get_time,
            "wait_until":   self._a_wait_until,
            "device_info":  self._a_device_info,
            "screen_power": self._a_screen_power,
            "adb_shell":    self._a_adb_shell,
            "read_color":   self._a_read_color,
            "launch_emulator": self._a_launch_emulator,
            "resize_emulator": self._a_resize_emulator,
            "kill_emulator":   self._a_kill_emulator,
            "restart_emulator": self._a_restart_emulator,
            "emulator_resolution": self._a_emulator_resolution,
            "win_send_text":self._a_send_text,
            "win_key":      self._a_win_key,
            "win_hotkey":   self._a_win_hotkey,
            "win_escape":   self._a_back,
            "win_click":    self._a_win_click,
            "win_scroll":   self._a_win_scroll,
            "win_mouse_move": self._a_win_mouse_move,
            "win_launch":   self._a_win_launch,
            "win_activate": self._a_win_activate,
            "win_close":    self._a_win_close,
            "win_kill":     self._a_win_kill,
            "win_resize":   self._a_win_resize,
            "win_move":     self._a_win_move,
            "win_minimize": self._a_win_minimize,
            "win_maximize": self._a_win_maximize,
            "win_restore":  self._a_win_restore,
            "win_always_on_top": self._a_win_always_on_top,
            "win_set_title": self._a_win_set_title,
            "win_style":    self._a_win_style,
            "win_info":     self._a_win_info,
            "app_stop":     self._a_app_stop,
            "app_uninstall": self._a_app_uninstall,
            "app_install":  self._a_app_install,
            "app_exit":     self._a_app_exit,
        }

    # ── Per-thread execution context ─────────────────────────────────────────
    # These read/write the *current thread's* slot, so the existing
    # ``self._vars[...]`` / ``self._last_pos`` accesses scattered through the
    # handlers stay unchanged but become thread-isolated.

    def _set_var(self, name: str, value: Any) -> None:
        """Write a variable and notify ``on_var`` subscribers (live var panel).

        If ``name`` is a declared global, the shared ``_globals`` dict is kept
        in sync so other threads/activities see the latest value too. Changing a
        select drops the previous option's children and seeds the new one's.
        """
        if not name:
            return
        self._vars[name] = value
        if name in self._globals:
            self._globals[name] = value
        self._emit("on_var", name, value)
        self._sync_option_children(name, value)

    def _select_defs(self) -> List[tuple]:
        """``(dotted name, select var)`` for every declared select in the flow."""
        found: List[tuple] = []

        def walk(variables, prefix: str = "") -> None:
            for var in variables or []:
                if not isinstance(var, dict):
                    continue
                nm = str(var.get("name") or "").strip()
                if not nm:
                    continue
                full = f"{prefix}.{nm}" if prefix else nm
                if var.get("type") == "select":
                    found.append((full, var))
                walk(var.get("children") or [], full)
                option_children = var.get("optionChildren") or {}
                if isinstance(option_children, dict):
                    for option, kids in option_children.items():
                        opt = str(option).strip()
                        if opt and isinstance(kids, list):
                            walk(kids, f"{full}.{opt}")

        flow = self.flow if isinstance(self.flow, dict) else {}
        walk(flow.get("globals") or [])
        for act in flow.get("activities") or []:
            if isinstance(act, dict):
                walk(act.get("vars") or [])
        return found

    def _sync_option_children(self, name: str, value: Any) -> None:
        """Keep only the option branches that match a select's new value."""
        # Later declarations win, matching seed order: activity vars override globals.
        matches = [var for full, var in self._select_defs() if full == name]
        match = matches[-1] if matches else None
        if match is None:
            return
        active = {str(item) for item in value} if isinstance(value, list) else {str(value)}
        option_children = match.get("optionChildren") or {}
        if not isinstance(option_children, dict):
            return
        # Drop only keys that belong to an option. A child of the select itself
        # (``mode.shared``) stays; switching options must not reset it.
        options = {str(option).strip() for option in option_children if str(option).strip()}
        prefix = f"{name}."
        for key in list(self._vars):
            if not str(key).startswith(prefix):
                continue
            head = str(key)[len(prefix):].split(".", 1)[0]
            if head in options:
                del self._vars[key]
                self._emit("on_var", key, None)
        for option, kids in option_children.items():
            opt = str(option).strip()
            if opt in active and isinstance(kids, list):
                for child in kids:
                    self._seed_var(child, self._vars, f"{name}.{opt}")
        for key, seeded in self._vars.items():
            if key.startswith(prefix):
                self._emit("on_var", key, seeded)

    @property
    def _vars(self) -> Dict[str, Any]:
        v = getattr(self._ctx, "vars", None)
        if v is None:
            v = {}
            self._ctx.vars = v
        return v

    @_vars.setter
    def _vars(self, value: Dict[str, Any]) -> None:
        self._ctx.vars = value if value is not None else {}

    @property
    def _last_pos(self) -> Optional[tuple]:
        return getattr(self._ctx, "last_pos", None)

    @_last_pos.setter
    def _last_pos(self, value: Optional[tuple]) -> None:
        self._ctx.last_pos = value

    @property
    def _break_loop(self) -> bool:
        return getattr(self._ctx, "break_loop", False)

    @_break_loop.setter
    def _break_loop(self, value: bool) -> None:
        self._ctx.break_loop = value

    # Set True when the current try_chain branch reaches an unhandled failure.
    # A condition returning false is only unhandled when its false/out path is not
    # wired; if the graph handles that path, the branch may still succeed.
    @property
    def _branch_failed(self) -> bool:
        return getattr(self._ctx, "branch_failed", False)

    @_branch_failed.setter
    def _branch_failed(self, value: bool) -> None:
        self._ctx.branch_failed = value

    # Set True when the current walk reaches an ``end`` node. A ``call`` resets
    # it before running its function graph and reads it after: reached End →
    # the call's "true" port, dead-ended (timeout etc.) → "false".
    @property
    def _reached_end(self) -> bool:
        return getattr(self._ctx, "reached_end", False)

    @_reached_end.setter
    def _reached_end(self, value: bool) -> None:
        self._ctx.reached_end = value

    @property
    def _try_chain_mode(self) -> bool:
        return getattr(self._ctx, "try_chain_mode", False)

    @_try_chain_mode.setter
    def _try_chain_mode(self, value: bool) -> None:
        self._ctx.try_chain_mode = value

    # ── Crash point ──────────────────────────────────────────────────────────
    # "Where did this activity actually die?" — the single most-asked question
    # after a long unattended run. Unlike _branch_failed / _reached_end this is
    # NOT thread-local: a parallel branch running on its own thread is exactly
    # the case you most need the answer for, so the record is shared and the
    # lock keeps two branches failing at once from interleaving.
    def _note_crash(self, node: Optional[Dict], reason: str,
                    message: str = "", weak: bool = False) -> None:
        """Remember the block a run died on.

        ``weak`` records only when nothing better is known yet: a dead end is
        the *symptom* of the action failure that came just before it (the failed
        block's "fail" port was left unwired), so the action keeps priority.
        """
        if not isinstance(node, dict):
            return
        with self._crash_lock:
            if weak and self._crash is not None:
                return
            ntype = node.get("type") or ""
            self._crash = {
                "node": node.get("id"),
                "type": ntype,
                "label": (NODE_TYPES.get(ntype, {}).get("label") or ntype or "block"),
                "name": str(node.get("name") or "").strip(),
                "reason": reason,
                "message": str(message or "")[:400],
                "ts": time.time(),
            }

    # ── Callbacks ────────────────────────────────────────────────────────────

    def on(self, event: str, fn: Callable) -> None:
        if event in self.callbacks:
            self.callbacks[event].append(fn)

    def _emit(self, event: str, *args) -> None:
        for fn in self.callbacks.get(event, []):
            try:
                fn(*args)
            except Exception as e:  # pragma: no cover - UI callback safety
                log_error(f"callback {event} failed: {e}")

    # ── Flow loading ─────────────────────────────────────────────────────────

    def load(self, flow: Dict[str, Any], flow_path: Optional[str] = None) -> None:
        """Install a parsed flow dict. ``flow_path`` anchors relative templates."""
        self.flow = flow or {}
        self.flow_path = flow_path
        # Which backend drives the flow: "adb" (Android device/emulator) or
        # "win32" (a native Windows program window). Selected in the designer's
        # project settings and honoured by _ensure_ready().
        self._controller = str(self.flow.get("controller") or "adb").strip().lower()
        self._win32_cfg = dict(self.flow.get("win32") or {})
        self._emu_cfg = dict(self.flow.get("emulator") or {})
        self.speedhack_cfg = dict(self.flow.get("speedhack") or {})
        # Workflow package: prefer top-level key; migrate legacy speedhack.package.
        pkg = str(self.flow.get("package") or "").strip()
        if not pkg:
            pkg = str((self.speedhack_cfg or {}).get("package") or "").strip()
        self.package = pkg
        # OCR model của flow. OCRReader migrates legacy engine names to the
        # sole current model (PP-OCRv5 Mobile recognition).
        self._ocr_backend = str(self.flow.get("ocr") or "").strip().lower()
        # ADB frame source for this flow: "scrcpy" | "adb". Key "capture" (also
        # accept legacy captureBackend / capture_backend). Applied on load so
        # designer preview + runner + test runs share the same source.
        cap_raw = (
            self.flow.get("capture")
            if self.flow.get("capture") not in (None, "")
            else self.flow.get("captureBackend")
            if self.flow.get("captureBackend") not in (None, "")
            else self.flow.get("capture_backend")
        )
        self._capture_backend = str(cap_raw or "").strip().lower()
        self._apply_capture_backend()
        # ADB input transport for this flow ("adb" | "scrcpy"). Key "input"
        # (also accept legacy inputBackend / input_backend); empty keeps the
        # process default (adb shell). Win32 flows ignore this — their transport
        # is win32.inputMode instead.
        in_raw = (
            self.flow.get("input")
            if self.flow.get("input") not in (None, "")
            else self.flow.get("inputBackend")
            if self.flow.get("inputBackend") not in (None, "")
            else self.flow.get("input_backend")
        )
        self._input_backend = str(in_raw or "").strip().lower()
        self._apply_input_backend()
        self._functions = {f.get("id"): f for f in (self.flow.get("functions") or []) if f.get("id")}
        # Global vars: declared at flow top level (``globals``), seeded into every
        # thread below. Reset the shared runtime dict on (re)load.
        self._globals = self._seed_vars({"vars": self.flow.get("globals") or []})

        base = (self.flow.get("templatesDir") or "").strip()
        anchors: List[str] = []
        if flow_path:
            anchors.append(os.path.dirname(os.path.abspath(flow_path)))
        anchors.append(os.getcwd())
        if base and os.path.isabs(base) and os.path.isdir(base):
            self.templates_base = base
        else:
            self.templates_base = ""
            for anchor in anchors:
                cand = os.path.join(anchor, base) if base else anchor
                if os.path.isdir(cand):
                    self.templates_base = cand
                    break
            if not self.templates_base:
                self.templates_base = anchors[0]
        log_info(
            f"Loaded '{self.flow.get('name', 'flow')}' "
            f"({len(self.activities())} activities), templates@ {self.templates_base}"
        )

    def globals_snapshot(self) -> Dict[str, Any]:
        """Public copy of the shared global-vars dict (for GUI var panels)."""
        return dict(self._globals or {})

    @staticmethod
    def load_file(path: str) -> Dict[str, Any]:
        """Read + JSON-decode a flow file (raises on bad JSON/IO).

        Transparently decrypts a packaged Runner's bundled ``workflow.json``
        (see ``src/utils/asset_crypto.py``); a plain file (source/Designer)
        round-trips through ``maybe_decrypt`` as a no-op."""
        from src.utils.asset_crypto import maybe_decrypt
        with open(path, "rb") as fh:
            raw = fh.read()
        return json.loads(maybe_decrypt(raw).decode("utf-8"))

    def activities(self) -> List[Dict[str, Any]]:
        return list(self.flow.get("activities", []) or [])

    def _resolve_template(self, raw: str) -> str:
        """Make a template path absolute, preferring the flow's templates dir."""
        raw = (raw or "").strip().replace("\\", "/")
        if not raw:
            return raw
        if os.path.isabs(raw) and os.path.exists(raw):
            return raw
        candidates = [os.path.join(self.templates_base, raw)]
        if self.flow_path:
            candidates.append(os.path.join(os.path.dirname(self.flow_path), raw))
        candidates.append(raw)
        for c in candidates:
            if os.path.exists(c):
                return c
        return candidates[0]

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _apply_ocr_backend(self) -> None:
        """Apply the workflow's recognition model to the active automation.

        Gọi sau khi backend (ADB/Win32) sẵn sàng — cả hai đều có ``self.auto.ocr``
        (OCRReader). Backend không khả dụng chỉ cảnh báo, không chặn run.
        """
        name = getattr(self, "_ocr_backend", "")
        if not name:
            return
        try:
            ocr = getattr(self.auto, "ocr", None)
            if ocr is None or getattr(ocr, "backend_name", None) == name:
                return
            if hasattr(self.auto, "set_ocr_backend"):
                ok = bool(self.auto.set_ocr_backend(name))
            else:
                ok = bool(ocr.set_backend(name))
            if ok:
                log_info(f"OCR model: {getattr(ocr, 'backend_name', name)}")
            else:
                log_warning(f"OCR model '{name}' is unavailable")
        except Exception as e:
            log_warning(f"Could not change OCR model to '{name}': {e}")

    def _apply_capture_backend(self) -> None:
        """Apply the flow's ADB capture source (scrcpy / adb screencap).

        Empty / missing key leaves the process-wide default alone (scrcpy).
        Only meaningful for ADB flows; Win32 captures windows, not this path.
        """
        name = getattr(self, "_capture_backend", "") or ""
        if name not in ("scrcpy", "adb"):
            return
        try:
            from src.core.adb.auto.scrcpy_capture import (
                get_capture_backend,
                set_capture_backend,
            )
            if get_capture_backend() == name:
                return
            set_capture_backend(name)
            log_info(f"Capture backend: {name}")
        except Exception as e:
            log_warning(f"Could not change capture backend to '{name}': {e}")

    def _apply_input_backend(self) -> None:
        """Apply the flow's ADB input transport ("adb" shell vs "scrcpy" control).

        Empty / missing key leaves the process default alone. Only meaningful
        for ADB flows; Win32 uses ``win32.inputMode`` instead.
        """
        name = getattr(self, "_input_backend", "") or ""
        if name not in ("adb", "scrcpy"):
            return
        try:
            from src.core.adb.input import (
                get_input_backend,
                set_input_backend,
            )
            if get_input_backend() == name:
                return
            set_input_backend(name)
            log_info(f"ADB input backend: {name}")
        except Exception as e:
            log_warning(f"Could not change ADB input backend to '{name}': {e}")

    def _flow_has_node_type(self, *ntypes: str) -> bool:
        """True if any activity/function graph in the loaded flow contains a
        node of one of the given types."""
        graphs = [(a.get("graph") or {}) for a in (self.flow.get("activities") or [])]
        graphs += [(f.get("graph") or {}) for f in (self.flow.get("functions") or [])]
        return any(
            str(n.get("type")) in ntypes
            for g in graphs for n in (g.get("nodes") or [])
        )

    def _ensure_ready(self) -> bool:
        """Connect the selected backend + start continuous capture if needed."""
        if getattr(self, "_controller", "adb") == "win32":
            return self._ensure_ready_win32()
        try:
            if not self.auto.adb.device:
                self.auto.adb.check_adb_connection()
            if not self.auto.adb.device:
                # A flow with a launch_emulator / if_emulator / wait_emulator
                # node may legitimately start with no device — those nodes
                # boot/find the emulator and attach to its ADB
                # (_attach_adb_after_boot).
                if self._flow_has_node_type("launch_emulator", "if_emulator", "wait_emulator"):
                    log_info("No device yet — an emulator node will boot/attach one")
                    self._apply_ocr_backend()
                    return True
                log_error("No ADB device connected")
                return False
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
            self._apply_ocr_backend()
            return True
        except Exception as e:
            log_error(f"Not ready: {e}")
            return False

    def _ensure_ready_win32(self) -> bool:
        """Attach to the target window + start window capture (Win32 backend).

        Swaps ``self.auto`` to a :class:`Win32GameAutomation` on first use (the
        engine builds an ADB backend by default in __init__), then attaches to
        the configured window."""
        try:
            from src.core.win32 import Win32GameAutomation
            if not isinstance(self.auto, Win32GameAutomation):
                try:
                    self.auto.stop_continuous_capture()
                except Exception:
                    pass
                self.auto = Win32GameAutomation(cfg=self._win32_cfg)
            else:
                self.auto.configure(self._win32_cfg)
            target = str(self._win32_cfg.get("window", "") or "").strip()
            has_launcher = self._flow_has_node_type("win_launch")
            if not self.auto.adb.device and target:
                self.auto.adb.check_adb_connection()  # attach an already-open window
            if not self.auto.adb.device:
                # A workflow may intentionally start the Windows program itself.
                # Do not require a Project-settings target before its Launch
                # program node has had a chance to create and attach the window.
                if has_launcher:
                    log_info("No Win32 target yet — Launch program will start/attach it")
                    self._apply_ocr_backend()
                    return True
                log_error(
                    f"Win32: window '{target}' not found — check Project settings"
                )
                return False
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
            self._apply_ocr_backend()
            return True
        except Exception as e:
            log_error(f"Win32 not ready: {e}")
            return False

    def _seq_thread_gone(self) -> bool:
        """True when no previous sequence/background worker is still unwinding.

        ``stop()`` only gives the old thread ~1s before reporting stopped; a
        node blocked in a long ADB call can outlive that. If a new start()
        cleared ``_stop`` while that thread was still inside a node, it would
        wake up and keep executing alongside the new run — two walkers driving
        one device. Give it a short grace join, then refuse."""
        prev = self._seq_thread
        with self._bg_lock:
            retired = list(self._retired_bg_threads.values())
        deadline = time.monotonic() + 2.0
        for worker in ([prev] if prev else []) + retired:
            if worker is threading.current_thread() or not worker.is_alive():
                continue
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
            if worker.is_alive():
                return False
        return True

    @_serialize_run_start
    def start(self, background: bool = True, with_speedhack: bool = True) -> bool:
        """Run all enabled sequence activities once, then start backgrounds.

        ``with_speedhack`` lets a caller run the flow *without* auto-applying its
        speedhack config — the designer's "Run test" passes ``False`` so testing a
        flow never injects Frida; speedhack there is a separate, manual action.
        """
        if self.running:
            log_warning("Already running", kind=LOG_KIND_RUN)
            return False
        if not self._seq_thread_gone():
            log_error("Previous run is still unwinding — wait a moment, then run again",
                      kind=LOG_KIND_RUN)
            return False
        if not self._ensure_ready():
            return False
        self._stop.clear()
        self.auto._stop_event.clear()
        self._pause.set()
        # A breakpoint left the last run in step mode; a new run starts free.
        self._debug_step = False
        self._debug_gate.set()
        self.running = True
        enabled = [a for a in self.activities() if a.get("enabled", True)]
        n_seq = sum(1 for a in enabled if a.get("type") != "background")
        n_bg = (len(enabled) - n_seq) if background else 0
        log_info(f"▶ Run started — {n_seq} activit{'y' if n_seq == 1 else 'ies'}"
                 + (f" + {n_bg} background" if n_bg else ""), kind=LOG_KIND_RUN)
        self._emit("on_start")

        if with_speedhack:
            self._start_speedhack()

        if background:
            self.start_all_background()

        self._seq_thread = threading.Thread(target=self._run_sequence, daemon=True)
        self._seq_thread.start()
        return True

    @_serialize_run_start
    def start_activity(self, activity_id: str, with_speedhack: bool = True) -> bool:
        """Run one activity on its own, whatever its ``enabled`` flag says.

        A sequence activity runs once (with its retries) and the engine stops;
        a background activity starts its polling loop and runs until
        :meth:`stop`. Used by the Runner's per-activity Run button.
        """
        act = next((a for a in self.activities() if str(a.get("id")) == str(activity_id)), None)
        if act is None:
            # The id came from a GUI list, so echoing it back tells the user
            # nothing — naming what IS here is what makes the mismatch visible.
            known = ", ".join(self._label(a) for a in self.activities())
            log_warning(f"Activity '{activity_id}' not found — workflow has: "
                        + (known or "(no activities)"), kind=LOG_KIND_RUN)
            return False
        if self.running:
            log_warning("Already running", kind=LOG_KIND_RUN)
            return False
        if not self._seq_thread_gone():
            log_error("Previous run is still unwinding — wait a moment, then run again",
                      kind=LOG_KIND_RUN)
            return False
        if not self._ensure_ready():
            return False
        self._stop.clear()
        self.auto._stop_event.clear()
        self._pause.set()
        # A breakpoint left the last run in step mode; a new run starts free.
        self._debug_step = False
        self._debug_gate.set()
        self.running = True
        self._emit("on_start")

        if with_speedhack:
            self._start_speedhack()

        if act.get("type") == "background":
            self.start_background(act)
            return True

        self._seq_thread = threading.Thread(target=self._run_single_activity, args=(act,), daemon=True)
        self._seq_thread.start()
        return True

    def _run_single_activity(self, act: Dict[str, Any]) -> None:
        try:
            self._run_activity(act)
        except Exception as e:
            with log_activity(act.get("name") or act.get("id")):
                log_error(f"✖ Crashed: {e}", kind=LOG_KIND_ACTIVITY)
        finally:
            if not self._bg_threads and not self._retired_bg_threads:
                self.running = False
                self._emit("on_stop")

    @_serialize_run_start
    def start_graph(self, graph: Dict[str, Any], start_id: str, seed_act: Optional[Dict[str, Any]] = None, step: bool = False) -> bool:
        """Run one graph from an arbitrary node, used by designer debug tools."""
        if self.running:
            log_warning("Already running", kind=LOG_KIND_RUN)
            return False
        if not self._seq_thread_gone():
            log_error("Previous run is still unwinding — wait a moment, then run again",
                      kind=LOG_KIND_RUN)
            return False
        if not self._ensure_ready():
            return False
        self._stop.clear()
        self.auto._stop_event.clear()
        self._pause.set()
        self._debug_step = bool(step)
        if step:
            self._debug_gate.clear()
        else:
            self._debug_gate.set()
        self.running = True
        self._emit("on_start")
        self._seq_thread = threading.Thread(
            target=self._run_graph_from_node,
            args=(graph or {}, start_id, seed_act or {"vars": []}),
            daemon=True,
        )
        self._seq_thread.start()
        return True

    def _run_graph_from_node(self, graph: Dict[str, Any], start_id: str, seed_act: Dict[str, Any]) -> None:
        # Dedicated thread: its logs belong to the activity / function under test.
        set_log_activity(seed_act.get("name") or seed_act.get("id") or "Debug run")
        try:
            self._vars = self._seed_vars(seed_act)
            self._last_pos = None
            self._break_loop = False
            self._branch_failed = False
            self._try_chain_mode = False
            self._fatal = ""
            for k, v in self._vars.items():
                self._emit("on_var", k, v)
            self._run_graph(graph, start_id=start_id)
        except Exception as e:
            log_error(f"Debug run error: {e}", kind=LOG_KIND_ACTIVITY)
        finally:
            self._debug_step = False
            self._debug_gate.set()
            self.running = False
            self._emit("on_node", None)
            self._emit("on_stop")
            set_log_activity(None)

    def configure_rounds(self, count: Any = 1, rest: Any = 0) -> Dict[str, Any]:
        """How many passes a full Start makes over the sequence activities.

        ``count`` 1 runs the sequence once (the default); N > 1 runs it N times;
        0 repeats it until stopped. ``rest`` is the pause between two passes, in
        seconds. Background activities are unaffected — they keep looping on
        their own schedule throughout. Takes effect from the next Start.
        """
        try:
            rounds = max(0, int(float(count)))
        except (TypeError, ValueError, OverflowError):
            rounds = 1
        try:
            pause = float(rest)
            pause = max(0.0, pause) if math.isfinite(pause) else 0.0
        except (TypeError, ValueError):
            pause = 0.0
        self.rounds, self.round_rest = rounds, pause
        return {"rounds": self.rounds, "rest": self.round_rest}

    def _rest_between_rounds(self, seconds: float) -> None:
        """Wait out the rest between passes; a Stop ends it at once and a pause
        holds the countdown where it is."""
        left = max(0.0, float(seconds))
        last = time.monotonic()
        while left > 0 and not self._stop.is_set():
            if not self._pause.is_set():
                self._pause.wait(timeout=0.1)
                last = time.monotonic()
                continue
            time.sleep(min(0.1, left))
            now = time.monotonic()
            left -= now - last
            last = now

    def _run_sequence_pass(self) -> tuple:
        """One pass over the enabled sequence activities → ``(ran, completed, failed)``."""
        ran = completed = failed = 0
        for act in self.activities():
            if self._stop.is_set():
                break
            if act.get("type") == "background" or not act.get("enabled", True):
                continue
            ran += 1
            if self._run_activity(act):
                completed += 1
            else:
                failed += 1
            if self._stop.is_set():
                break
            time.sleep(0.3)
        return ran, completed, failed

    def _run_sequence(self) -> None:
        completed = failed = 0
        total = int(getattr(self, "rounds", 1))
        rest = float(getattr(self, "round_rest", 0.0))
        repeating = total != 1
        round_no = 0
        try:
            while not self._stop.is_set():
                round_no += 1
                if repeating:
                    of = f"/{total}" if total else ""
                    log_info(f"↻ Round {round_no}{of}", kind=LOG_KIND_RUN)
                    self._emit("on_round", {"round": round_no, "total": total,
                                            "phase": "running", "restUntil": 0})
                ran, ok, bad = self._run_sequence_pass()
                completed += ok
                failed += bad
                if self._stop.is_set() or not ran:
                    break       # nothing enabled: repeating would only spin
                if total and round_no >= total:
                    break
                if rest > 0:
                    log_info(f"☾ Resting {self._duration(rest)} before round {round_no + 1}",
                             kind=LOG_KIND_RUN)
                    self._emit("on_round", {"round": round_no, "total": total, "phase": "resting",
                                            "restUntil": time.time() + rest})
                    self._rest_between_rounds(rest)
            # A stopped run already said "Stopped" — only summarise a full pass.
            if not self._stop.is_set():
                summary = f"{completed} completed" + (f", {failed} failed" if failed else "")
                if repeating:
                    summary = f"{round_no} round{'s' if round_no != 1 else ''}, {summary}"
                if failed:
                    log_warning(f"■ Sequence finished — {summary}", kind=LOG_KIND_RUN)
                else:
                    log_success(f"■ Sequence finished — {summary}", kind=LOG_KIND_RUN)
        except Exception as e:
            log_error(f"Sequence error: {e}", kind=LOG_KIND_RUN)
        finally:
            if not self._bg_threads and not self._retired_bg_threads:
                self.running = False
                self._emit("on_stop")

    @staticmethod
    def _duration(seconds: float) -> str:
        """``45s`` / ``12m`` / ``1h 30m`` — rest lengths in a log line."""
        s = int(round(seconds))
        if s < 60:
            return f"{s}s"
        h, m = divmod(s // 60, 60)
        rem = s % 60
        if h:
            return f"{h}h {m}m" if m else f"{h}h"
        return f"{m}m {rem}s" if rem else f"{m}m"

    def _run_activity(self, act: Dict[str, Any]) -> bool:
        # Every line logged on this thread while the activity runs — the engine,
        # functions it calls, src/core helpers — is prefixed with its name.
        with log_activity(act.get("name") or act.get("id") or "activity"):
            # A pooled worker thread would otherwise still carry the last block
            # of whichever activity ran on it before.
            set_log_node(None)
            try:
                return self._run_activity_attempts(act)
            except Exception as exc:
                # The Runner classifies outcomes from completion callbacks.
                # Logging alone would make a crashed activity look completed.
                log_error(f"✖ Crashed: {exc}", kind=LOG_KIND_ACTIVITY)
                self._emit("on_activity_complete", act, False)
                return False
            finally:
                set_log_node(None)

    def _run_activity_attempts(self, act: Dict[str, Any]) -> bool:
        retries = max(1, int(act.get("maxRetries", 1) or 1))
        self._vars = self._seed_vars(act)
        self._last_pos = None
        self._break_loop = False
        self._branch_failed = False
        self._try_chain_mode = False
        with self._crash_lock:
            self._crash = None
        self._fatal = ""
        self._emit("on_activity_start", act)
        for k, v in self._vars.items():
            self._emit("on_var", k, v)
        ok = False
        t0 = time.time()
        log_info("▶ Started" + (f" — up to {retries} attempts" if retries > 1 else ""),
                 kind=LOG_KIND_ACTIVITY)
        for attempt in range(1, retries + 1):
            if self._stop.is_set():
                break
            if attempt > 1:
                log_warning(f"↻ Attempt {attempt}/{retries}", kind=LOG_KIND_ACTIVITY)
            self._reached_end = False
            ok = self._run_graph(act.get("graph", {}) or {})
            # Same success rule as a function call: the walk must reach an End
            # node — a dead-end (e.g. a timed-out image wait with no false path)
            # is a failure. A stop (user or Stop node) is not painted as one.
            if ok and not self._stop.is_set():
                ok = self._reached_end
            if ok:
                break
        elapsed = time.time() - t0
        self._emit("on_node", None)  # clear highlight between activities
        # A user Stop is not a crash — only report where a genuine failure died.
        # A run aborted by _fail_run is one, even though it stopped the engine.
        stopped = self._stop.is_set() and not getattr(self, "_fatal", "")
        crash = None
        if not ok and not stopped:
            with self._crash_lock:
                crash = dict(self._crash) if self._crash else None
        if stopped:
            log_info(f"■ Stopped ({elapsed:.1f}s)", kind=LOG_KIND_ACTIVITY)
        elif ok:
            log_success(f"✔ Finished ({elapsed:.1f}s)", kind=LOG_KIND_ACTIVITY)
        else:
            reason = ""
            if crash:
                reason = f" — at {crash.get('name') or crash.get('label')}"
                if crash.get("message"):
                    reason += f": {crash.get('message')}"
            log_error(f"✖ Failed ({elapsed:.1f}s){reason}", kind=LOG_KIND_ACTIVITY)
        if not ok and not stopped:
            self._emit("on_activity_crash", act, crash)
        self._emit("on_activity_complete", act, ok)
        return ok

    # ── Graph traversal ──────────────────────────────────────────────────────

    @staticmethod
    def _build_adjacency(edges: List[Dict]) -> Dict[tuple, List[str]]:
        """Map ``(fromNodeId, fromPort) -> [targetNodeId, …]``."""
        adj: Dict[tuple, List[str]] = {}
        for e in edges or []:
            key = (e.get("from"), e.get("fromPort", "out"))
            adj.setdefault(key, []).append(e.get("to"))
        return adj

    @staticmethod
    def _next(adj: Dict[tuple, List[str]], node_id: str, port: str) -> Optional[str]:
        """First node wired to ``(node_id, port)`` (graphs use one wire/port)."""
        targets = adj.get((node_id, port))
        return targets[0] if targets else None

    def _node_done(self, node: Dict[str, Any], nid: str, status: str,
                   port: Optional[str]) -> None:
        """Log only the exit actually selected, using post-run variables."""
        # Nested function/sequence walks leave the child as the current log
        # owner. Attribute the parent's exit message back to the parent.
        set_log_node(nid)
        logs = node.get("outputLogs")
        if isinstance(logs, dict):
            key = port if port is not None else "$done"
            if status == "fail" and port == "out":
                key = "$error"
            output_log = logs.get(key)
        else:
            # Runner can still execute older files without opening Designer.
            output_log = node.get("outputLog")
        if output_log:
            log_info(self._format_msg(output_log), kind=LOG_KIND_USER)
        self._emit("on_node_done", nid, status, port)

    def _run_graph(self, graph: Dict[str, Any], depth: int = 0, start_id: Optional[str] = None) -> bool:
        nodes = {n.get("id"): n for n in graph.get("nodes", []) or []}
        adj = self._build_adjacency(graph.get("edges", []) or [])
        if start_id:
            cur = start_id if start_id in nodes else None
            if cur is None:
                log_warning(f"Start block '{start_id}' not found — "
                            "it may have been deleted from the graph", kind=LOG_KIND_ACTIVITY)
                return False
        else:
            start = next((n for n in nodes.values() if n.get("type") == "start"), None)
            if start is None:
                log_warning("Graph has no start node", kind=LOG_KIND_ACTIVITY)
                return False
            cur = start.get("id")
        self._walk(nodes, adj, cur, {}, depth)
        return not self._branch_failed

    def _walk(self, nodes, adj, cur, counters, depth):
        """Follow edges from ``cur`` until a dead-end / end node / stop.

        ``counters`` is this walk's loop state (parallel branches get their own).
        """
        steps = 0
        last_nid = None          # last block actually entered — see dead-end below
        while cur and not self._stop.is_set() and not self._background_cancelled():
            if not self._wait_to_run():
                break
            if (getattr(self, "honor_breakpoints", False) and not self._debug_step
                    and (nodes.get(cur) or {}).get("breakpoint")):
                self._hit_breakpoint(nodes[cur], cur)
            if self._debug_step:
                self._debug_gate.wait()
                self._debug_gate.clear()
                if self._stop.is_set():
                    break           # Stop releases the gate; it must not run the block
            steps += 1
            if steps > MAX_STEPS:
                log_warning("Step cap reached — stopping graph (cycle?)", kind=LOG_KIND_ACTIVITY)
                break
            node = nodes.get(cur)
            if node is None:
                break
            last_nid = cur
            # Every line logged from here on — the block's own output, the ADB
            # helpers it calls — is attributed to this node, so the designer can
            # point a log line back at the block on the canvas. The walk is
            # per-thread, so this never bleeds across parallel branches.
            set_log_node(cur)
            self._emit("on_node", cur)  # let the designer highlight the active node
            nid = cur                    # stable id for the post-run result event
            ntype = node.get("type")
            # Input log: emit as soon as execution enters the block. `log` keeps
            # its legacy key so existing workflow files retain this behavior.
            custom_log = node.get("log")
            if custom_log:
                log_info(self._format_msg(custom_log), kind=LOG_KIND_USER)
            if ntype == "end":
                self._reached_end = True
                self._node_done(node, nid, "ok", None)
                break
            spec = NODE_TYPES.get(ntype)
            kind = spec.get("kind") if spec else None
            # The block's Designer label ("Tap image"), for log lines that would
            # otherwise name the type ("tap_image") or the node's raw id.
            label = (spec or {}).get("label") or ntype
            params = node.get("params", {}) or {}

            # Universal delay: wait before running the block.
            db = self._delay_val(node, params)
            if db > 0:
                self._emit("on_node_delay", nid, "before", db)
                self._sleep(db)
                self._emit("on_node_delay", nid, None, 0)
                if self._stop.is_set() or self._background_cancelled():
                    break

            if kind == "start":
                self._node_done(node, nid, "ok", "out")
                cur = self._next(adj, cur, "out")
            elif kind == "stop":
                log_info("■ Stop block reached — stopping the run", kind=LOG_KIND_ACTIVITY)
                self._node_done(node, nid, "ok", None)
                self.stop()
                break
            elif kind == "try_next":
                # Abandon the current try_chain arm and let the outer try_chain
                # advance to the next numbered port (or "fail" if none left).
                if self._try_chain_mode:
                    log_info("↩ trying next branch — abandoning current branch")
                    self._branch_failed = True
                else:
                    log_warning("'Try next branch' outside Try in order — no effect")
                self._node_done(node, nid, "ok", None)
                break
            elif kind == "condition":
                try:
                    res = self._eval_condition(ntype, params)
                except Exception as e:
                    # A crash inside a condition counts as "false".
                    res = False
                    log_error(f"Block '{label}' error: {e}")
                port = "true" if res else "false"
                self._node_done(node, nid, "ok", port)  # branch taken
                nxt = self._next(adj, cur, port)
                if nxt is None:
                    nxt = self._next(adj, cur, "out")
                if self._try_chain_mode and not res and nxt is None:
                    self._branch_failed = True
                    break
                cur = nxt
            elif kind == "loop":
                if self._break_loop:
                    self._break_loop = False
                    log_info(f"↺ exited loop after {counters.get(cur, 0)} iterations (break)")
                    counters[cur] = 0
                    loop_port = "done"
                elif self._truthy(params.get("infinite", False)):
                    steps = 0  # don't let the safety cap kill an intentional ∞ loop
                    loop_port = "body"
                else:
                    done = counters.get(cur, 0)
                    count = self._resolve_count(params.get("count", 1), default=1)
                    if done < count:
                        counters[cur] = done + 1
                        loop_port = "body"
                    else:
                        log_info(f"↺ loop completed {done} iterations")
                        counters[cur] = 0
                        loop_port = "done"
                self._node_done(node, nid, "ok", loop_port)
                cur = self._next(adj, cur, loop_port)
            elif kind == "loop_until":
                # Lặp đến khi <điều kiện>: mỗi lần (re-)enter node, kiểm tra một
                # lần. Thoả → "found"; break trong thân → "found" (thoát); hết
                # maxLoops → "fail"; còn lượt → "body" (thân quay về cổng
                # "loop"). delay của node đóng vai trò poll interval.
                # Điều kiện tuỳ ntype: ảnh / màu / chữ / biến.
                what = self._loop_until_label(ntype, params)
                lu_port = None
                if self._break_loop:
                    self._break_loop = False
                    log_info(f"↺ exited 'loop until {what}' after {counters.get(cur, 0)} iterations (break)")
                    counters[cur] = 0
                    lu_port = "found"
                else:
                    if self._loop_until_hit(ntype, params):
                        log_info(f"↺ {what} after {counters.get(cur, 0)} iterations")
                        counters[cur] = 0
                        lu_port = "found"
                    else:
                        done = counters.get(cur, 0)
                        max_loops = self._resolve_count(params.get("maxLoops", 0), default=0)
                        if max_loops > 0 and done >= max_loops:
                            log_warning(f"↺ not {what} after {done} iterations — branch failed")
                            counters[cur] = 0
                            lu_port = "fail"
                        else:
                            counters[cur] = done + 1
                            steps = 0  # vòng lặp chủ ý — đừng để step cap cắt ngang
                            lu_port = "body"
                self._node_done(node, nid, "ok" if lu_port != "fail" else "fail", lu_port)
                nxt = self._next(adj, cur, lu_port)
                if lu_port == "fail" and nxt is None:
                    # fail không đi dây → nhánh này coi như thất bại (đỏ), giống
                    # một condition false cụt trong try_chain.
                    self._branch_failed = True
                    break
                cur = nxt
            elif kind == "parallel":
                self._run_parallel(nodes, adj, cur, depth)
                # Execution after all branches is handled inside _run_parallel
                # (the last branch to hit a join node continues from join.out).
                # The parent walk ends here — no "done" port anymore.
                break
            elif kind == "join":
                # Barrier for parallel branches. The last branch to arrive
                # continues walking; all earlier arrivals stop here.
                ctx = getattr(self._ctx, "join_ctx", None)
                if ctx is not None:
                    with ctx["lock"]:
                        ctx["remaining"] -= 1
                        ctx["join_node"] = cur
                        is_last = ctx["remaining"] == 0
                    if not is_last:
                        # Not the last branch — stop this thread here.
                        self._node_done(node, nid, "ok", None)
                        break
                    # Last branch: fall through and continue from "out".
                self._node_done(node, nid, "ok", "out")
                cur = self._next(adj, cur, "out")
            elif kind == "and":
                expected = self._port_count(params, 2)
                ctx = getattr(self._ctx, "join_ctx", None)
                if ctx is None:
                    if expected <= 1:
                        self._node_done(node, nid, "ok", "out")
                        cur = self._next(adj, cur, "out")
                    else:
                        log_warning(f"And requires {expected} parallel branches")
                        self._branch_failed = True
                        self._node_done(node, nid, "fail", "out")
                        break
                else:
                    is_last, ok = self._and_arrive(ctx, cur, expected, self._branch_failed)
                    if not is_last:
                        self._node_done(node, nid, "ok", None)
                        break
                    if not ok:
                        log_warning(f"And failed: a branch failed before {expected} branches joined")
                        self._branch_failed = True
                        self._node_done(node, nid, "fail", "out")
                        break
                    self._node_done(node, nid, "ok", "out")
                    cur = self._next(adj, cur, "out")
            elif kind == "random":
                # Pick one of count numbered ports at random (uniform distribution).
                count = self._port_count(params, 2)
                chosen = str(random.randint(1, count))
                log_info(f"🎲 random → branch {chosen}/{count}")
                self._node_done(node, nid, "ok", chosen)
                cur = self._next(adj, cur, chosen)
            elif kind == "try_chain":
                count = self._port_count(params, 3)
                ports = [str(i + 1) for i in range(count)]
                vars0 = dict(self._vars)
                pos0 = self._last_pos
                break0 = self._break_loop
                failed0 = self._branch_failed
                try0 = self._try_chain_mode

                success = False
                attempted = 0
                for port in ports:
                    if self._stop.is_set():
                        break
                    tgt = self._next(adj, cur, port)
                    if not tgt:
                        continue
                    attempted += 1
                    log_info(f"trying branch {port}/{count}")
                    self._node_done(node, nid, "ok", port)
                    self._vars = dict(vars0)
                    self._last_pos = pos0
                    self._break_loop = False
                    self._branch_failed = False
                    self._try_chain_mode = True
                    self._walk(nodes, adj, tgt, {}, depth)
                    if not self._branch_failed:
                        log_success(f"branch {port} succeeded")
                        success = True
                        break
                    log_warning(f"branch {port} failed → trying next branch")

                self._try_chain_mode = try0
                self._break_loop = break0
                if success:
                    # The successful branch already walked to its own end.
                    self._branch_failed = failed0
                    break
                self._vars = dict(vars0)
                self._last_pos = pos0
                self._branch_failed = failed0
                self._node_done(node, nid, "fail", "fail")
                if attempted:
                    log_warning("all ordered branches failed")
                cur = self._next(adj, cur, "fail")
            elif kind == "sequence":
                # Chạy các nhánh 1..N LẦN LƯỢT: dù nhánh trước fail hay thành
                # công vẫn sang nhánh kế. Mỗi nhánh là một đường độc lập (walk
                # tới dead-end). Khác try_chain: không dừng ở nhánh thành công
                # đầu tiên, và chỉ có một cổng tiếp tục chung là "end".
                count = self._port_count(params, 3)
                ports = [str(i + 1) for i in range(count)]
                break0 = self._break_loop
                try0 = self._try_chain_mode
                failed0 = self._branch_failed

                any_failed = False
                ran = 0
                for port in ports:
                    if self._stop.is_set():
                        break
                    tgt = self._next(adj, cur, port)
                    if not tgt:
                        continue
                    ran += 1
                    log_info(f"▶ running sequential branch {port}/{count}")
                    self._node_done(node, nid, "ok", port)
                    self._branch_failed = False
                    self._break_loop = False
                    # Nhánh tuần tự không phải nhánh try_chain: một action fail
                    # KHÔNG được cắt ngang nhánh (không `break`) để cả nhánh chạy
                    # hết — lỗi chỉ được ghi nhận.
                    self._try_chain_mode = False
                    self._walk(nodes, adj, tgt, {}, depth)
                    if self._branch_failed:
                        any_failed = True
                self._try_chain_mode = try0
                self._break_loop = break0
                # Lỗi của bất kỳ nhánh nào vẫn lan ra ngoài (kết quả run / arm
                # try_chain bao ngoài), nhưng không chặn các nhánh còn lại.
                self._branch_failed = bool(failed0 or any_failed)
                if ran:
                    log_info(f"⇉ completed {ran} sequential branches")
                # Cổng "end": đường tiếp tục chính, chạy SAU khi tất cả nhánh
                # 1..N đã xong (dù nhánh nào fail). Có dây "end" thì lỗi của các
                # nhánh chỉ mang tính best-effort (vẫn ghi log) — kết quả thật do
                # đường "end" quyết định, giống nhánh thành công của try_chain.
                # Không có dây "end" thì giữ nguyên hành vi cũ: lỗi nhánh lan ra
                # ngoài và node kết thúc ngay tại đây.
                end_tgt = self._next(adj, cur, "end")
                if end_tgt and not self._stop.is_set():
                    if any_failed:
                        log_warning("↳ a sequential branch failed — continuing through the 'end' port")
                    self._branch_failed = failed0
                    self._node_done(node, nid, "ok", "end")
                    self._break_loop = break0
                    # Tiếp tục trên cổng "end" NGAY TRONG walk này (không mở walk
                    # con): loop bọc quanh sequence vẫn đếm được số vòng vì bộ đếm
                    # vòng lặp nằm trong `counters` của walk hiện tại.
                    cur = end_tgt
                else:
                    self._branch_failed = bool(failed0 or any_failed)
                    self._break_loop = break0
                    break
            elif kind == "switch":
                # Evaluate each case top-to-bottom; first true wins its port "c{i}".
                taken = "default"
                for i, case in enumerate(params.get("cases", []) or []):
                    ctype = case.get("type")
                    if ctype not in SWITCH_CASE_TYPES:
                        continue
                    try:
                        if self._eval_condition(ctype, case.get("params", {}) or {}):
                            taken = f"c{i}"
                            break
                    except Exception as e:
                        log_warning(f"switch case {i} ({ctype}) error: {e}")
                self._node_done(node, nid, "ok", taken)
                nxt = self._next(adj, cur, taken)
                cur = nxt if nxt is not None else self._next(adj, cur, "default")
            elif kind == "call":
                self._emit("on_node", cur)  # highlight the call block while its function runs
                fid = params.get("fn")
                fn = self._functions.get(fid)
                ok_call = False
                if fn is None:
                    names = ", ".join(self._label(f) for f in self._functions.values())
                    log_warning(f"call → function '{fid}' not found"
                                + (f" — workflow has: {names}" if names
                                   else " — workflow has no functions"),
                                kind=LOG_KIND_ACTIVITY)
                elif depth >= MAX_CALL_DEPTH:
                    log_warning("Max function call depth reached (recursion?)", kind=LOG_KIND_ACTIVITY)
                else:
                    log_info(f"ƒ {fn.get('name', fid)}")
                    outer_end = self._reached_end
                    self._reached_end = False
                    self._run_graph(fn.get("graph", {}) or {}, depth + 1)
                    ok_call = self._reached_end
                    self._reached_end = outer_end
                    if not ok_call:
                        log_warning(f"ƒ {fn.get('name', fid)} → false (dead end, did not reach an End node)")
                # Result port: "true" khi function tới node End, "false" khi dead-end.
                port = "true" if ok_call else "false"
                self._node_done(node, nid, "ok" if ok_call else "fail", port)
                nxt = self._next(adj, cur, port)
                if nxt is None:
                    # Legacy flows wired the call's single "out" port — follow it
                    # regardless of the result so old workflows behave as before.
                    nxt = self._next(adj, cur, "out")
                if self._try_chain_mode and (self._branch_failed or (not ok_call and nxt is None)):
                    self._branch_failed = True
                    break
                cur = nxt
            else:  # action (or unknown -> just follow out)
                ok_act = True
                handler = self._actions.get(ntype)
                if ntype == "note":
                    # Ghi chú không phải block thực thi — nếu lỡ bị đấu dây vào
                    # đường chạy thì bỏ qua êm (đi tiếp cổng out, thường không có)
                    # thay vì rơi xuống "Unknown node" và fail cả nhánh.
                    pass
                elif handler is not None:
                    ok_act = self._run_action_with_retry(node, params, handler)
                else:
                    # The type name is all there is to report — no spec means no
                    # label — so say what its absence implies instead of echoing
                    # a bare identifier the user has never seen.
                    log_warning(f"Block '{ntype}' is unavailable in this engine version — "
                                "the workflow may have been saved by a newer version",
                                kind=LOG_KIND_ACTIVITY)
                    ok_act = False
                    self._branch_failed = True
                self._node_done(node, nid, "ok" if ok_act else "fail", "out")
                if self._try_chain_mode and not ok_act:
                    break
                cur = self._next(adj, cur, "out")

        # Falling out with no ``cur`` means the last block's chosen port had no
        # wire — the walk ran out of graph instead of reaching an End. Every
        # `break` above leaves ``cur`` set, so this only catches real dead ends.
        # Weak: if an action already failed here, its own record is the useful
        # one (the dead end is just its unwired "fail" port).
        if not cur and last_nid and not self._stop.is_set():
            self._note_crash(nodes.get(last_nid), "dead_end",
                             "this block's output is not connected — cannot reach an End block",
                             weak=True)
        return True

    def _run_parallel(self, nodes, adj, node_id, depth):
        """Run every wired branch port of a parallel node at once, then join.

        Branch count is read from the node's ``count`` param (default 3). Each
        branch runs on its own thread with its OWN copy of the current vars /
        last-position (snapshotted at the fork) so branches can't stomp each other.

        If any branch reaches a ``join`` node, a shared join_ctx coordinates the
        barrier: the last branch to arrive continues execution from the join's
        ``out`` port. Branches that arrive earlier stop at the join.
        """
        params = (nodes.get(node_id) or {}).get("params", {})
        count = self._port_count(params, 3)
        ports = [str(i + 1) for i in range(count)]

        vars0 = dict(self._vars)
        pos0 = self._last_pos

        active = [(p, self._next(adj, node_id, p)) for p in ports]
        active = [(p, tgt) for p, tgt in active if tgt]
        if not active:
            return

        # Shared barrier for join-node coordination (see _walk "join" handler).
        join_ctx: Dict[str, Any] = {
            "lock": threading.Lock(),
            "remaining": len(active),
            "join_node": None,   # id of the join node all branches converge to
            "barriers": {},      # per-And-node arrival / failure state
            "failed": False,     # any branch failed while running under this fork
            "reached_end": False,  # any branch hit an End node (function result)
        }

        threads = []
        for _p, tgt in active:
            self._node_done(nodes[node_id], node_id, "ok", _p)
            t = threading.Thread(
                target=self._walk_branch,
                args=(nodes, adj, tgt, depth, vars0, pos0, join_ctx, get_log_activity(),
                      getattr(self._ctx, "background_stop", None)),
                daemon=True)
            threads.append(t)
            t.start()

        log_info(f"⇉ running {len(threads)} parallel branches")
        for t in threads:
            t.join()

        for bid, state in join_ctx.get("barriers", {}).items():
            if state.get("arrived", 0) < state.get("expected", 0):
                join_ctx["failed"] = True
                self._emit("on_node_done", bid, "fail", "out")
                log_warning(
                    f"And '{bid}' received only {state.get('arrived', 0)}/"
                    f"{state.get('expected', 0)} branches"
                )

        # All branches done. If they converged at a join node, the last-arriving
        # branch already continued from join.out — nothing more to do here.
        # (The parent _walk call proceeds from wherever _run_parallel returns.)
        if join_ctx.get("failed"):
            self._branch_failed = True
        # An End node hit on a branch thread counts for the enclosing function's
        # true/false result — hoist it back onto the forking (caller) thread.
        if join_ctx.get("reached_end"):
            self._reached_end = True

    def _and_arrive(self, ctx: Dict[str, Any], node_id: str, expected: int, branch_failed: bool):
        """Record one parallel branch arriving at an And barrier."""
        with ctx["lock"]:
            barriers = ctx.setdefault("barriers", {})
            state = barriers.setdefault(node_id, {"arrived": 0, "failed": False, "expected": expected, "released": False})
            state["expected"] = expected
            state["arrived"] += 1
            state["failed"] = bool(state["failed"] or branch_failed)
            ctx["failed"] = bool(ctx.get("failed") or branch_failed)
            is_last = state["arrived"] >= expected and not state["released"]
            if is_last:
                state["released"] = True
            ok = not state["failed"]
        return is_last, ok

    def _walk_branch(self, nodes, adj, tgt, depth, vars0, pos0, join_ctx=None, activity=None,
                     background_stop=None):
        """Entry point for a parallel branch thread: seed this thread's context
        from the fork snapshot, then walk. Isolated from siblings + the parent."""
        set_log_activity(activity)     # a branch logs under its activity's name
        self._vars = dict(vars0)
        self._last_pos = pos0
        self._break_loop = False
        self._ctx.join_ctx = join_ctx   # thread-local; cleared when thread exits
        self._ctx.background_stop = background_stop
        self._branch_failed = False
        self._reached_end = False
        try:
            self._walk(nodes, adj, tgt, {}, depth)
        finally:
            if join_ctx is not None:
                with join_ctx["lock"]:
                    if self._branch_failed:
                        join_ctx["failed"] = True
                    if self._reached_end:
                        join_ctx["reached_end"] = True
            self._ctx.join_ctx = None
            set_log_activity(None)

    @staticmethod
    def _coerce(value: Any) -> Any:
        """Best-effort number coercion (keeps non-numeric strings as-is)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        try:
            s = str(value).strip()
            return float(s) if ("." in s or "e" in s.lower()) else int(s)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _port_count(params: Dict, default: int) -> int:
        """Numbered output ports of a fan-out block (parallel, try in order…).

        A blank or malformed count falls back to the block's default instead of
        raising mid-walk — the Designer draws the same default number of ports.
        """
        try:
            return max(1, int(float(params.get("count", default))))
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    def _format_msg(self, text: Any) -> str:
        """Fill ``{var}`` placeholders in a log message from the current vars.

        An unknown ``{name}`` is left untouched so the literal braces still show.
        """
        s = str(text)
        if "{" not in s:
            return s
        return re.sub(r"\{([^{}]+)\}",
                      lambda m: str(self._vars.get(m.group(1).strip(), m.group(0))),
                      s)

    def _apply_pattern(self, text: Any, pattern: Any, group: Any = 1) -> Optional[str]:
        """Extract capture ``group`` of regex ``pattern`` from ``text``.

        The same mechanism Parse text to variable uses, shared with every node
        that produces text (Read text / Run shell / Read window / Format text).
        No pattern → the whole text, stripped (existing behaviour). No match →
        "". An invalid regex → ``None`` so the caller can fail the node instead
        of silently writing junk into a variable.
        """
        raw = str(text or "")
        pat = str(pattern or "").strip()
        if not pat:
            return raw.strip()
        try:
            m = re.search(pat, raw, re.MULTILINE)
        except re.error as exc:
            log_error(f"pattern error /{pat}/: {exc}")
            return None
        if not m:
            return ""
        try:
            grp = int(group or 1)
        except (TypeError, ValueError):
            grp = 1
        if 0 <= grp <= len(m.groups()):
            return (m.group(grp) or "").strip()
        return (m.group(0) or "").strip()

    def _ocr_needle(self, params: Dict) -> tuple:
        """The string OCR match nodes look for, plus whether it is a regex.

        ``match`` = "pattern" reads ``pattern`` and matches it as a regex
        (parse_var style); anything else keeps the literal ``text`` substring.
        """
        if str(params.get("match", "text")).strip().lower() == "pattern":
            return str(self._resolve_value(params.get("pattern", "")) or ""), True
        return str(self._resolve_value(params.get("text", "")) or ""), False

    @staticmethod
    def _label(obj: Dict[str, Any]) -> str:
        """The human name of an activity / function / node, falling back to id.

        Log lines used to print the raw id, which is a UUID-shaped string the
        user never chose and cannot match to anything on screen.
        """
        return str(obj.get("name") or obj.get("id") or "?")

    def _seed_vars(self, act: Dict) -> Dict[str, Any]:
        """Initial variable values for a thread: globals first, then the
        activity's own declared ``vars`` (which may override a same-named
        global for this run). Nested children are flattened with dotted keys.
        A select option's own children use ``parent.<option>.<child>``."""
        out: Dict[str, Any] = {}
        for v in (self._globals or {}).items():
            out[v[0]] = v[1]
        for v in (act.get("vars") or []):
            self._seed_var(v, out)
        return out

    def _seed_var(self, v: Dict, out: Dict[str, Any], prefix: str = "") -> None:
        nm = str(v.get("name", "")).strip()
        if not nm:
            return
        full = f"{prefix}.{nm}" if prefix else nm
        t = v.get("type", "text")
        val = v.get("value")
        if t == "bool":
            out[full] = self._truthy(val)
        elif t == "number":
            c = self._coerce(val)
            out[full] = c if isinstance(c, (int, float)) and not isinstance(c, bool) else 0
        elif t == "select" and v.get("display") == "toggle-group" and v.get("multiple"):
            values = val if isinstance(val, list) else [val]
            out[full] = [o for o in (v.get("options") or []) if o in values]
        else:
            out[full] = "" if val is None else str(val)
        for child in (v.get("children") or []):
            self._seed_var(child, out, full)
        if t == "select":
            selected = out[full]
            active = {str(o) for o in selected} if isinstance(selected, list) else {str(selected)}
            option_children = v.get("optionChildren") or {}
            if isinstance(option_children, dict):
                for option, kids in option_children.items():
                    opt = str(option).strip()
                    if opt in active and isinstance(kids, list):
                        for child in kids:
                            self._seed_var(child, out, f"{full}.{opt}")

    # ── Background workers ───────────────────────────────────────────────────

    def start_all_background(self) -> None:
        for act in self.activities():
            if act.get("type") == "background" and act.get("enabled", True):
                self.start_background(act)

    def background_stopping(self, aid: str) -> bool:
        """A cancelled worker still owns a pending controller call."""
        with self._bg_lock:
            worker = self._retired_bg_threads.get(aid)
            return bool(worker is not None and worker.is_alive())

    def start_background(self, act: Dict[str, Any]) -> bool:
        aid = act.get("id") or act.get("name")
        if not aid:
            return False
        with self._bg_lock:
            if self.background_stopping(aid):
                log_warning("Background is still stopping — wait for its current action",
                            kind=LOG_KIND_ACTIVITY)
                return False
            existing = self._bg_threads.get(aid)
            if existing is not None and existing.is_alive():
                return True
            self._retired_bg_threads.pop(aid, None)
            stop_ev = threading.Event()
            self._bg_stop[aid] = stop_ev
            t = threading.Thread(target=self._bg_loop, args=(act, stop_ev), daemon=True)
            self._bg_threads[aid] = t
            t.start()
        interval = max(0.05, float(act.get("pollInterval", 1.0) or 1.0))
        with log_activity(act.get("name") or aid):
            log_info(f"▶ Background started — every {interval:g}s", kind=LOG_KIND_ACTIVITY)
        return True

    def stop_background(self, aid: str) -> None:
        with self._bg_lock:
            ev = self._bg_stop.get(aid)
            if ev:
                ev.set()
            t = self._bg_threads.pop(aid, None)
            self._bg_stop.pop(aid, None)
            if t is not None:
                self._retired_bg_threads[aid] = t
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=0.5)
        if t is not None:
            name = next((a.get("name") for a in self.activities()
                         if (a.get("id") or a.get("name")) == aid), None) or aid
            with log_activity(name):
                log_info("■ Background stopped", kind=LOG_KIND_ACTIVITY)

    def _bg_loop(self, act: Dict[str, Any], stop_ev: threading.Event) -> None:
        self._ctx.background_stop = stop_ev
        try:
            self._bg_loop_iterations(act, stop_ev)
        except Exception as exc:
            log_error(f"✖ Background crashed: {exc}", kind=LOG_KIND_ACTIVITY)
            self._emit("on_activity_complete", act, False)
        finally:
            self._ctx.background_stop = None
            aid = act.get("id") or act.get("name")
            current = threading.current_thread()
            with self._bg_lock:
                if self._bg_threads.get(aid) is current:
                    self._bg_threads.pop(aid, None)
                    self._bg_stop.pop(aid, None)
                if self._retired_bg_threads.get(aid) is current:
                    self._retired_bg_threads.pop(aid, None)
                ended = (self.running and not self._bg_threads
                         and not self._retired_bg_threads
                         and (self._seq_thread is None or not self._seq_thread.is_alive()))
                if ended:
                    self.running = False
            if ended:
                self._emit("on_stop")

    def _bg_loop_iterations(self, act: Dict[str, Any], stop_ev: threading.Event) -> None:
        name = act.get("name") or act.get("id")
        set_log_activity(name)     # dedicated worker thread — every line is this activity's
        while not stop_ev.is_set() and not self._stop.is_set():
            if not self._wait_to_run():
                break
            self._vars = self._seed_vars(act)
            self._last_pos = None
            self._break_loop = False
            self._branch_failed = False
            self._try_chain_mode = False
            self._reached_end = False
            self._emit("on_activity_start", act)
            try:
                ok = self._run_graph(act.get("graph", {}) or {})
                if not self._stop.is_set():
                    ok = bool(ok and self._reached_end)
            except Exception as e:
                ok = False
                log_error(f"✖ Crashed: {e}", kind=LOG_KIND_ACTIVITY)
            if stop_ev.is_set() and not self._stop.is_set():
                # Disabling a watcher is cancellation, not an activity failure.
                break
            self._emit("on_activity_complete", act, ok)
            interval = max(0.05, float(act.get("pollInterval", 1.0) or 1.0))
            end = time.time() + interval
            while time.time() < end and not stop_ev.is_set() and not self._stop.is_set():
                time.sleep(0.05)

    # ── Pause / stop ─────────────────────────────────────────────────────────

    def pause(self) -> None:
        self._pause.clear()
        log_info("❚❚ Paused", kind=LOG_KIND_RUN)

    def resume(self) -> None:
        self._pause.set()
        log_info("▶ Resumed", kind=LOG_KIND_RUN)

    def is_paused(self) -> bool:
        return not self._pause.is_set()

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        log_info("Stopping…", kind=LOG_KIND_RUN)
        self._stop.set()
        self.auto._stop_event.set()
        self._pause.set()
        self._debug_step = False
        self._debug_gate.set()
        self._stop_speedhack()
        # A Press key → Hold down left held must not keep the character walking.
        ctrl = getattr(self.auto, "adb", None)
        if getattr(self, "_controller", "adb") == "win32" and hasattr(ctrl, "release_all_keys"):
            try:
                ctrl.release_all_keys()
            except Exception as exc:
                log_warning(f"⌨ failed to release keys: {exc}")
        for aid in list(self._bg_threads.keys()):
            self.stop_background(aid)
        if (self._seq_thread and self._seq_thread.is_alive()
                and self._seq_thread is not threading.current_thread()):
            self._seq_thread.join(timeout=1.0)
        self.auto.stop_continuous_capture()
        self.running = False
        self._emit("on_stop")
        log_success("■ Stopped", kind=LOG_KIND_RUN)

    # Node types whose ``timeout`` param waits for a screen change. Single-node
    # test caps this so "Test block" returns in ~1s with an overlay instead of
    # hanging for the full configured wait (often 10s).
    _QUICK_TIMEOUT_TYPES = frozenset({
        "tap_image", "wait_image", "tap_image_any", "wait_image_any",
        "tap_color", "wait_color", "tap_text", "wait_text", "scroll_find",
        "win_wait_window", "wait_stable", "wait_app",
    })

    def run_single_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one node in isolation (no graph walk), on the calling thread.

        Used by the designer's "Test block" action: fires the same on_node /
        on_node_done callbacks as a real run so the UI paints the block
        amber→green/red, streams log output, and (when report_matches is on)
        emits on_match rects for the Preview overlay. Conditions report the
        taken branch; actions report ok/fail.

        Image/color wait timeouts are capped at 1s so a miss returns quickly
        with a best-score overlay instead of blocking for the full timeout.

        Returns ``{status, port}`` so the caller can relay the outcome.
        """
        if self.running:
            log_warning("A run is active — cannot run a single block")
            return {"status": "busy", "port": None}
        if not self._ensure_ready():
            return {"status": "error", "port": None}
        nid = node.get("id")
        ntype = node.get("type")
        # Shallow-copy params so timeout cap doesn't mutate the designer's node.
        params = dict(node.get("params", {}) or {})
        if ntype in self._QUICK_TIMEOUT_TYPES:
            try:
                params["timeout"] = min(float(params.get("timeout", 10) or 10), 1.0)
            except (TypeError, ValueError):
                params["timeout"] = 1.0
        work = dict(node)
        work["params"] = params
        spec = NODE_TYPES.get(ntype)
        kind = spec.get("kind") if spec else None
        label = (spec or {}).get("label") or ntype
        set_log_node(nid)
        self._emit("on_node", nid)
        input_log = work.get("log")
        if input_log:
            log_info(self._format_msg(input_log), kind=LOG_KIND_USER)
        port: Optional[str] = None
        status = "ok"
        try:
            if kind == "condition":
                res = self._eval_condition(ntype, params)
                port = "true" if res else "false"
            elif kind in ("start", "end", "note", "stop", "try_next"):
                # Terminals/notes/control exits have no side-effects standalone.
                port = None
            elif kind in ("loop", "loop_until", "parallel", "sequence", "and", "join",
                          "random", "switch", "try_chain", "call"):
                # Structural nodes don't make sense standalone; report no-op.
                log_info(f"Block '{label}' is structural — run it in a workflow")
                port = None
            else:
                handler = self._actions.get(ntype)
                if handler is not None:
                    ok_act = self._run_action_with_retry(work, params, handler)
                    status = "ok" if ok_act else "fail"
                    port = "out"
                else:
                    log_warning(f"Block '{ntype}' is unavailable in this engine version — "
                                "the workflow may have been saved by a newer version")
                    status = "fail"
                    port = "out"
        except Exception as e:
            log_error(f"Block '{label}' error: {e}")
            status = "fail"
            port = "false" if kind == "condition" else "out"
        self._node_done(work, nid, status, port)
        self._emit("on_node", None)  # clear the amber highlight
        return {"status": status, "port": port}

    def _delay_val(self, node: Dict, params: Dict) -> float:
        """Pre-block delay, including workflows not yet migrated on disk."""
        v = node.get("delay", node.get("delayBefore", params.get("delay")))
        try:
            return max(0.0, float(v or 0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _after_find_seconds(params: Dict) -> float:
        """Optional post-match wait; malformed values must never wait forever."""
        try:
            seconds = float(params.get("delayAfterFind", 0) or 0)
            return seconds if math.isfinite(seconds) and seconds > 0 else 0.0
        except (TypeError, ValueError, OverflowError):
            return 0.0

    def _wait_after_find(self, params: Dict) -> bool:
        """Wait after a successful match, then gate the pending tap on pause/stop."""
        if self._stop.is_set():
            return False
        delay = self._after_find_seconds(params)
        if delay:
            self._sleep(delay)
        if self._stop.is_set():
            return False
        self._pause.wait()
        return not self._stop.is_set()

    def _background_cancelled(self) -> bool:
        event = getattr(self._ctx, "background_stop", None)
        return bool(event is not None and event.is_set())

    def _wait_to_run(self) -> bool:
        while not self._stop.is_set() and not self._background_cancelled():
            if self._pause.wait(timeout=0.05):
                return not self._stop.is_set() and not self._background_cancelled()
        return False

    def _sleep(self, seconds: float) -> None:
        """Pause-aware, stop-aware sleep."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop.is_set() and not self._background_cancelled():
            if not self._wait_to_run():
                break
            time.sleep(0.05)

    def debug_next(self) -> None:
        """Release one node when running in step-debug mode."""
        self._debug_gate.set()

    def debug_continue(self) -> None:
        """Leave step mode and run on until the next breakpoint (or the end)."""
        self._debug_step = False
        self._debug_gate.set()

    def _hit_breakpoint(self, node: Dict[str, Any], nid: str) -> None:
        """Hold the walk *before* a breakpoint block runs: switch to step mode so
        Next step runs it and Continue runs on. Only Designer test runs honour
        breakpoints (``honor_breakpoints``); the Runner never stops on one."""
        spec = NODE_TYPES.get(node.get("type") or "", {})
        what = str(node.get("name") or "").strip() or spec.get("label") or node.get("type") or "block"
        log_info(f"⏸ Breakpoint — {what}", kind=LOG_KIND_ACTIVITY)
        self._debug_step = True
        self._debug_gate.clear()
        self._emit("on_node", nid)
        self._emit("on_breakpoint", nid)

    def _run_action_with_retry(self, node: Dict, params: Dict, handler: Callable[[Dict, Dict], bool]) -> bool:
        attempts = max(1, int(node.get("retryCount", 0) or 0) + 1)
        delay = max(0.0, float(node.get("retryDelay", 0) or 0))
        label = (NODE_TYPES.get(node.get("type"), {}).get("label") or node.get("type"))
        ok_act = False
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                ok_act = handler(node, params) is not False
                last_error = None
            except Exception as e:
                log_error(f"Block '{label}' error: {e}")
                ok_act = False
                last_error = e
            if ok_act:
                return True
            # A stopped run (user Stop, or _fail_run) must not retry the block.
            if self._stop.is_set():
                break
            if attempt < attempts:
                log_warning(f"✖ '{label}' failed → retry {attempt}/{attempts - 1}")
                if delay:
                    self._sleep(delay)
        self._branch_failed = True
        if self._stop.is_set() and getattr(self, "_fatal", ""):
            return False    # _fail_run already logged and recorded the real reason
        if last_error is None:
            log_warning(f"✖ '{label}' could not be completed")
        self._note_crash(
            node,
            "error" if last_error is not None else "failed",
            str(last_error) if last_error is not None
            else f"could not be completed after {attempts} attempts",
        )
        self._save_failure_screenshot(node)
        return False

    def _save_failure_screenshot(self, node: Dict) -> None:
        # Per-node opt-in, or the designer's "always capture" test-run mode.
        if not (node.get("screenshotOnFail") or self.capture_failures_always):
            return
        try:
            img = self.auto.capture_screen()
            if img is None:
                return
            import cv2
            out_dir = self.failure_screenshot_dir or os.path.join(os.getcwd(), "out", "workflow_failures")
            os.makedirs(out_dir, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(node.get("id") or node.get("type") or "node"))
            path = os.path.join(out_dir, f"fail_{safe}_{time.strftime('%Y%m%d_%H%M%S')}.png")
            # Unicode-safe write (cv2.imwrite chokes on non-ASCII Windows paths).
            ok, buf = cv2.imencode(".png", img)
            if ok:
                buf.tofile(path)
                log_warning(f"saved failure screenshot: {path}")
                self._emit("on_fail_shot", str(node.get("id") or ""), path)
        except Exception as e:
            log_warning(f"save failure screenshot failed: {e}")

    def _fail_run(self, node: Optional[Dict], message: str) -> bool:
        """Abort the whole run on a setup error no retry can fix (a missing game
        exe): log it, record it as the crash point, stop every activity.

        Unlike a normal action failure there is no retry and no fail branch —
        everything after a Launch program assumes the game is running, so going
        on would only fail again further down with a less useful message."""
        log_error(f"⛔ {message}")
        self._fatal = message
        self._note_crash(node, "fatal", message)
        self._branch_failed = True
        self.stop()
        return False
