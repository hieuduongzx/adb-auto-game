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

import base64
import datetime
import json
import os
import shutil
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

from src import runner_update
from src.core.adb import lifecycle
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    get_capture_backend,
    set_capture_backend,
    stop_scrcpy_sources,
)
from src.utils import (
    LOG_KIND_ACTIVITY,
    LOG_KIND_DETAIL,
    LOG_KIND_RUN,
    LOG_KIND_USER,
    add_log_subscriber,
    app_dir,
    bundle_dir,
    data_root,
    file_url,
    is_frozen,
    load_ui_settings,
    log_error,
    log_info,
    log_success,
    log_warning,
    push_webview_event,
    remove_log_subscriber,
    sanitize_name,
    save_ui_settings,
    slugify_workflow_name,
    theme_background,
    titled,
    webview_storage_path,
)
from src.version import APP_VERSION
from src.workflow import WorkflowEngine

# In a frozen build, writable resources (data/) live under data_root() — next to
# the app when writable, else %LOCALAPPDATA% (read-only Program Files install).
if is_frozen():
    _PROJECT_ROOT = data_root()

# Bundled HTML: ``apps/web`` from source, ``<_MEIPASS>/web`` when frozen.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))

# Node params that hold a machine-specific absolute path. Each one found in a
# loaded flow becomes a runner control (and is remembered in the runner config),
# so a built .exe can be re-pointed on another PC without editing the JSON.
RUNTIME_PATH_PARAMS = ("path", "apk")

# PC-side emulator nodes whose install folder comes from the shared project
# emulator setting (Runner Settings → Emulator) unless the node picks "Custom".
# Their path is therefore NOT offered as a per-activity control.
EMULATOR_NODE_TYPES = frozenset({
    "launch_emulator", "resize_emulator", "kill_emulator",
    "restart_emulator", "emulator_resolution",
})

# Families the shared emulator setting can name (a node may still use a custom
# command locally, but the project setting only carries a known family).
EMULATOR_KINDS = ("ldplayer", "mumu", "nox", "memu", "bluestacks")

# Game requirements — files the player copies into the game's install folder.
# A built Runner ships them as <exe folder>/requirements/ (packaging/build_runner.py
# copies the workflow's vendor/ there); from source they are the workflow's vendor/.
REQUIREMENTS_DIR = "requirements"
REQUIREMENTS_SRC = "vendor"
REQUIREMENTS_SKIP = (".gitkeep", "Thumbs.db", "desktop.ini", ".DS_Store")


def _copy_tree_elevated(src: str, dst: str) -> bool:
    """Copy ``src``'s contents into ``dst`` through an elevated robocopy.

    Game folders often live under Program Files, where a normal copy is refused.
    This launches robocopy with the ``runas`` verb (one UAC prompt) and waits for
    it, so the files land with admin rights. Returns True when the copy finished
    with robocopy's success exit codes (0–7). No-op off Windows."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return False

    skip = " ".join(f'"{name}"' for name in REQUIREMENTS_SKIP)
    params = (f'"{os.path.abspath(src)}" "{os.path.abspath(dst)}" '
              f'/E /COPY:DAT /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XF {skip}')

    class _SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SW_HIDE = 0
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "robocopy.exe"
    info.lpParameters = params
    info.nShow = SW_HIDE
    try:
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            return False
    except Exception as exc:
        log_warning(f"Elevation failed: {exc}")
        return False
    if not info.hProcess:
        return False
    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return int(code.value) < 8
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)


class WorkflowRunnerAPI:
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
        self._stop_intent = False
        self._run_failed = False
        self._run_counts: Dict[str, int] = {"completed": 0, "failed": 0, "stopped": 0}
        self._outcome: Optional[Dict[str, Any]] = None
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

    # ── Run outcome (completed / stopped / failed) ───────────────────────────
    # The engine only announces "a run started" and "a run stopped": a finished
    # pass, a user Stop and a fatal abort all end in on_stop, and an activity
    # cancelled mid-flight reports ok=False exactly like a failed one. So the
    # Stop *intent* is recorded here (stop()) and combined with the engine's own
    # failure signals — on_activity_crash, a failed activity, and the ``_fatal``
    # abort — to say truthfully how a run ended. No engine logic is changed.

    _OUTCOME_LABELS = {"completed": "Completed", "stopped": "Stopped", "failed": "Failed"}

    def _engine_stop_flags(self) -> tuple:
        """``(stopping, fatal)`` peeked read-only out of the engine.

        ``_stop`` is set by a user Stop, a workflow Stop block and by
        ``_fail_run``'s abort alike; ``_fatal`` is set *only* by ``_fail_run``
        (a Launch program with no program to start) — the one "stopped" that is
        genuinely a failure. Both are missing on a fresh engine, hence getattr.
        """
        event = getattr(self.engine, "_stop", None)
        try:
            stopping = bool(event is not None and event.is_set())
        except Exception:
            stopping = False
        return stopping, bool(str(getattr(self.engine, "_fatal", "") or ""))

    def _reset_run_tracking(self) -> None:
        self._stop_intent = False
        self._run_failed = False
        self._run_counts = {"completed": 0, "failed": 0, "stopped": 0}

    def _run_live(self) -> bool:
        """True between a run's on_start and its on_stop.

        Deliberately wider than ``engine.is_running()``: the engine flips
        ``running`` to False *just before* it emits on_stop, so a run that is
        still being wound down must not look idle to _begin_run()/stop().
        """
        return bool(self._run_active or self.engine.is_running())

    def _begin_run(self) -> None:
        """Start fresh outcome bookkeeping for a run that is about to be asked
        to start.

        Every entry point (Start, per-activity Run) calls this *before* it can
        bail out, so a blocked Start (a Launch program with no path) or a
        refused run_activity can never hand the previous run's Stop intent /
        failure flag to the next one. A run still winding down is left alone.
        """
        if not self._run_live():
            self._reset_run_tracking()

    def _outcome_fields(self) -> dict:
        """The last terminal outcome as flat keys, shared by ``running_state``
        and :meth:`get_state` so the page reads the same shape from either.

        ``outcome`` is None while a run is live and before the first run ever
        ended; the rest describe the run it belongs to (``runId``).
        """
        info = self._outcome or {}
        return {
            "outcome": info.get("kind"),
            "outcomeLabel": str(info.get("label") or ""),
            "outcomeReason": str(info.get("reason") or ""),
            "outcomeAt": str(info.get("at") or ""),
            "runId": int(info.get("runId") or self._run_id),
            "runCounts": dict(info.get("counts") or self._run_counts),
        }

    def _running_payload(self) -> dict:
        payload = {"running": self.engine.is_running(), "paused": self.engine.is_paused()}
        payload.update(self._outcome_fields())
        return payload

    def _on_engine_start(self) -> None:
        self._run_id += 1
        self._run_active = True
        self._act_status = {}
        self._reset_run_tracking()
        self._outcome = None
        self._push("running_state", self._running_payload())

    def _on_engine_stop(self) -> None:
        """Every terminal path lands here — classify the run once."""
        if self._run_active:
            self._run_active = False
            self._outcome = self._classify_outcome()
            if self._outcome["kind"] == "stopped":
                # A background activity cancelled by the Stop never reports
                # back (the engine just ends its loop), so settle its row.
                self._settle_stopped_activities()
            self._log_outcome(self._outcome)
        self._push("running_state", self._running_payload())

    def _classify_outcome(self) -> dict:
        """Decide how the run that just ended actually ended.

        Priority: a fatal abort is a failure even though it stopped the engine;
        a Stop (mine or the workflow's) is "stopped" and never a failure — which
        is the whole point of tracking intent, since a cancelled activity comes
        back as ok=False; otherwise a run that had any failed activity failed,
        and a clean pass completed.
        """
        stopping, fatal = self._engine_stop_flags()
        counts = dict(self._run_counts)
        intent = bool(self._stop_intent)
        if fatal:
            kind, reason = "failed", fatal
        elif intent or stopping:
            kind = "stopped"
            reason = "Stopped by you" if intent else "Stopped by the workflow"
        elif self._run_failed:
            kind = "failed"
            failed = counts.get("failed", 0)
            reason = (f"{failed} of {sum(counts.values())} activities failed"
                      if failed else "An activity failed")
        else:
            kind = "completed"
            done = counts.get("completed", 0)
            reason = (f"{done} activit{'y' if done == 1 else 'ies'} completed"
                      if done else "Run finished")
        return {"kind": kind, "label": self._OUTCOME_LABELS[kind], "reason": reason,
                "at": datetime.datetime.now().strftime("%H:%M:%S"),
                "epoch": time.time(), "runId": self._run_id, "counts": counts}

    def _log_outcome(self, info: dict) -> None:
        """One line in the Runner log per terminal outcome.

        The log is what an operator reads (and exports) after an unattended
        run, so how the run ended belongs in it rather than being inferred from
        the lines above it.
        """
        text = f"■ Run {info['label'].lower()}"
        if info.get("reason"):
            text += f" ({info['reason']})"
        if info["kind"] == "failed":
            log_error(text, kind=LOG_KIND_RUN)
        elif info["kind"] == "stopped":
            log_info(text, kind=LOG_KIND_RUN)
        else:
            log_success(text, kind=LOG_KIND_RUN)

    def _settle_stopped_activities(self) -> None:
        for act_id, status in list(self._act_status.items()):
            if status != "running":
                continue
            self._act_status[act_id] = "stopped"
            self._push("activity_update", {"id": act_id, "status": "stopped"})

    def _on_activity_start(self, act: dict) -> None:
        act_id = (act or {}).get("id")
        if act_id is not None:
            self._act_status[str(act_id)] = "running"
        self._push("activity_update", {"id": act_id, "status": "running"})

    def _on_activity_complete(self, act: dict, ok: bool) -> None:
        """Paint one activity's terminal state and count it for the outcome."""
        status = self._activity_status(ok)
        act_id = (act or {}).get("id")
        if act_id is not None:
            self._act_status[str(act_id)] = status
        self._run_counts[status] = self._run_counts.get(status, 0) + 1
        if status == "failed":
            self._run_failed = True
        self._push("activity_update", {"id": act_id, "status": status})

    def _on_activity_crash(self, act: dict, crash: Optional[dict]) -> None:
        """The engine emits this only for a genuine failure — a user Stop and a
        Stop block are excluded there — so it is the dependable "this run did
        not simply finish" signal."""
        self._run_failed = True

    def _activity_status(self, ok: bool) -> str:
        """A stopped activity is reported as stopped, not failed.

        The engine reports a cancelled activity as ok=False (indistinguishable
        from a failure at that level) and, for a stop landing inside a wait,
        even as ok=True — so an in-effect Stop outranks ``ok``. ``_fatal`` still
        wins: an aborted run did fail.
        """
        stopping, fatal = self._engine_stop_flags()
        if fatal:
            return "failed"
        if stopping or self._stop_intent:
            return "stopped"
        return "completed" if ok else "failed"

    # ── Log subscriber ───────────────────────────────────────────────────────

    # The Runner log is what an operator needs to follow an unattended run: run
    # and activity milestones, the workflow author's own log lines, and errors.
    # The engine's step-by-step detail (taps, matches, branches taken) is the
    # Designer's log, not this one.
    _RUNNER_LOG_KINDS = frozenset({LOG_KIND_RUN, LOG_KIND_ACTIVITY, LOG_KIND_USER})

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

    # ── State ────────────────────────────────────────────────────────────────

    def _config_path_for_flow(self, flow: dict, flow_path: str) -> str:
        """Readable per-workflow config: data/runner/<slug>_<hash>/config.json.

        The slug comes from ``slugify_workflow_name`` — it appends a short hash
        of the original name so distinct names ("A B" vs "A_B") can never
        collide on one config folder."""
        raw = str(flow.get("name") or "").strip()
        if not raw:
            raw = os.path.splitext(os.path.basename(flow_path or "workflow"))[0]
        slug = slugify_workflow_name(raw)
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
        for act in acts:
            for var in act.get("vars", []) or []:
                if var.get("type") == "select":
                    options = var.get("options") or []
                    if var.get("display") == "toggle-group" and var.get("multiple"):
                        values = var.get("value")
                        values = values if isinstance(values, list) else [values]
                        var["value"] = [o for o in options if o in values]
                    elif isinstance(var.get("value"), list):
                        var["value"] = next((o for o in var["value"] if o in options), options[0] if options else "")
                    elif var.get("value") not in options:
                        var["value"] = options[0] if options else ""
        # Retry count: the workflow's own ``maxRetries`` is the default the Runner
        # shows, and a Runner override (saved in this Runner's config) beats it.
        # Only the override is written to flow, in memory — the workflow file is
        # never written back.
        for act in acts:
            saved = act_cfg.get(str(act.get("id"))) if isinstance(act_cfg, dict) else None
            if isinstance(saved, dict) and saved.get("retries") is not None:
                try:
                    act["maxRetries"] = max(1, int(float(saved["retries"])))
                    continue
                except (TypeError, ValueError):
                    pass
            try:
                act["maxRetries"] = max(1, int(act.get("maxRetries", 1) or 1))
            except (TypeError, ValueError):
                act["maxRetries"] = 1
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
            for param in RUNTIME_PATH_PARAMS:
                if param in values and param in params:
                    params[param] = str(values[param] or "")
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
        # Project game path (Win32): the Settings tab override beats the path
        # chosen in the Designer; an empty override keeps the workflow's own.
        win = self.flow.get("win32")
        if not isinstance(win, dict):
            win = self.flow["win32"] = {}
        self._flow_game_path = str(win.get("path") or "").strip()
        override = str(cfg.get("win32Path") or "").strip()
        if override:
            win["path"] = override
        # Shared emulator setting (ADB): the Settings tab override beats the
        # workflow's own kind/folder; empty fields keep the workflow's own.
        emu = self.flow.get("emulator")
        if not isinstance(emu, dict):
            emu = self.flow["emulator"] = {}
        # Older files kept the emulator install folder on each node. Seed the
        # shared setting from the first one so consolidating doesn't lose it and
        # the Settings → Emulator card can re-point it.
        if not str(emu.get("path") or "").strip():
            for node in self._graph_nodes():
                if str(node.get("type") or "") not in EMULATOR_NODE_TYPES:
                    continue
                params = node.get("params") or {}
                if not str(params.get("path") or "").strip():
                    continue
                emu["path"] = str(params.get("path")).strip()
                kind = str(params.get("emulator") or "").strip().lower()
                if kind and kind not in ("custom", "last"):
                    emu["kind"] = kind
                break
        if not str(emu.get("kind") or "").strip():
            emu["kind"] = "ldplayer"
        self._flow_emulator = dict(emu)
        saved_emu = cfg.get("emulator")
        if isinstance(saved_emu, dict):
            if str(saved_emu.get("kind") or "").strip():
                emu["kind"] = str(saved_emu.get("kind")).strip()
            if str(saved_emu.get("path") or "").strip():
                emu["path"] = str(saved_emu.get("path")).strip()

    @staticmethod
    def _launch_uses_project_path(node: dict) -> bool:
        """True when a win_launch node takes the project game path rather than
        its own ``path`` (same rule as WorkflowEngine._win_launch_path)."""
        if str(node.get("type") or "") != "win_launch":
            return False
        params = node.get("params") or {}
        src = str(params.get("pathSrc") or "").strip().lower()
        if src:
            return src == "project"
        return not str(params.get("path") or "").strip()

    @staticmethod
    def _emulator_uses_project(node: dict) -> bool:
        """True when an emulator node takes the shared project emulator install
        folder rather than its own ``path``. Only an explicit "custom" source
        keeps a per-activity control; legacy nodes without ``pathSrc`` follow the
        shared setting (their old path is seeded into it on load)."""
        if str(node.get("type") or "") not in EMULATOR_NODE_TYPES:
            return False
        params = node.get("params") or {}
        return str(params.get("pathSrc") or "").strip().lower() != "custom"

    def _graph_nodes(self, activity_ids: Optional[List[str]] = None) -> List[dict]:
        """Every node a run of these activities (all when ``None``) can reach,
        following function calls."""
        functions = {f.get("id"): f for f in (self.flow.get("functions") or []) if f.get("id")}
        acts = list(self.flow.get("activities") or [])
        if activity_ids is not None:
            wanted = {str(a) for a in activity_ids}
            acts = [a for a in acts if str(a.get("id")) in wanted]
        found: List[dict] = []
        seen_functions: set = set()

        def scan(graph: dict) -> None:
            for node in (graph or {}).get("nodes", []) or []:
                found.append(node)
                if node.get("type") == "call":
                    fn_id = str((node.get("params") or {}).get("fn") or "")
                    if fn_id in functions and fn_id not in seen_functions:
                        seen_functions.add(fn_id)
                        scan(functions[fn_id].get("graph") or {})

        for act in acts:
            scan(act.get("graph") or {})
        return found

    def _game_path_status(self) -> dict:
        """Whether this game needs the project game path, and if it is usable.

        Needed by a Win32 game whose Launch program uses the project path, or
        that ships requirements to copy into the game folder."""
        path = str((self.flow.get("win32") or {}).get("path") or "").strip()
        needed = bool(self.flow) and self._controller() == "win32" and (
            any(self._launch_uses_project_path(n) for n in self._graph_nodes())
            or bool(self._requirements_dir()))
        return {"needed": needed, "path": path, "exists": bool(path) and os.path.isfile(path)}

    def _launch_preflight(self, activity_ids: Optional[List[str]]) -> List[dict]:
        """Launch program nodes that would stop the run: no path, or nothing at
        it. Checked before Start so a missing game shows up front, not minutes
        into a run. A path held in a variable is only known at run time — the
        node itself stops the run then."""
        if not self.flow or self._controller() != "win32":
            return []
        if activity_ids is None:
            activity_ids = [str(a.get("id")) for a in (self.flow.get("activities") or [])
                            if a.get("enabled", True)]
        var_names = {str(v.get("name")) for v in (self.flow.get("globals") or []) if v.get("name")}
        for act in self.flow.get("activities") or []:
            var_names |= {str(v.get("name")) for v in (act.get("vars") or []) if v.get("name")}
        game = str((self.flow.get("win32") or {}).get("path") or "").strip()
        problems: List[dict] = []
        seen: set = set()
        for node in self._graph_nodes(activity_ids):
            if node.get("type") != "win_launch" or node.get("id") in seen:
                continue
            seen.add(node.get("id"))
            label = str(node.get("note") or "Launch program")
            if self._launch_uses_project_path(node):
                if not game:
                    message = f"{label}: no game path — choose the game's .exe in Settings → Game"
                elif not os.path.isfile(game):
                    message = f"{label}: game not found at {game} — choose the game's .exe again"
                else:
                    continue
                problems.append({"message": message, "gamePath": True})
                continue
            raw = str((node.get("params") or {}).get("path") or "").strip()
            if raw in var_names or ("{" in raw and "}" in raw):
                continue
            if not raw:
                message = f"{label}: no program path — set it in the activity's settings"
            elif not os.path.isfile(raw):
                message = f"{label}: program not found at {raw} — fix it in the activity's settings"
            else:
                continue
            problems.append({"message": message, "gamePath": False})
        # One line per distinct problem (several nodes can share the project path).
        unique = {p["message"]: p for p in problems}
        return list(unique.values())

    def _blocked_by_launch_paths(self, activity_ids: Optional[List[str]]) -> bool:
        """Refuse to start when a Launch program can't find its program; the
        page shows the problems and offers to choose the game path."""
        problems = self._launch_preflight(activity_ids)
        if not problems:
            return False
        for problem in problems:
            log_error(f"Can't start: {problem['message']}")
        # A refused Start is still an ending the operator has to see — the page
        # would otherwise sit on the previous run's outcome.
        self._stop_intent = False
        self._run_failed = True
        self._outcome = {"kind": "failed", "label": self._OUTCOME_LABELS["failed"],
                         "reason": "Start blocked — " + "; ".join(p["message"] for p in problems),
                         "at": datetime.datetime.now().strftime("%H:%M:%S"),
                         "epoch": time.time(), "runId": self._run_id,
                         "counts": dict(self._run_counts)}
        self._push("running_state", self._running_payload())
        self._push("launch_blocked", {
            "problems": [p["message"] for p in problems],
            "needsGamePath": any(p["gamePath"] for p in problems),
            "gamePath": self._game_path_status(),
            "outcome": self._outcome_fields(),
        })
        return True

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

    def get_diagnostics(self) -> dict:
        """Return safe, read-only environment facts useful for support."""
        workflow_path = os.path.abspath(self.flow_path) if self.flow_path else ""
        req = self._requirements_payload()
        config = self._runner_config_path or ""
        return {
            "ok": True,
            "version": {"app": APP_VERSION, "appName": "Macro2k", "runner": self._runner_payload(),
                        "builtAt": self._runner_info.get("builtAt", ""),
                        "repo": self._runner_info.get("repo", ""), "frozen": is_frozen()},
            "mode": "packaged" if is_frozen() else "source",
            "controller": self._controller(),
            "capture": {"backend": get_capture_backend(), "backends": list(CAPTURE_BACKENDS)},
            "config": {"path": config, "exists": bool(config and os.path.isfile(config))},
            "workflow": {"path": workflow_path, "name": self.flow.get("name", ""),
                         "loaded": bool(self.flow), "exists": bool(workflow_path and os.path.isfile(workflow_path))},
            "data": {"root": data_root(), "folder": os.path.dirname(config) if config else data_root(),
                     "exists": os.path.isdir(os.path.dirname(config) if config else data_root())},
            "requirements": {"folder": req.get("folder", ""), "exists": bool(req.get("exists")),
                             "fileCount": len(req.get("files", []) or []),
                             "gameDir": req.get("gameDir", ""), "missing": req.get("missing", []),
                             "installed": req.get("installed", False)},
            "paths": {"app": app_dir(), "data": data_root(), "bundle": bundle_dir(),
                      "web": os.path.join(bundle_dir(), "web"), "config": config,
                      "workflow": workflow_path, "requirements": req.get("folder", "")},
            "log": {"entries": len(self._log_buffer), "max": 2000},
            "running": self._run_live(),
        }

    def export_log(self, path: str = "") -> dict:
        """Save retained Runner log as UTF-8, using the native dialog by default."""
        if not path:
            try:
                chosen = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename="macro2k-run.log", file_types=("Log files (*.log)", "Text files (*.txt)", "All files (*.*)")) if self._window else None
                path = chosen[0] if chosen else ""
            except Exception as exc:
                return {"ok": False, "path": "", "error": str(exc), "cancelled": False}
        if not path:
            return {"ok": False, "path": "", "error": "", "cancelled": True}
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for entry in self._log_buffer:
                    fh.write(str(entry.get("text", entry.get("message", ""))) + "\n")
            return {"ok": True, "path": os.path.abspath(path), "error": "", "cancelled": False}
        except Exception as exc:
            return {"ok": False, "path": path, "error": str(exc), "cancelled": False}

    def open_data_folder(self) -> dict:
        """Open the fixed per-runner data folder without accepting arbitrary paths."""
        folder = os.path.dirname(self._runner_config_path) if self._runner_config_path else data_root()
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
            return {"ok": True, "path": folder, "error": ""}
        except Exception as exc:
            return {"ok": False, "path": folder, "error": str(exc)}

    def get_state(self) -> dict:
        # "running"/"paused" plus the terminal-outcome keys, so the page reads
        # one shape whether it just opened or a run_activity event arrived.
        return {
            "title": "Macro2k Runner",
            "name": self.flow.get("name", ""),
            "loaded": bool(self.flow),
            "activities": self._activities_payload(),
            "log": self._log_buffer[-300:],
            **self._running_payload(),
            "speedhack": self.engine.speedhack_info(),
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
            "captureBackend": get_capture_backend(),
            "captureBackends": list(CAPTURE_BACKENDS),
            "controller": self._controller(),
            "win32": dict(self.flow.get("win32") or {}),
            "gamePathDefault": self._flow_game_path,
            "emulator": dict(self.flow.get("emulator") or {}),
            "emulatorDefault": self._flow_emulator,
            "requirements": self._requirements_payload(),
            "gamePath": self._game_path_status(),
            "configPath": self._runner_config_path or "",
            "runner": self._runner_payload(),
            "icon": self._icon_url(),
            "iconKey": self._icon_key(),
        }

    def _icon_url(self) -> str:
        """The game icon for the header: a built Runner's own icon, else the
        workflow's assets/icon.* or assets/cover.* (\"\" → the page draws initials)."""
        bundled = os.path.join(bundle_dir(), "runner_icon.png")
        if is_frozen() and os.path.isfile(bundled):
            return file_url(bundled)
        if self.flow_path:
            assets = os.path.join(os.path.dirname(os.path.abspath(self.flow_path)), "assets")
            for name in ("icon.png", "icon.jpg", "icon.jpeg", "icon.webp", "icon.ico",
                         "cover.png", "cover.jpg", "cover.jpeg", "cover.webp"):
                path = os.path.join(assets, name)
                if os.path.isfile(path):
                    return file_url(path)
        return ""

    def _icon_key(self) -> str:
        """Workflow folder name — the key the Hub hashes a game's hue from."""
        if self._runner_info.get("folder"):
            return str(self._runner_info["folder"])
        return os.path.basename(os.path.dirname(os.path.abspath(self.flow_path))) if self.flow_path else ""

    # ── Version + self-update (standalone Runner builds) ─────────────────────

    def _runner_payload(self) -> dict:
        info = self._runner_info
        return {
            "version": str(info.get("version") or ""),
            "appName": str(info.get("appName") or ""),
            "repo": str(info.get("repo") or ""),
            "builtAt": str(info.get("builtAt") or ""),
            "supported": runner_update.updates_supported(info),
            "update": dict(self._update),
        }

    def _auto_check_update(self) -> None:
        result = runner_update.check(self._runner_info)
        self._update = result
        if result.get("available"):
            log_success(f"Update available: v{result.get('version')}")
            self._push("update_available", result)

    def update_check(self) -> dict:
        """Ask GitHub for a newer release of this Runner."""
        result = runner_update.check(self._runner_info)
        self._update = result
        return result

    def update_apply(self) -> dict:
        """Download + install the newest release and restart. Returns only on
        failure or when already up to date."""
        if self.engine.is_running():
            return {"applied": False, "error": "Stop the run before updating", "upToDate": False}
        return runner_update.apply(
            self._runner_info,
            on_progress=lambda pct, stage: self._push("update_progress", {"pct": pct, "stage": stage}),
            before_exit=self._close,
        )

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
            "app_install": ("Install app", "APK file"),
        }
        kinds = {"launch_emulator": "folder", "win_launch": "file", "app_install": "file"}
        # Params holding a machine-specific absolute path: each one becomes a
        # runner control so a built .exe can be re-pointed without editing JSON.
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
                # Every serialized path-like parameter gets a generated setting;
                # known node types only refine its label and picker kind.
                for param in RUNTIME_PATH_PARAMS:
                    if param not in params:
                        continue
                    # A Launch program on the project path is set once in the
                    # Settings tab (Game path), not per activity.
                    if param == "path" and self._launch_uses_project_path(node):
                        continue
                    # Emulator nodes on the shared project setting (Settings →
                    # Emulator) likewise don't need a per-activity control.
                    if param == "path" and self._emulator_uses_project(node):
                        continue
                    node_label, field_label = labels.get(node_type, (node_type or "Action", "Path"))
                    node_label = str(node.get("note") or node_label)
                    found.append({
                        "id": f"{node_id}:{param}", "nodeId": node_id, "param": param,
                        "nodeLabel": node_label, "label": field_label,
                        "kind": kinds.get(node_type, "file"),
                        "value": str(params.get(param) or ""),
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
                          "options": v.get("options") or [],
                          "display": v.get("display", "dropdown"),
                          "multiple": v.get("display") == "toggle-group" and bool(v.get("multiple"))}
                         for v in (a.get("vars") or [])],
                "runtimeSettings": self._runtime_settings_for_activity(a),
            })
        return out

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
        log_success(f"Automation initialized successfully — {workflow_name}")
        # unity_bridge: show from the start whether the in-game plugin answers.
        self._push_bridge_status(force=True)
        # The controller just changed: start (or park) ADB device watching.
        self._kick_device_scan()
        return state

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
        # Cleared even when this Start is refused below, so a blocked run can't
        # leave the previous run's outcome flags behind (see _begin_run).
        self._begin_run()
        if not self.flow:
            log_warning("No workflow loaded — open this Runner from the Macro2k Hub")
            return False
        if self._blocked_by_launch_paths(None):
            return False
        self._select_run_device()
        # Reset UI activity statuses.
        for a in self._activities_payload():
            self._push("activity_update", {"id": a["id"], "status": "pending"})
        # Re-check the Unity Bridge now: the operator usually starts the game
        # right before pressing Start, so this is when it matters.
        self._push_bridge_status(force=True)
        return self.engine.start(background=True)

    def run_activity(self, activity_id: str) -> bool:
        """Run a single activity on its own, whether or not it is enabled.

        A sequence activity runs once; a background activity loops until Stop."""
        self._begin_run()
        if not self.flow:
            log_warning("No workflow loaded — open this Runner from the Macro2k Hub")
            return False
        if self.engine.is_running():
            log_warning("Stop the current run before running a single activity")
            return False
        if self._blocked_by_launch_paths([str(activity_id or "")]):
            return False
        self._select_run_device()
        self._push("activity_update", {"id": str(activity_id), "status": "pending"})
        return self.engine.start_activity(str(activity_id or ""))

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
                state = "enabled" if enabled else "disabled"
                activity_name = str(a.get("name") or activity_id)
                log_info(f"Activity {state} — {activity_name}")
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

    def set_activity_retries(self, activity_id: str, value) -> dict:
        """Runner-only retry count for one activity.

        This is a Runner setting: it overrides ``maxRetries`` in memory for the
        run and is saved to this Runner's own config — the workflow file is never
        touched. Returns ``{"ok", "retries"}``."""
        try:
            retries = max(1, int(float(value)))
        except (TypeError, ValueError):
            return {"ok": False, "retries": 1}
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                a["maxRetries"] = retries
                with self._runner_config_lock:
                    self._activity_runner_config(activity_id)["retries"] = retries
                    self._save_runner_config()
                return {"ok": True, "retries": retries}
        return {"ok": False, "retries": 1}

    def set_activity_var(self, activity_id: str, name: str, value) -> bool:
        """Override an activity variable's value (used at run time)."""
        for a in self.flow.get("activities", []) or []:
            if a.get("id") == activity_id:
                for v in a.get("vars", []) or []:
                    if v.get("name") == name:
                        if v.get("type") == "select":
                            options = v.get("options") or []
                            if v.get("display") == "toggle-group" and v.get("multiple"):
                                if not isinstance(value, list) or any(o not in options for o in value):
                                    return False
                                value = [o for o in options if o in value]
                            elif isinstance(value, list) or value not in options:
                                return False
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
        if self.engine.is_running() or param not in RUNTIME_PATH_PARAMS:
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

    # ── Project game path (Win32) ────────────────────────────────────────────

    def set_game_path(self, value: str) -> dict:
        """Override the project game path used by Launch program nodes set to
        "Project game path". An empty value restores the workflow's own path."""
        if self.engine.is_running() or not self.flow or self._controller() != "win32":
            return {"ok": False, "path": str((self.flow.get("win32") or {}).get("path") or "")}
        override = str(value or "").strip()
        effective = override or self._flow_game_path
        self.engine.set_win32_path(effective)   # also writes self.flow["win32"]["path"]
        with self._runner_config_lock:
            if override:
                self._runner_config["win32Path"] = override
            else:
                self._runner_config.pop("win32Path", None)
            self._save_runner_config()
        return {"ok": True, "path": effective, "requirements": self._requirements_payload(),
                "gamePath": self._game_path_status()}

    # ── Game requirements (files for the game's own folder) ──────────────────

    def _requirements_dir(self) -> str:
        """Folder holding the game requirements, or "" when there are none."""
        if is_frozen():
            folder = os.path.join(app_dir(), REQUIREMENTS_DIR)
        elif self.flow_path:
            folder = os.path.join(os.path.dirname(os.path.abspath(self.flow_path)), REQUIREMENTS_SRC)
        else:
            return ""
        return folder if self._requirement_files(folder) else ""

    @staticmethod
    def _requirement_files(folder: str) -> List[str]:
        """Relative paths of every shipped file under ``folder``."""
        found: List[str] = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name not in REQUIREMENTS_SKIP:
                    found.append(os.path.relpath(os.path.join(root, name), folder))
        return found

    def _game_dir(self) -> str:
        """Folder of the project game path (Settings → Game), if it exists."""
        path = str((self.flow.get("win32") or {}).get("path") or "").strip()
        folder = os.path.dirname(path) if path else ""
        return folder if folder and os.path.isdir(folder) else ""

    def _requirements_payload(self) -> dict:
        """``{}`` when this game ships no requirements; else what to copy and
        whether every file is already present in the game folder."""
        folder = self._requirements_dir()
        if not folder:
            return {}
        files = self._requirement_files(folder)
        game_dir = self._game_dir()
        missing = ([f for f in files if not os.path.exists(os.path.join(game_dir, f))]
                   if game_dir else files)
        items = sorted((n + (os.sep if os.path.isdir(os.path.join(folder, n)) else "")
                        for n in os.listdir(folder) if n not in REQUIREMENTS_SKIP), key=str.lower)
        return {"folder": folder, "items": items, "fileCount": len(files),
                "gameDir": game_dir, "missing": len(missing),
                "installed": bool(game_dir) and not missing}

    def open_requirements(self) -> bool:
        """Reveal the requirements folder in Explorer."""
        folder = self._requirements_dir()
        if not folder:
            return False
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
            return True
        except Exception as exc:
            log_warning(f"Couldn't open {folder}: {exc}")
            return False

    def copy_requirements_to_game(self) -> dict:
        """Copy the requirements into the game folder (merging, overwriting).

        Tries a normal copy first; if the folder refuses the write (Program
        Files and other protected locations), retries through an elevated
        robocopy, which raises one UAC prompt."""
        if self.engine.is_running():
            return {"ok": False, "error": "Stop the run first"}
        folder = self._requirements_dir()
        if not folder:
            return {"ok": False, "error": "This game has no required files"}
        game_dir = self._game_dir()
        if not game_dir:
            return {"ok": False, "error": "Choose the game's .exe in Settings → Game first"}

        elevated = False
        try:
            shutil.copytree(folder, game_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*REQUIREMENTS_SKIP))
        except (shutil.Error, OSError) as exc:
            detail = exc.args[0][0][2] if isinstance(exc, shutil.Error) and exc.args and exc.args[0] else exc
            log_warning(f"Normal copy blocked ({detail}) — retrying with admin rights")

        payload = self._requirements_payload()
        if not payload.get("installed"):
            # Nothing (or not everything) landed — do it as admin.
            log_info("Copying game files with administrator rights — confirm the UAC prompt…")
            if _copy_tree_elevated(folder, game_dir):
                elevated = True
            payload = self._requirements_payload()

        if payload.get("installed"):
            log_success(f"Copied game files into {game_dir} — restart the game to load them")
            return {"ok": True, "requirements": payload, "elevated": elevated}
        log_error(f"Couldn't copy game files into {game_dir}")
        return {"ok": False, "requirements": payload,
                "error": f"Couldn't copy into {game_dir} — close the game, or run the "
                         f"Runner as administrator and try again."}

    def pick_game_path(self, start: str = "") -> dict:
        """Choose the game .exe with the native picker, then save it."""
        if self.engine.is_running() or not self.flow:
            return {"ok": False, "path": ""}
        value = self._ask_path("file", start or self._flow_game_path,
                               ("Programs (*.exe;*.bat;*.cmd;*.com)", "All files (*.*)"))
        if not value:
            return {"ok": False, "path": ""}
        return self.set_game_path(value)

    # ── Shared emulator setting (ADB) ────────────────────────────────────────

    def set_emulator(self, kind: str, path: str) -> dict:
        """Override the shared emulator family + install folder used by emulator
        nodes on "Project emulator setting". Returns the effective setting."""
        if self.engine.is_running() or not self.flow or self._controller() == "win32":
            return {"ok": False, "emulator": dict(self.flow.get("emulator") or {})}
        kind = str(kind or "").strip().lower()
        if kind not in EMULATOR_KINDS:
            kind = str((self.flow.get("emulator") or {}).get("kind") or "ldplayer").strip().lower()
        if kind not in EMULATOR_KINDS:
            kind = "ldplayer"
        path = str(path or "").strip()
        self.engine.set_emulator_config(kind, path)
        with self._runner_config_lock:
            emu = self._runner_config.get("emulator")
            if not isinstance(emu, dict):
                emu = {}
                self._runner_config["emulator"] = emu
            emu["kind"] = kind
            emu["path"] = path
            self._save_runner_config()
        return {"ok": True, "emulator": {"kind": kind, "path": path},
                "emulatorDefault": self._flow_emulator}

    def pick_emulator_path(self, start: str = "") -> dict:
        """Choose the emulator install folder with the native picker, then save."""
        if self.engine.is_running() or not self.flow or self._controller() == "win32":
            return {"ok": False, "emulator": dict(self.flow.get("emulator") or {})}
        cur = dict(self.flow.get("emulator") or {})
        value = self._ask_path("folder", start or str(cur.get("path") or ""),
                               ("All files (*.*)",))
        if not value:
            return {"ok": False, "emulator": cur}
        return self.set_emulator(str(cur.get("kind") or ""), value)

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

    # ── Shared UI settings ───────────────────────────────────────────────────
    # Backed by the same file the Designer writes, so a theme or density picked
    # in any window is what every other window opens with. ``web/shared/
    # theme.js`` calls both of these.
    def get_settings(self) -> dict:
        return load_ui_settings()

    def save_settings(self, settings: dict) -> bool:
        return save_ui_settings(settings)

    # ── Live preview ─────────────────────────────────────────────────────────

    def _grab_frame(self):
        """One BGR frame from the active backend, or None when unavailable.

        ADB flows grab from the connected device; Win32 flows build/attach their
        window capture backend lazily (same path a run uses)."""
        try:
            auto = getattr(self.engine, "auto", None)
            if auto is None:
                return None
            if self._controller() == "win32":
                try:
                    from src.core.win32 import Win32GameAutomation
                    # Attach on the first frame, and keep retrying while no window
                    # is attached: the game is usually started *after* the app, so
                    # the window only becomes findable later. Throttled — a missing
                    # window must not re-enumerate (and re-log) at frame rate.
                    if (not isinstance(auto, Win32GameAutomation)
                            or not getattr(auto, "hwnd", None)):
                        now = time.time()
                        if now - self._win32_attach_at >= 2.0:
                            self._win32_attach_at = now
                            self.engine._ensure_ready_win32()
                        auto = self.engine.auto
                except Exception:
                    pass
                self._push_bridge_status()
            return auto.capture_screen()
        except Exception:
            return None

    def _push_bridge_status(self, force: bool = False) -> None:
        """Tell the page whether the in-game Unity Bridge answers.

        A ``unity_bridge`` workflow that can't reach its plugin silently falls
        back to ``anchored_touch``, which many Unity games ignore — the operator
        then sees "the window is there but nothing happens". Showing it in the
        footer (and logging it on attach) is what turns that into a one-glance
        diagnosis. Throttled; only for unity_bridge workflows."""
        if self._controller() != "win32":
            return
        cfg = (self.flow.get("win32") or {}) if self.flow else {}
        if str(cfg.get("inputMode") or "").strip().lower() != "unity_bridge":
            return
        now = time.time()
        if not force and now - self._bridge_status_at < 5.0:
            return
        self._bridge_status_at = now
        try:
            port = int(cfg.get("bridgePort") or 17820)
        except (TypeError, ValueError):
            port = 17820
        reply = ""
        try:
            from src.core.win32 import unity_bridge
            reply = unity_bridge.ping(port) or ""
        except Exception:
            reply = ""
        self._push("bridge_status", {"port": port, "ok": reply.startswith("ok"),
                                     "reply": reply})

    def _encode_frame(self, bgr) -> Optional[dict]:
        try:
            import cv2
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return None
            h, w = bgr.shape[:2]
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            return {"dataUrl": "data:image/jpeg;base64," + b64, "w": int(w), "h": int(h)}
        except Exception:
            return None

    def _push_frame(self, frame: Optional[dict]) -> None:
        if self._window is None or self._closing or not frame:
            return
        try:
            self._window.evaluate_js(
                'window.__recvFrame && window.__recvFrame("%s",%d,%d)'
                % (frame["dataUrl"], frame["w"], frame["h"]))
        except Exception:
            pass

    def capture_now(self) -> dict:
        """One synchronous frame for the Preview panel ({} when no frame)."""
        if self._window is None:
            return {}
        with self._capture_lock:
            img = self._grab_frame()
        return (self._encode_frame(img) if img is not None else None) or {}

    def capture(self) -> bool:
        """Fire-and-forget frame push, so the page never blocks on a capture."""
        if self._window is None or self._closing:
            return False
        threading.Thread(target=self._capture_once, daemon=True).start()
        return True

    def _capture_once(self) -> None:
        with self._capture_lock:
            img = self._grab_frame()
            frame = self._encode_frame(img) if img is not None else None
        self._push_frame(frame)

    def set_refresh_hz(self, hz: float) -> bool:
        try:
            self._refresh_hz = max(0.5, min(30.0, float(hz)))
        except (TypeError, ValueError):
            pass
        return True

    def set_auto_refresh(self, enabled: bool) -> bool:
        """Start/stop the preview frame loop. The page calls this when the
        Preview panel is shown or hidden, so nothing captures while it's shut."""
        self._auto_refresh_enabled = bool(enabled)
        if self._auto_refresh_enabled:
            if self._refresh_thread is None or not self._refresh_thread.is_alive():
                self._refresh_thread = threading.Thread(target=self._auto_refresh_loop, daemon=True)
                self._refresh_thread.start()
        return True

    def _auto_refresh_loop(self) -> None:
        while not self._closing and self._auto_refresh_enabled:
            start = time.time()
            self._capture_once()
            delay = (1.0 / max(0.5, self._refresh_hz)) - (time.time() - start)
            time.sleep(max(0.03, delay))

    # ── Devices ───────────────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        self._kick_device_scan()

    def select_device(self, serial: str) -> bool:
        if not self._adb_workflow():
            return False
        try:
            self._selected_serial = serial
            self.engine.auto.adb.device = None
            self.engine.auto.adb.device_id = serial
            self._connected_serial = None
            self.engine.set_selected_device(serial)
            threading.Thread(target=self._connect_device, args=(serial,), daemon=True).start()
            return True
        except Exception as e:
            log_error(f"Select device error: {e}")
            return False

    def _connect_device(self, serial: str) -> None:
        with self._device_lock:
            self._connect_device_locked(serial)

    def _connect_device_locked(self, serial: str) -> None:
        try:
            if serial != self._selected_serial:
                return
            self.engine.auto.adb.select_device(serial)
            self.engine.auto.adb.quick_refresh()
            if serial != self._selected_serial:
                return
            s = self.engine.auto.adb.get_status_summary()
            self._connected_serial = s.get("device_id") if s.get("connected") else None
            # The engine's "selected device" follows the live handle, not the
            # request: emulator nodes targeting `selected` must resolve to a
            # device that is actually connected.
            self.engine.set_selected_device(self._connected_serial or self._selected_serial)
            self._push("device_status", {
                "connected": bool(s.get("connected")),
                "serial": s.get("device_id"),
                "name": s.get("device_name") or serial,
            })
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _adb_workflow(self) -> bool:
        """True only when the loaded workflow drives a device over ADB.

        Everything below reaches the shared ADB server (``adb devices``, server
        start-up, emulator port scanning), so a Win32 project must not call any
        of it — that was the "why is my win32 game checking ADB" bug."""
        return self._controller() == "adb"

    def _ensure_adb_lease(self) -> None:
        """Claim this process as a live ADB client, once, on first need.

        Held so a sibling Macro2k app closing down doesn't ``kill-server`` out
        from under an in-flight ADB run. A Win32-only Runner never calls this,
        so it neither blocks nor triggers that teardown (see lifecycle)."""
        if self._adb_lease:
            return
        self._adb_lease = lifecycle.acquire_adb_lease("runner")

    def _kick_device_scan(self) -> None:
        """One device scan in the background, ADB workflows only."""
        if self._adb_workflow():
            self._ensure_adb_lease()
            threading.Thread(target=self._device_worker, args=(True,), daemon=True).start()
        else:
            # Clear any device state left over from an ADB project so the UI
            # doesn't keep a stale "Connecting…" around.
            self._selected_serial = None
            self._connected_serial = None
            self._push("devices_update", {"devices": [], "connected": False,
                                          "serial": None, "name": ""})

    def _device_worker(self, force_scan: bool = False) -> None:
        # The one place ADB is actually reached — hold the lease for as long as
        # that's true, however this got called.
        self._ensure_adb_lease()
        adb = self.engine.auto.adb
        with self._device_lock:
            try:
                if force_scan:
                    try:
                        adb.scan_all_devices()
                    except Exception as exc:
                        log_warning(f"ADB port scan failed: {exc}")
                devices = adb.list_devices(include_app=False) or []
                if devices and not self._selected_serial:
                    first = devices[0].get("serial")
                    if first:
                        self._selected_serial = first
                        adb.device_id = first
                        adb.select_device(first)
                elif devices and self._selected_serial:
                    if adb.device is None or adb.device_id != self._selected_serial:
                        adb.select_device(self._selected_serial)
                adb.quick_refresh()
                s = adb.get_status_summary(include_app=False)
                self._connected_serial = s.get("device_id") if s.get("connected") else None
                self.engine.set_selected_device(self._connected_serial or self._selected_serial)
                self._push("devices_update", {
                    "devices": devices,
                    "connected": bool(s.get("connected")),
                    "serial": s.get("device_id"),
                    "name": s.get("device_name") or s.get("device_id") or "",
                })
            except Exception as exc:
                log_warning(f"ADB device refresh failed: {exc}")
                adb.mark_disconnected("device refresh failed")
                self._connected_serial = None
                self.engine.set_selected_device(self._selected_serial)
                self._push("devices_update", {"devices": [], "connected": False,
                                              "serial": None, "name": ""})

    def _device_poll(self) -> None:
        while not self._closing:
            time.sleep(5)
            if not self._closing and self._adb_workflow():
                now = time.monotonic()
                deep = now - self._last_deep_scan >= self._deep_scan_interval
                if deep:
                    self._last_deep_scan = now
                self._device_worker(force_scan=deep)

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
        # A standalone Runner is titled after its game and its own version.
        info = runner_update.build_info()
        title = (f"{info.get('name') or info.get('appName')} {info['version']}"
                 if info.get("version") else titled("Macro2k Runner"))
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
