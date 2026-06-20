"""
Dev Helper - PySide6 utility for ADB auto-game development.

Modern Qt-based GUI for screenshot capture, region picking,
template matching, and OCR.

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
import numpy as np

from PySide6.QtCore import (
    Qt,
    QTimer,
    QSize,
    Signal,
    QRectF,
    QPointF,
    QPoint,
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QPainter,
    QColor,
    QPen,
    QBrush,
    QAction,
    QKeySequence,
    QShortcut,
    QPalette,
    QFontDatabase,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QSplitter,
    QComboBox,
    QPushButton,
    QCheckBox,
    QDoubleSpinBox,
    QLabel,
    QTabWidget,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QFileDialog,
    QPlainTextEdit,
    QStatusBar,
    QScrollArea,
    QGroupBox,
    QSizePolicy,
    QColorDialog,
    QMessageBox,
)

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


# ---------------------------------------------------------------------------
# Palette + QSS  (mirrors src/gui/pyside_gui.py for visual consistency)
# ---------------------------------------------------------------------------

class C:
    BG          = "#f0f0f0"
    PANEL       = "#ffffff"
    PANEL_ALT   = "#f5f5f5"
    BORDER      = "#dcdcdc"

    TEXT        = "#1a1a1a"
    TEXT_DIM    = "#555555"
    TEXT_MUTED  = "#888888"

    ACCENT      = "#3b82f6"
    ACCENT_BG   = "#eff6ff"

    OK          = "#16a34a"
    OK_BG       = "#dcfce7"
    WARN         = "#ea580c"
    WARN_BG     = "#fff7ed"
    ERR         = "#dc2626"
    ERR_BG      = "#fef2f2"
    INFO        = "#2563eb"
    INFO_BG     = "#eff6ff"


QSS = f"""
QMainWindow {{
    background-color: {C.BG};
}}

QWidget {{
    color: {C.TEXT};
    font-family: "Segoe UI", "Microsoft Sans Serif", sans-serif;
    font-size: 12px;
}}

QToolTip {{
    background-color: {C.TEXT};
    color: white;
    border: none;
    padding: 4px 8px;
    border-radius: 2px;
    font-size: 11px;
}}

QFrame#panel {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
}}

QLabel#title {{
    font-size: 13px;
    font-weight: 700;
    color: {C.TEXT};
}}
QLabel#subtitle {{
    color: {C.TEXT_MUTED};
    font-size: 11px;
}}

QPushButton {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 4px 10px;
    font-weight: 500;
    font-size: 12px;
}}
QPushButton:hover    {{ background-color: #e8e8e8; }}
QPushButton:pressed  {{ background-color: #ddd; }}
QPushButton:disabled {{ color: {C.TEXT_MUTED}; background-color: {C.PANEL_ALT}; }}

QPushButton#btnCapture {{
    background-color: {C.ACCENT};
    color: white;
    border: 1px solid {C.ACCENT};
    padding: 4px 14px;
    font-weight: 600;
}}
QPushButton#btnCapture:hover    {{ background-color: #2563eb; }}
QPushButton#btnCapture:pressed  {{ background-color: #1d4ed8; }}
QPushButton#btnCapture:disabled {{ background-color: #93c5fd; color: #dbeafe; }}

QPushButton.smallBtn {{
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.TEXT_DIM};
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton.smallBtn:hover {{ background-color: #e8e8e8; color: {C.TEXT}; }}
QPushButton.smallBtn:disabled {{ color: {C.TEXT_MUTED}; }}

QComboBox {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 3px 8px;
    min-height: 18px;
}}
QComboBox:hover {{ border-color: {C.ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.TEXT_DIM};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    selection-background-color: {C.ACCENT_BG};
    selection-color: {C.TEXT};
    outline: 0;
}}

QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 2px 6px;
    selection-background-color: {C.ACCENT};
    selection-color: white;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {C.ACCENT};
}}
QLineEdit:disabled {{ background-color: {C.PANEL_ALT}; color: {C.TEXT_MUTED}; }}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {C.PANEL_ALT};
    border: none;
    width: 14px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: #e0e0e0;
}}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {C.BORDER};
    background-color: {C.PANEL};
    border-radius: 2px;
}}
QCheckBox::indicator:hover {{ border-color: {C.ACCENT}; }}
QCheckBox::indicator:checked {{
    background-color: {C.ACCENT};
    border-color: {C.ACCENT};
    image: none;
}}

QTabWidget::pane {{
    border: 1px solid {C.BORDER};
    background: {C.PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background: {C.PANEL_ALT};
    color: {C.TEXT_DIM};
    border: 1px solid {C.BORDER};
    padding: 5px 16px;
    margin-right: 2px;
    font-weight: 500;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {C.PANEL};
    color: {C.TEXT};
    border-bottom-color: {C.PANEL};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{ background: #e0e0e0; color: {C.TEXT}; }}

QGroupBox {{
    background-color: transparent;
    border: 1px solid {C.BORDER};
    border-radius: 2px;
    margin-top: 10px;
    padding: 8px 8px 6px 8px;
    font-weight: 600;
    color: {C.TEXT_DIM};
    font-size: 11px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    background-color: {C.BG};
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QPlainTextEdit#logView {{
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #333;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    padding: 4px 6px;
}}

QStatusBar {{
    background-color: {C.PANEL};
    color: {C.TEXT_DIM};
    border-top: 1px solid {C.BORDER};
    padding: 1px 6px;
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {C.TEXT_DIM}; padding: 0 4px; }}

QSplitter::handle {{ background-color: {C.BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #c0c0c0;
    min-height: 14px;
}}
QScrollBar::handle:vertical:hover {{ background: #a0a0a0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 6px; background: transparent; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: #c0c0c0; min-width: 14px; }}
QScrollBar::handle:horizontal:hover {{ background: #a0a0a0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def _ensure_out_dir() -> str:
    os.makedirs(DEFAULT_OUT_DIR, exist_ok=True)
    return DEFAULT_OUT_DIR


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


# --- workers (threads, drained from main thread via Qt signals) ----------


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


def _bgr_to_qimage(bgr: np.ndarray) -> QImage:
    """Convert OpenCV BGR ndarray to a QImage (RGB888)."""
    if bgr is None or bgr.size == 0:
        return QImage()
    if len(bgr.shape) == 2:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.tobytes(), w, h, w * 3, QImage.Format_RGB888).copy()


# --- preview widget ------------------------------------------------------


class PreviewWidget(QWidget):
    """Displays the screenshot + overlays; emits pick / region signals."""

    pointPicked = Signal(int, int)
    regionPicked = Signal(int, int, int, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(400, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

        self._screen: Optional[np.ndarray] = None
        self._pixmap: Optional[QPixmap] = None

        # Layout transform: image -> widget
        self._scale = 1.0
        self._offset_x = 0
        self._offset_y = 0

        # Mouse / drag state (widget coords)
        self._dragging = False
        self._drag_start: Optional[QPoint] = None
        self._drag_end: Optional[QPoint] = None

        # Selections (image coords)
        self._last_point: Optional[Tuple[int, int]] = None
        self._region: Optional[Tuple[int, int, int, int]] = None
        self._overlay: List[Tuple[int, int, int, int, float]] = []

    # ----- image / state -----

    def set_image(self, bgr: Optional[np.ndarray]) -> None:
        self._screen = bgr
        if bgr is None or bgr.size == 0:
            self._pixmap = None
        else:
            self._pixmap = QPixmap.fromImage(_bgr_to_qimage(bgr))
            # If resolution changed, drop selections.
            h, w = bgr.shape[:2]
            prev_h = getattr(self, "_tex_h", 0)
            if prev_h and prev_h != h:
                self._region = None
                self._last_point = None
                self._overlay = []
            self._tex_w = w
            self._tex_h = h
        self.update()

    def set_overlay(self, rects: List[Tuple[int, int, int, int, float]]) -> None:
        self._overlay = rects
        self.update()

    def clear_overlay(self) -> None:
        self._overlay = []
        self.update()

    def set_region(self, rect: Optional[Tuple[int, int, int, int]]) -> None:
        self._region = rect
        self.update()

    def clear_selections(self) -> None:
        self._region = None
        self._last_point = None
        self._overlay = []
        self.update()

    # ----- coordinate mapping -----

    def _recompute_layout(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self._scale, self._offset_x, self._offset_y = 1.0, 0, 0
            return
        iw = self._pixmap.width()
        ih = self._pixmap.height()
        ww = max(1, self.width())
        wh = max(1, self.height())
        self._scale = min(ww / iw, wh / ih)
        dw = int(iw * self._scale)
        dh = int(ih * self._scale)
        self._offset_x = (ww - dw) // 2
        self._offset_y = (wh - dh) // 2

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
    ) -> QRectF:
        rx = self._offset_x + x * self._scale
        ry = self._offset_y + y * self._scale
        rw = max(1.0, w * self._scale)
        rh = max(1.0, h * self._scale)
        return QRectF(rx, ry, rw, rh)

    # ----- paint -----

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(18, 18, 18))

        if self._pixmap is None or self._pixmap.isNull():
            p.setPen(QColor(180, 180, 180))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "No screenshot yet. Press 'Capture' (F5) to grab one.")
            return

        self._recompute_layout()
        iw = self._pixmap.width()
        ih = self._pixmap.height()
        dw = int(iw * self._scale)
        dh = int(ih * self._scale)
        target = QRectF(self._offset_x, self._offset_y, dw, dh)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(target, self._pixmap,
                     QRectF(0, 0, iw, ih))

        # Match overlay (red).
        pen_red = QPen(QColor(220, 38, 38), 2)
        p.setPen(pen_red)
        p.setBrush(Qt.NoBrush)
        for x, y, w, h, _conf in self._overlay:
            p.drawRect(self._image_to_widget_rect(x, y, w, h))
            p.drawText(QPointF(self._offset_x + (x + 2) * self._scale,
                               self._offset_y + y * self._scale - 4),
                       f"{_conf:.2f}")

        # Selected region (cyan).
        if self._region:
            x, y, w, h = self._region
            p.setPen(QPen(QColor(6, 182, 212), 2))
            p.drawRect(self._image_to_widget_rect(x, y, w, h))

        # Last-clicked point (yellow crosshair).
        if self._last_point:
            x, y = self._last_point
            cx = int(self._offset_x + x * self._scale)
            cy = int(self._offset_y + y * self._scale)
            p.setPen(QPen(QColor(234, 179, 8), 2))
            p.drawLine(cx - 8, cy, cx + 8, cy)
            p.drawLine(cx, cy - 8, cx, cy + 8)

        # Drag preview.
        if self._dragging and self._drag_start and self._drag_end:
            p.setPen(QPen(QColor(6, 182, 212, 200), 1))
            r = QRectF(self._drag_start, self._drag_end).normalized()
            p.drawRect(r)

        p.end()

    # ----- mouse -----

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._screen is None:
            return
        self._dragging = True
        self._drag_start = event.position().toPoint()
        self._drag_end = self._drag_start
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            return
        self._drag_end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or not self._dragging:
            self._dragging = False
            return
        self._dragging = False
        start = self._drag_start
        end = self._drag_end
        self._drag_start = None
        self._drag_end = None
        if not start or not end:
            self.update()
            return

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        if abs(dx) + abs(dy) < 5:
            pt = self._widget_to_image(end.x(), end.y())
            if pt is not None:
                self._last_point = pt
                self._region = None
                self.pointPicked.emit(*pt)
        else:
            p1 = self._widget_to_image(start.x(), start.y()) or (0, 0)
            p2 = self._widget_to_image(end.x(), end.y()) or (0, 0)
            x1, y1 = p1
            x2, y2 = p2
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            if rw > 1 and rh > 1:
                self._region = (rx, ry, rw, rh)
                self._last_point = None
                self.regionPicked.emit(rx, ry, rw, rh)
        self.update()


# --- main window ---------------------------------------------------------


class DevHelper(QMainWindow):
    """PySide6-based dev helper."""

    AUTO_REFRESH_MIN_HZ = 0.2
    AUTO_REFRESH_MAX_HZ = 30.0
    INFO_REFRESH_INTERVAL = 2.0  # seconds

    def __init__(self) -> None:
        super().__init__()

        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()
        self.matcher = TemplateMatcher(cache_size=64)

        self._template_path: Optional[str] = None
        self._ocr_reader = None

        self._capture_in_flight = False
        self._info_in_flight = False
        self._capture_q: "queue.Queue[_CaptureResult]" = queue.Queue()
        self._info_q: "queue.Queue[_DeviceInfoResult]" = queue.Queue()

        self._auto_refresh_enabled = True
        self._refresh_hz = 5.0
        self._last_auto_capture = 0.0
        self._last_info_refresh = 0.0

        self._device_labels: List[str] = []

        # UI handles
        self._info_labels: dict[str, QLabel] = {}

        self._build_ui()

        # Timers
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)  # ms
        self._poll_timer.timeout.connect(self._poll_queues)
        self._poll_timer.start()

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(100)
        self._auto_timer.timeout.connect(self._handle_auto_refresh)
        self._auto_timer.start()

        self._info_timer = QTimer(self)
        self._info_timer.setInterval(int(self.INFO_REFRESH_INTERVAL * 1000))
        self._info_timer.timeout.connect(self._refresh_device_info_async)
        self._info_timer.start()

        add_log_subscriber(self._on_log_bus)

        QTimer.singleShot(50, self._refresh_devices)
        QTimer.singleShot(100, self._refresh_device_info_async)

    # ----- UI construction -----

    def _build_ui(self) -> None:
        self.setWindowTitle("ADB Auto-Game - Dev Helper")
        self.resize(1280, 820)
        self.setMinimumSize(1000, 680)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        root.addLayout(self._build_toolbar())

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        top_split = QSplitter(Qt.Horizontal)
        top_split.setChildrenCollapsible(False)
        top_split.addWidget(self._build_preview())
        top_split.addWidget(self._build_tools_panel())
        top_split.setStretchFactor(0, 1)
        top_split.setStretchFactor(1, 0)
        top_split.setSizes([880, 380])
        splitter.addWidget(top_split)

        splitter.addWidget(self._build_log_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([600, 140])
        root.addWidget(splitter, 1)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Ready")

        # Shortcuts
        QShortcut(QKeySequence("F5"), self,
                  activated=self._capture_async)
        QShortcut(QKeySequence("Escape"), self,
                  activated=self._clear_log)

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        bar.addWidget(QLabel("Device:"))
        self._device_combo = QComboBox()
        self._device_combo.setMinimumWidth(320)
        self._device_combo.currentTextChanged.connect(self._on_device_changed)
        bar.addWidget(self._device_combo)

        for label, cb in (
            ("Refresh", self._refresh_devices),
            ("Scan ports", self._scan_ports),
            ("Restart ADB", self._restart_adb),
        ):
            btn = QPushButton(label)
            btn.setProperty("class", "smallBtn")
            btn.clicked.connect(cb)
            bar.addWidget(btn)

        btn_cap = QPushButton("Capture (F5)")
        btn_cap.setObjectName("btnCapture")
        btn_cap.clicked.connect(self._capture_async)
        bar.addWidget(btn_cap)

        bar.addSpacing(12)
        self._hz_spin = QDoubleSpinBox()
        self._hz_spin.setRange(self.AUTO_REFRESH_MIN_HZ,
                              self.AUTO_REFRESH_MAX_HZ)
        self._hz_spin.setSingleStep(0.5)
        self._hz_spin.setDecimals(1)
        self._hz_spin.setValue(5.0)
        self._hz_spin.setFixedWidth(70)
        self._hz_spin.valueChanged.connect(self._on_hz_changed)
        bar.addWidget(self._hz_spin)

        bar.addStretch(1)

        self._auto_chk = QCheckBox("Auto")
        self._auto_chk.setChecked(True)
        self._auto_chk.toggled.connect(self._on_auto_toggle)
        bar.addWidget(self._auto_chk)

        self._dev_status = QLabel("Not connected")
        self._dev_status.setStyleSheet(f"color:{C.TEXT_MUTED}; font-weight:600;")
        bar.addWidget(self._dev_status)

        return bar

    def _build_preview(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        header = QHBoxLayout()
        self._size_label = QLabel("Preview")
        header.addWidget(self._size_label)
        header.addStretch(1)
        hint = QLabel("(click = pick point, drag = select region)")
        hint.setStyleSheet(f"color:{C.TEXT_MUTED};")
        header.addWidget(hint)
        lay.addLayout(header)

        self._preview = PreviewWidget()
        self._preview.pointPicked.connect(self._on_point_picked)
        self._preview.regionPicked.connect(self._on_region_picked)
        lay.addWidget(self._preview, 1)
        return wrap

    def _build_tools_panel(self) -> QWidget:
        wrap = QWidget()
        wrap.setMaximumWidth(400)
        wrap.setMinimumWidth(320)
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_inspect_tab(), "Inspect")
        self._tabs.addTab(self._build_template_tab(), "Template")
        self._tabs.addTab(self._build_device_tab(), "Device")
        lay.addWidget(self._tabs)
        return wrap

    # ----- Device tab -----

    def _build_device_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        form = QFormLayout(inner)
        form.setLabelAlignment(Qt.AlignRight)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(6)

        info_keys = [
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
        for label, key in info_keys:
            val = QLabel("-")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._info_labels[key] = val
            form.addRow(label, val)

        btns = QHBoxLayout()
        b1 = QPushButton("Refresh info")
        b1.clicked.connect(self._refresh_device_info_async)
        b2 = QPushButton("Copy info")
        b2.clicked.connect(self._copy_device_info)
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addStretch(1)
        form.addRow(btns)

        scroll.setWidget(inner)
        return scroll

    # ----- Template tab -----

    def _build_template_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        v.addWidget(QLabel("Pick a template PNG and run it against the screenshot."))

        path_row = QHBoxLayout()
        self._tpl_path = QLineEdit()
        self._tpl_path.setPlaceholderText("Path to template PNG")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_template)
        path_row.addWidget(self._tpl_path, 1)
        path_row.addWidget(browse)
        v.addLayout(path_row)

        self._tpl_threshold = QDoubleSpinBox()
        self._tpl_threshold.setRange(0.1, 0.999)
        self._tpl_threshold.setSingleStep(0.05)
        self._tpl_threshold.setDecimals(2)
        self._tpl_threshold.setValue(0.85)
        thr_form = QFormLayout()
        thr_form.addRow("Threshold:", self._tpl_threshold)
        v.addLayout(thr_form)

        self._tpl_grayscale = QCheckBox("Grayscale")
        self._tpl_multiscale = QCheckBox("Multi-scale (0.8 .. 1.2)")
        v.addWidget(self._tpl_grayscale)
        v.addWidget(self._tpl_multiscale)

        btn_row = QHBoxLayout()
        b_best = QPushButton("Find best match")
        b_best.clicked.connect(lambda: self._run_match(False))
        b_all = QPushButton("Find all matches")
        b_all.clicked.connect(lambda: self._run_match(True))
        btn_row.addWidget(b_best)
        btn_row.addWidget(b_all)
        v.addLayout(btn_row)

        b_clear = QPushButton("Clear overlay")
        b_clear.clicked.connect(self._clear_overlay)
        v.addWidget(b_clear)

        self._tpl_result = QLabel("No match yet.")
        self._tpl_result.setWordWrap(True)
        v.addWidget(self._tpl_result)
        v.addStretch(1)

        scroll.setWidget(inner)
        return scroll

    # ----- Inspect tab -----

    def _build_inspect_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        # Screenshot
        gb_shot = QGroupBox("Screenshot")
        gl = QHBoxLayout(gb_shot)
        b_save = QPushButton("Save full...")
        b_save.clicked.connect(self._save_full)
        b_load = QPushButton("Load file...")
        b_load.clicked.connect(self._load_image_from_file)
        gl.addWidget(b_save)
        gl.addWidget(b_load)
        gl.addStretch(1)
        v.addWidget(gb_shot)

        # Point & Color
        gb_pc = QGroupBox("Point & Color")
        form = QFormLayout(gb_pc)
        form.setLabelAlignment(Qt.AlignRight)
        self._point_x = QLineEdit(); self._point_x.setReadOnly(True)
        self._point_y = QLineEdit(); self._point_y.setReadOnly(True)
        xy_row = QHBoxLayout()
        xy_row.addWidget(QLabel("X:"))
        xy_row.addWidget(self._point_x)
        xy_row.addWidget(QLabel("Y:"))
        xy_row.addWidget(self._point_y)
        xy_row.addStretch(1)
        form.addRow("Point:", xy_row)

        self._color_hex = QLineEdit(); self._color_hex.setReadOnly(True)
        self._color_swatch = QLabel()
        self._color_swatch.setFixedSize(28, 22)
        self._color_swatch.setAutoFillBackground(True)
        sw_row = QHBoxLayout()
        sw_row.addWidget(QLabel("HEX:"))
        sw_row.addWidget(self._color_hex, 1)
        sw_row.addWidget(self._color_swatch)
        form.addRow("Color:", sw_row)

        self._color_rgb = QLineEdit(); self._color_rgb.setReadOnly(True)
        form.addRow("RGB:", self._color_rgb)

        pc_btns = QHBoxLayout()
        for label, cb in (
            ("Copy x,y", self._copy_xy),
            ("Copy HEX", self._copy_hex),
            ("Tap point", self._tap_picked),
        ):
            b = QPushButton(label)
            b.clicked.connect(cb)
            pc_btns.addWidget(b)
        pc_btns.addStretch(1)
        form.addRow(pc_btns)
        v.addWidget(gb_pc)

        # Region
        gb_r = QGroupBox("Region")
        rform = QFormLayout(gb_r)
        rform.setLabelAlignment(Qt.AlignRight)
        self._region_x = self._mk_int_spin()
        self._region_y = self._mk_int_spin()
        self._region_w = self._mk_int_spin()
        self._region_h = self._mk_int_spin()
        xy = QHBoxLayout()
        xy.addWidget(QLabel("X:"))
        xy.addWidget(self._region_x)
        xy.addWidget(QLabel("Y:"))
        xy.addWidget(self._region_y)
        xy.addStretch(1)
        rform.addRow("Pos:", xy)
        wh = QHBoxLayout()
        wh.addWidget(QLabel("W:"))
        wh.addWidget(self._region_w)
        wh.addWidget(QLabel("H:"))
        wh.addWidget(self._region_h)
        wh.addStretch(1)
        rform.addRow("Size:", wh)

        r_btns = QHBoxLayout()
        for label, cb in (
            ("Apply", self._apply_manual_region),
            ("Save crop...", self._save_region),
            ("Copy x,y,w,h", self._copy_region),
            ("Clear", self._clear_region),
        ):
            b = QPushButton(label)
            b.clicked.connect(cb)
            r_btns.addWidget(b)
        r_btns.addStretch(1)
        rform.addRow(r_btns)
        v.addWidget(gb_r)

        # OCR
        gb_ocr = QGroupBox("OCR")
        oform = QVBoxLayout(gb_ocr)
        self._ocr_result = QLineEdit()
        self._ocr_result.setReadOnly(True)
        oform.addWidget(self._ocr_result)
        wl_row = QHBoxLayout()
        self._ocr_whitelist = QLineEdit()
        self._ocr_whitelist.setPlaceholderText("Whitelist e.g. 0123456789/")
        b_read = QPushButton("Read text")
        b_read.clicked.connect(self._read_region_text)
        b_copy_ocr = QPushButton("Copy")
        b_copy_ocr.clicked.connect(self._copy_ocr_result)
        wl_row.addWidget(self._ocr_whitelist, 1)
        wl_row.addWidget(b_read)
        wl_row.addWidget(b_copy_ocr)
        oform.addLayout(wl_row)
        self._ocr_ascii = QCheckBox("ASCII only (strip Vietnamese diacritics)")
        oform.addWidget(self._ocr_ascii)
        eng_row = QHBoxLayout()
        eng_row.addWidget(QLabel("Engine:"))
        self._ocr_engine = QLabel("not loaded")
        self._ocr_engine.setStyleSheet(f"color:{C.TEXT_MUTED};")
        eng_row.addWidget(self._ocr_engine, 1)
        oform.addLayout(eng_row)
        v.addWidget(gb_ocr)

        # Tap
        gb_tap = QGroupBox("Tap")
        tform = QFormLayout(gb_tap)
        tform.setLabelAlignment(Qt.AlignRight)
        self._tap_x = self._mk_int_spin()
        self._tap_y = self._mk_int_spin()
        tap_row = QHBoxLayout()
        tap_row.addWidget(QLabel("X:"))
        tap_row.addWidget(self._tap_x)
        tap_row.addWidget(QLabel("Y:"))
        tap_row.addWidget(self._tap_y)
        tap_row.addStretch(1)
        tform.addRow("Pos:", tap_row)
        b_tap = QPushButton("Send tap")
        b_tap.clicked.connect(self._send_tap_manual)
        tform.addRow(b_tap)
        v.addWidget(gb_tap)

        # Swipe
        gb_sw = QGroupBox("Swipe")
        sform = QFormLayout(gb_sw)
        sform.setLabelAlignment(Qt.AlignRight)
        self._swipe_x1 = self._mk_int_spin()
        self._swipe_y1 = self._mk_int_spin()
        self._swipe_x2 = self._mk_int_spin()
        self._swipe_y2 = self._mk_int_spin()
        fr = QHBoxLayout()
        fr.addWidget(QLabel("X1:")); fr.addWidget(self._swipe_x1)
        fr.addWidget(QLabel("Y1:")); fr.addWidget(self._swipe_y1)
        fr.addStretch(1)
        sform.addRow("From:", fr)
        to = QHBoxLayout()
        to.addWidget(QLabel("X2:")); to.addWidget(self._swipe_x2)
        to.addWidget(QLabel("Y2:")); to.addWidget(self._swipe_y2)
        to.addStretch(1)
        sform.addRow("To:", to)
        self._swipe_dur = QSpinBox()
        self._swipe_dur.setRange(50, 100000)
        self._swipe_dur.setSingleStep(50)
        self._swipe_dur.setValue(300)
        dur_row = QHBoxLayout()
        dur_row.addWidget(self._swipe_dur)
        dur_row.addWidget(QLabel("ms"))
        dur_row.addStretch(1)
        sform.addRow("Dur:", dur_row)
        b_sw = QPushButton("Send swipe")
        b_sw.clicked.connect(self._send_swipe)
        sform.addRow(b_sw)
        v.addWidget(gb_sw)

        v.addStretch(1)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _mk_int_spin() -> QSpinBox:
        s = QSpinBox()
        s.setRange(0, 100000)
        s.setSingleStep(0)
        s.setValue(0)
        s.setFixedWidth(80)
        return s

    # ----- log panel -----

    def _build_log_panel(self) -> QWidget:
        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        head = QHBoxLayout()
        ll = QLabel("LOG")
        ll.setStyleSheet(
            f"color:{C.TEXT}; font-weight:700; font-size:11px;"
        )
        head.addWidget(ll)
        head.addStretch(1)
        b_clear = QPushButton("Clear")
        b_clear.setProperty("class", "smallBtn")
        b_clear.setFixedWidth(70)
        b_clear.clicked.connect(self._clear_log)
        head.addWidget(b_clear)
        v.addLayout(head)
        self._log_view = QPlainTextEdit()
        self._log_view.setObjectName("logView")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(8)
        self._log_view.setFont(mono)
        v.addWidget(self._log_view)
        return wrap

    # ===== device ops =====

    def _refresh_devices(self, *_a) -> None:
        try:
            self.scanner.ensure_adb_server_running()
            devices = self.controller.client.devices()
        except Exception as exc:
            log_warning(f"ADB server unreachable: {exc}")
            devices = []

        prev = self._device_combo.currentText()
        prev_serial = ""
        if prev and "  -  " in prev:
            prev_serial = prev.split("  -  ")[0]
        elif prev:
            prev_serial = prev

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

        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        if items:
            self._device_combo.addItems(items)
            sel = items[0]
            for it in items:
                if prev_serial and it.startswith(prev_serial):
                    sel = it
                    break
            self._device_combo.setCurrentText(sel)
            self._select_device(sel.split("  -  ")[0])
        else:
            self._device_combo.addItem("(no devices)")
        self._device_combo.blockSignals(False)

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

    def _on_device_changed(self, text: str) -> None:
        if not text or "  -  " not in text:
            serial = text or ""
        else:
            serial = text.split("  -  ")[0]
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

    # ===== device info =====

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
            self._dev_status.setText("Not connected")
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
            app_str = (f"{app_name}  ({app_pkg})"
                       if app_name and app_name != "-" else app_pkg)
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
        self._dev_status.setText(label)
        self._set_status(
            f"{ui['serial']} | {model} | Android {android_str} | "
            f"{ui['screen_size']} | App: {app_str}"
        )

    def _set_device_info(self, ui: dict) -> None:
        for key, val in ui.items():
            lbl = self._info_labels.get(key)
            if lbl is not None:
                lbl.setText(str(val))

    def _copy_device_info(self, *_a) -> None:
        pretty = {
            "status": "Status", "serial": "Serial", "model": "Model",
            "brand": "Brand", "android": "Android",
            "ro.product.cpu.abi": "ABI",
            "screen_size": "Resolution", "screen_density": "Density",
            "app": "App", "battery": "Battery", "ip": "IP", "uptime": "Uptime",
        }
        lines = []
        for key, lbl in self._info_labels.items():
            lines.append(f"{pretty.get(key, key)}: {lbl.text()}")
        QApplication.clipboard().setText("\n".join(lines))
        self._set_status("Copied device info")

    # ===== capture =====

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
        self._preview.set_image(img)
        h, w = img.shape[:2]
        self._size_label.setText(f"Preview  {w} x {h}")

    def _on_capture_failed(self, msg: str) -> None:
        log_error(f"Capture failed: {msg}")
        self._set_status(f"Capture failed: {msg}")

    # ----- auto refresh -----

    def _on_auto_toggle(self, checked: bool) -> None:
        self._auto_refresh_enabled = bool(checked)
        if self._auto_refresh_enabled:
            self._set_status(f"Auto refresh: {self._refresh_hz:.1f} Hz")
        self._last_auto_capture = time.monotonic()

    def _on_hz_changed(self, val: float) -> None:
        self._refresh_hz = max(self.AUTO_REFRESH_MIN_HZ,
                               min(self.AUTO_REFRESH_MAX_HZ, float(val)))

    def _handle_auto_refresh(self) -> None:
        if not self._auto_refresh_enabled:
            return
        now = time.monotonic()
        period = 1.0 / max(0.1, self._refresh_hz)
        if now - self._last_auto_capture >= period:
            self._last_auto_capture = now
            self._capture_async()

    # ===== queue polling =====

    def _poll_queues(self) -> None:
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
                    if "status" in self._info_labels:
                        self._info_labels["status"].setText(f"Error: {res.error}")
                    self._dev_status.setText("Not connected")
                elif res.info:
                    self._on_device_info_fetched(res.info)
        except queue.Empty:
            pass

    # ===== point / colour =====

    def _on_point_picked(self, x: int, y: int) -> None:
        self._point_x.setText(str(x))
        self._point_y.setText(str(y))
        self._tap_x.setValue(x)
        self._tap_y.setValue(y)
        img = self._preview._screen
        if img is not None and 0 <= y < img.shape[0] and 0 <= x < img.shape[1]:
            b, g, r = img[y, x][:3]
            r, g, b = int(r), int(g), int(b)
            self._color_hex.setText(f"#{r:02X}{g:02X}{b:02X}")
            self._color_rgb.setText(f"{r}, {g}, {b}")
            self._color_swatch.setStyleSheet(
                f"background-color: #{r:02X}{g:02X}{b:02X};"
            )
        self._set_status(f"Picked ({x}, {y})")

    def _copy_xy(self, *_a) -> None:
        x = self._point_x.text()
        y = self._point_y.text()
        if not x or not y:
            return
        QApplication.clipboard().setText(f"{x}, {y}")
        self._set_status("Copied x,y")

    def _copy_hex(self, *_a) -> None:
        v = self._color_hex.text()
        if not v:
            return
        QApplication.clipboard().setText(v)
        self._set_status("Copied HEX")

    def _tap_picked(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device")
            return
        try:
            x = int(self._point_x.text() or "0")
            y = int(self._point_y.text() or "0")
        except ValueError:
            return
        if self.controller.tap(x, y):
            log_success(f"Tapped ({x}, {y})")
        else:
            log_error(f"Tap failed at ({x}, {y})")

    # ===== region =====

    def _on_region_picked(self, x: int, y: int, w: int, h: int) -> None:
        self._region_x.setValue(x)
        self._region_y.setValue(y)
        self._region_w.setValue(w)
        self._region_h.setValue(h)
        self._sync_tap_to_region_center(x, y, w, h)
        self._set_status(
            f"Region {x},{y} {w}x{h} - tap target = "
            f"({x + w // 2}, {y + h // 2})"
        )

    def _sync_tap_to_region_center(self, x: int, y: int, w: int, h: int) -> None:
        cx = x + w // 2
        cy = y + h // 2
        self._tap_x.setValue(cx)
        self._tap_y.setValue(cy)
        self._point_x.setText(str(cx))
        self._point_y.setText(str(cy))
        img = self._preview._screen
        if img is not None and 0 <= cy < img.shape[0] and 0 <= cx < img.shape[1]:
            b, g, r = img[cy, cx][:3]
            r, g, b = int(r), int(g), int(b)
            self._color_hex.setText(f"#{r:02X}{g:02X}{b:02X}")
            self._color_rgb.setText(f"{r}, {g}, {b}")
            self._color_swatch.setStyleSheet(
                f"background-color: #{r:02X}{g:02X}{b:02X};"
            )

    def _apply_manual_region(self, *_a) -> None:
        img = self._preview._screen
        if img is None:
            return
        x = self._region_x.value()
        y = self._region_y.value()
        w = self._region_w.value()
        h = self._region_h.value()
        if w <= 0 or h <= 0:
            return
        self._preview.set_region((x, y, w, h))
        self._sync_tap_to_region_center(x, y, w, h)

    def _clear_region(self, *_a) -> None:
        self._preview.set_region(None)
        for w in (self._region_x, self._region_y,
                  self._region_w, self._region_h):
            w.setValue(0)

    def _current_region(self) -> Optional[Tuple[int, int, int, int]]:
        x = self._region_x.value()
        y = self._region_y.value()
        w = self._region_w.value()
        h = self._region_h.value()
        if w > 0 and h > 0:
            return (x, y, w, h)
        return None

    def _copy_region(self, *_a) -> None:
        region = self._current_region()
        if not region:
            self._set_status("No region selected")
            return
        x, y, w, h = region
        QApplication.clipboard().setText(f"{x}, {y}, {w}, {h}")
        self._set_status(f"Copied region {x}, {y}, {w}, {h}")

    def _save_region(self, *_a) -> None:
        img = self._preview._screen
        region = self._current_region()
        if img is None or not region:
            self._set_status("No region to save")
            return
        x, y, w, h = region
        crop = img[y:y + h, x:x + w].copy()
        path, _ = QFileDialog.getSaveFileName(
            self, "Save region",
            os.path.join(_ensure_out_dir(),
                        f"region_{_ts()}_{w}x{h}.png"),
            "PNG (*.png);;All files (*.*)",
        )
        if path:
            self._save_image_to(path, crop, "region")

    # ===== save / load =====

    def _save_full(self, *_a) -> None:
        img = self._preview._screen
        if img is None:
            self._set_status("Capture a screenshot first")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save screenshot",
            os.path.join(_ensure_out_dir(), f"screenshot_{_ts()}.png"),
            "PNG (*.png);;All files (*.*)",
        )
        if path:
            self._save_image_to(path, img, "screenshot")

    def _load_image_from_file(self, *_a) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load image", _ensure_out_dir(),
            "Images (*.png *.jpg *.jpeg *.bmp);;All files (*.*)",
        )
        if not path:
            return
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            log_error(f"Failed to load {path}")
            return
        self._on_captured(img)
        log_info(f"Loaded image: {path}")

    @staticmethod
    def _save_image_to(path: str, img: np.ndarray, kind: str) -> None:
        if cv2.imwrite(path, img):
            log_success(f"Saved {kind}: {path}")
        else:
            log_error(f"Failed to write {path}")

    # ===== template matching =====

    def _browse_template(self, *_a) -> None:
        start = self._tpl_path.text() or os.path.join(_PROJECT_ROOT, "assets")
        if not os.path.isdir(start):
            start = os.path.dirname(start) or _PROJECT_ROOT
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick template", start,
            "Images (*.png *.jpg *.jpeg *.bmp);;All files (*.*)",
        )
        if path:
            self._tpl_path.setText(path)
            self._template_path = path

    def _run_match(self, all_matches: bool) -> None:
        img = self._preview._screen
        if img is None:
            self._set_status("Capture a screenshot first")
            return
        path = self._tpl_path.text().strip()
        if not path or not os.path.exists(path):
            self._set_status("Pick a valid template path")
            return
        grayscale = self._tpl_grayscale.isChecked()
        threshold = float(self._tpl_threshold.value())
        multiscale = self._tpl_multiscale.isChecked()

        tpl = self.matcher.load(path, grayscale=grayscale)
        if tpl is None:
            log_error(f"Could not load template: {path}")
            return
        th, tw = tpl.shape[:2]

        rects: List[Tuple[int, int, int, int, float]] = []
        if all_matches:
            results = self.matcher.match_all(
                img, tpl,
                threshold=threshold, use_grayscale=grayscale,
            )
            for cx, cy, conf in results:
                x = max(0, cx - tw // 2)
                y = max(0, cy - th // 2)
                rects.append((x, y, tw, th, float(conf)))
            self._tpl_result.setText(f"Found {len(results)} match(es).")
            log_info(f"match_all -> {len(results)} hit(s) (thr={threshold:.2f})")
        else:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2] if multiscale else None
            res = self.matcher.match(
                img, tpl,
                threshold=threshold, use_grayscale=grayscale,
                multi_scale=multiscale, scales=scales,
            )
            if res is None:
                self._tpl_result.setText(f"No match >= {threshold:.2f}.")
                self._preview.clear_overlay()
                return
            cx, cy, conf, scale = res
            sw = int(tw * scale)
            sh = int(th * scale)
            x = max(0, cx - sw // 2)
            y = max(0, cy - sh // 2)
            rects.append((x, y, sw, sh, float(conf)))
            self._tpl_result.setText(
                f"Match: center=({cx},{cy}) conf={conf:.3f} scale={scale:.2f}"
            )
            log_info(f"match -> ({cx},{cy}) conf={conf:.3f} scale={scale:.2f}")

        self._preview.set_overlay(rects)

    def _clear_overlay(self, *_a) -> None:
        self._preview.clear_overlay()

    # ===== tap / swipe =====

    def _send_tap_manual(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device")
            return
        x = self._tap_x.value()
        y = self._tap_y.value()
        if self.controller.tap(x, y):
            log_success(f"Tapped ({x}, {y})")

    def _send_swipe(self, *_a) -> None:
        if not self.controller.device:
            self._set_status("No device")
            return
        x1 = self._swipe_x1.value()
        y1 = self._swipe_y1.value()
        x2 = self._swipe_x2.value()
        y2 = self._swipe_y2.value()
        dur = self._swipe_dur.value()
        if self.controller.swipe(x1, y1, x2, y2, dur):
            log_success(f"Swiped ({x1},{y1}) -> ({x2},{y2})")

    # ===== OCR =====

    def _read_region_text(self, *_a) -> None:
        img = self._preview._screen
        if img is None:
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

        whitelist = self._ocr_whitelist.text().strip() or None
        text = self._ocr_reader.read_text(
            img, region=region, whitelist=whitelist,
        )
        self._ocr_result.setText(text)
        engine = self._ocr_reader.backend_name
        self._ocr_engine.setText(engine if engine != "none" else "n/a")
        x, y, w, h = region
        if text:
            log_success(f"OCR [{engine}] ({x},{y} {w}x{h}) -> {text!r}")
        else:
            log_warning(f"OCR [{engine}] ({x},{y} {w}x{h}) -> (no text)")

    def _copy_ocr_result(self, *_a) -> None:
        text = self._ocr_result.text()
        if not text:
            self._set_status("No OCR result to copy")
            return
        QApplication.clipboard().setText(text)
        self._set_status("Copied OCR result")

    # ===== log =====

    def _on_log_bus(self, level: str, message: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{level.upper()}] {message}"
        # QPlainTextEdit.appendPlainText is thread-safe.
        self._log_view.appendPlainText(line)

    def _clear_log(self, *_a) -> None:
        self._log_view.clear()

    # ===== status =====

    def _set_status(self, msg: str) -> None:
        self._status.showMessage(msg)

    # ===== cleanup =====

    def closeEvent(self, event) -> None:
        try:
            remove_log_subscriber(self._on_log_bus)
        except Exception:
            pass
        super().closeEvent(event)


# --- entry point ---------------------------------------------------------


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Dev Helper")
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C.BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C.PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C.PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C.PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C.ACCENT_BG))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C.TEXT))
    app.setPalette(palette)
    app.setStyleSheet(QSS)

    win = DevHelper()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())