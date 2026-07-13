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
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# --- bootstrap: make `src.*` importable when run from apps/ ---------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import webview

from src.core.adb import ADBController, DeviceScanner
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    capture_screen as capture_screen_frame,
    get_capture_backend,
    set_capture_backend,
    stop_scrcpy_sources,
    warm_scrcpy_source,
)
from src.core.adb.auto.ocr import KNOWN_BACKENDS, OCRReader
from src.core.adb.auto.template_matcher import TemplateMatcher
from src.core.frida_speedhack import FridaSpeedhackManager
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

# Bundled HTML: ``apps/web`` from source, ``<_MEIPASS>/web`` when frozen.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
# Default home for saved workflows. Each workflow lives in its own subfolder
# ``workflows/<name>/<name>.json`` (with its ``templates/`` bundle alongside),
# next to the .exe in a frozen build or in the repo root from source.
_WORKFLOWS_DIR = os.path.join(_PROJECT_ROOT, "workflows")
# Transient flow written for the "Run GUI" handoff to the runner.
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


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _shell(device, cmd: str) -> str:
    try:
        return (device.shell(cmd) or "").strip()
    except Exception:
        return ""


def _safe_detect_app(device) -> Optional[str]:
    try:
        from src.core.adb.controller import _detect_current_app
        return _detect_current_app(device)
    except Exception:
        return None


# Properties fetched for the device info panel (mirrors DevScope).
_DEVICE_INFO_PROPS = (
    "ro.product.model",
    "ro.product.manufacturer",
    "ro.product.brand",
    "ro.product.device",
    "ro.product.cpu.abi",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.build.version.security_patch",
    "ro.build.display.id",
    "ro.serialno",
)


class WorkflowDesignerAPI:
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    def __init__(self) -> None:
        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()

        self._engine: Optional[WorkflowEngine] = None
        self._wf_path: Optional[str] = None
        self._last_dir: Optional[str] = None
        # When launched from the Hub with a path, prefer this over lastWorkflow.
        self._pending_load: Optional[str] = None

        self._window: Optional[webview.Window] = None
        self._closing = False
        self._log_buffer: List[Dict] = []

        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None
        # When no device is listed, periodically deep-scan emulator ports so a
        # freshly-booted instance is picked up without a manual "Scan ports".
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

    # ── Setup ────────────────────────────────────────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log)
        threading.Thread(target=self._device_worker, daemon=True).start()
        threading.Thread(target=self._device_poll, daemon=True).start()
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()

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
            "captureBackend": get_capture_backend(),
            "captureBackends": list(CAPTURE_BACKENDS),
            "ocrBackends": list(KNOWN_BACKENDS),
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

    # ── Live Preview capture (mirrors DevScope) ─────────────────────────────
    # Only the Preview tab drives these; auto-refresh is OFF by default and the
    # JS side turns it on/off when the tab is shown/hidden, so captures only run
    # while the user is actually looking at the mirror.

    def _push_frame(self, bgr: np.ndarray) -> None:
        """Send a JPEG screenshot frame to JS as a data URL.

        Always report the frame's own width/height so the Preview box uses the
        real capture size (ADB screencap native resolution), not a stale value.
        """
        if self._window is None or self._closing:
            return
        try:
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                return
            h, w = bgr.shape[:2]
            self._screen_w = int(w)
            self._screen_h = int(h)
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            self._window.evaluate_js(
                f'window.__recvFrame("data:image/jpeg;base64,{b64}",{w},{h})')
        except Exception:
            pass

    def set_capture_source(self, kind: str = "adb", cfg: Optional[dict] = None) -> bool:
        """Point the Preview tab's capture at ADB or a Win32 window.

        Called from the designer whenever the project's controller / target
        window changes, so preview + crop + colour-inspect all grab from the
        same source the workflow will run against."""
        self._capture_kind = "win32" if str(kind) == "win32" else "adb"
        if self._capture_kind == "win32":
            try:
                from src.core.win32 import Win32Controller
                if self._win32 is None:
                    self._win32 = Win32Controller(cfg or {})
                else:
                    self._win32.configure(cfg or {})
            except Exception as exc:
                log_warning(f"Win32 capture source error: {exc}")
                return False
        return True

    def capture(self) -> bool:
        if self._capture_kind == "win32":
            if self._win32 is None:
                self._push("capture_failed", {"error": "No Win32 window set"})
                return False
        elif self.controller.device is None:
            # Device already gone — stop the live preview loop quietly. Do not
            # push capture_failed every tick (that was flooding the UI/log).
            if self._auto_refresh_enabled:
                self._on_device_lost("No device selected")
            return False
        with self._capture_lock:
            if self._capture_in_flight:
                return False
            self._capture_in_flight = True
        threading.Thread(target=self._capture_worker, daemon=True).start()
        return True

    def _on_device_lost(self, reason: str = "") -> None:
        """Stop live capture and tell the UI the device is gone — once."""
        if getattr(self, "_device_lost_announced", False) and not self._auto_refresh_enabled:
            # Already stopped + announced; stay quiet until a reconnect.
            return
        self._device_lost_announced = True
        was_refreshing = self._auto_refresh_enabled
        self._auto_refresh_enabled = False
        # Drop the stale ADB handle if capture hasn't already.
        try:
            self.controller.mark_disconnected(reason)
        except Exception:
            self.controller.device = None
        self._connected_serial = None
        try:
            stop_scrcpy_sources()
        except Exception:
            pass
        msg = reason or "Device not found"
        log_warning(f"Preview stopped — device lost: {msg}")
        self._push("device_status", {"connected": False, "serial": None, "name": ""})
        if was_refreshing:
            self._push("capture_failed", {"error": f"Device disconnected — capture stopped ({msg})"})

    def _capture_worker(self) -> None:
        try:
            if self._capture_kind == "win32":
                if not self._win32.device:
                    self._win32.attach()
                if not self._win32.device:
                    self._push("capture_failed", {"error": "Target Win32 window not found"})
                    return
                img = self._win32.capture_frame()
            else:
                img = capture_screen_frame(self.controller)
                # Capture path cleared the handle on "device not found" — stop
                # the preview loop so we don't keep spawning workers.
                if img is None and self.controller.device is None:
                    self._on_device_lost("device not found")
                    return
            if img is None:
                self._push("capture_failed", {"error": "Failed to capture screen"})
                return
            # Successful frame — allow a future disconnect to re-announce.
            self._device_lost_announced = False
            h, w = img.shape[:2]
            self._screen = img
            self._screen_w = w
            self._screen_h = h
            self._push_frame(img)
        except Exception as exc:
            if self._capture_kind != "win32" and (
                self.controller.device is None
                or ADBController.is_device_gone_error(exc)
            ):
                try:
                    self.controller.mark_disconnected(str(exc))
                except Exception:
                    self.controller.device = None
                self._on_device_lost(str(exc))
                return
            self._push("capture_failed", {"error": str(exc)})
        finally:
            with self._capture_lock:
                self._capture_in_flight = False

    def _auto_refresh_loop(self) -> None:
        while not self._closing:
            time.sleep(0.1)
            if not self._auto_refresh_enabled or self._closing:
                continue
            # Bail early when ADB already dropped the device (e.g. another
            # thread marked it disconnected mid-run).
            if self._capture_kind != "win32" and self.controller.device is None:
                self._on_device_lost("No device selected")
                continue
            now = time.monotonic()
            period = 1.0 / max(0.1, self._refresh_hz)
            if now - self._last_auto_capture >= period:
                self._last_auto_capture = now
                self.capture()

    def set_auto_refresh(self, enabled: bool) -> bool:
        self._auto_refresh_enabled = bool(enabled)
        self._last_auto_capture = time.monotonic()
        if enabled:
            # Fresh Preview session — allow disconnect messaging again.
            self._device_lost_announced = False
        return True

    def set_refresh_hz(self, hz: float) -> bool:
        self._refresh_hz = max(0.2, min(30.0, float(hz)))
        return True

    def tap(self, x: int, y: int) -> bool:
        # Preview right-click tap goes to whatever the preview captures from:
        # the Win32 target window in a Win32 project, else the ADB device.
        if self._capture_kind == "win32":
            if self._win32 is None:
                return False
            if not self._win32.device:
                self._win32.attach()
            if not self._win32.device:
                return False
            return bool(self._win32.tap(int(x), int(y)))
        if self.controller.device is None:
            return False
        return bool(self.controller.tap(int(x), int(y)))

    # ── Scope toolset: selection / color / crop / OCR / match / actions ──────
    # Mirrors DevScope's DevHelperAPI so the Preview tab doubles as a region
    # picker + action tester. Crops land in the open workflow's ``templates/``
    # folder (resolved on demand) so they're picked up by image nodes directly.

    def _scope_out(self) -> str:
        """Resolve (and cache) the folder where preview crops/screenshots save.

        Falls back to the project ``out/`` dir when no workflow context exists.
        """
        if self._scope_out_dir and os.path.isdir(self._scope_out_dir):
            return self._scope_out_dir
        try:
            dest = self._workflow_templates_dir("")
        except Exception:
            dest = None
        if not dest:
            dest = os.path.join(_PROJECT_ROOT, "out")
        os.makedirs(dest, exist_ok=True)
        self._scope_out_dir = dest
        return dest

    def _scope_refresh_out(self) -> None:
        """Drop the cached output dir so the next crop re-resolves (e.g. after
        a save-as moved the workflow into a new folder)."""
        self._scope_out_dir = None

    def scope_out_dir(self) -> str:
        """Resolve (lazily) and announce the folder where preview crops save.

        Called by JS when entering the Preview tab so the Vùng chọn / Thư viện
        labels reflect the current workflow's templates folder.
        """
        path = self._scope_out()
        self._push("out_dir", {"path": path})
        return path

    def set_point(self, x: int, y: int) -> dict:
        self._last_point = (int(x), int(y))
        self._region = None
        color = self._pixel_color(int(x), int(y))
        return {"x": int(x), "y": int(y), **color}

    def set_region(self, x: int, y: int, w: int, h: int) -> dict:
        self._region = (int(x), int(y), int(w), int(h))
        self._last_point = None
        cx = int(x) + int(w) // 2
        cy = int(y) + int(h) // 2
        color = self._pixel_color(cx, cy)
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                "centerX": cx, "centerY": cy, **color}

    def _pixel_color(self, x: int, y: int) -> dict:
        img = self._screen
        if img is None or not (0 <= y < self._screen_h and 0 <= x < self._screen_w):
            return {"hex": "", "rgb": ""}
        b, g, r = img[y, x][:3]
        r, g, b = int(r), int(g), int(b)
        return {"hex": f"#{r:02X}{g:02X}{b:02X}", "rgb": f"{r}, {g}, {b}"}

    def clear_selection(self) -> bool:
        self._region = None
        self._last_point = None
        self._overlay = []
        self._push("selection_cleared", {})
        return True

    def check_color(self, x: int, y: int, hex_color: str, tolerance: int = 10) -> dict:
        if self._screen is None:
            return {"match": False, "error": "No screenshot"}
        x, y, tolerance = int(x), int(y), int(tolerance)
        if not (0 <= y < self._screen_h and 0 <= x < self._screen_w):
            return {"match": False, "error": "Out of bounds"}
        b, g, r = self._screen[y, x][:3]
        r, g, b = int(r), int(g), int(b)
        actual_hex = f"#{r:02X}{g:02X}{b:02X}"
        target = hex_color.lstrip("#")
        if len(target) != 6:
            return {"match": False, "error": "Invalid hex"}
        try:
            tr = int(target[0:2], 16)
            tg = int(target[2:4], 16)
            tb = int(target[4:6], 16)
        except ValueError:
            return {"match": False, "error": "Invalid hex"}
        dist = max(abs(r - tr), abs(g - tg), abs(b - tb))
        return {"match": dist <= tolerance, "actual": actual_hex,
                "dist": dist, "actual_rgb": f"{r}, {g}, {b}"}

    def swipe(self, x1: int, y1: int, x2: int, y2: int, dur: int) -> bool:
        # Like tap(): route to whatever the preview captures from (Win32 window
        # in a Win32 project, else the ADB device) so right-drag swipes work in
        # both project kinds.
        if self._capture_kind == "win32":
            if self._win32 is None:
                return False
            if not self._win32.device:
                self._win32.attach()
            if not self._win32.device:
                return False
            return bool(self._win32.swipe(int(x1), int(y1), int(x2), int(y2), int(dur)))
        if self.controller.device is None:
            return False
        return bool(self.controller.swipe(int(x1), int(y1), int(x2), int(y2), int(dur)))

    def long_press(self, x: int, y: int, duration: int = 800) -> bool:
        if self.controller.device is None:
            return False
        try:
            self.controller.device.shell(
                f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration)}")
            return True
        except Exception:
            return False

    def send_key(self, keycode) -> bool:
        if self.controller.device is None:
            return False
        try:
            self.controller.device.shell(f"input keyevent {keycode}")
            return True
        except Exception:
            return False

    def input_text(self, text: str) -> bool:
        if self.controller.device is None or not text:
            return False
        try:
            safe = (text.replace("\\", "\\\\").replace('"', '\\"')
                    .replace("$", "\\$").replace("`", "\\`").replace(" ", "%s"))
            self.controller.device.shell(f'input text "{safe}"')
            return True
        except Exception:
            return False

    # ── Crop / save ───────────────────────────────────────────────────────────

    def save_full(self, name: str = "") -> bool:
        if self._screen is None:
            return False
        out_dir = self._scope_out()
        clean = _sanitize_name(name)
        fname = (f"{clean}_{_ts()}.png" if clean else f"screenshot_{_ts()}.png")
        path = os.path.join(out_dir, fname)
        return bool(cv2.imwrite(path, self._screen))

    def _ensure_region_in_filename(self, path: str, x, y, w, h) -> str:
        base, ext = os.path.splitext(path)
        suffix = f"_{x}_{y}_{w}_{h}"
        if re.search(r"_\d+_\d+_\d+_\d+(?:\.\d+)?$", base):
            return path
        return f"{base}{suffix}{ext}"

    def save_crop_dialog(self, name: str = "") -> bool:
        region = self._region
        if self._screen is None or not region:
            return False
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        clean = _sanitize_name(name)
        default = (f"{clean}_{x}_{y}_{w}_{h}.png" if clean
                   else f"region_{_ts()}_{x}_{y}_{w}_{h}.png")
        out_dir = self._scope_out()
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=out_dir, save_filename=default,
                    file_types=("PNG (*.png)", "JPEG (*.jpg;*.jpeg)", "All files (*.*)"))
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception:
            path = None
        if not path:
            path = os.path.join(out_dir, default)
        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        path = self._ensure_region_in_filename(path, x, y, w, h)
        return bool(cv2.imwrite(path, crop))

    def quick_crop(self, name: str = "") -> str:
        """Save the current region crop into the open workflow's templates folder.

        Always lands in the resolved workflow ``templates/`` dir (e.g.
        ``workflows/Cherry_Tale/templates/``) so the crop is immediately usable as
        a node template. Returns the saved path; "" on failure (no screen/region).
        """
        region = self._region
        if self._screen is None or not region:
            return ""
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        out_dir = self._scope_out()
        clean = _sanitize_name(name)
        if clean:
            fname = f"{clean}_{x}_{y}_{w}_{h}.png"
            if os.path.exists(os.path.join(out_dir, fname)):
                fname = f"{clean}_{_ts()}_{x}_{y}_{w}_{h}.png"
        else:
            fname = f"crop_{_ts()}_{x}_{y}_{w}_{h}.png"
        path = os.path.join(out_dir, fname)
        if cv2.imwrite(path, crop):
            log_success(f"Region captured: {path}")
            return path
        return ""

    def pick_out_dir(self) -> str:
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.FOLDER_DIALOG, directory=self._scope_out())
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
                    if path and os.path.isdir(str(path)):
                        self._scope_out_dir = str(path)
                        self._push("out_dir", {"path": self._scope_out_dir})
        except Exception:
            pass
        return self._scope_out()

    def pick_folder(self, start: str = "") -> str:
        """Open a folder-picker dialog and return the chosen directory (or "").

        Used by the ``launch_emulator`` node's path field to browse to an
        emulator install folder. Opens at ``start`` when it is a real directory.
        """
        win = self._win()
        if win is None:
            return ""
        start_dir = start if start and os.path.isdir(start) else ""
        try:
            paths = win.create_file_dialog(webview.FOLDER_DIALOG, directory=start_dir)
        except Exception as exc:
            log_warning(f"Dialog error: {exc}")
            return ""
        if not paths:
            return ""
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        return str(path)

    def list_windows(self) -> list:
        """List visible top-level windows as ``[{title, cls, pid}]`` for the
        Win32 window picker in the designer. Returns [] if pywin32 is
        unavailable."""
        try:
            import win32gui
            import win32process
        except Exception:
            return []
        out: List[dict] = []
        seen: set = set()

        def _cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = (win32gui.GetWindowText(hwnd) or "").strip()
                if not title:
                    return
                cls = win32gui.GetClassName(hwnd) or ""
                try:
                    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                except Exception:
                    pid = 0
                key = (title, cls, pid)
                if key in seen:
                    return
                seen.add(key)
                out.append({"title": title, "cls": cls, "pid": int(pid)})
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            pass
        out.sort(key=lambda w: w["title"].lower())
        return out

    # ── Template matching ─────────────────────────────────────────────────────

    def pick_template(self) -> str:
        """Open a file dialog to pick a template image.

        Always opens in the current workflow's ``templates/`` folder first —
        that's where image-node templates belong, so it should be the default
        every time, not whatever folder the last dialog landed in. Falls back to
        the project ``out/`` dir if no workflow context exists.
        """
        win = self._win()
        if win is None:
            return ""
        # Resolve the workflow's templates dir (NOT via _start_dir — that would
        # honour a stale remembered dir and miss the templates folder).
        try:
            start_dir = self._scope_out()
        except Exception:
            start_dir = ""
        if not start_dir or not os.path.isdir(start_dir):
            start_dir = os.path.join(_PROJECT_ROOT, "out")
            os.makedirs(start_dir, exist_ok=True)
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
        return str(path)

    def match_template(self, template_path: str, threshold: float,
                       grayscale: bool, multiscale: bool, all_matches: bool) -> dict:
        if self._screen is None:
            return {"error": "Capture a screenshot first"}
        path = (template_path or "").strip()
        if not path or not os.path.exists(path):
            return {"error": "Pick a valid template path"}
        grayscale = bool(grayscale)
        threshold = float(threshold)
        tpl = self._matcher.load(path, grayscale=grayscale)
        if tpl is None:
            return {"error": "Could not load template"}
        th, tw = tpl.shape[:2]
        rects: List[List[float]] = []
        if all_matches:
            results = self._matcher.match_all(
                self._screen, tpl, threshold=threshold, use_grayscale=grayscale)
            for cx, cy, conf in results:
                rects.append([max(0, cx - tw // 2), max(0, cy - th // 2), tw, th, float(conf)])
            summary = f"Found {len(results)} match(es)."
        else:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2] if multiscale else None
            res = self._matcher.match(
                self._screen, tpl, threshold=threshold, use_grayscale=grayscale,
                multi_scale=multiscale, scales=scales)
            if res is None:
                self._overlay = []
                self._push("overlay", {"rects": []})
                return {"summary": f"No match >= {threshold:.2f}.", "rects": []}
            cx, cy, conf, scale = res
            sw, sh = int(tw * scale), int(th * scale)
            rects.append([max(0, cx - sw // 2), max(0, cy - sh // 2), sw, sh, float(conf)])
            summary = f"Match: center=({cx},{cy}) conf={conf:.3f} scale={scale:.2f}"
        self._overlay = [(r[0], r[1], r[2], r[3], r[4]) for r in rects]
        self._push("overlay", {"rects": rects})
        return {"summary": summary, "rects": rects}

    def clear_overlay(self) -> bool:
        self._overlay = []
        self._push("overlay", {"rects": []})
        return True

    # ── OCR ───────────────────────────────────────────────────────────────────

    def set_ocr_backend(self, name: str) -> dict:
        try:
            if self._ocr_reader is None:
                self._ocr_reader = OCRReader(backend=name)
            else:
                self._ocr_reader.set_backend(name)
            engine = self._ocr_reader.backend_name
            available = bool(self._ocr_reader.available)
            return {"engine": engine if engine != "none" else "n/a", "available": available}
        except Exception as exc:
            return {"engine": "n/a", "available": False}

    def read_text(self, whitelist: str = "") -> str:
        if self._screen is None:
            return ""
        region = self._region
        if not region:
            return ""
        if self._ocr_reader is None:
            self._ocr_reader = OCRReader(backend=KNOWN_BACKENDS[0])
        if not self._ocr_reader.available:
            return ""
        wl = (whitelist or "").strip() or None
        return self._ocr_reader.read_text(self._screen, region=region, whitelist=wl) or ""

    # ── Asset library ─────────────────────────────────────────────────────────

    def list_assets(self) -> list:
        out_dir = self._scope_out()
        if not os.path.exists(out_dir):
            return []
        exts = (".png", ".jpg", ".jpeg", ".bmp")
        items = []
        for root, _dirs, files in os.walk(out_dir):
            for fname in files:
                if not fname.lower().endswith(exts):
                    continue
                path = os.path.join(root, fname)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                rel = os.path.relpath(path, out_dir).replace("\\", "/")
                items.append({"name": rel, "path": path.replace("\\", "/"),
                              "size": st.st_size})
        items.sort(key=lambda it: it.get("size", 0), reverse=True)
        return items[:200]

    def get_asset_thumbnail(self, path: str) -> str:
        try:
            img = cv2.imread(path)
            if img is None:
                return ""
            h, w = img.shape[:2]
            tw = 96
            th = max(1, int(h * tw / w))
            thumb = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return ""
            return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception:
            return ""

    def delete_asset(self, path: str) -> bool:
        try:
            from pathlib import Path
            p = Path(path)
            if p.exists() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
                p.unlink()
                return True
        except Exception:
            pass
        return False

    # ── Device info (mirrors DevScope) ────────────────────────────────────────

    def refresh_info(self) -> None:
        threading.Thread(target=self._info_worker, daemon=True).start()

    def _info_worker(self) -> None:
        with self._info_lock:
            if self._info_in_flight:
                return
            self._info_in_flight = True
        try:
            device = self.controller.device
            if device is None:
                self._push("device_info", {
                    "status": "Disconnected", "serial": "-", "model": "-",
                    "brand": "-", "android": "-", "abi": "-", "screen_size": "-",
                    "density": "-", "app": "-", "battery": "-", "ip": "-", "uptime": "-"})
                return
            info: Dict[str, Any] = {"serial": device.serial, "status": "Connected"}
            cmd = " ; ".join(f"getprop {p}" for p in _DEVICE_INFO_PROPS)
            values = [v.strip() for v in _shell(device, cmd).splitlines()]
            while len(values) < len(_DEVICE_INFO_PROPS):
                values.append("")
            for key, val in zip(_DEVICE_INFO_PROPS, values):
                info[key] = val or "-"
            size_str = "-"
            for line in _shell(device, "wm size").splitlines():
                if ":" in line:
                    size_str = line.split(":", 1)[1].strip()
                    break
            info["screen_size"] = size_str or "-"
            density_str = "-"
            for line in _shell(device, "wm density").splitlines():
                if ":" in line:
                    density_str = line.split(":", 1)[1].strip()
                    break
            info["screen_density"] = density_str or "-"
            batt = {"level": "-", "status": "-", "temperature": "-",
                    "AC powered": "-", "USB powered": "-"}
            for line in _shell(device, "dumpsys battery").splitlines():
                line = line.strip()
                for key in list(batt.keys()):
                    if line.startswith(f"{key}:"):
                        batt[key] = line[len(key) + 1:].strip()
            status_map = {"1": "Unknown", "2": "Charging", "3": "Discharging",
                          "4": "Not charging", "5": "Full"}
            status_text = status_map.get(batt["status"], batt["status"])
            temp_c = "-"
            try:
                temp_c = f"{int(batt['temperature']) / 10:.1f}C"
            except (TypeError, ValueError):
                pass
            powered = []
            if batt["AC powered"].lower() == "true":
                powered.append("AC")
            if batt["USB powered"].lower() == "true":
                powered.append("USB")
            powered_str = ", ".join(powered) if powered else "battery"
            info["battery"] = f"{batt['level']}% ({status_text}, {powered_str}, {temp_c})"
            pkg = _safe_detect_app(device)
            app_str = "-"
            if pkg:
                app_str = pkg
            info["app"] = app_str
            ip_addr = "-"
            for line in _shell(device, "ip route").splitlines():
                if " src " in line:
                    parts = line.split(" src ")
                    if len(parts) > 1:
                        ip_addr = parts[1].split()[0]
                        break
            info["ip"] = ip_addr or "-"
            uptime_str = "-"
            try:
                secs = float(_shell(device, "cat /proc/uptime").split()[0])
                hours, rem = divmod(int(secs), 3600)
                mins, _ = divmod(rem, 60)
                uptime_str = f"{hours}h {mins}m"
            except (ValueError, IndexError):
                pass
            info["uptime"] = uptime_str
            android = info.get("ro.build.version.release", "-")
            sdk = info.get("ro.build.version.sdk", "-")
            android_str = (f"{android} (SDK {sdk})" if sdk and sdk != "-" else android)
            brand = info.get("ro.product.brand", "-")
            self._push("device_info", {
                "status": "Connected", "serial": info.get("serial", "-"),
                "model": info.get("ro.product.model", "-"), "brand": brand,
                "android": android_str, "abi": info.get("ro.product.cpu.abi", "-"),
                "screen_size": info.get("screen_size", "-"),
                "density": info.get("screen_density", "-"), "app": app_str,
                "battery": info.get("battery", "-"), "ip": info.get("ip", "-"),
                "uptime": info.get("uptime", "-")})
        except Exception:
            pass
        finally:
            with self._info_lock:
                self._info_in_flight = False

    def copy_info(self) -> bool:
        self._push("copy_device_info", {})
        return True

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        log_info("Log cleared")
        return True

    def save_log(self) -> str:
        """Save the full backend log buffer to a .txt file (native save dialog).

        Returns the written path, or "" when the buffer is empty / the dialog
        was cancelled / the write failed.
        """
        if not self._log_buffer:
            return ""
        lines = [f"{e.get('ts', '')} [{e.get('level', 'info').upper():7s}] {e.get('msg', '')}"
                 for e in self._log_buffer]
        default = f"workflow_log_{_ts()}.txt"
        path = None
        win = self._win()
        try:
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG, directory=self._scope_out(), save_filename=default,
                    file_types=("Text (*.txt)", "All files (*.*)"))
                if paths:
                    path = paths[0] if isinstance(paths, (list, tuple)) else paths
        except Exception:
            path = None
        if not path:
            return ""
        if not path.lower().endswith(".txt"):
            path += ".txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            return ""
        return path

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
            log_warning(f"Saving settings failed: {exc}")
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
        """Return the workflow to open on startup.

        Prefers a path passed from the Hub / CLI (``_pending_load``), else the
        remembered ``lastWorkflow`` from settings.

        ``{ok, path, name, text}`` when a file is available, else ``{}``.
        """
        path: Optional[str] = None
        if self._pending_load and os.path.isfile(self._pending_load):
            path = self._pending_load
            self._pending_load = None
        else:
            self._pending_load = None
            raw = (self.get_settings() or {}).get("lastWorkflow")
            if raw and os.path.isfile(str(raw)):
                path = str(raw)
        if not path:
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            name = ""
            try:
                name = (json.loads(text) or {}).get("name", "")
            except Exception:
                pass
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            return {"ok": True, "path": path, "name": name, "text": text}
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
            if s.get("connected"):
                self._device_lost_announced = False
            self._push("device_status", {
                "connected": bool(s.get("connected")),
                "serial": s.get("device_id"),
                "name": s.get("device_name") or serial,
            })
            self._warm_capture_async()
        except Exception as e:
            log_error(f"Connect device error: {e}")

    def _warm_capture_async(self) -> None:
        """Pre-start the scrcpy frame source for the connected device.

        Runs right after a device connects (not on Play), so by the time the
        user starts a test run the client already has frames and the first
        block executes immediately instead of waiting out the scrcpy warm-up.
        """
        serial = self._connected_serial or self._selected_serial
        if not serial:
            return
        threading.Thread(target=warm_scrcpy_source, args=(serial,), daemon=True).start()

    def _device_worker(self, deep: bool = False) -> None:
        """Refresh the device list. ``deep`` also probes known emulator ports
        (slower) — used on a 30s cadence when nothing is connected so a new
        emulator instance is found without a manual Scan ports click."""
        with self._device_lock:
            try:
                self.scanner.ensure_adb_server_running()
                devices = self.controller.client.devices()
                items = self.scanner.unique_devices(devices)
                if not items and deep:
                    try:
                        found = self.scanner.scan_all(stop_on_first=False) or []
                        if found:
                            log_info(f"Auto-scan found {len(found)} device(s)")
                    except Exception as exc:
                        log_warning(f"Auto port scan failed: {exc}")
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
                serials = {d.get("serial") for d in items if d.get("serial")}
                # Selected emulator closed → clear handle + stop live capture.
                wanted = self._selected_serial or self._connected_serial
                if wanted and wanted not in serials:
                    self.controller.mark_disconnected("no longer in adb devices")
                    self._connected_serial = None
                    if self._auto_refresh_enabled and self._capture_kind != "win32":
                        self._on_device_lost(f"{wanted} not found")
                    else:
                        self._push("device_status", {
                            "connected": False, "serial": None, "name": "",
                        })
                elif items:
                    s = self.controller.get_status_summary()
                    self._connected_serial = s.get("device_id") if s.get("connected") else None
                    if s.get("connected"):
                        self._device_lost_announced = False
                    self._push("device_status", {
                        "connected": bool(s.get("connected")),
                        "serial": s.get("device_id"),
                        "name": s.get("device_name") or "",
                    })
                    if self._connected_serial:
                        self._warm_capture_async()
                else:
                    # Empty device list — mirror disconnected state to the UI.
                    if self.controller.device is not None or self._connected_serial:
                        self.controller.mark_disconnected("no devices left")
                        self._connected_serial = None
                        if self._auto_refresh_enabled and self._capture_kind != "win32":
                            self._on_device_lost("no devices")
                        else:
                            self._push("device_status", {
                                "connected": False, "serial": None, "name": "",
                            })
            except Exception:
                self._push("devices_update", {"devices": []})

    def _device_poll(self) -> None:
        """Light refresh every 5s; when no device is connected, also deep-scan
        emulator ports about every 30s so a newly started instance is found."""
        while not self._closing:
            time.sleep(5)
            if self._closing:
                break
            deep = False
            # Deep-scan when nothing is connected — a light adb-devices poll is
            # enough while a device is live; offline, re-probe emulator ports.
            if not self._connected_serial:
                now = time.monotonic()
                if now - self._last_deep_scan >= self._deep_scan_interval:
                    deep = True
                    self._last_deep_scan = now
            self._device_worker(deep=deep)

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
                log_info(f"Bundled {n} template images into ./{_TEMPLATES_DIRNAME}/")
        except Exception as exc:
            log_warning(f"Couldn't bundle template images: {exc} — saving the original JSON")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    # ── Workflow file ops ──────────────────────────────────────────────────────

    def workflow_node_types(self) -> dict:
        return {k: {"label": v["label"], "kind": v["kind"], "outs": v["outs"]}
                for k, v in NODE_TYPES.items()}

    def workflow_new(self, name: str = "") -> bool:
        """Forget the open file so the next save creates
        ``workflows/<name>/workflow.json``."""
        self._wf_path = None
        self._remember_last_workflow(None)   # a fresh doc shouldn't reopen the old one
        self._scope_refresh_out()
        return True

    def _default_flow_path(self, name: str) -> str:
        """Default save target: ``<workflows>/<name>/workflow.json``.

        Used whenever the user doesn't pick an explicit location. Each workflow
        gets its own folder so ``_write_flow`` can bundle a sibling
        ``templates/`` folder, keeping the pair portable.
        """
        clean = _sanitize_name(name) or "workflow"
        folder = os.path.join(_WORKFLOWS_DIR, clean)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "workflow.json")

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
            log_info(f"Saving by default into workflows/{_sanitize_name(name) or 'workflow'}/")
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            self._write_flow(flow_json, path)
            self._wf_path = path
            self._remember_dir(path)
            self._remember_last_workflow(path)
            self._scope_refresh_out()
            log_success(f"Workflow saved: {path}")
            return True
        except Exception as exc:
            log_error(f"Saving workflow failed: {exc}")
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
            self._scope_refresh_out()
            log_success(f"Saved: {path}")
            return {"ok": True, "path": path}
        except Exception as exc:
            log_error(f"Save failed: {exc}")
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
            self._scope_refresh_out()
            log_info(f"Workflow opened: {path}")
            return text
        except Exception as exc:
            log_error(f"Opening workflow failed: {exc}")
            return ""

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
        try:
            if serial and not is_win32:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Couldn't select a device for the engine: {exc}")
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        self._engine.load(flow, flow_path=anchor)
        self._engine.failure_screenshot_dir = os.path.join(_PROJECT_ROOT, "out", "workflow_failures")
        self._bind_workflow_callbacks()
        # Test runs never auto-apply speedhack — that's a separate ▶ action.
        ok = self._engine.start(background=True, with_speedhack=False)
        self._push("workflow_state", {"running": ok})
        if ok:
            # Seed the panel with global vars immediately (activity vars arrive
            # via on_var when each activity starts).
            self._push("vars_snapshot", {"vars": dict(self._engine._globals)})
            log_success("Workflow started")
        return ok

    def workflow_stop(self) -> bool:
        if self._engine:
            self._engine.stop()
        self._push("workflow_state", {"running": False})
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
        self._engine.callbacks["on_node_done"] = [
            lambda nid, st, port: self._push("node_result", {"id": nid, "status": st, "port": port})]
        self._engine.callbacks["on_var"] = [
            lambda name, value: self._push("var_update", {"name": name, "value": value})]
        self._engine.callbacks["on_activity_start"] = [
            lambda act: self._push("activity_active", {"id": act.get("id")})]
        self._engine.callbacks["on_activity_complete"] = [
            lambda act, ok: self._push("activity_result",
                                       {"id": act.get("id"), "status": "ok" if ok else "fail"})]
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

    def workflow_running(self) -> bool:
        return bool(self._engine and self._engine.is_running())

    def workflow_run_from_node(self, flow_json: str, edit_kind: str, edit_id: str, node_id: str, step: bool = False) -> bool:
        try:
            flow = json.loads(flow_json)
        except Exception as exc:
            log_error(f"Invalid workflow JSON: {exc}")
            return False
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
        try:
            if serial and not is_win32:
                self._engine.auto.adb.device_id = serial
                self._engine.auto.adb.select_device(serial)
        except Exception as exc:
            log_warning(f"Couldn't select a device for the engine: {exc}")
        anchor = self._wf_path or os.path.join(_PROJECT_ROOT, "flow.json")
        self._engine.load(flow, flow_path=anchor)
        self._engine.failure_screenshot_dir = os.path.join(_PROJECT_ROOT, "out", "workflow_failures")
        self._bind_workflow_callbacks()
        graph = None
        seed_act = {"vars": []}
        if edit_kind == "function":
            fn = next((f for f in flow.get("functions", []) or [] if f.get("id") == edit_id), None)
            graph = (fn or {}).get("graph")
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
            self._push("vars_snapshot", {"vars": dict(self._engine._globals)})
            log_success("Workflow debug run started")
        return ok

    def workflow_debug_step(self) -> bool:
        if self._engine:
            self._engine.debug_next()
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

    # ── Standalone speed hack (manual ▶, independent of the test run) ──────────

    def _sh_push(self, active: bool, running: bool) -> None:
        self._push("speedhack_state", {"active": active, "running": running})

    def speedhack_start(self, speed=2.0, package: str = "") -> bool:
        """Start (or live-adjust) the speed hack on its own — no workflow needed.

        ADB-only: uses Frida. Win32 projects have no speed hack (the old
        cheat.dll injection was removed) — refuse there with a clear message.
        """
        if self._capture_kind == "win32":
            log_error("[speedhack] not supported in Win32 mode (ADB/Frida only).")
            return False
        try:
            scale = float(speed)
        except (TypeError, ValueError):
            scale = 2.0
        if self.controller.device is None:
            log_error("[speedhack] no device selected")
            return False
        if scale <= 0 or scale == 1.0:
            log_warning("[speedhack] speed must differ from 1.0 to accelerate")
            return False
        # Already running → just push the new scale live (no re-inject, no package).
        if self._sh_mgr is not None:
            ok = self._sh_mgr.set_scale(scale)
            self._sh_push(bool(self._sh_mgr.active), True)
            return ok
        pkg = (package or "").strip()
        if not pkg:
            log_error("[speedhack] a game package is required to enable the speed hack")
            return False
        mgr = FridaSpeedhackManager(package=pkg)
        mgr.adb_controller = self.controller
        if not mgr.available:
            log_warning("[speedhack] frida-inject not found in vendor/frida/")
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
        log_info(f"[speedhack] will accelerate '{mgr.package}' x{scale} once the game runs…")
        while mgr is not None and stop_ev is not None and not stop_ev.is_set():
            if mgr.active:
                return
            try:
                if mgr.set_scale(scale):
                    log_success(f"[speedhack] enabled x{scale}")
                    self._sh_push(True, True)
                    return
            except Exception as e:
                log_warning(f"[speedhack] retrying: {e}")
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
                log_warning(f"[speedhack] error while disabling: {e}")
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
            log_warning(f"Couldn't resolve the templates folder: {exc}")
            return None

    def open_devscope(self, flow_json: str = "") -> bool:
        """Launch DevScope, pointing its output at this workflow's ``templates/``
        folder so region crops / screenshots save alongside the flow."""
        try:
            out_dir = self._workflow_templates_dir(flow_json)
            launch_tool("devscope", [out_dir] if out_dir else None)
            if out_dir:
                log_success(f"DevScope opened · images save to: {out_dir}")
            else:
                log_success("DevScope opened")
            return True
        except Exception as exc:
            log_error(f"Opening DevScope failed: {exc}")
            return False

    # Back-compat alias for any old JS / callers.
    open_dev_helper = open_devscope

    def open_runner(self, flow_json: str) -> bool:
        """Launch the Runner GUI (separate process) preloaded with this flow.

        The runner resolves template images relative to the file it loads, so we
        can't just dump the raw JSON next to it — its ``templates/<file>`` paths
        point at the *original* workflow bundle. ``_write_flow`` re-bundles the
        templates into a sibling ``templates/`` folder (pulling from the original
        ``self._wf_path`` bundle / absolute picker paths) and rewrites the paths,
        so the temp run file is self-contained and the runner finds every image.
        """
        try:
            os.makedirs(_RUN_TMP_DIR, exist_ok=True)
            tmp = os.path.join(_RUN_TMP_DIR, "_designer_run.json")
            self._write_flow(flow_json, tmp)
            launch_tool("runner", [tmp])
            log_success("Runner GUI opened with the current workflow")
            return True
        except Exception as exc:
            log_error(f"Opening Runner failed: {exc}")
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
        stop_scrcpy_sources()
        remove_log_subscriber(self._on_log)


# ── Entry points ────────────────────────────────────────────────────────────

def create_workflow_designer_window(
    title: str = "Workflow2k",
    auto_load: Optional[str] = None,
) -> webview.Window:
    api = WorkflowDesignerAPI()
    if auto_load and os.path.isfile(auto_load):
        api._pending_load = os.path.abspath(auto_load)
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
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    # Optional path from the Hub: ``python apps/workflow_designer.py path.json``
    auto = sys.argv[1] if len(sys.argv) > 1 else None
    run(auto)
