"""PyWebView-based DevScope — device inspector for ADB auto-game.

Reuses the same visual language as Macro2k (IBM Plex tokens, light surface
palette, pill status, slim scrollbars) and exposes a ``DevScopeAPI`` to JavaScript via ``pywebview.api.*``.

Features:
- Device picker (ADBController + DeviceScanner) + port scan / restart ADB
- Screenshot capture (manual + auto-refresh at configurable Hz)
- Click to pick a point, drag to select a region (device coordinates)
- Color picker (RGB / HEX at last clicked point)
- Manual tap / swipe sender
- Template match tester (threshold / grayscale / multi-scale)
- OCR via OCRReader (Tesseract / EasyOCR / PaddleOCR) - switchable at runtime
- Live device info panel
- Region crop: Save crop... (dialog), QuickCrop (no dialog) + filename field

Run::

    python apps/devscope.py

Saved crops default to ``./out/`` next to the project root.
"""
from __future__ import annotations

import base64
import datetime
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --- bootstrap: make `src.*` importable when run from apps/ ---------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import cv2
import numpy as np
import webview

from src.core.adb import ADBController, DeviceScanner, device_info, lifecycle
from src.core.adb.auto.scrcpy_capture import (
    CAPTURE_BACKENDS,
    capture_screen as capture_screen_frame,
    get_capture_backend,
    set_capture_backend,
    stop_scrcpy_sources,
)
from src.core.adb.auto.ocr import KNOWN_BACKENDS, OCRReader
from src.core.adb.auto.template_matcher import TemplateMatcher
from src.utils import (
    add_log_subscriber,
    bundle_dir,
    data_root,
    file_url,
    is_frozen,
    launch_tool,
    log_error,
    log_info,
    log_success,
    log_warning,
    push_webview_event,
    remove_log_subscriber,
    sanitize_name,
    titled,
    ts_stamp,
    webview_storage_path,
)

# In a frozen build, writable resources (out/, data/) live under data_root() —
# next to the app when writable, else %LOCALAPPDATA% (read-only Program Files).
if is_frozen():
    _PROJECT_ROOT = data_root()

# Bundled HTML: from source it sits in ``apps/web``; in a frozen build it is
# collected under ``<_MEIPASS>/web``.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
DEFAULT_OUT_DIR = os.path.join(_PROJECT_ROOT, "out")

# Properties fetched for the Device tab info panel live in
# ``src.core.adb.device_info`` (shared with the Workflow Designer).


def _ts() -> str:
    return ts_stamp()


def _sanitize_name(raw: str) -> str:
    return sanitize_name(raw)


class DevScopeAPI:
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    AUTO_REFRESH_MIN_HZ = 0.2
    AUTO_REFRESH_MAX_HZ = 30.0
    INFO_REFRESH_INTERVAL = 2.0  # seconds

    def __init__(self, out_dir: Optional[str] = None) -> None:
        # Register as a live ADB client so a sibling closing down doesn't kill
        # the shared ADB server out from under us (see src/core/adb/lifecycle).
        lifecycle.acquire_adb_lease("devscope")
        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()
        self.matcher = TemplateMatcher(cache_size=64)

        self._ocr_reader: Optional[OCRReader] = None
        # When launched from the Workflow Designer this points at the workflow's
        # templates/ folder, so crops/screenshots bundle with that workflow.
        self._out_dir: str = DEFAULT_OUT_DIR
        self._pinned_out_dir = False
        if out_dir:
            try:
                os.makedirs(out_dir, exist_ok=True)
                self._out_dir = os.path.abspath(out_dir)
                self._pinned_out_dir = True
            except Exception:
                pass

        # Last directory a file dialog landed in, so dialogs reopen there instead
        # of always defaulting to ./out.
        self._last_dir: Optional[str] = None

        self._window: Optional[webview.Window] = None
        self._closing = False
        self._log_buffer: List[Dict] = []

        # Latest screenshot state (device pixel coords).
        self._screen: Optional[np.ndarray] = None
        self._screen_w = 0
        self._screen_h = 0

        # Current selection state shared with JS.
        self._last_point: Optional[Tuple[int, int]] = None
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._overlay: List[Tuple[int, int, int, int, float]] = []

        # Auto-refresh. Default to 20 Hz so DevScope feels like a live mirror.
        self._auto_refresh_enabled = True
        self._refresh_hz = 20.0
        self._last_auto_capture = 0.0
        self._device_lost_announced = False

        # Background workers.
        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None

        # In-flight guards.
        self._capture_lock = threading.Lock()
        self._capture_in_flight = False
        self._capture_generation = 0
        self._info_lock = threading.Lock()
        self._info_in_flight = False

    # ── Setup (called after window is created) ───────────────────────────────

    def _attach(self, window: webview.Window) -> None:
        self._window = window
        add_log_subscriber(self._on_log)
        # Kick device refresh + background pollers.
        threading.Thread(target=self._device_worker, daemon=True).start()
        threading.Thread(target=self._device_poll, daemon=True).start()
        threading.Thread(target=self._info_poll, daemon=True).start()
        threading.Thread(target=self._auto_refresh_loop, daemon=True).start()
        # One immediate capture so the canvas isn't empty.
        self.capture()

    # ── Log subscriber ───────────────────────────────────────────────────────

    def _on_log(self, level: str, message: str) -> None:
        bucket = {
            "info": "info", "success": "success", "warning": "warning",
            "error": "error",
        }.get(level, "info")
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = {"ts": ts, "level": bucket, "msg": message}
        self._log_buffer.append(entry)
        if len(self._log_buffer) > 2000:
            self._log_buffer = self._log_buffer[-2000:]
        self._push("log", entry)

    # ── JS push helper ───────────────────────────────────────────────────────

    def _push(self, event_type: str, data: dict) -> None:
        if self._window is None or self._closing:
            return
        try:
            push_webview_event(self._window, event_type, data)
        except Exception:
            pass

    def _push_frame(self, bgr: np.ndarray) -> None:
        """Send a JPEG screenshot frame to JS as a data URL."""
        if self._window is None or self._closing:
            return
        try:
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                return
            b64 = base64.b64encode(buf.tobytes()).decode("ascii")
            self._window.evaluate_js(f'window.__recvFrame("data:image/jpeg;base64,{b64}",{self._screen_w},{self._screen_h})')
        except Exception:
            pass

    # ── Public API: initial state ───────────────────────────────────────────

    def get_state(self) -> dict:
        """Initial state hydration called by JS on load."""
        return {
            "ocrBackends": list(KNOWN_BACKENDS),
            "autoRefresh": self._auto_refresh_enabled,
            "refreshHz": self._refresh_hz,
            "minHz": self.AUTO_REFRESH_MIN_HZ,
            "maxHz": self.AUTO_REFRESH_MAX_HZ,
            "connectedSerial": self._connected_serial,
            "selectedSerial": self._selected_serial,
            "outDir": self._out_dir,
            "captureBackend": get_capture_backend(),
            "captureBackends": list(CAPTURE_BACKENDS),
            "log": self._log_buffer[-300:],
        }

    def set_capture_backend(self, backend: str) -> dict:
        selected = set_capture_backend(backend)
        self._push("capture_backend", {"backend": selected})
        return {"backend": selected, "backends": list(CAPTURE_BACKENDS)}

    # ── Device ops ───────────────────────────────────────────────────────────

    def refresh_devices(self) -> None:
        threading.Thread(target=self._device_worker, daemon=True).start()

    def select_device(self, serial: str) -> bool:
        try:
            self._selected_serial = serial or None
            threading.Thread(
                target=self._connect_device, args=(serial,), daemon=True,
            ).start()
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
                serials = {d.get("serial") for d in items if d.get("serial")}
                wanted = self._selected_serial or self._connected_serial
                if wanted and wanted not in serials:
                    self.controller.mark_disconnected("no longer listed by adb devices")
                    self._connected_serial = None
                    if self._auto_refresh_enabled:
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
                else:
                    if self.controller.device is not None or self._connected_serial:
                        self.controller.mark_disconnected("no devices remain")
                        self._connected_serial = None
                        if self._auto_refresh_enabled:
                            self._on_device_lost("no devices")
                        else:
                            self._push("device_status", {
                                "connected": False, "serial": None, "name": "",
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
        if found:
            log_success(f"Found {len(found)} device(s)")
        else:
            log_warning("No devices found on any port")
        self._device_worker()

    def _restart_adb_worker(self) -> None:
        log_info("Restarting ADB server...")
        if self.scanner.restart_adb_server():
            log_success("ADB server restarted")
        else:
            log_error("Failed to restart ADB server")
        self._device_worker()

    # ── Device info tab ──────────────────────────────────────────────────────

    def refresh_info(self) -> None:
        threading.Thread(target=self._info_worker, daemon=True).start()

    def _info_poll(self) -> None:
        while not self._closing:
            time.sleep(self.INFO_REFRESH_INTERVAL)
            if not self._closing:
                self._info_worker()

    def _info_worker(self) -> None:
        with self._info_lock:
            if self._info_in_flight:
                return
            self._info_in_flight = True
        try:
            ui = device_info.collect_device_info(
                self.controller.device,
                app_name_resolver=self.controller.get_app_name,
            )
            self._push("device_info", ui)
        except Exception as exc:
            log_error(f"Device info error: {exc}")
        finally:
            with self._info_lock:
                self._info_in_flight = False

    def copy_info(self) -> bool:
        """Copy the last device info to clipboard via JS."""
        self._push("copy_device_info", {})
        return True

    # ── Capture ──────────────────────────────────────────────────────────────

    def capture(self) -> bool:
        """Capture a screenshot and push a JPEG frame to JS."""
        if self.controller.device is None:
            if self._auto_refresh_enabled:
                self._on_device_lost("No device selected")
            return False
        with self._capture_lock:
            if self._capture_in_flight:
                return False
            self._capture_in_flight = True
            generation = self._capture_generation
        threading.Thread(target=self._capture_worker, args=(generation,), daemon=True).start()
        return True

    def _on_device_lost(self, reason: str = "") -> None:
        """Stop live capture and notify UI once when the ADB device vanishes."""
        if getattr(self, "_device_lost_announced", False) and not self._auto_refresh_enabled:
            return
        self._device_lost_announced = True
        was_refreshing = self._auto_refresh_enabled
        self._auto_refresh_enabled = False
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
        log_warning(f"Auto-refresh stopped — device disconnected: {msg}")
        self._push("auto_refresh", {"enabled": False})
        self._push("device_status", {"connected": False, "serial": None, "name": ""})
        if was_refreshing:
            self._push("capture_failed", {
                "error": f"Device disconnected — capture stopped ({msg})",
            })

    def _capture_worker(self, generation: int) -> None:
        try:
            img = capture_screen_frame(self.controller)
            if img is None and self.controller.device is None:
                self._on_device_lost("device not found")
                return
            if img is None:
                self._push("capture_failed", {"error": "Failed to capture screen"})
                return
            self._device_lost_announced = False
            h, w = img.shape[:2]
            with self._capture_lock:
                if generation != self._capture_generation:
                    return
                self._screen = img
                self._screen_w = w
                self._screen_h = h
            # Resolution change drops stale selections.
            self._push_frame(img)
            self._push("captured", {"w": w, "h": h})
        except Exception as exc:
            if self.controller.device is None or ADBController.is_device_gone_error(exc):
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
            if self.controller.device is None:
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
            self._device_lost_announced = False
        self._push("auto_refresh", {"enabled": self._auto_refresh_enabled})
        return True

    def set_refresh_hz(self, hz: float) -> bool:
        self._refresh_hz = max(self.AUTO_REFRESH_MIN_HZ,
                               min(self.AUTO_REFRESH_MAX_HZ, float(hz)))
        return True

    # ── Selection (point / region / overlay) ─────────────────────────────────

    def set_point(self, x: int, y: int) -> dict:
        """Called by JS when the user clicks a point on the canvas."""
        self._last_point = (int(x), int(y))
        self._region = None
        color = self._pixel_color(int(x), int(y))
        return {"x": int(x), "y": int(y), **color}

    def set_region(self, x: int, y: int, w: int, h: int) -> dict:
        """Called by JS when the user finishes dragging a region."""
        self._region = (int(x), int(y), int(w), int(h))
        self._last_point = None
        cx = int(x) + int(w) // 2
        cy = int(y) + int(h) // 2
        color = self._pixel_color(cx, cy)
        return {"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                "centerX": cx, "centerY": cy, **color}

    def _pixel_color(self, x: int, y: int) -> dict:
        return device_info.pixel_color(self._screen, self._screen_w,
                                       self._screen_h, int(x), int(y))

    def clear_selection(self) -> bool:
        self._region = None
        self._last_point = None
        self._overlay = []
        self._push("selection_cleared", {})
        return True

    # ── Tap / swipe ──────────────────────────────────────────────────────────

    def tap(self, x: int, y: int) -> bool:
        if self.controller.device is None:
            log_error("Tap failed: no device")
            return False
        if self.controller.tap(int(x), int(y)):
            log_success(f"Tapped ({x}, {y})")
            return True
        log_error(f"Tap failed at ({x}, {y})")
        return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, dur: int) -> bool:
        if self.controller.device is None:
            log_error("Swipe failed: no device")
            return False
        if self.controller.swipe(int(x1), int(y1), int(x2), int(y2), int(dur)):
            log_success(f"Swiped ({x1},{y1}) -> ({x2},{y2})")
            return True
        log_error("Swipe failed")
        return False

    # ── Region crop: Save / QuickCrop ────────────────────────────────────────

    def save_crop_dialog(self, name: str = "") -> bool:
        """Open a native Save-As dialog then write the current region crop."""
        region = self._region
        if self._screen is None or not region:
            log_warning("No region to save")
            return False
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        clean = _sanitize_name(name)
        # Filename embeds the region so Macro2k can auto-fill a search region.
        default = (f"{clean}_{x}_{y}_{w}_{h}.png" if clean
                   else f"region_{_ts()}_{x}_{y}_{w}_{h}.png")
        dialog_ok = True
        paths = None
        out_dir = self._out_dir
        os.makedirs(out_dir, exist_ok=True)
        try:
            wins = webview.windows
            win = wins[0] if wins else None
            if win:
                paths = win.create_file_dialog(
                    webview.SAVE_DIALOG,
                    directory=out_dir,
                    save_filename=default,
                    file_types=("PNG (*.png)", "JPEG (*.jpg;*.jpeg)", "All files (*.*)")
                )
            else:
                dialog_ok = False
        except Exception as exc:
            log_warning(f"Dialog error: {exc} — saving to output folder instead")
            dialog_ok = False

        if dialog_ok:
            # Dialog showed: None / empty = user cancelled
            if not paths:
                log_info("Save cancelled")
                return False
            path = paths[0] if isinstance(paths, (list, tuple)) else paths
        else:
            # No window available — fall back silently to output folder
            path = os.path.join(out_dir, default)

        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        # If the user edits the filename and removes coords, we still try to inject
        # the current region back in when the name contains no coordinate suffix.
        path = device_info.ensure_region_in_filename(path, x, y, w, h)
        if cv2.imwrite(path, crop):
            log_success(f"Saved crop: {path}")
            return True
        log_error(f"Failed to write {path}")
        return False

    def _ensure_region_in_filename(self, path: str, x, y, w, h) -> str:
        """Back-compat wrapper — logic lives in ``device_info``."""
        return device_info.ensure_region_in_filename(path, x, y, w, h)

    def _pkg_subdir(self) -> str:
        """Return the QuickCrop output folder.

        Standalone DevScope keeps crops grouped under ``out/<package>/``. When
        Macro2k launches DevScope with a workflow templates folder, that folder
        is already the target bundle, so QuickCrop must not create a package
        subfolder or the designer will not find ``templates/<file>`` assets.
        """
        if self._pinned_out_dir:
            os.makedirs(self._out_dir, exist_ok=True)
            return self._out_dir
        pkg = (device_info.safe_detect_app(self.controller.device)
               if self.controller.device is not None else None)
        clean = _sanitize_name(pkg or "unknown_app") or "unknown_app"
        out_dir = os.path.join(self._out_dir, clean)
        os.makedirs(out_dir, exist_ok=True)
        return out_dir

    def quick_crop(self, name: str = "") -> bool:
        """Save the current region crop without a dialog, into ``out/<package>/``.

        Uses ``name`` (sanitized) when non-empty, otherwise falls back to
        ``crop_<timestamp>_<x>_<y>_<w>_<h>.png`` so no prompt interrupts the flow.
        The filename embeds the region so Macro2k can auto-fill it.
        """
        region = self._region
        if self._screen is None or not region:
            log_warning("No region to crop")
            return False
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        out_dir = self._pkg_subdir()
        clean = _sanitize_name(name)
        if clean:
            fname = f"{clean}_{x}_{y}_{w}_{h}.png"
            if os.path.exists(os.path.join(out_dir, fname)):
                fname = f"{clean}_{_ts()}_{x}_{y}_{w}_{h}.png"
        else:
            fname = f"crop_{_ts()}_{x}_{y}_{w}_{h}.png"
        path = os.path.join(out_dir, fname)
        if cv2.imwrite(path, crop):
            log_success(f"QuickCrop: {path}")
            return True
        log_error(f"Failed to write {path}")
        return False

    def save_full(self, name: str = "") -> bool:
        """Save the full screenshot to the current output folder (no dialog)."""
        if self._screen is None:
            log_warning("Capture a screenshot first")
            return False
        out_dir = self._out_dir
        os.makedirs(out_dir, exist_ok=True)
        clean = _sanitize_name(name)
        fname = (f"{clean}_{_ts()}.png" if clean
                 else f"screenshot_{_ts()}.png")
        path = os.path.join(out_dir, fname)
        if cv2.imwrite(path, self._screen):
            log_success(f"Saved screenshot: {path}")
            return True
        log_error(f"Failed to write {path}")
        return False

    def open_image(self) -> bool:
        """Load a local image into DevScope using a native file picker."""
        try:
            wins = webview.windows
            win = wins[0] if wins else None
            if win is None:
                log_warning("No window available for file dialog")
                return False
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=self._start_dir(self._out_dir),
                allow_multiple=False,
                file_types=(
                    "Images (*.png;*.jpg;*.jpeg;*.bmp;*.webp)",
                    "All files (*.*)",
                ),
            )
        except Exception as exc:
            log_error(f"File dialog error: {exc}")
            return False
        if not paths:
            return False
        path = str(paths[0] if isinstance(paths, (list, tuple)) else paths)
        if Path(path).suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            log_warning("Unsupported image format")
            return False
        image = cv2.imread(path, cv2.IMREAD_COLOR)
        if image is None:
            log_error(f"Unable to read image: {path}")
            return False
        self._auto_refresh_enabled = False
        self._push("auto_refresh", {"enabled": False})
        with self._capture_lock:
            self._capture_generation += 1
        self._last_dir = os.path.dirname(path)
        self._screen = image
        self._screen_h, self._screen_w = image.shape[:2]
        self._last_point = None
        self._region = None
        self._overlay = []
        self._push("selection_cleared", {})
        self._push_frame(image)
        self._push("captured", {"w": self._screen_w, "h": self._screen_h})
        log_success(f"Opened image: {path}")
        return True

    def pick_out_dir(self) -> str:
        """Open a native folder-picker dialog to change the output directory."""
        try:
            wins = webview.windows
            win = wins[0] if wins else None
            if win is None:
                log_warning("No window available for folder dialog")
                return self._out_dir
            paths = win.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=self._out_dir,
            )
        except Exception as exc:
            log_warning(f"Folder dialog error: {exc}")
            return self._out_dir
        if not paths:
            return self._out_dir
        path = paths[0] if isinstance(paths, (list, tuple)) else paths
        if path and os.path.isdir(str(path)):
            self._out_dir = str(path)
            os.makedirs(self._out_dir, exist_ok=True)
            self._push("out_dir", {"path": self._out_dir})
            log_info(f"Output folder: {self._out_dir}")
        return self._out_dir

    # ── Dialog directory memory ────────────────────────────────────────────────

    def _start_dir(self, fallback: str) -> str:
        """Reopen dialogs in the last-used folder, else a sensible fallback."""
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

    # ── Template matching ────────────────────────────────────────────────────

    def pick_template(self) -> str:
        """Open a native Open-file dialog and return the chosen path (or "")."""
        try:
            wins = webview.windows
            win = wins[0] if wins else None
            if win is None:
                log_warning("No window available for file dialog")
                return ""
            start_dir = self._start_dir(
                self._out_dir if os.path.isdir(self._out_dir) else _PROJECT_ROOT)
            paths = win.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=start_dir,
                allow_multiple=False,
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

    def match_template(
        self, template_path: str, threshold: float,
        grayscale: bool, multiscale: bool, all_matches: bool,
    ) -> dict:
        """Run a template match and return overlay rects + summary."""
        if self._screen is None:
            return {"error": "Capture a screenshot first"}
        result = device_info.run_template_match(
            self.matcher, self._screen, template_path,
            threshold, grayscale, multiscale, all_matches,
        )
        if result.get("error"):
            log_error(result["error"])
            return result
        rects = result["rects"]
        if all_matches:
            log_info(f"match_all -> {len(rects)} hit(s) "
                     f"(thr={float(threshold):.2f})")
        elif rects:
            r = rects[0]
            log_info(f"match -> ({r[0] + r[2] // 2},{r[1] + r[3] // 2}) "
                     f"conf={r[4]:.3f}")
        self._overlay = [(r[0], r[1], r[2], r[3], r[4]) for r in rects]
        self._push("overlay", {"rects": rects})
        return result
    def clear_overlay(self) -> bool:
        self._overlay = []
        self._push("overlay", {"rects": []})
        return True

    # ── OCR ──────────────────────────────────────────────────────────────────

    def set_ocr_backend(self, name: str) -> dict:
        if self._ocr_reader is None:
            self._ocr_reader = OCRReader(backend=name)
        else:
            self._ocr_reader.set_backend(name)
        engine = self._ocr_reader.backend_name
        available = bool(self._ocr_reader.available)
        if available:
            log_info(f"OCR backend: {engine}")
        else:
            log_warning(f"OCR backend '{name}' not available")
        return {"engine": engine if engine != "none" else "n/a",
                "available": available}

    def read_text(self, whitelist: str = "") -> str:
        if self._screen is None:
            log_warning("Capture a screenshot first")
            return ""
        region = self._region
        if not region:
            log_warning("Drag a region or set X/Y/W/H first")
            return ""
        if self._ocr_reader is None:
            self._ocr_reader = OCRReader(backend=KNOWN_BACKENDS[0])
        if not self._ocr_reader.available:
            log_error("No OCR backend available")
            return ""
        wl = (whitelist or "").strip() or None
        text = self._ocr_reader.read_text(self._screen, region=region, whitelist=wl)
        engine = self._ocr_reader.backend_name
        x, y, w, h = region
        if text:
            log_success(f"OCR [{engine}] ({x},{y} {w}x{h}) -> {text!r}")
        else:
            log_warning(f"OCR [{engine}] ({x},{y} {w}x{h}) -> (no text)")
        return text

    # ── Key events ───────────────────────────────────────────────────────────

    def send_key(self, keycode) -> bool:
        if self.controller.device is None:
            log_error("send_key: no device")
            return False
        try:
            self.controller.device.shell(f"input keyevent {keycode}")
            log_success(f"Key: {keycode}")
            return True
        except Exception as e:
            log_error(f"Key event failed: {e}")
            return False

    # ── Long press ───────────────────────────────────────────────────────────

    def long_press(self, x: int, y: int, duration: int = 800) -> bool:
        if self.controller.device is None:
            log_error("long_press: no device")
            return False
        try:
            self.controller.device.shell(
                f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration)}"
            )
            log_success(f"Long press ({x}, {y}) {duration}ms")
            return True
        except Exception as e:
            log_error(f"Long press failed: {e}")
            return False

    # ── Text injection ───────────────────────────────────────────────────────

    def input_text(self, text: str) -> bool:
        if self.controller.device is None:
            log_error("input_text: no device")
            return False
        if not text:
            return False
        try:
            safe = (text
                    .replace("\\", "\\\\")
                    .replace('"', '\\"')
                    .replace("$", "\\$")
                    .replace("`", "\\`")
                    .replace(" ", "%s"))
            self.controller.device.shell(f'input text "{safe}"')
            log_success(f"Text: {text!r}")
            return True
        except Exception as e:
            log_error(f"Text injection failed: {e}")
            return False

    # ── Color check ──────────────────────────────────────────────────────────

    def check_color(self, x: int, y: int, hex_color: str, tolerance: int = 10) -> dict:
        return device_info.check_color_at(self._screen, self._screen_w,
                                          self._screen_h, x, y, hex_color,
                                          tolerance)

    # ── Asset library ────────────────────────────────────────────────────────

    def list_assets(self) -> list:
        """List image assets under the output folder, including per-package
        subfolders (e.g. QuickCrop's ``out/<package>/``). Names are shown
        relative to the output root so ``pkg/file.png`` stays distinguishable.
        """
        return device_info.list_image_assets(self._out_dir)

    def get_asset_thumbnail(self, path: str) -> str:
        return device_info.asset_thumbnail(self._out_dir, path)

    def delete_asset(self, path: str) -> bool:
        return device_info.delete_asset(self._out_dir, path)

    # ── Tool switching ─────────────────────────────────────────────────────────

    def open_workflow_designer(self) -> bool:
        """Launch the Workflow Designer in a separate process."""
        try:
            launch_tool("designer")
            log_success("Opened Macro2k")
            return True
        except Exception as exc:
            log_error(f"Failed to open Macro2k: {exc}")
            return False

    # ── Log ───────────────────────────────────────────────────────────────────

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        return True

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        stop_scrcpy_sources()
        # Only stop the shared ADB server when no sibling Macro2k process
        # (Runner / Designer / another DevScope) still holds a lease.
        lifecycle.release_adb_and_kill_if_last("devscope")
        remove_log_subscriber(self._on_log)


# ── Entry points ──────────────────────────────────────────────────────────────

def create_devscope_window(title: str = titled("DevScope"),
                           out_dir: Optional[str] = None) -> webview.Window:
    api = DevScopeAPI(out_dir=out_dir)
    html_path = os.path.join(_WEB_DIR, "scope", "index.html")
    url = file_url(html_path)

    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=1280,
        height=820,
        resizable=True,
        min_size=(1000, 680),
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    window.events.closed += lambda: api._close()
    return window


def run(out_dir: Optional[str] = None) -> None:
    """Create the window and start the event loop (standalone entry point).

    ``out_dir`` (optional, also accepted as the first CLI arg) presets the
    output folder — the Workflow Designer passes its workflow's templates/ dir.
    """
    create_devscope_window(out_dir=out_dir)
    webview.start(
        debug=False,
        private_mode=False,
        storage_path=webview_storage_path("devscope"),
    )


if __name__ == "__main__":
    _out = sys.argv[1] if len(sys.argv) > 1 else None
    run(_out)
