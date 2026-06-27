"""Execute JSON workflows against a connected device.

The engine wraps an :class:`~src.core.adb.auto.ADBGameAutomation` instance and
runs the **node graph** of each activity. It is shared by two front-ends:

* the **Run test** button in ``tools/dev_helper.py`` (design-time preview), and
* the standalone **runner GUI** (``src/gui/workflow_runner_gui.py``).

Both feed it the exact same JSON, so a flow that runs in the designer runs
unchanged in the runner.

Each activity holds a directed **node graph** (``nodes`` + ``edges``). Execution
starts at the ``start`` node and follows output ports edge-by-edge:

* an **action** node (tap, swipe, …) runs, then follows its ``out`` port;
* an **if_image** node follows ``true`` or ``false`` depending on the match;
* a **loop** node follows ``body`` ``count`` times (wire the body back to the
  loop node to iterate), then ``done``;
* reaching an ``end`` node — or a port with no edge — ends the activity.

There are two activity modes, mirroring ``src/game_core/base_game.py``:

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

import os
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.core import ADBGameAutomation
from src.utils import log_error, log_info, log_success, log_warning


# ── Node catalog ─────────────────────────────────────────────────────────────
#
# Single source of truth for the node types the engine understands. ``kind``
# drives traversal; ``outs`` lists the output port ids each node exposes. The
# designer UI keeps a richer mirror (icons + field widgets) keyed by the same
# names. Safety cap on total steps guards against runaway cycles.
MAX_STEPS = 100_000
MAX_CALL_DEPTH = 50  # guards against functions that (in)directly call themselves

NODE_TYPES: Dict[str, Dict[str, Any]] = {
    "start":      {"label": "Bắt đầu",       "kind": "start",     "ins": 0, "outs": ["out"]},
    "end":        {"label": "Kết thúc",      "kind": "end",       "ins": 1, "outs": []},
    "stop":       {"label": "Dừng tất cả",   "kind": "stop",      "ins": 1, "outs": []},
    "call":       {"label": "Gọi function",  "kind": "call",      "ins": 1, "outs": ["out"]},
    "note":       {"label": "Ghi chú",       "kind": "note",      "ins": 0, "outs": []},
    "tap":        {"label": "Chạm",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "double_tap": {"label": "Chạm đúp",      "kind": "action",    "ins": 1, "outs": ["out"]},
    "tap_random": {"label": "Chạm ngẫu nhiên","kind": "action",   "ins": 1, "outs": ["out"]},
    "long_press": {"label": "Giữ",           "kind": "action",    "ins": 1, "outs": ["out"]},
    "swipe":      {"label": "Vuốt",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "swipe_dir":  {"label": "Vuốt hướng",    "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait":       {"label": "Chờ",           "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait_random":{"label": "Chờ ngẫu nhiên","kind": "action",    "ins": 1, "outs": ["out"]},
    "tap_image":  {"label": "Chạm ảnh",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_image": {"label": "Chờ ảnh",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_text":  {"label": "Chờ chữ",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "send_text":  {"label": "Nhập văn bản",  "kind": "action",    "ins": 1, "outs": ["out"]},
    "key":        {"label": "Phím",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "back":       {"label": "Back",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "home":       {"label": "Home",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "launch_app": {"label": "Mở ứng dụng",   "kind": "action",    "ins": 1, "outs": ["out"]},
    "screenshot": {"label": "Chụp màn hình", "kind": "action",    "ins": 1, "outs": ["out"]},
    "log":        {"label": "Ghi nhật ký",   "kind": "action",    "ins": 1, "outs": ["out"]},
    "set_var":    {"label": "Đặt biến",      "kind": "action",    "ins": 1, "outs": ["out"]},
    "calc_var":   {"label": "Tính biến",     "kind": "action",    "ins": 1, "outs": ["out"]},
    "read_var":   {"label": "Đọc chữ → biến","kind": "action",    "ins": 1, "outs": ["out"]},
    "break":      {"label": "Thoát vòng lặp","kind": "action",    "ins": 1, "outs": ["out"]},
    "if_image":   {"label": "Nếu thấy ảnh",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_text":    {"label": "Nếu thấy chữ",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_var":     {"label": "Nếu biến",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "loop":       {"label": "Lặp lại",       "kind": "loop",      "ins": 1, "outs": ["body", "done"]},
    "parallel":   {"label": "Chạy song song","kind": "parallel",  "ins": 1, "outs": ["1", "2", "3", "done"]},
}


class WorkflowEngine:
    """Run a JSON workflow, honouring pause/stop and the sequence/background split."""

    def __init__(
        self,
        automation: Optional[ADBGameAutomation] = None,
        ocr_backend: Optional[str] = None,
    ) -> None:
        self.auto = automation or ADBGameAutomation(ocr_backend=ocr_backend)

        self.flow: Dict[str, Any] = {}
        self.flow_path: Optional[str] = None
        self.templates_base: str = ""
        # Reusable subroutines, keyed by id. Each value is a function dict with
        # its own ``graph`` (nodes + edges); a ``call`` node runs one inline.
        self._functions: Dict[str, Dict[str, Any]] = {}
        # Variables for set_var / if_var, reset at the start of each activity run.
        self._vars: Dict[str, Any] = {}
        # Center (x, y) of the most recently found image/text. An image
        # condition (if_image / wait_image) sets it; a tap/long_press node with
        # target="found" then acts on it — so "if see image → tap it" works.
        self._last_pos: Optional[tuple] = None
        # Set by a "break" node; the next loop node it reaches exits to "done".
        self._break_loop: bool = False

        self.running = False
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # not paused

        self._seq_thread: Optional[threading.Thread] = None
        self._bg_threads: Dict[str, threading.Thread] = {}
        self._bg_stop: Dict[str, threading.Event] = {}

        # GUI hooks; all optional.
        self.callbacks: Dict[str, List[Callable]] = {
            "on_start": [], "on_stop": [],
            "on_activity_start": [], "on_activity_complete": [],
            "on_node": [],  # fired with the node id about to execute (None = idle)
        }

        # Dispatch table for action nodes: type -> handler(node, params) -> bool.
        self._actions: Dict[str, Callable[[Dict, Dict], bool]] = {
            "tap": self._a_tap,
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
            "break": self._a_break,
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
                log_error(f"[workflow] callback {event} failed: {e}")

    # ── Flow loading ─────────────────────────────────────────────────────────

    def load(self, flow: Dict[str, Any], flow_path: Optional[str] = None) -> None:
        """Install a parsed flow dict. ``flow_path`` anchors relative templates."""
        self.flow = flow or {}
        self.flow_path = flow_path
        self._functions = {f.get("id"): f for f in (self.flow.get("functions") or []) if f.get("id")}
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
            f"[workflow] Loaded '{self.flow.get('name', 'flow')}' "
            f"({len(self.activities())} activities), templates@ {self.templates_base}"
        )

    @staticmethod
    def load_file(path: str) -> Dict[str, Any]:
        """Read + JSON-decode a flow file (raises on bad JSON/IO)."""
        import json
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

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

    def _ensure_ready(self) -> bool:
        """Connect ADB + start continuous capture if needed."""
        try:
            if not self.auto.adb.device:
                self.auto.adb.check_adb_connection()
            if not self.auto.adb.device:
                log_error("[workflow] No ADB device connected")
                return False
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
            return True
        except Exception as e:
            log_error(f"[workflow] Not ready: {e}")
            return False

    def start(self, background: bool = True) -> bool:
        """Run all enabled sequence activities once, then start backgrounds."""
        if self.running:
            log_warning("[workflow] Already running")
            return False
        if not self._ensure_ready():
            return False
        self._stop.clear()
        self.auto._stop_event.clear()
        self._pause.set()
        self.running = True
        self._emit("on_start")

        if background:
            self.start_all_background()

        self._seq_thread = threading.Thread(target=self._run_sequence, daemon=True)
        self._seq_thread.start()
        return True

    def _run_sequence(self) -> None:
        try:
            for act in self.activities():
                if self._stop.is_set():
                    break
                if act.get("type") == "background":
                    continue
                if not act.get("enabled", True):
                    continue
                self._run_activity(act)
                if self._stop.is_set():
                    break
                time.sleep(0.3)
            log_success("[workflow] Sequence finished")
        except Exception as e:
            log_error(f"[workflow] Sequence error: {e}")
        finally:
            if not self._bg_threads:
                self.running = False
                self._emit("on_stop")

    def _run_activity(self, act: Dict[str, Any]) -> bool:
        name = act.get("name") or act.get("id") or "activity"
        retries = max(1, int(act.get("maxRetries", 1) or 1))
        self._vars = self._seed_vars(act)
        self._last_pos = None
        self._break_loop = False
        self._emit("on_activity_start", act)
        ok = False
        for attempt in range(1, retries + 1):
            if self._stop.is_set():
                break
            if attempt > 1:
                log_info(f"[workflow] Retry {name} ({attempt}/{retries})")
            log_info(f"[workflow] ▶ {name}")
            ok = self._run_graph(act.get("graph", {}) or {})
            if ok:
                break
        if ok:
            log_success(f"[workflow] ✔ {name}")
        else:
            log_warning(f"[workflow] ✖ {name}")
        self._emit("on_node", None)  # clear highlight between activities
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

    def _run_graph(self, graph: Dict[str, Any], depth: int = 0) -> bool:
        nodes = {n.get("id"): n for n in graph.get("nodes", []) or []}
        adj = self._build_adjacency(graph.get("edges", []) or [])
        start = next((n for n in nodes.values() if n.get("type") == "start"), None)
        if start is None:
            log_warning("[workflow] Graph has no start node")
            return False
        self._walk(nodes, adj, self._next(adj, start.get("id"), "out"), {}, depth)
        return True

    def _walk(self, nodes, adj, cur, counters, depth):
        """Follow edges from ``cur`` until a dead-end / end node / stop.

        ``counters`` is this walk's loop state (parallel branches get their own).
        """
        steps = 0
        while cur and not self._stop.is_set():
            self._pause.wait()
            steps += 1
            if steps > MAX_STEPS:
                log_warning("[workflow] Step cap reached — stopping graph (cycle?)")
                break
            node = nodes.get(cur)
            if node is None:
                break
            self._emit("on_node", cur)  # let the designer highlight the active node
            ntype = node.get("type")
            if ntype == "end":
                break
            spec = NODE_TYPES.get(ntype)
            kind = spec.get("kind") if spec else None
            params = node.get("params", {}) or {}

            if kind == "stop":
                log_info("[workflow] Dừng theo node Stop")
                self.stop()
                break
            elif kind == "condition":
                res = self._eval_condition(ntype, params)
                port = "true" if res else "false"
                nxt = self._next(adj, cur, port)
                cur = nxt if nxt is not None else self._next(adj, cur, "out")
            elif kind == "loop":
                if self._break_loop:
                    self._break_loop = False
                    counters[cur] = 0
                    cur = self._next(adj, cur, "done")
                elif self._truthy(params.get("infinite", False)):
                    steps = 0  # don't let the safety cap kill an intentional ∞ loop
                    cur = self._next(adj, cur, "body")
                else:
                    done = counters.get(cur, 0)
                    count = max(0, int(params.get("count", 1)))
                    if done < count:
                        counters[cur] = done + 1
                        cur = self._next(adj, cur, "body")
                    else:
                        counters[cur] = 0
                        cur = self._next(adj, cur, "done")
            elif kind == "parallel":
                self._run_parallel(nodes, adj, cur, depth)
                cur = self._next(adj, cur, "done")
            elif kind == "call":
                fid = params.get("fn")
                fn = self._functions.get(fid)
                if fn is None:
                    log_warning(f"[workflow] call -> unknown function '{fid}'")
                elif depth >= MAX_CALL_DEPTH:
                    log_warning("[workflow] Max function call depth reached (recursion?)")
                else:
                    log_info(f"[workflow] ƒ {fn.get('name', fid)}")
                    self._run_graph(fn.get("graph", {}) or {}, depth + 1)
                cur = self._next(adj, cur, "out")
            else:  # action (or unknown -> just follow out)
                handler = self._actions.get(ntype)
                if handler is not None:
                    try:
                        handler(node, params)
                    except Exception as e:
                        log_error(f"[workflow] Node '{ntype}' error: {e}")
                else:
                    log_warning(f"[workflow] Unknown node: {ntype}")
                cur = self._next(adj, cur, "out")
        return True

    def _run_parallel(self, nodes, adj, node_id, depth):
        """Run every wired branch port of a parallel node at once, then join."""
        ports = [p for p in (NODE_TYPES["parallel"]["outs"]) if p != "done"]
        threads = []
        for p in ports:
            tgt = self._next(adj, node_id, p)
            if not tgt:
                continue
            t = threading.Thread(
                target=self._walk, args=(nodes, adj, tgt, {}, depth), daemon=True)
            threads.append(t)
            t.start()
        if threads:
            log_info(f"[workflow] ⇉ chạy song song {len(threads)} nhánh")
        for t in threads:
            t.join()

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
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    def _seed_vars(self, act: Dict) -> Dict[str, Any]:
        """Initial variable values declared on the activity (``vars``)."""
        out: Dict[str, Any] = {}
        for v in (act.get("vars") or []):
            nm = str(v.get("name", "")).strip()
            if not nm:
                continue
            t = v.get("type", "text")
            val = v.get("value")
            if t == "bool":
                out[nm] = self._truthy(val)
            elif t == "number":
                c = self._coerce(val)
                out[nm] = c if isinstance(c, (int, float)) and not isinstance(c, bool) else 0
            else:  # text / select → string
                out[nm] = "" if val is None else str(val)
        return out

    @staticmethod
    def _region(params: Dict) -> tuple:
        return (int(params.get("x", 0)), int(params.get("y", 0)),
                int(params.get("w", 200)), int(params.get("h", 80)))

    def _eval_condition(self, ntype: str, params: Dict) -> bool:
        if ntype == "if_image":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            negate = bool(params.get("negate", False))
            res = self.auto.find_template(tpl, threshold=threshold)
            if res:
                self._last_pos = (res[0], res[1])
            return (res is not None) != negate
        if ntype == "tap_image":
            # Find (with timeout), remember position, optionally wait, then tap.
            tpl = self._resolve_template(params.get("template", ""))
            res = self.auto.wait_for_template(
                tpl, timeout=float(params.get("timeout", 5.0)),
                threshold=float(params.get("threshold", 0.85)),
            )
            if not res:
                log_warning(f"[workflow] tap_image miss: {os.path.basename(tpl)}")
                return False
            self._last_pos = (res[0], res[1])
            self._sleep(float(params.get("delay", 0)))  # wait after seeing, before tap
            tc = 2 if str(params.get("taps", "1")) in ("2", "double") else 1
            return bool(self.auto.tap(res[0], res[1], tap_count=tc))
        if ntype == "wait_image":
            tpl = self._resolve_template(params.get("template", ""))
            res = self.auto.wait_for_template(
                tpl, timeout=float(params.get("timeout", 10.0)),
                threshold=float(params.get("threshold", 0.85)),
            )
            if res:
                self._last_pos = (res[0], res[1])
                self._sleep(float(params.get("delay", 0)))  # wait after seeing, before continuing
            return res is not None
        if ntype == "wait_text":
            return bool(self.auto.wait_for_text_in_region(
                str(params.get("text", "")), region=self._region(params),
                timeout=float(params.get("timeout", 10.0)),
            ))
        if ntype == "if_text":
            negate = bool(params.get("negate", False))
            found = self.auto.region_contains_text(
                str(params.get("text", "")), region=self._region(params))
            return bool(found) != negate
        if ntype == "if_var":
            cur = self._vars.get(str(params.get("name", "")))
            return self._compare(cur, str(params.get("op", "==")), params.get("value", ""))
        return False

    def _compare(self, cur: Any, op: str, rhs: Any) -> bool:
        # Boolean comparison when the right-hand side is true/false.
        if op in ("==", "!=") and str(rhs).strip().lower() in ("true", "false"):
            res = self._truthy(cur) == (str(rhs).strip().lower() == "true")
            return res if op == "==" else not res
        a, b = self._coerce(cur), self._coerce(rhs)
        # Fall back to string compare when types differ for ordering ops.
        try:
            if op == "==":
                return a == b or str(cur) == str(rhs)
            if op == "!=":
                return not (a == b or str(cur) == str(rhs))
            if op == ">":
                return a > b
            if op == "<":
                return a < b
            if op == ">=":
                return a >= b
            if op == "<=":
                return a <= b
        except TypeError:
            return False
        return False

    # ── Background workers ───────────────────────────────────────────────────

    def start_all_background(self) -> None:
        for act in self.activities():
            if act.get("type") == "background" and act.get("enabled", True):
                self.start_background(act)

    def start_background(self, act: Dict[str, Any]) -> None:
        aid = act.get("id") or act.get("name")
        if not aid or aid in self._bg_threads:
            return
        stop_ev = threading.Event()
        self._bg_stop[aid] = stop_ev
        t = threading.Thread(target=self._bg_loop, args=(act, stop_ev), daemon=True)
        self._bg_threads[aid] = t
        t.start()
        log_info(f"[workflow] [bg] started '{act.get('name', aid)}'")

    def stop_background(self, aid: str) -> None:
        ev = self._bg_stop.get(aid)
        if ev:
            ev.set()
        t = self._bg_threads.pop(aid, None)
        self._bg_stop.pop(aid, None)
        if t and t.is_alive():
            t.join(timeout=0.5)
        log_info(f"[workflow] [bg] stopped '{aid}'")

    def _bg_loop(self, act: Dict[str, Any], stop_ev: threading.Event) -> None:
        name = act.get("name") or act.get("id")
        while not stop_ev.is_set() and not self._stop.is_set():
            self._pause.wait()
            self._vars = self._seed_vars(act)
            self._last_pos = None
            self._break_loop = False
            try:
                self._run_graph(act.get("graph", {}) or {})
            except Exception as e:
                log_error(f"[workflow] [bg] '{name}' error: {e}")
            interval = max(0.05, float(act.get("pollInterval", 1.0) or 1.0))
            end = time.time() + interval
            while time.time() < end and not stop_ev.is_set() and not self._stop.is_set():
                time.sleep(0.05)

    # ── Pause / stop ─────────────────────────────────────────────────────────

    def pause(self) -> None:
        self._pause.clear()
        log_info("[workflow] Paused")

    def resume(self) -> None:
        self._pause.set()
        log_info("[workflow] Resumed")

    def is_paused(self) -> bool:
        return not self._pause.is_set()

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        log_info("[workflow] Stopping…")
        self._stop.set()
        self.auto._stop_event.set()
        self._pause.set()
        for aid in list(self._bg_threads.keys()):
            self.stop_background(aid)
        if self._seq_thread and self._seq_thread.is_alive():
            self._seq_thread.join(timeout=1.0)
        self.auto.stop_continuous_capture()
        self.running = False
        self._emit("on_stop")
        log_success("[workflow] Stopped")

    def _sleep(self, seconds: float) -> None:
        """Pause-aware, stop-aware sleep."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop.is_set():
            self._pause.wait()
            time.sleep(0.05)

    # ── Action handlers ──────────────────────────────────────────────────────

    def _pos(self, p) -> tuple:
        """(x, y) for a tap-like node: the found image, or fixed coords."""
        if str(p.get("target", "pos")) == "found" and self._last_pos:
            return self._last_pos
        return (int(p.get("x", 0)), int(p.get("y", 0)))

    def _a_tap(self, node, p) -> bool:
        x, y = self._pos(p)
        return self.auto.tap(x, y)

    def _a_double_tap(self, node, p) -> bool:
        x, y = self._pos(p)
        return self.auto.tap(x, y, tap_count=2)

    def _a_swipe_dir(self, node, p) -> bool:
        direction = str(p.get("direction", "up")).lower()
        dist = int(p.get("distance", 400))
        dur = int(p.get("duration", 300))
        try:
            w, h = self.auto.adb.get_screen_size()
        except Exception:
            w, h = 0, 0
        cx, cy = (w // 2, h // 2) if (w and h) else (540, 960)
        dx = dy = 0
        if direction == "up":
            dy = -dist
        elif direction == "down":
            dy = dist
        elif direction == "left":
            dx = -dist
        elif direction == "right":
            dx = dist
        return self.auto.swipe(cx, cy, cx + dx, cy + dy, dur)

    def _a_tap_random(self, node, p) -> bool:
        x, y = int(p.get("x", 0)), int(p.get("y", 0))
        w, h = int(p.get("w", 0)), int(p.get("h", 0))
        rx = x + (random.randint(0, w) if w > 0 else 0)
        ry = y + (random.randint(0, h) if h > 0 else 0)
        return self.auto.tap(rx, ry)

    def _a_wait_random(self, node, p) -> bool:
        lo = float(p.get("min", 0.5))
        hi = float(p.get("max", 2.0))
        if hi < lo:
            lo, hi = hi, lo
        self._sleep(random.uniform(lo, hi))
        return True

    def _resolve_operand(self, raw: Any) -> float:
        """A calc operand: a number literal, or the value of a variable name."""
        s = str(raw).strip()
        if s in self._vars:
            v = self._coerce(self._vars[s])
            return float(v) if isinstance(v, (int, float)) else 0.0
        v = self._coerce(s)
        return float(v) if isinstance(v, (int, float)) else 0.0

    def _a_set_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        if name:
            self._vars[name] = self._coerce(p.get("value", ""))
            log_info(f"[workflow] set {name} = {self._vars[name]!r}")
        return True

    def _a_calc_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        if not name:
            return True
        op = str(p.get("op", "+"))
        cur = self._resolve_operand(self._vars.get(name, 0))
        rhs = self._resolve_operand(p.get("value", 0))
        if op == "+":
            res = cur + rhs
        elif op == "-":
            res = cur - rhs
        elif op == "*":
            res = cur * rhs
        elif op == "/":
            res = cur / rhs if rhs else 0.0
        else:  # "=" assign
            res = rhs
        # Keep ints clean (3.0 -> 3) for nicer comparisons/logs.
        if isinstance(res, float) and res.is_integer():
            res = int(res)
        self._vars[name] = res
        log_info(f"[workflow] {name} {op}= {rhs} -> {res}")
        return True

    def _a_read_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        text = self.auto.read_text(region=self._region(p)) or ""
        if name:
            self._vars[name] = self._coerce(text.strip())
            log_info(f"[workflow] read {name} = {self._vars[name]!r}")
        return True

    def _a_break(self, node, p) -> bool:
        self._break_loop = True
        log_info("[workflow] break — sẽ thoát vòng lặp kế tiếp")
        return True

    def _a_long_press(self, node, p) -> bool:
        x, y = self._pos(p)
        return self.auto.adb.swipe(x, y, x, y, int(p.get("duration", 800)))

    def _a_swipe(self, node, p) -> bool:
        return self.auto.swipe(
            int(p.get("x1", 0)), int(p.get("y1", 0)),
            int(p.get("x2", 0)), int(p.get("y2", 0)),
            int(p.get("duration", 300)),
        )

    def _a_wait(self, node, p) -> bool:
        self._sleep(float(p.get("seconds", 1.0)))
        return True

    def _a_send_text(self, node, p) -> bool:
        return self.auto.send_text(str(p.get("text", "")))

    def _a_key(self, node, p) -> bool:
        code = p.get("keycode", "")
        try:
            return self.auto.press_key(int(code))
        except (TypeError, ValueError):
            try:
                self.auto.adb.device.shell(f"input keyevent {code}")
                return True
            except Exception:
                return False

    def _a_back(self, node, p) -> bool:
        return self.auto.go_back()

    def _a_home(self, node, p) -> bool:
        return self.auto.go_home()

    def _a_launch_app(self, node, p) -> bool:
        pkg = str(p.get("package", "")).strip()
        return bool(pkg) and self.auto.adb.launch_app(pkg)

    def _a_screenshot(self, node, p) -> bool:
        self.auto.capture_screen()
        return True

    def _a_log(self, node, p) -> bool:
        log_info(f"[workflow] {p.get('message', '')}")
        return True
