"""PyWebView runner GUI for JSON workflows.

A sibling of ``apps/workflow_designer.py`` (a workflow file drives this one
instead of the graph editor). The workflow is always handed in at launch — by
the Hub's Run button, the Designer, or bundled into a standalone Runner .exe —
there is no in-app file picker. Its sequence/background activities appear with
enable toggles, a per-activity Run button, Start / Stop / Pause controls, and a
live log.

The actual execution is delegated to :class:`src.workflow.WorkflowEngine`, so a
flow behaves identically here and in the designer's *Run test*.

Run::

    python apps/workflow_runner.py workflows/<Name>/workflow.json
"""
from __future__ import annotations

import datetime
import os
import sys
import threading
from typing import Any, Dict, List, Optional

# --- bootstrap: make `src.*` (and the runner/ package) importable --------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_APPS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (_PROJECT_ROOT, _APPS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webview

from src import runner_update
from src.core.adb import lifecycle
from src.core.adb.auto.scrcpy_capture import (
    stop_scrcpy_sources,
)
from src.utils import (
    LOG_KIND_ACTIVITY,
    LOG_KIND_DETAIL,
    LOG_KIND_RUN,
    LOG_KIND_USER,
    add_log_subscriber,
    file_url,
    log_error,
    push_webview_event,
    remove_log_subscriber,
    theme_background,
    webview_storage_path,
)
from src.workflow import WorkflowEngine

from runner.common import (  # noqa: F401 - re-exported for callers and tests
    _PROJECT_ROOT,
    _WEB_DIR,
    EMULATOR_KINDS,
    EMULATOR_NODE_TYPES,
    REQUIREMENTS_DIR,
    REQUIREMENTS_SKIP,
    REQUIREMENTS_SRC,
    RUNTIME_PATH_PARAMS,
    _copy_tree_elevated,
    runner_title,
)
from runner.controls import ControlMixin
from runner.devices import DeviceMixin
from runner.outcome import OutcomeMixin
from runner.preview import PreviewMixin
from runner.settings import SettingsMixin
from runner.state import StateMixin
from runner.updates import UpdateMixin


class WorkflowRunnerAPI(OutcomeMixin, StateMixin, UpdateMixin, ControlMixin, SettingsMixin,
                        PreviewMixin, DeviceMixin):
    """Methods exposed to JavaScript via ``pywebview.api.*``."""

    def __init__(self) -> None:
        # The ADB lease is taken lazily, the first time this Runner actually
        # becomes an ADB consumer (see _ensure_adb_lease). Taking it here would
        # make a standalone Win32 build claim a stake in the shared server it
        # never uses — and then kill that server on close.
        self._adb_lease: Optional[str] = None
        self.engine = WorkflowEngine()
        self.flow: Dict[str, Any] = {}
        self.flow_path: Optional[str] = None
        self._runner_config: Dict[str, Any] = {}
        self._runner_config_path: Optional[str] = None
        self._runner_config_lock = threading.RLock()
        self._run_request_lock = threading.Lock()
        # win32.path as the workflow ships it — what a cleared override falls back to.
        self._flow_game_path = ""
        # emulator.{kind,path} as the workflow ships it — default for the
        # Runner's Settings → Emulator override.
        self._flow_emulator: Dict[str, Any] = {}

        self._window: Optional[webview.Window] = None
        self._closing = False
        self._log_buffer: List[Dict] = []
        self._pending_load: Optional[str] = None  # flow path to auto-load on attach

        # Terminal run outcomes (see "Run outcome" below): the engine reports a
        # user Stop exactly like a failure, so the intent behind a Stop is
        # tracked here, per run, and reset by every run entry point.
        self._run_id = 0
        self._run_active = False
        self._run_scope: Optional[List[str]] = None
        self._run_started_at = 0.0
        self._stop_intent = False
        self._run_failed = False
        self._run_counts: Dict[str, int] = {"completed": 0, "failed": 0, "stopped": 0}
        self._outcome: Optional[Dict[str, Any]] = None
        # The round a repeating Start is on ({round, total, phase, restUntil});
        # None for a single pass and between runs. See configure_rounds.
        self._round: Optional[Dict[str, Any]] = None
        # Per-activity tallies for the run's history record: id → {name, ok,
        # failed, stopped, seconds}; plus when each running activity began.
        self._run_acts: Dict[str, Dict[str, Any]] = {}
        self._act_t0: Dict[str, float] = {}
        # Last status pushed per activity id — used to settle rows that a Stop
        # cancelled before they could report back (background activities).
        self._act_status: Dict[str, str] = {}

        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None
        self._last_deep_scan = 0.0
        self._deep_scan_interval = 30.0

        # Live preview: a background thread pushes JPEG frames to the page while
        # the Preview panel is open (set_auto_refresh). Frames come from the same
        # capture backend the engine uses, so what you see is what a run sees.
        self._auto_refresh_enabled = False
        self._refresh_hz = 6.0
        self._refresh_thread: Optional[threading.Thread] = None
        self._capture_lock = threading.Lock()
        self._capture_request_lock = threading.Lock()
        # Last time the preview tried to (re)attach the Win32 window — see
        # _grab_frame; a missing window is retried at most every 2 s.
        self._win32_attach_at = 0.0
        # Last time the Unity Bridge was probed for the footer indicator.
        self._bridge_status_at = 0.0

        # A standalone Runner build knows its own version + update repo.
        self._runner_info: Dict[str, Any] = runner_update.build_info()
        self._update: Dict[str, Any] = {}

        # Mirror engine running/paused into the UI, and classify how the run
        # ended (completed / stopped / failed) on the way out.
        self.engine.on("on_start", self._on_engine_start)
        self.engine.on("on_stop", self._on_engine_stop)
        self.engine.on("on_activity_start", self._on_activity_start)
        self.engine.on("on_activity_complete", self._on_activity_complete)
        self.engine.on("on_activity_crash", self._on_activity_crash)
        self.engine.on("on_round", self._on_round)

    # ── Setup ────────────────────────────────────────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log, with_meta=True)
        if self._pending_load:
            try:
                self._load_path(self._pending_load)
            except Exception as exc:
                log_error(f"Auto-load failed: {exc}")
            self._pending_load = None
        # The poll thread lives for the session but stays idle unless an ADB
        # workflow is loaded — a Win32 game must never touch the ADB server.
        threading.Thread(target=self._device_poll, daemon=True).start()
        self._kick_device_scan()
        if runner_update.updates_supported(self._runner_info):
            threading.Thread(target=self._auto_check_update, daemon=True).start()

    # ── Log subscriber ───────────────────────────────────────────────────────

    # The Runner log is what an operator needs to follow an unattended run: run
    # and activity milestones, the workflow author's own log lines, and errors.
    # The engine's step-by-step detail (taps, matches, branches taken) is the
    # Designer's log, not this one.
    _RUNNER_LOG_KINDS = frozenset({LOG_KIND_RUN, LOG_KIND_ACTIVITY, LOG_KIND_USER})
    # Win32 internals (window handle, capture API, bridge handshake). Errors
    # still pass: a failed attach is something the operator can act on.
    _TECH_LOG = (
        "[win32] Attached window",
        "[win32] Capture is using",
        "[win32] Starting continuous",
        "[win32] Stopping continuous",
        "[win32] unity_bridge connected",
        "[win32] unity_bridge: injecting",
    )

    def _on_log(self, level: str, message: str, meta: Optional[dict] = None) -> None:
        meta = meta or {}
        kind = meta.get("kind")
        activity = meta.get("activity")
        if level != "error" and kind not in self._RUNNER_LOG_KINDS:
            if kind == LOG_KIND_DETAIL:
                return
            # Untagged lines from src/core while an activity runs are that
            # step's internals; outside a run they are app / device news.
            if activity:
                return
            if message.startswith(self._TECH_LOG):
                return
        bucket = {"info": "info", "success": "success",
                  "warning": "warning", "error": "error"}.get(level, "info")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        scope = activity or "Runner"
        entry = {"ts": ts, "level": bucket, "scope": scope, "text": message,
                 "kind": kind or "app", "msg": f"[{scope}] {message}"}
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

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        self._auto_refresh_enabled = False
        remove_log_subscriber(self._on_log)
        try:
            self.engine.stop()
        except Exception:
            pass
        stop_scrcpy_sources()
        # Only stop the shared ADB server when no sibling Macro2k process
        # (Designer / DevScope / Hub) still holds a lease. A Win32-only Runner
        # never took one, so it has nothing to release and must not kill a
        # server some other app is still using.
        if self._adb_lease:
            lifecycle.release_adb_and_kill_if_last("runner")


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_runner_window(title: Optional[str] = None,
                                  auto_load: Optional[str] = None) -> webview.Window:
    if not title:
        # A standalone Runner is titled after its game from the first frame;
        # a source run is renamed once its workflow loads (_load_path).
        info = runner_update.build_info()
        title = runner_title(info.get("name") or info.get("appName"), info.get("version") or "")
    api = WorkflowRunnerAPI()
    api._pending_load = auto_load
    html_path = os.path.join(_WEB_DIR, "runner", "index.html")
    url = file_url(html_path)
    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        # Fixed desktop canvas: the right control pane gets more room than the
        # activity list, so the Runner stays compact without breaking the split.
        width=720,
        height=800,
        resizable=True,
        min_size=(420, 620),
        background_color=theme_background(),
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
    # The workflow JSON to load — Hub Run and Designer Open Runner pass one.
    auto = sys.argv[1] if len(sys.argv) > 1 else None
    run(auto)
