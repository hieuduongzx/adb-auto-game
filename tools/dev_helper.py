"""PyWebView-based Dev Helper for ADB auto-game development.

This is the web-tech replacement for ``tools/dev_helper.py`` (PySide6).
It reuses the same visual language as ``src/gui/web/index.html`` (IBM
Plex tokens, light surface palette, pill status, slim scrollbars) and
exposes a ``DevHelperAPI`` to JavaScript via ``pywebview.api.*``.

Features mirror the PySide6 version:
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

    python tools/dev_helper_web.py

Saved crops default to ``./out/`` next to the project root.
"""
from __future__ import annotations

import base64
import datetime
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- bootstrap: make `src.*` importable when run from tools/ -------------
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import cv2
import numpy as np
import webview

from src.core.adb import ADBController, DeviceScanner
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

# In a frozen build, writable resources (out/, data/) live next to the .exe.
if is_frozen():
    _PROJECT_ROOT = app_dir()

# Bundled HTML: from source it sits in ``tools/web``; in a frozen build it is
# collected under ``<_MEIPASS>/web``.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(__file__), "web"))
DEFAULT_OUT_DIR = os.path.join(_PROJECT_ROOT, "out")

# Properties fetched for the Device tab info panel.
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


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _ensure_out_dir() -> str:
    os.makedirs(DEFAULT_OUT_DIR, exist_ok=True)
    return DEFAULT_OUT_DIR


def _sanitize_name(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", raw.strip())
    cleaned = cleaned.strip("._-")
    return cleaned


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


class DevHelperAPI:
    """Methods exposed to JavaScript as ``window.pywebview.api.*``."""

    AUTO_REFRESH_MIN_HZ = 0.2
    AUTO_REFRESH_MAX_HZ = 30.0
    INFO_REFRESH_INTERVAL = 2.0  # seconds

    def __init__(self, out_dir: Optional[str] = None) -> None:
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

        # Background workers.
        self._device_lock = threading.Lock()
        self._selected_serial: Optional[str] = None
        self._connected_serial: Optional[str] = None

        # In-flight guards.
        self._capture_lock = threading.Lock()
        self._capture_in_flight = False
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
            payload = json.dumps({"type": event_type, "data": data},
                                  ensure_ascii=False)
            safe = payload.replace("\\", "\\\\").replace("`", "\\`")
            self._window.evaluate_js(f"window.__recv(`{safe}`)")
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
            device = self.controller.device
            if device is None:
                self._push("device_info", {
                    "status": "Disconnected", "serial": "-", "model": "-",
                    "brand": "-", "android": "-", "abi": "-",
                    "screen_size": "-", "density": "-", "app": "-",
                    "battery": "-", "ip": "-", "uptime": "-",
                })
                return
            info: Dict[str, Any] = {"serial": device.serial, "status": "Connected"}

            getprop_cmd = " ; ".join(f"getprop {p}" for p in _DEVICE_INFO_PROPS)
            values = [v.strip() for v in _shell(device, getprop_cmd).splitlines()]
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
                    prefix = f"{key}:"
                    if line.startswith(prefix):
                        batt[key] = line[len(prefix):].strip()
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
                app_name = self.controller._get_app_name_for_package(pkg)
                app_str = (f"{app_name}  ({pkg})"
                           if app_name and app_name != "-" else pkg)
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
            android_str = (f"{android} (SDK {sdk})"
                           if sdk and sdk != "-" else android)
            brand = info.get("ro.product.brand", "-")
            manufacturer = info.get("ro.product.manufacturer", "-")
            if (manufacturer and manufacturer != "-"
                    and manufacturer.lower() != brand.lower()):
                brand_str = f"{brand} / {manufacturer}"
            else:
                brand_str = brand

            ui = {
                "status": "Connected",
                "serial": info.get("serial", "-"),
                "model": info.get("ro.product.model", "-"),
                "brand": brand_str,
                "android": android_str,
                "abi": info.get("ro.product.cpu.abi", "-"),
                "screen_size": info.get("screen_size", "-"),
                "density": info.get("screen_density", "-"),
                "app": app_str,
                "battery": info.get("battery", "-"),
                "ip": info.get("ip", "-"),
                "uptime": info.get("uptime", "-"),
            }
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
            self._push("capture_failed", {"error": "No device selected"})
            return False
        with self._capture_lock:
            if self._capture_in_flight:
                return False
            self._capture_in_flight = True
        threading.Thread(target=self._capture_worker, daemon=True).start()
        return True

    def _capture_worker(self) -> None:
        try:
            img = capture_screen_frame(self.controller)
            if img is None:
                self._push("capture_failed", {"error": "Failed to capture screen"})
                return
            h, w = img.shape[:2]
            self._screen = img
            self._screen_w = w
            self._screen_h = h
            # Resolution change drops stale selections.
            self._push_frame(img)
            self._push("captured", {"w": w, "h": h})
        except Exception as exc:
            self._push("capture_failed", {"error": str(exc)})
        finally:
            with self._capture_lock:
                self._capture_in_flight = False

    def _auto_refresh_loop(self) -> None:
        while not self._closing:
            time.sleep(0.1)
            if not self._auto_refresh_enabled or self._closing:
                continue
            now = time.monotonic()
            period = 1.0 / max(0.1, self._refresh_hz)
            if now - self._last_auto_capture >= period:
                self._last_auto_capture = now
                self.capture()

    def set_auto_refresh(self, enabled: bool) -> bool:
        self._auto_refresh_enabled = bool(enabled)
        self._last_auto_capture = time.monotonic()
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
        # Filename embeds the region so Workflow2k can auto-fill a search region.
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
                log_info("Lưu bị huỷ")
                return False
            path = paths[0] if isinstance(paths, (list, tuple)) else paths
        else:
            # No window available — fall back silently to output folder
            path = os.path.join(out_dir, default)

        if not path.lower().endswith((".png", ".jpg", ".jpeg")):
            path += ".png"
        # If the user edits the filename and removes coords, we still try to inject
        # the current region back in when the name contains no coordinate suffix.
        path = self._ensure_region_in_filename(path, x, y, w, h)
        if cv2.imwrite(path, crop):
            log_success(f"Saved crop: {path}")
            return True
        log_error(f"Failed to write {path}")
        return False

    def _ensure_region_in_filename(self, path: str, x: int, y: int, w: int, h: int) -> str:
        """Make sure a saved crop filename ends with _x_y_w_h.ext.

        If the user-supplied path already has a coordinate suffix, leave it alone.
        Otherwise rewrite the basename so Workflow2k can parse the region later.
        """
        base, ext = os.path.splitext(path)
        suffix = f"_{x}_{y}_{w}_{h}"
        if re.search(r"_\d+_\d+_\d+_\d+(?:\.\d+)?$", base):
            return path
        return f"{base}{suffix}{ext}"

    def _pkg_subdir(self) -> str:
        """Return the QuickCrop output folder.

        Standalone DevScope keeps crops grouped under ``out/<package>/``. When
        Workflow2k launches DevScope with a workflow templates folder, that folder
        is already the target bundle, so QuickCrop must not create a package
        subfolder or the designer will not find ``templates/<file>`` assets.
        """
        if self._pinned_out_dir:
            os.makedirs(self._out_dir, exist_ok=True)
            return self._out_dir
        pkg = _safe_detect_app(self.controller.device) if self.controller.device is not None else None
        clean = _sanitize_name(pkg or "unknown_app") or "unknown_app"
        out_dir = os.path.join(self._out_dir, clean)
        os.makedirs(out_dir, exist_ok=True)
        return out_dir

    def quick_crop(self, name: str = "") -> bool:
        """Save the current region crop without a dialog, into ``out/<package>/``.

        Uses ``name`` (sanitized) when non-empty, otherwise falls back to
        ``crop_<timestamp>_<x>_<y>_<w>_<h>.png`` so no prompt interrupts the flow.
        The filename embeds the region so Workflow2k can auto-fill it.
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
        path = (template_path or "").strip()
        if not path or not os.path.exists(path):
            return {"error": "Pick a valid template path"}
        grayscale = bool(grayscale)
        threshold = float(threshold)
        multiscale = bool(multiscale)
        all_matches = bool(all_matches)

        tpl = self.matcher.load(path, grayscale=grayscale)
        if tpl is None:
            log_error(f"Could not load template: {path}")
            return {"error": "Could not load template"}
        th, tw = tpl.shape[:2]

        rects: List[List[float]] = []
        if all_matches:
            results = self.matcher.match_all(
                self._screen, tpl,
                threshold=threshold, use_grayscale=grayscale,
            )
            for cx, cy, conf in results:
                x = max(0, cx - tw // 2)
                y = max(0, cy - th // 2)
                rects.append([x, y, tw, th, float(conf)])
            log_info(f"match_all -> {len(results)} hit(s) (thr={threshold:.2f})")
            summary = f"Found {len(results)} match(es)."
        else:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2] if multiscale else None
            res = self.matcher.match(
                self._screen, tpl,
                threshold=threshold, use_grayscale=grayscale,
                multi_scale=multiscale, scales=scales,
            )
            if res is None:
                self._overlay = []
                self._push("overlay", {"rects": []})
                return {"summary": f"No match >= {threshold:.2f}.", "rects": []}
            cx, cy, conf, scale = res
            sw = int(tw * scale)
            sh = int(th * scale)
            x = max(0, cx - sw // 2)
            y = max(0, cy - sh // 2)
            rects.append([x, y, sw, sh, float(conf)])
            log_info(f"match -> ({cx},{cy}) conf={conf:.3f} scale={scale:.2f}")
            summary = (f"Match: center=({cx},{cy}) "
                       f"conf={conf:.3f} scale={scale:.2f}")

        self._overlay = [(r[0], r[1], r[2], r[3], r[4]) for r in rects]
        self._push("overlay", {"rects": rects})
        return {"summary": summary, "rects": rects}

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

    # ── Asset library ────────────────────────────────────────────────────────

    def list_assets(self) -> list:
        """List image assets under the output folder, including per-package
        subfolders (e.g. QuickCrop's ``out/<package>/``). Names are shown
        relative to the output root so ``pkg/file.png`` stays distinguishable.
        """
        out_dir = self._out_dir
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
                items.append({
                    "name": rel,
                    "path": path.replace("\\", "/"),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                })
        items.sort(key=lambda it: it["mtime"], reverse=True)
        for it in items:
            it.pop("mtime", None)
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
            return ("data:image/jpeg;base64,"
                    + base64.b64encode(buf.tobytes()).decode("ascii"))
        except Exception:
            return ""

    def delete_asset(self, path: str) -> bool:
        try:
            p = Path(path)
            if p.exists() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}:
                p.unlink()
                return True
            return False
        except Exception:
            return False

    # ── Tool switching ─────────────────────────────────────────────────────────

    def open_workflow_designer(self) -> bool:
        """Launch the Workflow Designer in a separate process."""
        try:
            launch_tool("designer")
            log_success("Đã mở Workflow2k")
            return True
        except Exception as exc:
            log_error(f"Mở Workflow2k thất bại: {exc}")
            return False

    # ── Log ───────────────────────────────────────────────────────────────────

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        log_info("Đã xoá nhật ký")
        return True

    # ── Teardown ─────────────────────────────────────────────────────────────

    def _close(self) -> None:
        self._closing = True
        stop_scrcpy_sources()
        remove_log_subscriber(self._on_log)


# ── Entry points ──────────────────────────────────────────────────────────────

def create_dev_helper_window(title: str = "DevScope",
                             out_dir: Optional[str] = None) -> webview.Window:
    api = DevHelperAPI(out_dir=out_dir)
    html_path = os.path.join(_WEB_DIR, "scope", "index.html")
    url = f"file:///{html_path.replace(os.sep, '/')}"

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
    create_dev_helper_window(out_dir=out_dir)
    webview.start(debug=False, private_mode=False)


if __name__ == "__main__":
    _out = sys.argv[1] if len(sys.argv) > 1 else None
    run(_out)
