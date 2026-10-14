"""PyWebView-based Workflow Designer for ADB auto-game.

Standalone app for building automation **workflows** as node graphs and
test-running them. Drag nodes from the palette, wire them (loose-connect /
Ctrl-stack), group them into sequence/background activities and reusable
functions, then export to JSON or hit **Run test** against a connected device.

The actual execution is delegated to :class:`src.workflow.WorkflowEngine`, so a
flow behaves identically here and in the standalone runner GUI.

Run::

    python apps/workflow_designer.py

Flows save under ``workflows/`` by default.
"""
from __future__ import annotations

import datetime
import os
import sys
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

# --- bootstrap: make `src.*` importable when run from apps/ ---------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
_APPS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (_PROJECT_ROOT, _APPS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import webview

from src.core.adb import ADBController, DeviceScanner, lifecycle
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    get_capture_backend,
    set_capture_backend,
    stop_scrcpy_sources,
)
from src.core.adb.input import (
    INPUT_BACKENDS as ADB_INPUT_BACKENDS,
    get_input_backend as get_adb_input_backend,
    set_input_backend as set_adb_input_backend,
)
from src.core.adb.auto.ocr import KNOWN_BACKENDS, OCR_MODEL_LABELS, OCRReader
from src.core.adb.auto.template_matcher import TemplateMatcher
from src.core.frida_speedhack import FridaSpeedhackManager
from src.workflow import WorkflowEngine
from src.utils import (
    add_log_subscriber,
    file_url,
    push_webview_event,
    remove_log_subscriber,
    theme_background,
    titled,
    webview_storage_path,
)

from designer.build import BuildMixin
from designer.common import (  # noqa: F401 - re-exported for callers and tests
    _PROJECT_ROOT,
    _RUN_TMP_DIR,
    _TEMPLATES_DIRNAME,
    _WEB_DIR,
    _WORKFLOWS_DIR,
    _sanitize_name,
)
from designer.devices import DeviceMixin
from designer.library import LibraryMixin
from designer.preview import PreviewMixin
from designer.project import ProjectMixin
from designer.runs import RunMixin
from designer.speedhack import SpeedhackMixin
from designer.templates import (  # noqa: F401 - re-exported for callers and tests
    _norm_tpl,
    build_template_index,
    group_duplicate_items,
    iter_owners,
    iter_template_refs,
)


class WorkflowDesignerAPI(PreviewMixin, DeviceMixin, LibraryMixin, ProjectMixin,
                          RunMixin, SpeedhackMixin, BuildMixin):
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        # Register as a live ADB client so a sibling closing down doesn't kill
        # the shared ADB server out from under us (see src/core/adb/lifecycle).
        lifecycle.acquire_adb_lease("designer")
        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()

        self._engine: Optional[WorkflowEngine] = None
        self._wf_path: Optional[str] = None
        self._last_dir: Optional[str] = None
        # Folder the Library tab last listed. Held so the file actions that
        # follow a listing (thumbnail, delete, rename) act on the folder that
        # listing came from, not on whatever the app happens to be scoped to now.
        self._library_out_dir: str = ""
        # When launched from the Hub with a path, prefer this over lastWorkflow.
        self._pending_load: Optional[str] = None

        self._window: Optional[webview.Window] = None
        self._closing = False
        self._log_buffer: List[Dict] = []

        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None
        # Periodically deep-scan emulator ports so additional instances are
        # discovered even while another emulator remains connected.
        self._last_deep_scan = 0.0
        self._deep_scan_interval = 30.0

        # Capture source for the Preview tab: "adb" (self.controller) or "win32"
        # (a native window via Win32Controller). Kept in sync from the designer UI
        # so preview/crop/inspect capture from whatever the project targets.
        self._capture_kind = "adb"
        self._win32 = None  # lazily-built Win32Controller

        # Live Preview tab state (mirrors DevScope). Auto-refresh defaults OFF so
        # no capture work happens until the user opens the Preview tab.
        self._screen: Optional[np.ndarray] = None
        self._screen_w = 0
        self._screen_h = 0
        self._capture_lock = threading.Lock()
        self._capture_in_flight = False
        self._auto_refresh_enabled = False
        self._refresh_hz = 30.0
        self._last_auto_capture = 0.0
        # After a device-gone failure we stop live capture and announce once;
        # cleared on reconnect / when Preview auto-refresh is turned back on.
        self._device_lost_announced = False

        # DevScope-style tool state shared with the Preview tab's tool panel:
        # the last picked point / drag region / template-match overlay, plus the
        # OCR + matcher backends. Crops land in the open workflow's templates
        # folder so they're immediately usable as node templates.
        self._ocr_reader: Optional[OCRReader] = None
        self._matcher = TemplateMatcher(cache_size=64)
        self._last_point: Optional[Tuple[int, int]] = None
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._overlay: List[Tuple[int, int, int, int, float]] = []
        self._scope_out_dir: Optional[str] = None
        self._info_lock = threading.Lock()
        self._info_in_flight = False

        # Standalone speed hack — fully decoupled from the test run. The designer's
        # "Run test" never injects Frida; speedhack is its own manual ▶ action, so
        # it owns its own manager/retry-thread rather than riding the engine run.
        self._sh_mgr: Optional[FridaSpeedhackManager] = None
        self._sh_stop: Optional[threading.Event] = None

        # "Start game" runs on its own worker (emulator boot can take minutes);
        # the flag keeps a second click from starting a parallel boot.
        self._game_launching = False

    # ── Setup ────────────────────────────────────────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log, with_meta=True)
        threading.Thread(target=self._device_worker, daemon=True).start()
        threading.Thread(target=self._device_poll, daemon=True).start()
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()

    # ── Log + push ───────────────────────────────────────────────────────────

    def _on_log(self, level: str, message: str, meta: Optional[dict] = None) -> None:
        bucket = {"info": "info", "success": "success",
                  "warning": "warning", "error": "error"}.get(level, "info")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        # The Designer keeps every line, engine detail included (the Runner
        # shows only milestones). Each starts with the activity that logged it,
        # or [Designer] for the app's own messages.
        meta = meta or {}
        scope = meta.get("activity") or "Designer"
        entry = {"ts": ts, "level": bucket, "scope": scope, "text": message,
                 "kind": meta.get("kind") or "app", "msg": f"[{scope}] {message}"}
        # The graph block that logged this, when the engine knows it — the log
        # panel uses it to offer "jump to this block" on the line itself.
        node = meta.get("node")
        if node:
            entry["node"] = node
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

    def get_state(self) -> dict:
        return {
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
            "captureBackend": get_capture_backend(),
            "captureBackends": list(CAPTURE_BACKENDS),
            "inputBackend": get_adb_input_backend(),
            "inputBackends": list(ADB_INPUT_BACKENDS),
            "ocrBackends": list(KNOWN_BACKENDS),
            "ocrModels": [
                {"id": model, "label": OCR_MODEL_LABELS[model]}
                for model in KNOWN_BACKENDS
            ],
            "outDir": self._scope_out_dir or "",
            "log": self._log_buffer[-300:],
        }

    def set_capture_backend(self, backend: str) -> dict:
        selected = set_capture_backend(backend)
        self._push("capture_backend", {"backend": selected})
        # Switching backends stops all scrcpy sources — re-warm right away so
        # the next run doesn't pay the client warm-up again.
        if selected == "scrcpy":
            self._warm_capture_async()
        return {"backend": selected, "backends": list(CAPTURE_BACKENDS)}

    def set_input_backend(self, backend: str) -> dict:
        """Select the ADB input transport (shell "adb" vs "scrcpy" control)."""
        selected = set_adb_input_backend(backend)
        self._push("input_backend", {"backend": selected})
        return {"backend": selected, "backends": list(ADB_INPUT_BACKENDS)}

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        self._stop_test_hotkeys()
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
        stop_scrcpy_sources()
        # Only stop the shared ADB server when no sibling Macro2k process
        # (Runner / DevScope / Hub) still holds a lease.
        lifecycle.release_adb_and_kill_if_last("designer")
        remove_log_subscriber(self._on_log)


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_designer_window(
    title: str = titled(),
    auto_load: Optional[str] = None,
) -> webview.Window:
    api = WorkflowDesignerAPI()
    if auto_load and os.path.isfile(auto_load):
        api._pending_load = os.path.abspath(auto_load)
    html_path = os.path.join(_WEB_DIR, "wf", "index.html")
    url = file_url(html_path)
    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=1480,
        height=920,
        resizable=True,
        min_size=(1080, 720),
        background_color=theme_background(),
    )
    window.events.loaded += lambda: api._attach(window)
    window.events.closed += lambda: api._close()
    return window


def _enable_windows_dpi_awareness() -> None:
    """Ask Windows for per-monitor DPI awareness before the window is created.

    Without this, WebView2 is often bitmap-scaled by the OS (especially on
    125%/150% display scaling) and the whole canvas reads as a permanent soft
    blur layer — focus/hover does not clear it.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE (Windows 8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def run(auto_load: Optional[str] = None) -> None:
    """Open the Designer. Optional *auto_load* is a workflow JSON path to open."""
    _enable_windows_dpi_awareness()
    create_workflow_designer_window(auto_load=auto_load)
    # Own WebView2 profile so Hub/Runner can stay open at the same time.
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=webview_storage_path("designer"),
    )


if __name__ == "__main__":
    # Optional path from the Hub: ``python apps/workflow_designer.py path.json``
    auto = sys.argv[1] if len(sys.argv) > 1 else None
    run(auto)
