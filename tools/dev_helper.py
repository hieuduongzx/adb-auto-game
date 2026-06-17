"""
Dev Helper - Dear PyGui utility for ADB auto-game development.

Modern GPU-accelerated GUI for screenshot capture, region picking,
template matching, and OCR. All features mirror the previous PySide6 /
Tkinter versions but rendered via Dear PyGui's immediate-mode UI.

Features
--------
- Device picker (ADBController + DeviceScanner)
- Screenshot capture (manual + auto-refresh)
- Click image to pick a point (device coordinates)
- Drag a region -> save crop / OCR
- Template match tester (threshold / grayscale / multi-scale)
- Color picker (RGB / HEX at last clicked point)
- Manual tap / swipe sender
- OCR via OCRReader (RapidOCR / PaddleOCR / Tesseract)
- Live device info panel

Run::

    python tools/dev_helper.py

Saved files default to ``./out/`` next to the project root.
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# --- bootstrap -----------------------------------------------------------

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# UTF-8 stdout/stderr for Windows console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

import cv2
import dearpygui.dearpygui as dpg
import numpy as np

from src.core.adb import ADBController, DeviceScanner
from src.core.adb.auto.template_matcher import TemplateMatcher
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)


# --- constants -----------------------------------------------------------

DEFAULT_OUT_DIR = os.path.join(_PROJECT_ROOT, "out")


def _ensure_out_dir() -> str:
    os.makedirs(DEFAULT_OUT_DIR, exist_ok=True)
    return DEFAULT_OUT_DIR


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _bgr_to_rgba_float(bgr: np.ndarray) -> Tuple[np.ndarray, int, int]:
    """Convert OpenCV BGR ndarray to a flat RGBA float32 (0-1) buffer."""
    if bgr is None or bgr.size == 0:
        return np.zeros(4, dtype=np.float32), 1, 1
    if len(bgr.shape) == 2:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    rgba = np.empty((h, w, 4), dtype=np.float32)
    rgba[..., :3] = rgb.astype(np.float32) / 255.0
    rgba[..., 3] = 1.0
    return rgba.ravel(), w, h


# --- workers (threads, drained from frame loop) ---------------------------


@dataclass
class _CaptureResult:
    img: Optional[np.ndarray] = None
    error: Optional[str] = None


@dataclass
class _DeviceInfoResult:
    info: dict = field(default_factory=dict)
    error: Optional[str] = None


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


def _capture_worker(controller: ADBController, q: "queue.Queue") -> None:
    try:
        raw = controller.capture_screen_raw()
        if not raw:
            q.put(_CaptureResult(error="Empty screenshot from device"))
            return
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            q.put(_CaptureResult(error="Failed to decode PNG screenshot"))
            return
        q.put(_CaptureResult(img=img))
    except Exception as exc:
        q.put(_CaptureResult(error=str(exc)))


def _device_info_worker(controller: ADBController, q: "queue.Queue") -> None:
    device = controller.device
    if device is None:
        q.put(_DeviceInfoResult(error="No device"))
        return
    try:
        info: dict = {"serial": device.serial, "state": "device"}

        getprop_cmd = " ; ".join(f"getprop {p}" for p in _DEVICE_INFO_PROPS)
        raw_lines = _shell(device, getprop_cmd).splitlines()
        values = [line.strip() for line in raw_lines]
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
        info["app_package"] = pkg or "-"
        info["app_name"] = (
            controller._get_app_name_for_package(pkg) if pkg else "-"
        )

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

        q.put(_DeviceInfoResult(info=info))
    except Exception as exc:
        q.put(_DeviceInfoResult(error=str(exc)))


# --- main app -----------------------------------------------------------


class DevHelper:
    """Dear PyGui-based dev helper.

    DPG is immediate-mode and tag-based: widgets are referenced by string
    IDs rather than object handles. The class wraps the global DPG state
    so we can keep ADB / matcher / OCR helpers as instance attributes.
    """

    AUTO_REFRESH_MIN_HZ = 0.2
    AUTO_REFRESH_MAX_HZ = 5.0
    INFO_REFRESH_INTERVAL = 2.0  # seconds

    # Tag constants kept here for editor autocomplete / search.
    T_VIEWPORT       = "viewport"
    T_PRIMARY_WIN    = "primary_window"
    T_DEVICE_COMBO   = "device_combo"
    T_DEV_STATUS     = "dev_status"
    T_AUTO_CHK       = "auto_chk"
    T_HZ_SPIN        = "hz_spin"
    T_PREVIEW_CANVAS = "preview_canvas"
    T_PREVIEW_DRAW   = "preview_draw"
    T_PREVIEW_TEX    = "preview_tex"
    T_SIZE_LABEL     = "size_label"
    T_STATUS_BAR     = "status_bar"
    T_LOG_CHILD      = "log_child"

    # Inspect tab fields
    T_POINT_X        = "point_x"
    T_POINT_Y        = "point_y"
    T_COLOR_HEX      = "color_hex"
    T_COLOR_RGB      = "color_rgb"
    T_COLOR_SWATCH   = "color_swatch"
    T_REGION_X       = "region_x"
    T_REGION_Y       = "region_y"
    T_REGION_W       = "region_w"
    T_REGION_H       = "region_h"
    T_TAP_X          = "tap_x"
    T_TAP_Y          = "tap_y"
    T_SWIPE_X1       = "swipe_x1"
    T_SWIPE_Y1       = "swipe_y1"
    T_SWIPE_X2       = "swipe_x2"
    T_SWIPE_Y2       = "swipe_y2"
    T_SWIPE_DUR      = "swipe_dur"
    T_OCR_RESULT     = "ocr_result"
    T_OCR_WHITELIST  = "ocr_whitelist"
    T_OCR_ENGINE     = "ocr_engine"
    T_OCR_ASCII      = "ocr_ascii"

    # Template tab
    T_TPL_PATH       = "tpl_path"
    T_TPL_THRESHOLD  = "tpl_threshold"
    T_TPL_GRAYSCALE  = "tpl_grayscale"
    T_TPL_MULTISCALE = "tpl_multiscale"
    T_TPL_RESULT     = "tpl_result"

    def __init__(self) -> None:
        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()
        self.matcher = TemplateMatcher(cache_size=64)

        self._screen: Optional[np.ndarray] = None
        self._template_path: Optional[str] = None
        self._ocr_reader = None

        self._capture_in_flight = False
        self._info_in_flight = False
        self._capture_q: "queue.Queue[_CaptureResult]" = queue.Queue()
        self._info_q: "queue.Queue[_DeviceInfoResult]" = queue.Queue()

        self._last_info_refresh = 0.0
        self._last_auto_capture = 0.0
        self._auto_refresh_enabled = False
        self._refresh_hz = 1.0

        # Image / canvas state
        self._tex_w = 1
        self._tex_h = 1
        self._canvas_w = 800
        self._canvas_h = 600
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0

        # Mouse / drag state
        self._dragging = False
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_end: Optional[Tuple[int, int]] = None

        # Picked / selected state (image coords)
        self._last_point: Optional[Tuple[int, int]] = None
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._overlay: List[Tuple[int, int, int, int, float]] = []

        # Device labels parallel to combobox indices (so we can resolve
        # serial after the user picks a label).
        self._device_labels: List[str] = []

        # Field tags whose .StringValue will be filled by the device-info
        # worker. label, key.
        self._info_keys: List[Tuple[str, str]] = [
            ("Status",     "status"),
            ("Serial",     "serial"),
            ("Model",      "model"),
            ("Brand",      "brand"),
            ("Android",    "android"),
            ("ABI",        "ro.product.cpu.abi"),
            ("Resolution", "screen_size"),
            ("Density",    "screen_density"),
            ("Battery",    "battery"),
            ("IP",         "ip"),
            ("Uptime",     "uptime"),
            ("App",        "app"),
        ]
        self._info_tags: dict[str, str] = {}

    # ----- DPG setup -----

    def setup(self) -> None:
        dpg.create_context()

        with dpg.texture_registry():
            # Empty placeholder texture; resized when the first frame arrives.
            dpg.add_dynamic_texture(
                width=self._tex_w, height=self._tex_h,
                default_value=[0.1, 0.1, 0.1, 1.0],
                tag=self.T_PREVIEW_TEX,
            )

        with dpg.window(tag=self.T_PRIMARY_WIN, label="Dev Helper",
                        no_title_bar=True, no_move=True, no_resize=True,
                        no_collapse=True):
            self._build_toolbar()
            dpg.add_separator()
            with dpg.group(horizontal=True):
                self._build_preview()
                self._build_tools_panel()
            dpg.add_separator()
            self._build_log_panel()
            dpg.add_separator()
            dpg.add_text("", tag=self.T_STATUS_BAR)

        dpg.create_viewport(
            title="ADB Auto-Game - Dev Helper",
            width=1280, height=820, min_width=1000, min_height=680,
        )
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_primary_window(self.T_PRIMARY_WIN, True)
        dpg.set_viewport_resize_callback(self._on_viewport_resize)

        # Mouse handlers (global for the canvas).
        with dpg.handler_registry():
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._on_mouse_click,
            )
            dpg.add_mouse_release_handler(
                button=dpg.mvMouseButton_Left,
                callback=self._on_mouse_release,
            )
            dpg.add_key_press_handler(
                key=dpg.mvKey_F5,
                callback=lambda *_: self._capture_async(),
            )

        add_log_subscriber(self._on_log_bus)
        self._refresh_devices()
        self._refresh_device_info_async()

    # ----- toolbar ----------------------------------------------------------

    def _build_toolbar(self) -> None:
        with dpg.group(horizontal=True):
            dpg.add_text("Device:")
            dpg.add_combo(
                items=[], tag=self.T_DEVICE_COMBO, width=320,
                callback=self._on_device_changed,
            )
            dpg.add_button(label="Refresh", callback=self._refresh_devices)
            dpg.add_button(label="Scan ports", callback=self._scan_ports)
            dpg.add_button(label="Restart ADB", callback=self._restart_adb)
            dpg.add_text("|")
            dpg.add_button(label="Capture (F5)", callback=self._capture_async)
            dpg.add_checkbox(label="Auto", tag=self.T_AUTO_CHK,
                             callback=self._on_auto_toggle)
            dpg.add_text("Hz:")
            dpg.add_input_float(
                tag=self.T_HZ_SPIN, default_value=1.0,
                min_value=self.AUTO_REFRESH_MIN_HZ,
                max_value=self.AUTO_REFRESH_MAX_HZ,
                min_clamped=True, max_clamped=True,
                step=0.5, format="%.1f", width=80,
                callback=self._on_hz_changed,
            )
            dpg.add_spacer(width=20)
            dpg.add_text("Not connected", tag=self.T_DEV_STATUS)

    # ----- preview ----------------------------------------------------------

    def _build_preview(self) -> None:
        with dpg.child_window(width=-380, height=-110,
                              border=True, tag=self.T_PREVIEW_CANVAS):
            with dpg.group(horizontal=True):
                dpg.add_text("Preview")
                dpg.add_text("", tag=self.T_SIZE_LABEL)
                dpg.add_text(
                    "  (click = pick point, drag = select region)",
                )
            # Drawlist receives the image + all overlays. We resize it to
            # match the parent child_window in _on_viewport_resize.
            dpg.add_drawlist(
                width=800, height=600, tag=self.T_PREVIEW_DRAW,
            )

    # ----- tools panel ------------------------------------------------------

    def _build_tools_panel(self) -> None:
        # Single scrollable panel, no tabs. Sections are grouped under
        # bold dividers and each one is a collapsing header so users
        # can fold away the bits they don't need.
        with dpg.child_window(width=380, height=-110, border=True):
            self._section_divider("DEVICE")
            self._build_device_section()

            self._section_divider("TEMPLATE")
            self._build_template_section()

            self._section_divider("INSPECT")
            self._build_inspect_section()

    @staticmethod
    def _section_divider(label: str) -> None:
        """Bold uppercase label + thin separator to group related headers."""
        dpg.add_spacer(height=4)
        dpg.add_text(label)
        dpg.add_separator()
        dpg.add_spacer(height=2)

    def _build_inspect_section(self) -> None:
        with dpg.collapsing_header(label="Screenshot", default_open=True):
            with dpg.group(horizontal=True):
                dpg.add_button(label="Save full...", callback=self._save_full)
                dpg.add_button(label="Load file...",
                               callback=self._load_image_from_file)

        with dpg.collapsing_header(label="Point & Color", default_open=True):
            with dpg.group(horizontal=True):
                dpg.add_text("X:")
                dpg.add_input_text(tag=self.T_POINT_X, width=70, readonly=True)
                dpg.add_text("Y:")
                dpg.add_input_text(tag=self.T_POINT_Y, width=70, readonly=True)
            with dpg.group(horizontal=True):
                dpg.add_text("HEX:")
                dpg.add_input_text(tag=self.T_COLOR_HEX, width=90, readonly=True)
                dpg.add_color_button(
                    tag=self.T_COLOR_SWATCH,
                    default_value=(40, 40, 40, 255),
                    width=22, height=22, no_border=False,
                )
            with dpg.group(horizontal=True):
                dpg.add_text("RGB:")
                dpg.add_input_text(tag=self.T_COLOR_RGB, width=180, readonly=True)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Copy x,y", callback=self._copy_xy)
                dpg.add_button(label="Copy HEX", callback=self._copy_hex)
                dpg.add_button(label="Tap point", callback=self._tap_picked)

        with dpg.collapsing_header(label="Region", default_open=True):
            with dpg.group(horizontal=True):
                dpg.add_text("X:")
                dpg.add_input_int(tag=self.T_REGION_X, width=80,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
                dpg.add_text("Y:")
                dpg.add_input_int(tag=self.T_REGION_Y, width=80,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
            with dpg.group(horizontal=True):
                dpg.add_text("W:")
                dpg.add_input_int(tag=self.T_REGION_W, width=80,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
                dpg.add_text("H:")
                dpg.add_input_int(tag=self.T_REGION_H, width=80,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Apply",
                               callback=self._apply_manual_region)
                dpg.add_button(label="Save crop...", callback=self._save_region)
                dpg.add_button(label="Copy x,y,w,h", callback=self._copy_region)
                dpg.add_button(label="Clear", callback=self._clear_region)

            dpg.add_spacer(height=4)
            dpg.add_text("OCR")
            dpg.add_input_text(tag=self.T_OCR_RESULT, width=-1, readonly=True)
            with dpg.group(horizontal=True):
                dpg.add_input_text(
                    tag=self.T_OCR_WHITELIST, width=160,
                    hint="Whitelist e.g. 0123456789/",
                )
                dpg.add_button(label="Read text",
                               callback=self._read_region_text)
                dpg.add_button(label="Copy", callback=self._copy_ocr_result)
            with dpg.group(horizontal=True):
                dpg.add_checkbox(
                    label="ASCII only (strip Vietnamese diacritics)",
                    tag=self.T_OCR_ASCII, default_value=False,
                )
            with dpg.group(horizontal=True):
                dpg.add_text("Engine:")
                dpg.add_text("not loaded", tag=self.T_OCR_ENGINE)

        with dpg.collapsing_header(label="Tap", default_open=True):
            with dpg.group(horizontal=True):
                dpg.add_text("X:")
                dpg.add_input_int(tag=self.T_TAP_X, width=80,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
                dpg.add_text("Y:")
                dpg.add_input_int(tag=self.T_TAP_Y, width=80,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
            dpg.add_button(label="Send tap", callback=self._send_tap_manual,
                           width=-1)

        with dpg.collapsing_header(label="Swipe", default_open=False):
            with dpg.group(horizontal=True):
                dpg.add_text("From:")
                dpg.add_input_int(tag=self.T_SWIPE_X1, width=70,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
                dpg.add_input_int(tag=self.T_SWIPE_Y1, width=70,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
            with dpg.group(horizontal=True):
                dpg.add_text("To:  ")
                dpg.add_input_int(tag=self.T_SWIPE_X2, width=70,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
                dpg.add_input_int(tag=self.T_SWIPE_Y2, width=70,
                                  default_value=0, min_value=0, min_clamped=True,
                                  step=0)
            with dpg.group(horizontal=True):
                dpg.add_text("Dur: ")
                dpg.add_input_int(tag=self.T_SWIPE_DUR, width=80,
                                  default_value=300, min_value=50,
                                  min_clamped=True, step=50)
                dpg.add_text("ms")
            dpg.add_button(label="Send swipe", callback=self._send_swipe,
                           width=-1)

    def _build_template_section(self) -> None:
        with dpg.collapsing_header(label="Template Match", default_open=True):
            dpg.add_text("Pick a template PNG and run it against the screenshot.",
                         wrap=350)
            dpg.add_spacer(height=4)
            with dpg.group(horizontal=True):
                dpg.add_input_text(tag=self.T_TPL_PATH, width=-90,
                                   hint="Path to template PNG")
                dpg.add_button(label="Browse...",
                               callback=self._browse_template)
            dpg.add_spacer(height=6)
            dpg.add_input_float(
                tag=self.T_TPL_THRESHOLD, label="Threshold",
                default_value=0.85, min_value=0.1, max_value=0.999,
                min_clamped=True, max_clamped=True, step=0.05, format="%.2f",
                width=120,
            )
            dpg.add_checkbox(label="Grayscale", tag=self.T_TPL_GRAYSCALE)
            dpg.add_checkbox(label="Multi-scale (0.8 .. 1.2)",
                             tag=self.T_TPL_MULTISCALE)
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Find best match",
                               callback=lambda: self._run_match(False))
                dpg.add_button(label="Find all matches",
                               callback=lambda: self._run_match(True))
            dpg.add_button(label="Clear overlay", callback=self._clear_overlay,
                           width=-1)
            dpg.add_spacer(height=6)
            dpg.add_text("No match yet.", tag=self.T_TPL_RESULT,
                         wrap=350)

    def _build_device_section(self) -> None:
        with dpg.collapsing_header(label="Device Info", default_open=True):
            dpg.add_text("Live info. Refreshes every 2 s.",
                         wrap=350)
            dpg.add_spacer(height=4)
            with dpg.table(header_row=False, resizable=False,
                           borders_innerH=False, borders_outerH=False,
                           borders_innerV=False, borders_outerV=False):
                dpg.add_table_column(width_fixed=True, init_width_or_weight=90)
                dpg.add_table_column(width_stretch=True)
                for label, key in self._info_keys:
                    with dpg.table_row():
                        dpg.add_text(f"{label}:")
                        tag = f"info_{key}"
                        self._info_tags[key] = tag
                        dpg.add_text("-", tag=tag, wrap=240)
            dpg.add_spacer(height=6)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Refresh info",
                               callback=self._refresh_device_info_async)
                dpg.add_button(label="Copy info",
                               callback=self._copy_device_info)

    # ----- log panel --------------------------------------------------------

    def _build_log_panel(self) -> None:
        with dpg.group(horizontal=True):
            dpg.add_text("Log")
            dpg.add_button(label="Clear", callback=self._clear_log,
                           small=True)
        dpg.add_child_window(tag=self.T_LOG_CHILD, height=120, border=True)

    # ===== run loop =======================================================

    def run(self) -> None:
        """Main render loop. Drains worker queues + handles auto-refresh."""
        while dpg.is_dearpygui_running():
            self._drain_queues()
            self._handle_auto_refresh()
            self._handle_periodic_info_refresh()
            self._handle_drag_motion()
            dpg.render_dearpygui_frame()
        try:
            remove_log_subscriber(self._on_log_bus)
        except Exception:
            pass
        dpg.destroy_context()

    # ===== viewport / canvas sizing ======================================

    def _on_viewport_resize(self, _sender=None, _app=None) -> None:
        # Resize the drawlist to fill the preview child window.
        try:
            cw = dpg.get_item_rect_size(self.T_PREVIEW_CANVAS)
        except Exception:
            return
        if not cw or len(cw) < 2:
            return
        new_w = max(200, int(cw[0]) - 16)
        new_h = max(200, int(cw[1]) - 60)  # leave room for header text
        if (new_w, new_h) == (self._canvas_w, self._canvas_h):
            return
        self._canvas_w = new_w
        self._canvas_h = new_h
        dpg.configure_item(self.T_PREVIEW_DRAW, width=new_w, height=new_h)
        self._render_canvas()

    # ===== device ops ====================================================

    def _refresh_devices(self, *_a) -> None:
        try:
            self.scanner.ensure_adb_server_running()
            devices = self.controller.client.devices()
        except Exception as exc:
            log_warning(f"ADB server unreachable: {exc}")
            devices = []

        prev_serial = ""
        cur = dpg.get_value(self.T_DEVICE_COMBO)
        if cur and "  -  " in cur:
            prev_serial = cur.split("  -  ")[0]
        elif cur:
            prev_serial = cur

        items: List[str] = []
        if not devices:
            self.controller.device = None
            self.controller.device_id = None
            self._set_status("No ADB devices. Try Scan ports.")
        else:
            for d in devices:
                try:
                    model = (d.shell("getprop ro.product.model") or "").strip()
                except Exception:
                    model = ""
                label = f"{d.serial}  -  {model}" if model else d.serial
                items.append(label)
        self._device_labels = items
        dpg.configure_item(self.T_DEVICE_COMBO, items=items)
        if items:
            sel = items[0]
            for it in items:
                if it.startswith(prev_serial) and prev_serial:
                    sel = it
                    break
            dpg.set_value(self.T_DEVICE_COMBO, sel)
            self._select_device(sel.split("  -  ")[0])
        else:
            dpg.set_value(self.T_DEVICE_COMBO, "(no devices)")

        self._refresh_device_info_async()

    def _select_device(self, serial: Optional[str]) -> None:
        if not serial:
            return
        try:
            for d in self.controller.client.devices():
                if d.serial == serial:
                    self.controller.device = d
                    self.controller.device_id = d.serial
                    name = self.controller.get_device_name()
                    width, height = self.controller.get_screen_size()
                    self._set_status(
                        f"Connected: {serial} ({name}) - {width}x{height}"
                    )
                    return
            self._set_status(f"Device {serial} not available")
        except Exception as exc:
            log_error(f"Failed to select device {serial}: {exc}")

    def _on_device_changed(self, _sender=None, app_data: str = "") -> None:
        if not app_data or "  -  " not in app_data:
            serial = app_data or ""
        else:
            serial = app_data.split("  -  ")[0]
        self._select_device(serial)
        self._refresh_device_info_async()

    def _scan_ports(self, *_a) -> None:
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
        self._refresh_devices()

    def _restart_adb(self, *_a) -> None:
        log_info("Restarting ADB server...")
        if self.scanner.restart_adb_server():
            log_success("ADB server restarted")
        else:
            log_error("Failed to restart ADB server")
        self._refresh_devices()

    # ===== device info ===================================================

    def _refresh_device_info_async(self, *_a) -> None:
        if self._info_in_flight:
            return
        if self.controller.device is None:
            self._set_device_info({
                "status": "Disconnected",
                "serial": "-", "model": "-", "brand": "-",
                "android": "-", "ro.product.cpu.abi": "-",
                "screen_size": "-", "screen_density": "-",
                "app": "-", "battery": "-", "ip": "-", "uptime": "-",
            })
            dpg.set_value(self.T_DEV_STATUS, "Not connected")
            return
        self._info_in_flight = True
        threading.Thread(
            target=_device_info_worker,
            args=(self.controller, self._info_q),
            daemon=True, name="dev-helper-info",
        ).start()

    def _on_device_info_fetched(self, info: dict) -> None:
        android = info.get("ro.build.version.release", "-")
        sdk = info.get("ro.build.version.sdk", "-")
        android_str = f"{android} (SDK {sdk})" if sdk and sdk != "-" else android

        model = info.get("ro.product.model", "-")
        brand = info.get("ro.product.brand", "-")
        manufacturer = info.get("ro.product.manufacturer", "-")
        if manufacturer and manufacturer != "-" and manufacturer.lower() != brand.lower():
            brand_str = f"{brand} / {manufacturer}"
        else:
            brand_str = brand

        app_pkg = info.get("app_package", "-")
        app_name = info.get("app_name", "-")
        if app_pkg and app_pkg != "-":
            app_str = f"{app_name}  ({app_pkg})" if app_name and app_name != "-" else app_pkg
        else:
            app_str = "-"

        ui = {
            "status": "Connected",
            "serial": info.get("serial", "-"),
            "model": model,
            "brand": brand_str,
            "android": android_str,
            "ro.product.cpu.abi": info.get("ro.product.cpu.abi", "-"),
            "screen_size": info.get("screen_size", "-"),
            "screen_density": info.get("screen_density", "-"),
            "app": app_str,
            "battery": info.get("battery", "-"),
            "ip": info.get("ip", "-"),
            "uptime": info.get("uptime", "-"),
        }
        self._set_device_info(ui)

        label = model.strip() or ui["serial"] or "Connected"
        if model and ui["serial"] and model != ui["serial"]:
            label = f"{model}  ({ui['serial']})"
        dpg.set_value(self.T_DEV_STATUS, label)
        self._set_status(
            f"{ui['serial']} | {model} | Android {android_str} | "
            f"{ui['screen_size']} | App: {app_str}"
        )

    def _set_device_info(self, ui: dict) -> None:
        for key, tag in self._info_tags.items():
            try:
                dpg.set_value(tag, str(ui.get(key, "-")))
            except Exception:
                pass

    def _copy_device_info(self, *_a) -> None:
        pretty = {
            "status": "Status", "serial": "Serial", "model": "Model",
            "brand": "Brand", "android": "Android",
            "ro.product.cpu.abi": "ABI",
            "screen_size": "Resolution", "screen_density": "Density",
            "app": "App", "battery": "Battery", "ip": "IP", "uptime": "Uptime",
        }
        lines = [
            f"{pretty.get(k, k)}: {dpg.get_value(tag)}"
            for k, tag in self._info_tags.items()
        ]
        dpg.set_clipboard_text("\n".join(lines))
        self._set_status("Copied device info")

    def _handle_periodic_info_refresh(self) -> None:
        now = time.monotonic()
        if now - self._last_info_refresh >= self.INFO_REFRESH_INTERVAL:
            self._last_info_refresh = now
            self._refresh_device_info_async()

    # ===== capture =======================================================

    def _capture_async(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device selected")
            return
        if self._capture_in_flight:
            return
        self._capture_in_flight = True
        threading.Thread(
            target=_capture_worker,
            args=(self.controller, self._capture_q),
            daemon=True, name="dev-helper-capture",
        ).start()

    def _on_captured(self, img: np.ndarray) -> None:
        old_size = (self._tex_w, self._tex_h)
        self._screen = img
        h, w = img.shape[:2]
        if (w, h) != old_size:
            # Resize the dynamic texture by deleting + re-adding (DPG
            # doesn't support resizing dynamic textures in place).
            try:
                dpg.delete_item(self.T_PREVIEW_TEX)
            except Exception:
                pass
            with dpg.texture_registry():
                rgba_flat, _, _ = _bgr_to_rgba_float(img)
                dpg.add_dynamic_texture(
                    width=w, height=h,
                    default_value=rgba_flat.tolist(),
                    tag=self.T_PREVIEW_TEX,
                )
            self._tex_w, self._tex_h = w, h
            # Resolution change: drop selections.
            self._region = None
            self._last_point = None
            self._overlay = []
        else:
            rgba_flat, _, _ = _bgr_to_rgba_float(img)
            dpg.set_value(self.T_PREVIEW_TEX, rgba_flat.tolist())

        dpg.set_value(self.T_SIZE_LABEL, f"  {w} x {h}")
        self._render_canvas()

    def _on_capture_failed(self, msg: str) -> None:
        log_error(f"Capture failed: {msg}")
        self._set_status(f"Capture failed: {msg}")

    # ----- auto-refresh -----

    def _on_auto_toggle(self, _sender=None, app_data: bool = False) -> None:
        self._auto_refresh_enabled = bool(app_data)
        if self._auto_refresh_enabled:
            self._set_status(f"Auto refresh: {self._refresh_hz:.1f} Hz")
        self._last_auto_capture = time.monotonic()

    def _on_hz_changed(self, _sender=None, app_data: float = 1.0) -> None:
        try:
            self._refresh_hz = float(app_data)
        except (TypeError, ValueError):
            self._refresh_hz = 1.0
        self._refresh_hz = max(self.AUTO_REFRESH_MIN_HZ,
                               min(self.AUTO_REFRESH_MAX_HZ, self._refresh_hz))

    def _handle_auto_refresh(self) -> None:
        if not self._auto_refresh_enabled:
            return
        now = time.monotonic()
        period = 1.0 / max(0.1, self._refresh_hz)
        if now - self._last_auto_capture >= period:
            self._last_auto_capture = now
            self._capture_async()

    # ===== queue draining ================================================

    def _drain_queues(self) -> None:
        try:
            while True:
                res = self._capture_q.get_nowait()
                self._capture_in_flight = False
                if res.error:
                    self._on_capture_failed(res.error)
                elif res.img is not None:
                    self._on_captured(res.img)
        except queue.Empty:
            pass
        try:
            while True:
                res = self._info_q.get_nowait()
                self._info_in_flight = False
                if res.error:
                    if "status" in self._info_tags:
                        dpg.set_value(self._info_tags["status"],
                                      f"Error: {res.error}")
                    dpg.set_value(self.T_DEV_STATUS, "Not connected")
                elif res.info:
                    self._on_device_info_fetched(res.info)
        except queue.Empty:
            pass

    # ===== mouse / canvas ================================================

    def _on_mouse_click(self, _sender=None, _data=None) -> None:
        # Only start a drag when the mouse is over the drawlist.
        if not dpg.is_item_hovered(self.T_PREVIEW_DRAW):
            return
        if self._screen is None:
            return
        x, y = dpg.get_mouse_pos(local=False)
        # Translate to drawlist-local (drawlist sits inside the child window
        # with its own padding; ``get_drawing_mouse_pos`` returns coords in
        # the drawlist space which is exactly what we want).
        try:
            lx, ly = dpg.get_drawing_mouse_pos()
        except Exception:
            lx, ly = x, y
        self._dragging = True
        self._drag_start = (int(lx), int(ly))
        self._drag_end = self._drag_start
        self._render_canvas()

    def _handle_drag_motion(self) -> None:
        if not self._dragging:
            return
        if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            return
        try:
            lx, ly = dpg.get_drawing_mouse_pos()
        except Exception:
            return
        new_end = (int(lx), int(ly))
        if new_end != self._drag_end:
            self._drag_end = new_end
            self._render_canvas()

    def _on_mouse_release(self, _sender=None, _data=None) -> None:
        if not self._dragging or self._screen is None:
            self._dragging = False
            return
        self._dragging = False
        start = self._drag_start
        end = self._drag_end
        self._drag_start = None
        self._drag_end = None
        if not start or not end:
            self._render_canvas()
            return

        dx, dy = end[0] - start[0], end[1] - start[1]
        if abs(dx) + abs(dy) < 5:
            pt = self._widget_to_image(*end)
            if pt is not None:
                self._last_point = pt
                self._region = None
                self._on_point_picked(*pt)
        else:
            p1 = self._widget_to_image(*start) or (0, 0)
            p2 = self._widget_to_image(*end) or (0, 0)
            x1, y1 = p1
            x2, y2 = p2
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            if rw > 1 and rh > 1:
                self._region = (rx, ry, rw, rh)
                self._last_point = None
                self._on_region_picked(rx, ry, rw, rh)

        self._render_canvas()

    # Coordinate mapping ---------------------------------------------------

    def _recompute_layout(self) -> None:
        if self._screen is None or self._tex_w <= 0 or self._tex_h <= 0:
            self._scale, self._offset_x, self._offset_y = 1.0, 0, 0
            return
        ww = max(1, self._canvas_w)
        wh = max(1, self._canvas_h)
        self._scale = min(ww / self._tex_w, wh / self._tex_h)
        draw_w = int(self._tex_w * self._scale)
        draw_h = int(self._tex_h * self._scale)
        self._offset_x = (ww - draw_w) // 2
        self._offset_y = (wh - draw_h) // 2

    def _widget_to_image(self, x: int, y: int) -> Optional[Tuple[int, int]]:
        if self._screen is None or self._scale <= 0:
            return None
        ix = int(round((x - self._offset_x) / self._scale))
        iy = int(round((y - self._offset_y) / self._scale))
        if 0 <= ix < self._tex_w and 0 <= iy < self._tex_h:
            return (ix, iy)
        return None

    def _image_to_widget_rect(
        self, x: int, y: int, w: int, h: int
    ) -> Tuple[int, int, int, int]:
        rx = int(self._offset_x + x * self._scale)
        ry = int(self._offset_y + y * self._scale)
        rw = max(1, int(w * self._scale))
        rh = max(1, int(h * self._scale))
        return (rx, ry, rx + rw, ry + rh)

    def _render_canvas(self) -> None:
        # Clear all draw items, then redraw image + overlays.
        try:
            dpg.delete_item(self.T_PREVIEW_DRAW, children_only=True)
        except Exception:
            return

        if self._screen is None:
            dpg.draw_text(
                (10, 10),
                "No screenshot yet. Press 'Capture' (F5) to grab one.",
                size=14,
                parent=self.T_PREVIEW_DRAW,
            )
            return

        self._recompute_layout()
        draw_w = max(1, int(self._tex_w * self._scale))
        draw_h = max(1, int(self._tex_h * self._scale))
        dpg.draw_image(
            self.T_PREVIEW_TEX,
            (self._offset_x, self._offset_y),
            (self._offset_x + draw_w, self._offset_y + draw_h),
            parent=self.T_PREVIEW_DRAW,
        )

        # Match overlay (red).
        for x, y, w, h, conf in self._overlay:
            x0, y0, x1, y1 = self._image_to_widget_rect(x, y, w, h)
            dpg.draw_rectangle(
                (x0, y0), (x1, y1),
                color=(220, 38, 38, 255), thickness=2,
                parent=self.T_PREVIEW_DRAW,
            )
            dpg.draw_text(
                (x0 + 2, y0 - 16), f"{conf:.2f}",
                color=(220, 38, 38, 255), size=12,
                parent=self.T_PREVIEW_DRAW,
            )

        # Selected region (cyan).
        if self._region:
            x, y, w, h = self._region
            x0, y0, x1, y1 = self._image_to_widget_rect(x, y, w, h)
            dpg.draw_rectangle(
                (x0, y0), (x1, y1),
                color=(6, 182, 212, 255), thickness=2,
                parent=self.T_PREVIEW_DRAW,
            )

        # Last-clicked point (yellow crosshair).
        if self._last_point:
            x, y = self._last_point
            cx = int(self._offset_x + x * self._scale)
            cy = int(self._offset_y + y * self._scale)
            dpg.draw_line((cx - 8, cy), (cx + 8, cy),
                          color=(234, 179, 8, 255), thickness=2,
                          parent=self.T_PREVIEW_DRAW)
            dpg.draw_line((cx, cy - 8), (cx, cy + 8),
                          color=(234, 179, 8, 255), thickness=2,
                          parent=self.T_PREVIEW_DRAW)

        # Drag preview.
        if self._dragging and self._drag_start and self._drag_end:
            x0, y0 = self._drag_start
            x1, y1 = self._drag_end
            dpg.draw_rectangle(
                (x0, y0), (x1, y1),
                color=(6, 182, 212, 200), thickness=1,
                parent=self.T_PREVIEW_DRAW,
            )

    # ===== point / colour ================================================

    def _on_point_picked(self, x: int, y: int) -> None:
        dpg.set_value(self.T_POINT_X, str(x))
        dpg.set_value(self.T_POINT_Y, str(y))
        dpg.set_value(self.T_TAP_X, x)
        dpg.set_value(self.T_TAP_Y, y)
        if self._screen is not None:
            b, g, r = self._screen[y, x][:3]
            r, g, b = int(r), int(g), int(b)
            dpg.set_value(self.T_COLOR_HEX, f"#{r:02X}{g:02X}{b:02X}")
            dpg.set_value(self.T_COLOR_RGB, f"{r}, {g}, {b}")
            try:
                dpg.configure_item(self.T_COLOR_SWATCH,
                                   default_value=(r, g, b, 255))
            except Exception:
                pass
        self._set_status(f"Picked ({x}, {y})")

    def _copy_xy(self, *_a) -> None:
        x = dpg.get_value(self.T_POINT_X)
        y = dpg.get_value(self.T_POINT_Y)
        if not x or not y:
            return
        dpg.set_clipboard_text(f"{x}, {y}")
        self._set_status("Copied x,y")

    def _copy_hex(self, *_a) -> None:
        v = dpg.get_value(self.T_COLOR_HEX)
        if not v:
            return
        dpg.set_clipboard_text(v)
        self._set_status("Copied HEX")

    def _tap_picked(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device")
            return
        try:
            x = int(dpg.get_value(self.T_POINT_X) or "0")
            y = int(dpg.get_value(self.T_POINT_Y) or "0")
        except ValueError:
            return
        if self.controller.tap(x, y):
            log_success(f"Tapped ({x}, {y})")
        else:
            log_error(f"Tap failed at ({x}, {y})")

    # ===== region ========================================================

    def _on_region_picked(self, x: int, y: int, w: int, h: int) -> None:
        dpg.set_value(self.T_REGION_X, x)
        dpg.set_value(self.T_REGION_Y, y)
        dpg.set_value(self.T_REGION_W, w)
        dpg.set_value(self.T_REGION_H, h)
        self._sync_tap_to_region_center(x, y, w, h)
        self._set_status(
            f"Region {x},{y} {w}x{h} - tap target = "
            f"({x + w // 2}, {y + h // 2})"
        )

    def _sync_tap_to_region_center(
        self, x: int, y: int, w: int, h: int
    ) -> None:
        cx = x + w // 2
        cy = y + h // 2
        dpg.set_value(self.T_TAP_X, cx)
        dpg.set_value(self.T_TAP_Y, cy)
        dpg.set_value(self.T_POINT_X, str(cx))
        dpg.set_value(self.T_POINT_Y, str(cy))
        if (self._screen is not None
                and 0 <= cy < self._screen.shape[0]
                and 0 <= cx < self._screen.shape[1]):
            b, g, r = self._screen[cy, cx][:3]
            r, g, b = int(r), int(g), int(b)
            dpg.set_value(self.T_COLOR_HEX, f"#{r:02X}{g:02X}{b:02X}")
            dpg.set_value(self.T_COLOR_RGB, f"{r}, {g}, {b}")
            try:
                dpg.configure_item(self.T_COLOR_SWATCH,
                                   default_value=(r, g, b, 255))
            except Exception:
                pass

    def _apply_manual_region(self, *_a) -> None:
        if self._screen is None:
            return
        x = int(dpg.get_value(self.T_REGION_X) or 0)
        y = int(dpg.get_value(self.T_REGION_Y) or 0)
        w = int(dpg.get_value(self.T_REGION_W) or 0)
        h = int(dpg.get_value(self.T_REGION_H) or 0)
        if w <= 0 or h <= 0:
            return
        self._region = (x, y, w, h)
        self._last_point = None
        self._sync_tap_to_region_center(x, y, w, h)
        self._render_canvas()

    def _clear_region(self, *_a) -> None:
        self._region = None
        for tag in (self.T_REGION_X, self.T_REGION_Y,
                    self.T_REGION_W, self.T_REGION_H):
            dpg.set_value(tag, 0)
        self._render_canvas()

    def _current_region(self) -> Optional[Tuple[int, int, int, int]]:
        if self._region and self._region[2] > 0 and self._region[3] > 0:
            return self._region
        x = int(dpg.get_value(self.T_REGION_X) or 0)
        y = int(dpg.get_value(self.T_REGION_Y) or 0)
        w = int(dpg.get_value(self.T_REGION_W) or 0)
        h = int(dpg.get_value(self.T_REGION_H) or 0)
        if w > 0 and h > 0:
            return (x, y, w, h)
        return None

    def _copy_region(self, *_a) -> None:
        region = self._current_region()
        if not region:
            self._set_status("No region selected")
            return
        x, y, w, h = region
        dpg.set_clipboard_text(f"{x}, {y}, {w}, {h}")
        self._set_status(f"Copied region {x}, {y}, {w}, {h}")

    def _save_region(self, *_a) -> None:
        if self._screen is None or not self._region:
            self._set_status("No region to save")
            return
        x, y, w, h = self._region
        crop = self._screen[y:y + h, x:x + w].copy()
        self._open_save_dialog(
            tag="save_region_dialog",
            label="Save region",
            suggested=f"region_{_ts()}_{w}x{h}.png",
            on_pick=lambda path: self._save_image_to(path, crop, "region"),
        )

    # ===== save full / load ==============================================

    def _save_full(self, *_a) -> None:
        if self._screen is None:
            self._set_status("Capture a screenshot first")
            return
        self._open_save_dialog(
            tag="save_full_dialog",
            label="Save screenshot",
            suggested=f"screenshot_{_ts()}.png",
            on_pick=lambda path: self._save_image_to(path, self._screen,
                                                    "screenshot"),
        )

    def _load_image_from_file(self, *_a) -> None:
        # Use a unique tag for each invocation so reopening the dialog works.
        tag = f"load_dialog_{int(time.monotonic() * 1000)}"

        def _picked(_s, app_data) -> None:
            sels = list(app_data.get("selections", {}).values())
            if not sels:
                return
            path = sels[0]
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None:
                log_error(f"Failed to load {path}")
                return
            self._on_captured(img)
            log_info(f"Loaded image: {path}")

        with dpg.file_dialog(directory_selector=False,
                             show=True, callback=_picked,
                             width=600, height=420, modal=True,
                             default_path=_ensure_out_dir(),
                             tag=tag):
            dpg.add_file_extension(".png")
            dpg.add_file_extension(".jpg")
            dpg.add_file_extension(".jpeg")
            dpg.add_file_extension(".bmp")
            dpg.add_file_extension(".*")

    def _open_save_dialog(self, tag: str, label: str, suggested: str,
                          on_pick) -> None:
        # Re-create per call to avoid stale state.
        try:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        except Exception:
            pass

        def _picked(_s, app_data) -> None:
            path = app_data.get("file_path_name") or ""
            if not path:
                return
            on_pick(path)

        with dpg.file_dialog(directory_selector=False,
                             show=True, callback=_picked,
                             width=600, height=420, modal=True,
                             default_path=_ensure_out_dir(),
                             default_filename=suggested,
                             tag=tag):
            dpg.add_file_extension(".png")
            dpg.add_file_extension(".*")

    @staticmethod
    def _save_image_to(path: str, img: np.ndarray, kind: str) -> None:
        if cv2.imwrite(path, img):
            log_success(f"Saved {kind}: {path}")
        else:
            log_error(f"Failed to write {path}")

    # ===== template matching =============================================

    def _browse_template(self, *_a) -> None:
        tag = f"tpl_dialog_{int(time.monotonic() * 1000)}"

        def _picked(_s, app_data) -> None:
            sels = list(app_data.get("selections", {}).values())
            if not sels:
                return
            path = sels[0]
            dpg.set_value(self.T_TPL_PATH, path)
            self._template_path = path

        start = (dpg.get_value(self.T_TPL_PATH)
                 or os.path.join(_PROJECT_ROOT, "assets"))
        if not os.path.isdir(start):
            start = os.path.dirname(start) or _PROJECT_ROOT

        with dpg.file_dialog(directory_selector=False,
                             show=True, callback=_picked,
                             width=600, height=420, modal=True,
                             default_path=start,
                             tag=tag):
            dpg.add_file_extension(".png")
            dpg.add_file_extension(".*")

    def _run_match(self, all_matches: bool) -> None:
        if self._screen is None:
            self._set_status("Capture a screenshot first")
            return
        path = (dpg.get_value(self.T_TPL_PATH) or "").strip()
        if not path or not os.path.exists(path):
            self._set_status("Pick a valid template path")
            return
        grayscale = bool(dpg.get_value(self.T_TPL_GRAYSCALE))
        threshold = float(dpg.get_value(self.T_TPL_THRESHOLD) or 0.85)
        multiscale = bool(dpg.get_value(self.T_TPL_MULTISCALE))

        tpl = self.matcher.load(path, grayscale=grayscale)
        if tpl is None:
            log_error(f"Could not load template: {path}")
            return
        th, tw = tpl.shape[:2]

        rects: List[Tuple[int, int, int, int, float]] = []
        if all_matches:
            results = self.matcher.match_all(
                self._screen, tpl,
                threshold=threshold, use_grayscale=grayscale,
            )
            for cx, cy, conf in results:
                x = max(0, cx - tw // 2)
                y = max(0, cy - th // 2)
                rects.append((x, y, tw, th, float(conf)))
            dpg.set_value(self.T_TPL_RESULT,
                          f"Found {len(results)} match(es).")
            log_info(f"match_all -> {len(results)} hit(s) (thr={threshold:.2f})")
        else:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2] if multiscale else None
            res = self.matcher.match(
                self._screen, tpl,
                threshold=threshold, use_grayscale=grayscale,
                multi_scale=multiscale, scales=scales,
            )
            if res is None:
                dpg.set_value(self.T_TPL_RESULT,
                              f"No match >= {threshold:.2f}.")
                self._overlay = []
                self._render_canvas()
                return
            cx, cy, conf, scale = res
            sw = int(tw * scale)
            sh = int(th * scale)
            x = max(0, cx - sw // 2)
            y = max(0, cy - sh // 2)
            rects.append((x, y, sw, sh, float(conf)))
            dpg.set_value(
                self.T_TPL_RESULT,
                f"Match: center=({cx},{cy}) conf={conf:.3f} scale={scale:.2f}"
            )
            log_info(
                f"match -> ({cx},{cy}) conf={conf:.3f} scale={scale:.2f}"
            )

        self._overlay = rects
        self._render_canvas()

    def _clear_overlay(self, *_a) -> None:
        self._overlay = []
        self._render_canvas()

    # ===== tap / swipe ===================================================

    def _send_tap_manual(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device")
            return
        x = int(dpg.get_value(self.T_TAP_X) or 0)
        y = int(dpg.get_value(self.T_TAP_Y) or 0)
        if self.controller.tap(x, y):
            log_success(f"Tapped ({x}, {y})")

    def _send_swipe(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device")
            return
        x1 = int(dpg.get_value(self.T_SWIPE_X1) or 0)
        y1 = int(dpg.get_value(self.T_SWIPE_Y1) or 0)
        x2 = int(dpg.get_value(self.T_SWIPE_X2) or 0)
        y2 = int(dpg.get_value(self.T_SWIPE_Y2) or 0)
        dur = int(dpg.get_value(self.T_SWIPE_DUR) or 300)
        if self.controller.swipe(x1, y1, x2, y2, dur):
            log_success(f"Swiped ({x1},{y1}) -> ({x2},{y2})")

    # ===== OCR ===========================================================

    def _read_region_text(self, *_a) -> None:
        if self._screen is None:
            self._set_status("Capture or load a screenshot first")
            return
        region = self._current_region()
        if not region:
            self._set_status("Drag a region or set X/Y/W/H first")
            return

        try:
            from src.core.adb.auto.ocr import OCRReader
        except ImportError as e:
            log_error(
                f"OCR module unavailable: {e}. Install one of: "
                "rapidocr-onnxruntime / paddleocr / pytesseract"
            )
            return

        if self._ocr_reader is None:
            self._ocr_reader = OCRReader()

        if not self._ocr_reader.available:
            log_error(
                "No OCR backend available. Install one of: "
                "rapidocr-onnxruntime / paddleocr / pytesseract"
            )
            return

        whitelist = (dpg.get_value(self.T_OCR_WHITELIST) or "").strip() or None
        text = self._ocr_reader.read_text(
            self._screen, region=region, whitelist=whitelist,
        )
        dpg.set_value(self.T_OCR_RESULT, text)
        engine = self._ocr_reader.backend_name
        dpg.set_value(self.T_OCR_ENGINE, engine if engine != "none" else "n/a")
        x, y, w, h = region
        if text:
            log_success(f"OCR [{engine}] ({x},{y} {w}x{h}) -> {text!r}")
        else:
            log_warning(f"OCR [{engine}] ({x},{y} {w}x{h}) -> (no text)")

    def _copy_ocr_result(self, *_a) -> None:
        text = dpg.get_value(self.T_OCR_RESULT) or ""
        if not text:
            self._set_status("No OCR result to copy")
            return
        dpg.set_clipboard_text(text)
        self._set_status("Copied OCR result")

    # ===== log ===========================================================

    def _on_log_bus(self, level: str, message: str) -> None:
        # Append from any thread; DPG widget mutation is thread-safe.
        try:
            ts = time.strftime("%H:%M:%S")
            with dpg.mutex():
                dpg.add_text(
                    f"[{ts}] [{level.upper()}] {message}",
                    parent=self.T_LOG_CHILD, wrap=0,
                )
                # Cap to ~2000 lines.
                kids = dpg.get_item_children(self.T_LOG_CHILD, 1) or []
                if len(kids) > 2000:
                    for stale in kids[: len(kids) - 2000]:
                        try:
                            dpg.delete_item(stale)
                        except Exception:
                            pass
                # Auto-scroll to bottom.
                try:
                    dpg.set_y_scroll(self.T_LOG_CHILD,
                                     dpg.get_y_scroll_max(self.T_LOG_CHILD))
                except Exception:
                    pass
        except Exception:
            pass

    def _clear_log(self, *_a) -> None:
        try:
            kids = dpg.get_item_children(self.T_LOG_CHILD, 1) or []
            for k in kids:
                dpg.delete_item(k)
        except Exception:
            pass

    # ===== status bar ====================================================

    def _set_status(self, msg: str) -> None:
        try:
            dpg.set_value(self.T_STATUS_BAR, msg)
        except Exception:
            pass


# --- entry point ---------------------------------------------------------


def main() -> int:
    app = DevHelper()
    app.setup()
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

