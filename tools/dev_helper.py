"""
Dev Helper - All-in-one PySide6 utility for ADB auto-game development.

Features
--------
- Device picker (uses ADBController + DeviceScanner)
- Live device screenshot preview
- Click to pick a point (device coordinates) -> copy / send tap
- Drag to select a region -> save cropped PNG (great for templates)
- Template match tester (TemplateMatcher) with threshold / grayscale / multi-scale
- Color picker (RGB / HEX at last clicked point)
- Manual tap / swipe sender

Run::

    python tools/dev_helper.py

Saved files default to ``./out/`` next to the project root.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Make the project root importable when running as a script.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Reconfigure stdout/stderr to UTF-8 (Windows console fix for VN strings).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

import cv2
import numpy as np

from PySide6.QtCore import (
    QObject,
    QPoint,
    QRect,
    QSettings,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QGuiApplication,
    QImage,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.adb import ADBController, DeviceScanner
from src.core.adb.auto.template_matcher import TemplateMatcher
from src.gui.pyside_gui import C, PulsingDot, QSS as BASE_QSS, _add_card_shadow
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)


# ---------------------------------------------------------------------------
# Theme - extends src.gui.pyside_gui's premium light SaaS palette/QSS with
# styles for the form-heavy widgets dev_helper uses (spinboxes, line edits,
# combos, tabs, group boxes, toolbar).
# ---------------------------------------------------------------------------


DEV_QSS = BASE_QSS + f"""
/* Toolbar (compact light bar) */
QToolBar {{
    background: {C.PANEL};
    border: none;
    border-bottom: 1px solid {C.BORDER};
    spacing: 6px;
    padding: 6px 10px;
}}
QToolBar QLabel {{ color: {C.TEXT_DIM}; font-weight: 600; }}
QToolBar QToolButton {{
    background: transparent;
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 14px;
    padding: 5px 12px;
    font-weight: 600;
    font-size: 12px;
}}
QToolBar QToolButton:hover {{
    background: {C.PANEL_HI};
    border-color: {C.TEXT_MUTED};
}}
QToolBar QToolButton:pressed {{ background: #e5e7eb; }}
QToolBar QToolButton:checked {{
    background: {C.SLATE_BG};
    color: {C.ACCENT_DIM};
    border-color: {C.ACCENT};
}}
QToolBar::separator {{
    background: {C.BORDER};
    width: 1px;
    margin: 6px 8px;
}}

/* Status bar */
QStatusBar {{
    background: {C.PANEL};
    border-top: 1px solid {C.BORDER};
    color: {C.TEXT_DIM};
}}
QStatusBar::item {{ border: none; }}

/* Group boxes - card-like containers with a clear title */
QGroupBox {{
    background: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 10px 12px 12px 12px;
    font-weight: 700;
    color: {C.TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -2px;
    padding: 0 6px;
    background: {C.PANEL};
    color: {C.TEXT_MUTED};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}}

/* Tab widget */
QTabWidget::pane {{
    border: 1px solid {C.BORDER};
    border-radius: 10px;
    background: {C.PANEL};
    top: -1px;
}}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{
    background: transparent;
    color: {C.TEXT_MUTED};
    padding: 8px 16px;
    margin-right: 2px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 12px;
}}
QTabBar::tab:hover {{ color: {C.TEXT}; background: {C.PANEL_HI}; }}
QTabBar::tab:selected {{
    background: {C.PANEL};
    color: {C.ACCENT};
    border: 1px solid {C.BORDER};
    border-bottom-color: {C.PANEL};
}}

/* Line edits, spin boxes, combo boxes */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {C.SLATE_BG};
    selection-color: {C.TEXT};
    min-height: 20px;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {C.ACCENT};
}}
QLineEdit:read-only {{
    background: {C.PANEL_ALT};
    color: {C.TEXT_DIM};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled {{
    background: #fafafa;
    color: {C.TEXT_MUTED};
    border-color: #f1f3f5;
}}

QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 14px;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 4px solid {C.TEXT_MUTED};
    width: 0; height: 0;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 4px solid {C.TEXT_MUTED};
    width: 0; height: 0;
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.TEXT_MUTED};
    width: 0; height: 0;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    selection-background-color: {C.SLATE_BG};
    selection-color: {C.TEXT};
    outline: none;
    padding: 4px;
}}

/* Form labels */
QFormLayout > QLabel,
QFormLayout QLabel {{
    color: {C.TEXT_DIM};
    font-weight: 600;
}}

/* Scroll area used inside the Inspect tab */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


DEFAULT_OUT_DIR = os.path.join(_PROJECT_ROOT, "out")


def _ensure_out_dir() -> str:
    os.makedirs(DEFAULT_OUT_DIR, exist_ok=True)
    return DEFAULT_OUT_DIR


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _bgr_to_qpixmap(bgr: np.ndarray) -> QPixmap:
    """Convert OpenCV BGR ndarray to QPixmap."""
    if bgr is None or bgr.size == 0:
        return QPixmap()
    if len(bgr.shape) == 2:
        h, w = bgr.shape
        img = QImage(bgr.data, w, h, w, QImage.Format.Format_Grayscale8)
    else:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(img.copy())


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


class CaptureWorker(QObject):
    """Async screenshot worker (avoids blocking the UI)."""

    captured = Signal(object)  # np.ndarray (BGR) or None
    failed = Signal(str)

    def __init__(self, controller: ADBController) -> None:
        super().__init__()
        self._controller = controller

    @Slot()
    def run(self) -> None:
        try:
            raw = self._controller.capture_screen_raw()
            if not raw:
                self.failed.emit("Empty screenshot from device")
                return
            arr = np.frombuffer(raw, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                self.failed.emit("Failed to decode PNG screenshot")
                return
            self.captured.emit(img)
        except Exception as exc:  # pragma: no cover - device errors
            self.failed.emit(str(exc))


class DeviceInfoWorker(QObject):
    """Async device-info fetcher.

    All ADB shell calls happen off the UI thread. The result is a flat dict
    of strings (or "-") so the GUI can just `.setText` each field.
    """

    fetched = Signal(dict)
    failed = Signal(str)

    # Properties we read from getprop in a single shell call.
    _PROPS = (
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

    def __init__(self, controller: ADBController) -> None:
        super().__init__()
        self._controller = controller

    @staticmethod
    def _shell(device, cmd: str) -> str:
        try:
            return (device.shell(cmd) or "").strip()
        except Exception:
            return ""

    @Slot()
    def run(self) -> None:
        device = self._controller.device
        if device is None:
            self.failed.emit("No device")
            return
        try:
            info: dict = {
                "serial": device.serial,
                "state": "device",
            }

            # Bulk getprop in a single shell call (much faster than N round-trips).
            getprop_cmd = " ; ".join(f"getprop {p}" for p in self._PROPS)
            raw = self._shell(device, getprop_cmd).splitlines()
            values = [line.strip() for line in raw]
            # Pad in case some props are missing.
            while len(values) < len(self._PROPS):
                values.append("")
            for key, val in zip(self._PROPS, values):
                info[key] = val or "-"

            # Screen size + density.
            wm_size = self._shell(device, "wm size")
            # e.g. "Physical size: 1080x1920" or with override.
            size_str = "-"
            for line in wm_size.splitlines():
                if ":" in line:
                    size_str = line.split(":", 1)[1].strip()
                    break
            info["screen_size"] = size_str or "-"

            wm_density = self._shell(device, "wm density")
            density_str = "-"
            for line in wm_density.splitlines():
                if ":" in line:
                    density_str = line.split(":", 1)[1].strip()
                    break
            info["screen_density"] = density_str or "-"

            # Battery (level + status + temperature).
            batt_raw = self._shell(device, "dumpsys battery")
            batt = {"level": "-", "status": "-", "temperature": "-",
                    "AC powered": "-", "USB powered": "-"}
            for line in batt_raw.splitlines():
                line = line.strip()
                for key in list(batt.keys()):
                    prefix = f"{key}:"
                    if line.startswith(prefix):
                        batt[key] = line[len(prefix):].strip()
            # Status code -> text. (BatteryManager.BATTERY_STATUS_*)
            status_map = {"1": "Unknown", "2": "Charging", "3": "Discharging",
                          "4": "Not charging", "5": "Full"}
            status_text = status_map.get(batt["status"], batt["status"])
            level = batt["level"]
            temp_c = "-"
            try:
                temp_c = f"{int(batt['temperature']) / 10:.1f}°C"
            except (TypeError, ValueError):
                pass
            powered = []
            if batt["AC powered"].lower() == "true":
                powered.append("AC")
            if batt["USB powered"].lower() == "true":
                powered.append("USB")
            powered_str = ", ".join(powered) if powered else "battery"
            info["battery"] = f"{level}% ({status_text}, {powered_str}, {temp_c})"

            # Foreground app.
            pkg = _safe_detect_app(device)
            info["app_package"] = pkg or "-"
            info["app_name"] = (
                self._controller._get_app_name_for_package(pkg) if pkg else "-"
            )

            # IP address (best-effort, optional).
            ip_raw = self._shell(device, "ip route")
            ip_addr = "-"
            for line in ip_raw.splitlines():
                if " src " in line:
                    parts = line.split(" src ")
                    if len(parts) > 1:
                        ip_addr = parts[1].split()[0]
                        break
            info["ip"] = ip_addr or "-"

            # Uptime (seconds since boot, in human form).
            up_raw = self._shell(device, "cat /proc/uptime")
            uptime_str = "-"
            try:
                secs = float(up_raw.split()[0])
                hours, rem = divmod(int(secs), 3600)
                mins, _ = divmod(rem, 60)
                uptime_str = f"{hours}h {mins}m"
            except (ValueError, IndexError):
                pass
            info["uptime"] = uptime_str

            self.fetched.emit(info)
        except Exception as exc:  # pragma: no cover - device errors
            self.failed.emit(str(exc))


def _safe_detect_app(device) -> Optional[str]:
    """Wrapper around the controller's package detector that never raises."""
    try:
        from src.core.adb.controller import _detect_current_app
        return _detect_current_app(device)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Image preview widget
# ---------------------------------------------------------------------------


@dataclass
class _MatchOverlay:
    rects: List[Tuple[int, int, int, int, float]]  # x, y, w, h, conf (image coords)


class ImageView(QLabel):
    """Image preview with click-to-pick and drag-to-select region.

    All coordinates emitted are in **image (device) pixel space**, not in
    widget space. The widget keeps the source pixmap unscaled internally and
    paints a scaled copy + overlays in :meth:`paintEvent`.
    """

    pointPicked = Signal(int, int)  # image x, y
    regionPicked = Signal(int, int, int, int)  # x, y, w, h (image coords)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(480, 320))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel { background: #f8f9fa; color: #9ca3af; "
            "border: 1px solid #e5e7eb; border-radius: 10px; }"
        )
        self.setText("No screenshot yet. Press 'Capture' to grab one.")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._pix: Optional[QPixmap] = None
        self._scale: float = 1.0
        self._offset: QPoint = QPoint(0, 0)

        self._dragging = False
        self._drag_start_widget: Optional[QPoint] = None
        self._drag_end_widget: Optional[QPoint] = None

        self._last_point: Optional[Tuple[int, int]] = None
        self._region: Optional[Tuple[int, int, int, int]] = None  # image coords
        self._overlay: Optional[_MatchOverlay] = None

        self.setMouseTracking(True)

    # ----- public API -----

    def set_image(self, bgr: np.ndarray) -> None:
        """Update the displayed image while preserving any user-picked
        point / region / match overlay so auto-refresh doesn't wipe them.

        Selections are in image (device) coordinate space, so they remain
        valid as long as the device resolution doesn't change. If it does
        change, we clear them to avoid out-of-bounds artifacts.
        """
        new_pix = _bgr_to_qpixmap(bgr)
        old_size = (self._pix.width(), self._pix.height()) if self.has_image() else None
        new_size = (new_pix.width(), new_pix.height())
        self._pix = new_pix

        if old_size is not None and old_size != new_size:
            # Resolution changed - drop selections to keep them sane.
            self._overlay = None
            self._region = None
            self._last_point = None

        self.setText("")
        self.update()

    def has_image(self) -> bool:
        return self._pix is not None and not self._pix.isNull()

    def image_size(self) -> Tuple[int, int]:
        if not self.has_image():
            return (0, 0)
        return (self._pix.width(), self._pix.height())

    def clear_image(self) -> None:
        self._pix = None
        self._overlay = None
        self._region = None
        self._last_point = None
        self.setText("No screenshot yet. Press 'Capture' to grab one.")
        self.update()

    def set_match_overlay(self, rects: List[Tuple[int, int, int, int, float]]) -> None:
        self._overlay = _MatchOverlay(rects=rects)
        self.update()

    def clear_overlay(self) -> None:
        self._overlay = None
        self.update()

    def last_point(self) -> Optional[Tuple[int, int]]:
        return self._last_point

    def selected_region(self) -> Optional[Tuple[int, int, int, int]]:
        return self._region

    # ----- coordinate mapping -----

    def _recompute_layout(self) -> None:
        if not self.has_image():
            self._scale = 1.0
            self._offset = QPoint(0, 0)
            return
        pw, ph = self._pix.width(), self._pix.height()
        ww, wh = self.width(), self.height()
        if pw <= 0 or ph <= 0 or ww <= 0 or wh <= 0:
            self._scale = 1.0
            self._offset = QPoint(0, 0)
            return
        self._scale = min(ww / pw, wh / ph)
        draw_w = int(pw * self._scale)
        draw_h = int(ph * self._scale)
        self._offset = QPoint((ww - draw_w) // 2, (wh - draw_h) // 2)

    def _widget_to_image(self, p: QPoint) -> Optional[Tuple[int, int]]:
        if not self.has_image() or self._scale <= 0:
            return None
        x = (p.x() - self._offset.x()) / self._scale
        y = (p.y() - self._offset.y()) / self._scale
        ix, iy = int(round(x)), int(round(y))
        pw, ph = self._pix.width(), self._pix.height()
        if 0 <= ix < pw and 0 <= iy < ph:
            return (ix, iy)
        return None

    def _image_to_widget_rect(
        self, x: int, y: int, w: int, h: int
    ) -> QRect:
        rx = int(self._offset.x() + x * self._scale)
        ry = int(self._offset.y() + y * self._scale)
        rw = max(1, int(w * self._scale))
        rh = max(1, int(h * self._scale))
        return QRect(rx, ry, rw, rh)

    # ----- Qt events -----

    def resizeEvent(self, ev) -> None:  # noqa: D401, N802
        super().resizeEvent(ev)
        self.update()

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if not self.has_image():
            return
        if ev.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_widget = ev.position().toPoint()
            self._drag_end_widget = self._drag_start_widget
            self.update()

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._dragging:
            self._drag_end_widget = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if not self._dragging or ev.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        end = ev.position().toPoint()
        start = self._drag_start_widget or end
        self._drag_end_widget = end

        # Treat tiny drags as a click (point pick), otherwise as a region.
        if (start - end).manhattanLength() < 5:
            pt = self._widget_to_image(end)
            if pt is not None:
                self._last_point = pt
                self._region = None
                self.pointPicked.emit(*pt)
        else:
            p1 = self._widget_to_image(start)
            p2 = self._widget_to_image(end)
            if p1 is None or p2 is None:
                # Clamp to image bounds best-effort.
                self._recompute_layout()
                pw, ph = self._pix.width(), self._pix.height()
                p1 = p1 or (
                    max(0, min(pw - 1, int((start.x() - self._offset.x()) / self._scale))),
                    max(0, min(ph - 1, int((start.y() - self._offset.y()) / self._scale))),
                )
                p2 = p2 or (
                    max(0, min(pw - 1, int((end.x() - self._offset.x()) / self._scale))),
                    max(0, min(ph - 1, int((end.y() - self._offset.y()) / self._scale))),
                )
            x1, y1 = p1
            x2, y2 = p2
            rx, ry = min(x1, x2), min(y1, y2)
            rw, rh = abs(x2 - x1), abs(y2 - y1)
            if rw > 1 and rh > 1:
                self._region = (rx, ry, rw, rh)
                self._last_point = None
                self.regionPicked.emit(rx, ry, rw, rh)

        self._drag_start_widget = None
        self._drag_end_widget = None
        self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        super().paintEvent(ev)
        if not self.has_image():
            return

        self._recompute_layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target_w = int(self._pix.width() * self._scale)
        target_h = int(self._pix.height() * self._scale)
        painter.drawPixmap(
            QRect(self._offset.x(), self._offset.y(), target_w, target_h),
            self._pix,
            QRect(0, 0, self._pix.width(), self._pix.height()),
        )

        # Match overlay (red boxes).
        if self._overlay and self._overlay.rects:
            pen = QPen(QColor(255, 60, 60))
            pen.setWidth(2)
            painter.setPen(pen)
            for x, y, w, h, conf in self._overlay.rects:
                rect = self._image_to_widget_rect(x, y, w, h)
                painter.drawRect(rect)
                painter.drawText(
                    rect.adjusted(2, -16, 0, 0),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                    f"{conf:.2f}",
                )

        # Selected region (cyan).
        if self._region:
            pen = QPen(QColor(0, 200, 230))
            pen.setWidth(2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            x, y, w, h = self._region
            painter.drawRect(self._image_to_widget_rect(x, y, w, h))

        # Last click point (yellow crosshair).
        if self._last_point:
            x, y = self._last_point
            pen = QPen(QColor(255, 215, 0))
            pen.setWidth(2)
            painter.setPen(pen)
            cx = int(self._offset.x() + x * self._scale)
            cy = int(self._offset.y() + y * self._scale)
            painter.drawLine(cx - 8, cy, cx + 8, cy)
            painter.drawLine(cx, cy - 8, cx, cy + 8)

        # Drag preview (while dragging).
        if self._dragging and self._drag_start_widget and self._drag_end_widget:
            pen = QPen(QColor(0, 200, 230, 200))
            pen.setWidth(1)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawRect(QRect(self._drag_start_widget, self._drag_end_widget))

        painter.end()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class DevHelper(QMainWindow):
    log_signal = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ADB Auto-Game - Dev Helper")
        self.resize(1280, 820)

        # Persistent settings (refresh rate, geometry, etc.)
        self.settings = QSettings("kilocode", "adb-auto-game-dev-helper")

        self.controller = ADBController(auto_connect=False)
        self.scanner = DeviceScanner()
        self.matcher = TemplateMatcher(cache_size=64)

        self._screen: Optional[np.ndarray] = None
        self._template_path: Optional[str] = None
        self._last_match_template_size: Optional[Tuple[int, int]] = None

        self._capture_thread: Optional[QThread] = None
        self._capture_worker: Optional[CaptureWorker] = None

        self._info_thread: Optional[QThread] = None
        self._info_worker: Optional[DeviceInfoWorker] = None
        self._info_fields: dict = {}  # populated by _build_device_info_box

        self._build_ui()
        self._wire_signals()
        self._refresh_devices(initial=True)

        # Wire log subscriber -> log panel.
        self.log_signal.connect(self._append_log)
        add_log_subscriber(self._on_log)

        # Periodic device-info refresh (foreground app etc. change while you
        # use the device). 2s is gentle on ADB while still feeling live.
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(2000)
        self._info_timer.timeout.connect(self._refresh_device_info_async)
        self._info_timer.start()

    # ----- UI -----

    def _build_ui(self) -> None:
        self.setStatusBar(QStatusBar(self))

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header card (title + device picker + capture controls)
        root.addWidget(self._build_header_card())

        # Main split: image preview (card) | tools tabs (card)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(12)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        # Left: image preview wrapped in a card
        preview_card = QFrame()
        preview_card.setObjectName("card")
        _add_card_shadow(preview_card)
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(8)

        preview_head = QHBoxLayout()
        preview_title = QLabel("PREVIEW")
        preview_title.setObjectName("sectionTitle")
        preview_head.addWidget(preview_title)
        preview_head.addStretch(1)
        self.preview_size_label = QLabel("—")
        self.preview_size_label.setStyleSheet(
            f"color:{C.TEXT_MUTED};font-size:11px;font-weight:600;"
            "letter-spacing:0.4px;"
        )
        preview_head.addWidget(self.preview_size_label)
        preview_layout.addLayout(preview_head)

        self.view = ImageView()
        preview_layout.addWidget(self.view, 1)

        splitter.addWidget(preview_card)

        # Right: tools tabs (Inspect + Template) wrapped in a card
        tools_card = QFrame()
        tools_card.setObjectName("card")
        _add_card_shadow(tools_card)
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(12, 12, 12, 12)
        tools_layout.setSpacing(8)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_inspect_tab(), "Inspect")
        self.tabs.addTab(self._build_template_tab(), "Template")
        self.tabs.addTab(self._build_device_tab(), "Device")
        tools_layout.addWidget(self.tabs, 1)

        splitter.addWidget(tools_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([800, 480])

        # Bottom: log card
        root.addWidget(self._build_log_card())

    def _build_header_card(self) -> QWidget:
        """Header card: title/subtitle, device cluster, capture controls."""
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 14, 16, 12)
        outer.setSpacing(10)

        # ---- Top row: title + device pill + actions ----
        top = QHBoxLayout()
        top.setSpacing(16)

        # Left: title + subtitle
        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel("Dev Helper")
        title.setObjectName("title")
        subtitle = QLabel("ADB screenshot, region picker, and template tester")
        subtitle.setObjectName("subtitle")
        left.addWidget(title)
        left.addWidget(subtitle)
        top.addLayout(left)

        top.addStretch(1)

        # Device status pill (label, dot, value text)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_lbl = QLabel("DEVICE")
        status_lbl.setObjectName("statusLabel")
        self.dev_dot = PulsingDot(C.TEXT_MUTED)
        self.dev_value = QLabel("Not connected")
        self.dev_value.setObjectName("statusValue")
        self.dev_value.setStyleSheet(f"color:{C.TEXT_MUTED};font-weight:700;")
        status_row.addWidget(status_lbl)
        status_row.addSpacing(2)
        status_row.addWidget(self.dev_dot)
        status_row.addWidget(self.dev_value)
        top.addLayout(status_row)

        outer.addLayout(top)

        # Hairline divider
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"background-color: {C.BORDER}; border: none; max-height: 1px;"
        )
        outer.addWidget(sep)

        # ---- Bottom row: device picker + actions + capture controls ----
        controls = QHBoxLayout()
        controls.setSpacing(10)

        controls.addWidget(self._mk_caption("EMULATOR"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(280)
        controls.addWidget(self.device_combo)

        btn_refresh = QPushButton("⟳  Refresh")
        btn_refresh.setProperty("class", "ghostBtn")
        btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_refresh.clicked.connect(self._refresh_devices)
        controls.addWidget(btn_refresh)

        btn_scan = QPushButton("Scan ports")
        btn_scan.setProperty("class", "ghostBtn")
        btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_scan.clicked.connect(self._scan_ports)
        controls.addWidget(btn_scan)

        btn_restart = QPushButton("Restart ADB")
        btn_restart.setProperty("class", "ghostBtn")
        btn_restart.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_restart.clicked.connect(self._restart_adb)
        controls.addWidget(btn_restart)

        # Vertical separator
        vsep = QFrame()
        vsep.setFrameShape(QFrame.Shape.VLine)
        vsep.setStyleSheet(
            f"background-color: {C.BORDER}; border: none; max-width: 1px;"
        )
        controls.addWidget(vsep)

        self.btn_capture = QPushButton("📷  Capture (F5)")
        self.btn_capture.setObjectName("btnStart")
        self.btn_capture.setMinimumHeight(34)
        self.btn_capture.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_capture.clicked.connect(self._capture_async)
        # Also wire as QAction so the F5 shortcut still works.
        self.act_capture = QAction("Capture", self)
        self.act_capture.setShortcut(QKeySequence("F5"))
        self.act_capture.triggered.connect(self._capture_async)
        self.addAction(self.act_capture)
        controls.addWidget(self.btn_capture)

        self.auto_capture = QCheckBox("Auto")
        self.auto_capture.setToolTip("Continuously capture at the rate set on the right")
        controls.addWidget(self.auto_capture)

        controls.addWidget(self._mk_caption("RATE"))
        self.refresh_hz = QDoubleSpinBox()
        self.refresh_hz.setRange(0.1, 60.0)
        self.refresh_hz.setSingleStep(1.0)
        self.refresh_hz.setDecimals(1)
        try:
            saved_hz = float(self.settings.value("refresh_hz", 30.0))
        except (TypeError, ValueError):
            saved_hz = 30.0
        saved_hz = max(0.1, min(60.0, saved_hz))
        self.refresh_hz.setValue(saved_hz)
        self.refresh_hz.setSuffix(" Hz")
        self.refresh_hz.setFixedWidth(90)
        self.refresh_hz.setToolTip(
            "Refresh rate in Hz. Higher = smoother but more ADB load. "
            "Capped at 60 Hz. Saved automatically."
        )
        controls.addWidget(self.refresh_hz)

        controls.addStretch(1)

        outer.addLayout(controls)

        # Wire auto-refresh timer (used to live in old _build_toolbar).
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._capture_async)
        self._apply_refresh_rate()
        self.refresh_hz.valueChanged.connect(self._apply_refresh_rate)
        self.auto_capture.toggled.connect(
            lambda on: self._auto_timer.start() if on else self._auto_timer.stop()
        )

        return card

    @staticmethod
    def _mk_caption(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("statusLabel")
        return lbl

    def _build_log_card(self) -> QWidget:
        """Bottom log card, styled to match the other cards."""
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("LOG")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addStretch(1)

        clear_btn = QPushButton("Clear")
        clear_btn.setFlat(True)
        clear_btn.setStyleSheet(
            f"QPushButton {{ color: {C.TEXT_MUTED}; background: transparent;"
            "border: none; padding: 4px 8px; font-weight: 600; font-size: 12px; }"
            f"QPushButton:hover {{ color: {C.TEXT}; }}"
        )
        clear_btn.clicked.connect(lambda: self.log_view.clear())
        head.addWidget(clear_btn)
        layout.addLayout(head)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        layout.addWidget(self.log_view, 1)

        card.setMinimumHeight(160)
        card.setMaximumHeight(240)
        return card

    def _apply_refresh_rate(self) -> None:
        """Sync QTimer interval with the Hz spinbox value and persist it."""
        hz = max(0.1, float(self.refresh_hz.value()))
        # Cap at ~60 fps (16 ms) since the spinbox max is 60.
        interval_ms = max(16, int(round(1000.0 / hz)))
        self._auto_timer.setInterval(interval_ms)
        if self.auto_capture.isChecked():
            self._auto_timer.start()  # restart with new interval
        # Persist so we restore the same rate next launch.
        self.settings.setValue("refresh_hz", hz)
        self.statusBar().showMessage(
            f"Auto refresh: {hz:.1f} Hz (~{interval_ms} ms)"
        )

    def _build_inspect_tab(self) -> QWidget:
        """Compact panel: screenshot I/O, point/color, region, tap/swipe.

        Device info has its own tab to keep this one focused on inspection
        actions. Tap and Swipe live side-by-side in a 2-column row to save
        vertical space.
        """
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)

        info = QLabel(
            "Click image to pick a point. Drag to select a region. "
            "Coordinates are in device pixels."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"QLabel {{ color: {C.TEXT_MUTED}; font-size: 12px; }}"
        )
        v.addWidget(info)

        # ---- Save / Load row (capture lives in the header) ----
        grp_io = QGroupBox("Screenshot")
        gc = QHBoxLayout(grp_io)
        gc.setSpacing(8)
        btn_save = QPushButton("Save full…")
        btn_save.clicked.connect(self._save_full)
        gc.addWidget(btn_save)
        btn_load = QPushButton("Load file…")
        btn_load.clicked.connect(self._load_image_from_file)
        gc.addWidget(btn_load)
        gc.addStretch(1)
        self.size_label = QLabel("Size: —")
        self.size_label.setStyleSheet(f"color:{C.TEXT_MUTED};font-weight:600;")
        gc.addWidget(self.size_label)
        v.addWidget(grp_io)

        # ---- Point && Color group ----
        grp_point = QGroupBox("Point && Color")
        gp = QVBoxLayout(grp_point)
        gp.setSpacing(6)

        # XY on a single row
        xy_row = QHBoxLayout()
        xy_row.setSpacing(6)
        xy_row.addWidget(self._mk_caption("X"))
        self.point_x = QLineEdit(); self.point_x.setReadOnly(True)
        self.point_x.setMaximumWidth(80)
        xy_row.addWidget(self.point_x)
        xy_row.addSpacing(6)
        xy_row.addWidget(self._mk_caption("Y"))
        self.point_y = QLineEdit(); self.point_y.setReadOnly(True)
        self.point_y.setMaximumWidth(80)
        xy_row.addWidget(self.point_y)
        xy_row.addStretch(1)
        gp.addLayout(xy_row)

        # HEX + RGB + swatch on one row
        col_row = QHBoxLayout()
        col_row.setSpacing(6)
        col_row.addWidget(self._mk_caption("HEX"))
        self.color_hex = QLineEdit(); self.color_hex.setReadOnly(True)
        self.color_hex.setMaximumWidth(96)
        col_row.addWidget(self.color_hex)
        col_row.addSpacing(6)
        col_row.addWidget(self._mk_caption("RGB"))
        self.color_rgb = QLineEdit(); self.color_rgb.setReadOnly(True)
        col_row.addWidget(self.color_rgb, 1)
        self.color_swatch = QFrame()
        self.color_swatch.setFixedSize(28, 22)
        self.color_swatch.setStyleSheet(
            f"QFrame {{ background: {C.PANEL_ALT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 4px; }}"
        )
        col_row.addWidget(self.color_swatch)
        gp.addLayout(col_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_copy_xy = QPushButton("Copy x,y")
        btn_copy_xy.clicked.connect(self._copy_xy)
        btn_row.addWidget(btn_copy_xy)
        btn_copy_hex = QPushButton("Copy HEX")
        btn_copy_hex.clicked.connect(self._copy_hex)
        btn_row.addWidget(btn_copy_hex)
        btn_row.addStretch(1)
        btn_tap_pt = QPushButton("Tap point")
        btn_tap_pt.setObjectName("btnStart")
        btn_tap_pt.clicked.connect(self._tap_picked)
        btn_row.addWidget(btn_tap_pt)
        gp.addLayout(btn_row)
        v.addWidget(grp_point)

        # ---- Region group ----
        grp_region = QGroupBox("Region")
        gr = QVBoxLayout(grp_region)
        gr.setSpacing(6)
        # X/Y on one row, W/H on another (instead of 4 stacked rows)
        rxy = QHBoxLayout()
        rxy.setSpacing(6)
        self.region_x = QSpinBox(); self.region_x.setRange(0, 99999)
        self.region_y = QSpinBox(); self.region_y.setRange(0, 99999)
        rxy.addWidget(self._mk_caption("X")); rxy.addWidget(self.region_x, 1)
        rxy.addSpacing(6)
        rxy.addWidget(self._mk_caption("Y")); rxy.addWidget(self.region_y, 1)
        gr.addLayout(rxy)
        rwh = QHBoxLayout()
        rwh.setSpacing(6)
        self.region_w = QSpinBox(); self.region_w.setRange(0, 99999)
        self.region_h = QSpinBox(); self.region_h.setRange(0, 99999)
        rwh.addWidget(self._mk_caption("W")); rwh.addWidget(self.region_w, 1)
        rwh.addSpacing(6)
        rwh.addWidget(self._mk_caption("H")); rwh.addWidget(self.region_h, 1)
        gr.addLayout(rwh)

        region_btns = QHBoxLayout()
        region_btns.setSpacing(6)
        btn_apply = QPushButton("Apply")
        btn_apply.clicked.connect(self._apply_manual_region)
        region_btns.addWidget(btn_apply)
        btn_save_region = QPushButton("Save crop…")
        btn_save_region.clicked.connect(self._save_region)
        region_btns.addWidget(btn_save_region)
        btn_copy_region = QPushButton("Copy x,y,w,h")
        btn_copy_region.setToolTip(
            "Copy the current region as 'x, y, w, h' to the clipboard"
        )
        btn_copy_region.clicked.connect(self._copy_region)
        region_btns.addWidget(btn_copy_region)
        btn_clear_region = QPushButton("Clear")
        btn_clear_region.clicked.connect(self._clear_region)
        region_btns.addWidget(btn_clear_region)
        region_btns.addStretch(1)
        gr.addLayout(region_btns)

        # OCR row: read text from the current region (Tesseract).
        ocr_row = QHBoxLayout()
        ocr_row.setSpacing(6)
        ocr_row.addWidget(self._mk_caption("OCR"))
        self.ocr_result = QLineEdit()
        self.ocr_result.setReadOnly(True)
        self.ocr_result.setPlaceholderText(
            "Read text in region (Tesseract)…"
        )
        ocr_row.addWidget(self.ocr_result, 1)
        self.ocr_whitelist = QLineEdit()
        self.ocr_whitelist.setPlaceholderText("Whitelist (e.g. 0123456789/)")
        self.ocr_whitelist.setMaximumWidth(160)
        self.ocr_whitelist.setToolTip(
            "Optional Tesseract char whitelist. Leave blank to allow any char."
        )
        ocr_row.addWidget(self.ocr_whitelist)
        btn_ocr = QPushButton("Read text")
        btn_ocr.setToolTip(
            "Run OCR on the current region using Tesseract. "
            "Requires the Tesseract binary on PATH."
        )
        btn_ocr.clicked.connect(self._read_region_text)
        ocr_row.addWidget(btn_ocr)
        btn_copy_ocr = QPushButton("Copy")
        btn_copy_ocr.setToolTip("Copy the OCR result to the clipboard")
        btn_copy_ocr.clicked.connect(self._copy_ocr_result)
        ocr_row.addWidget(btn_copy_ocr)
        gr.addLayout(ocr_row)

        v.addWidget(grp_region)

        # ---- Tap | Swipe in a single row (two side-by-side group boxes) ----
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        # --- Tap ---
        grp_tap = QGroupBox("Tap")
        tap_layout = QVBoxLayout(grp_tap)
        tap_layout.setSpacing(6)
        tap_xy = QHBoxLayout()
        tap_xy.setSpacing(6)
        self.tap_x = QSpinBox(); self.tap_x.setRange(0, 99999)
        self.tap_y = QSpinBox(); self.tap_y.setRange(0, 99999)
        tap_xy.addWidget(self._mk_caption("X")); tap_xy.addWidget(self.tap_x, 1)
        tap_xy.addSpacing(6)
        tap_xy.addWidget(self._mk_caption("Y")); tap_xy.addWidget(self.tap_y, 1)
        tap_layout.addLayout(tap_xy)
        btn_tap = QPushButton("Send tap")
        btn_tap.setObjectName("btnStart")
        btn_tap.clicked.connect(self._send_tap_manual)
        tap_layout.addWidget(btn_tap)
        tap_layout.addStretch(1)
        input_row.addWidget(grp_tap, 1)

        # --- Swipe ---
        grp_swipe = QGroupBox("Swipe")
        swipe_layout = QVBoxLayout(grp_swipe)
        swipe_layout.setSpacing(6)

        sf = QHBoxLayout()
        sf.setSpacing(6)
        self.swipe_x1 = QSpinBox(); self.swipe_x1.setRange(0, 99999)
        self.swipe_y1 = QSpinBox(); self.swipe_y1.setRange(0, 99999)
        sf.addWidget(self._mk_caption("FROM"))
        sf.addWidget(self.swipe_x1, 1); sf.addWidget(self.swipe_y1, 1)
        swipe_layout.addLayout(sf)

        st = QHBoxLayout()
        st.setSpacing(6)
        self.swipe_x2 = QSpinBox(); self.swipe_x2.setRange(0, 99999)
        self.swipe_y2 = QSpinBox(); self.swipe_y2.setRange(0, 99999)
        st.addWidget(self._mk_caption("TO  "))
        st.addWidget(self.swipe_x2, 1); st.addWidget(self.swipe_y2, 1)
        swipe_layout.addLayout(st)

        sd = QHBoxLayout()
        sd.setSpacing(6)
        self.swipe_dur = QSpinBox()
        self.swipe_dur.setRange(50, 10000); self.swipe_dur.setValue(300)
        self.swipe_dur.setSuffix(" ms")
        sd.addWidget(self._mk_caption("DUR "))
        sd.addWidget(self.swipe_dur, 1)
        swipe_layout.addLayout(sd)

        btn_swipe = QPushButton("Send swipe")
        btn_swipe.setObjectName("btnStart")
        btn_swipe.clicked.connect(self._send_swipe)
        swipe_layout.addWidget(btn_swipe)
        input_row.addWidget(grp_swipe, 1)

        v.addLayout(input_row)
        v.addStretch(1)

        # Wrap in a scroll area for narrow windows.
        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    def _build_device_tab(self) -> QWidget:
        """Dedicated tab for device info (was previously inside Inspect)."""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)

        hint = QLabel(
            "Live information for the currently selected device. Refreshes "
            "automatically every 2 s."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"QLabel {{ color: {C.TEXT_MUTED}; font-size: 12px; }}"
        )
        v.addWidget(hint)

        v.addWidget(self._build_device_info_box())
        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(w)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    def _build_device_info_box(self) -> QGroupBox:
        """Create the Device Info group box and store field references.

        Fields are kept in ``self._info_fields`` so the worker callback can
        update them generically without one slot per row. Layout uses two
        columns to better fill the dedicated Device tab.
        """
        from PySide6.QtWidgets import QGridLayout

        box = QGroupBox("Device Info")
        outer = QVBoxLayout(box)
        outer.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # (label, key in info dict)
        rows = [
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

        self._info_fields = {}
        # Lay out into 2 columns x N rows. Tall keys (App) span full width
        # at the bottom so long package names have room.
        col_count = 2
        regular = [r for r in rows if r[1] != "app"]
        for i, (label_text, key) in enumerate(regular):
            r = i // col_count
            c = (i % col_count) * 2
            label = QLabel(label_text.upper())
            label.setStyleSheet(
                f"color:{C.TEXT_MUTED};font-size:10px;font-weight:700;"
                "letter-spacing:0.6px;"
            )
            value = QLabel("-")
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            value.setWordWrap(True)
            value.setStyleSheet(f"QLabel {{ color: {C.TEXT}; font-weight: 600; }}")
            grid.addWidget(label, r, c)
            grid.addWidget(value, r, c + 1)
            self._info_fields[key] = value

        # App row spans full width since values can be long.
        next_row = (len(regular) + col_count - 1) // col_count
        app_label = QLabel("APP")
        app_label.setStyleSheet(
            f"color:{C.TEXT_MUTED};font-size:10px;font-weight:700;"
            "letter-spacing:0.6px;"
        )
        app_value = QLabel("-")
        app_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        app_value.setWordWrap(True)
        app_value.setStyleSheet(f"QLabel {{ color: {C.TEXT}; font-weight: 600; }}")
        grid.addWidget(app_label, next_row, 0)
        grid.addWidget(app_value, next_row, 1, 1, 3)
        self._info_fields["app"] = app_value

        outer.addLayout(grid)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_refresh = QPushButton("Refresh info")
        btn_refresh.clicked.connect(self._refresh_device_info_async)
        btn_row.addWidget(btn_refresh)
        btn_copy = QPushButton("Copy info")
        btn_copy.clicked.connect(self._copy_device_info)
        btn_row.addWidget(btn_copy)
        btn_row.addStretch(1)
        outer.addLayout(btn_row)

        return box

    def _build_template_tab(self) -> QWidget:
        outer = QWidget()
        v = QVBoxLayout(outer)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(10)

        info = QLabel(
            "Pick a template PNG and run it against the current screenshot."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"QLabel {{ color: {C.TEXT_MUTED}; font-size: 12px; }}"
        )
        v.addWidget(info)

        # ---- Template source ----
        grp_src = QGroupBox("Template")
        gs = QVBoxLayout(grp_src)
        gs.setSpacing(8)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.template_path_edit = QLineEdit()
        self.template_path_edit.setPlaceholderText("Path to template PNG…")
        row.addWidget(self.template_path_edit, 1)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self._browse_template)
        row.addWidget(btn_browse)
        gs.addLayout(row)
        v.addWidget(grp_src)

        # ---- Options ----
        grp_opts = QGroupBox("Options")
        form = QFormLayout(grp_opts)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.1, 0.999)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(0.85)
        form.addRow("Threshold:", self.threshold_spin)

        self.grayscale_chk = QCheckBox("Grayscale")
        form.addRow("", self.grayscale_chk)
        self.multiscale_chk = QCheckBox("Multi-scale (0.8 .. 1.2)")
        form.addRow("", self.multiscale_chk)
        v.addWidget(grp_opts)

        # ---- Actions ----
        grp_run = QGroupBox("Run")
        gr = QVBoxLayout(grp_run)
        gr.setSpacing(6)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        btn_one = QPushButton("Find best match")
        btn_one.setObjectName("btnStart")
        btn_one.clicked.connect(lambda: self._run_match(all_matches=False))
        row2.addWidget(btn_one)
        btn_all = QPushButton("Find all matches")
        btn_all.clicked.connect(lambda: self._run_match(all_matches=True))
        row2.addWidget(btn_all)
        gr.addLayout(row2)

        btn_clear = QPushButton("Clear overlay")
        btn_clear.clicked.connect(self.view.clear_overlay)
        gr.addWidget(btn_clear)

        self.match_result_label = QLabel("No match yet.")
        self.match_result_label.setWordWrap(True)
        self.match_result_label.setStyleSheet(
            f"QLabel {{ color: {C.TEXT_DIM}; font-size: 12px; "
            f"background: {C.PANEL_ALT}; border: 1px solid {C.BORDER}; "
            "border-radius: 6px; padding: 8px 10px; }"
        )
        gr.addWidget(self.match_result_label)
        v.addWidget(grp_run)

        v.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(outer)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return scroll

    # ----- signals -----

    def _wire_signals(self) -> None:
        self.view.pointPicked.connect(self._on_point_picked)
        self.view.regionPicked.connect(self._on_region_picked)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)

    # ----- device ops -----

    def _refresh_devices(self, initial: bool = False) -> None:
        try:
            self.scanner.ensure_adb_server_running()
            devices = self.controller.client.devices()
        except Exception as exc:
            log_warning(f"ADB server unreachable: {exc}")
            devices = []

        prev_serial = self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if not devices:
            self.device_combo.addItem("(no devices)", userData=None)
            self.controller.device = None
            self.controller.device_id = None
            self.statusBar().showMessage("No ADB devices. Try Scan ports.")
        else:
            for d in devices:
                # Show "serial - model" so multiple emulators are easy to tell apart.
                try:
                    model = (d.shell("getprop ro.product.model") or "").strip()
                except Exception:
                    model = ""
                label = f"{d.serial}  -  {model}" if model else d.serial
                self.device_combo.addItem(label, userData=d.serial)
            # Prefer keeping previous selection.
            if prev_serial:
                idx = self.device_combo.findData(prev_serial)
                if idx >= 0:
                    self.device_combo.setCurrentIndex(idx)
                else:
                    self.device_combo.setCurrentIndex(0)
            else:
                self.device_combo.setCurrentIndex(0)
            self._select_device(self.device_combo.currentData())

        self.device_combo.blockSignals(False)
        if initial and not devices:
            log_info("No devices found. Use 'Scan ports' to detect emulators.")
        # Update the info panel right away so the user sees fresh data.
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
                    self.statusBar().showMessage(
                        f"Connected: {serial} ({name}) - {width}x{height}"
                    )
                    return
            self.statusBar().showMessage(f"Device {serial} not available")
        except Exception as exc:
            log_error(f"Failed to select device {serial}: {exc}")

    def _on_device_changed(self, _idx: int) -> None:
        self._select_device(self.device_combo.currentData())
        # Refresh the info panel right away when the user picks a new device.
        self._refresh_device_info_async()

    def _scan_ports(self) -> None:
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

    def _restart_adb(self) -> None:
        log_info("Restarting ADB server...")
        if self.scanner.restart_adb_server():
            log_success("ADB server restarted")
        else:
            log_error("Failed to restart ADB server")
        self._refresh_devices()

    # ----- device info -----

    def _refresh_device_info_async(self) -> None:
        """Kick off an off-thread refresh of the Device Info panel."""
        if self._info_thread is not None:
            return  # one in-flight at a time

        device = self.controller.device
        if device is None:
            self._set_device_info({
                "status": "Disconnected",
                "serial": "-", "model": "-", "brand": "-",
                "android": "-", "ro.product.cpu.abi": "-",
                "screen_size": "-", "screen_density": "-",
                "app": "-", "battery": "-", "ip": "-", "uptime": "-",
            })
            self._update_header_device_pill(connected=False)
            return

        self._info_thread = QThread(self)
        self._info_worker = DeviceInfoWorker(self.controller)
        self._info_worker.moveToThread(self._info_thread)
        self._info_thread.started.connect(self._info_worker.run)
        self._info_worker.fetched.connect(self._on_device_info_fetched)
        self._info_worker.failed.connect(self._on_device_info_failed)
        self._info_worker.fetched.connect(self._info_thread.quit)
        self._info_worker.failed.connect(self._info_thread.quit)
        self._info_thread.finished.connect(self._cleanup_info_thread)
        self._info_thread.start()

    def _cleanup_info_thread(self) -> None:
        if self._info_thread:
            self._info_thread.deleteLater()
        if self._info_worker:
            self._info_worker.deleteLater()
        self._info_thread = None
        self._info_worker = None

    @Slot(dict)
    def _on_device_info_fetched(self, info: dict) -> None:
        """Translate the raw worker dict into the friendly form the UI shows."""
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
        self._update_header_device_pill(connected=True, model=model,
                                        serial=ui["serial"])

        # Mirror the most useful bits into the status bar too.
        self.statusBar().showMessage(
            f"{ui['serial']} | {model} | Android {android_str} | "
            f"{ui['screen_size']} | App: {app_str}"
        )

    @Slot(str)
    def _on_device_info_failed(self, msg: str) -> None:
        # Soft-fail: keep whatever the panel had, just mark status.
        if "status" in self._info_fields:
            self._info_fields["status"].setText(f"Error: {msg}")
        self._update_header_device_pill(connected=False)

    def _update_header_device_pill(self, connected: bool,
                                   model: str = "", serial: str = "") -> None:
        """Sync the header card's DEVICE pill with current connection state."""
        if not hasattr(self, "dev_value") or not hasattr(self, "dev_dot"):
            return
        if connected:
            label = model.strip() or serial or "Connected"
            if model and serial and model != serial:
                label = f"{model}  ({serial})"
            self.dev_value.setText(label)
            self.dev_value.setStyleSheet(f"color:{C.TEXT};font-weight:700;")
            self.dev_dot.setColor(C.OK)
        else:
            self.dev_value.setText("Not connected")
            self.dev_value.setStyleSheet(f"color:{C.TEXT_MUTED};font-weight:700;")
            self.dev_dot.setColor(C.TEXT_MUTED)

    def _set_device_info(self, ui: dict) -> None:
        for key, label in self._info_fields.items():
            label.setText(str(ui.get(key, "-")))

    def _copy_device_info(self) -> None:
        """Copy the currently-displayed device info to the clipboard."""
        if not self._info_fields:
            return
        lines = []
        # Re-derive labels by walking the form layout would be fragile; just
        # re-use the key names which are already human-readable enough.
        pretty = {
            "status": "Status",
            "serial": "Serial",
            "model": "Model",
            "brand": "Brand",
            "android": "Android",
            "ro.product.cpu.abi": "ABI",
            "screen_size": "Resolution",
            "screen_density": "Density",
            "app": "App",
            "battery": "Battery",
            "ip": "IP",
            "uptime": "Uptime",
        }
        for key, label in self._info_fields.items():
            lines.append(f"{pretty.get(key, key)}: {label.text()}")
        QGuiApplication.clipboard().setText("\n".join(lines))
        self.statusBar().showMessage("Copied device info")

    # ----- capture -----

    def _capture_async(self) -> None:
        if not self.controller.device:
            self.statusBar().showMessage("No device selected")
            return
        if self._capture_thread is not None:
            return  # Already running.

        self._capture_thread = QThread(self)
        self._capture_worker = CaptureWorker(self.controller)
        self._capture_worker.moveToThread(self._capture_thread)
        self._capture_thread.started.connect(self._capture_worker.run)
        self._capture_worker.captured.connect(self._on_captured)
        self._capture_worker.failed.connect(self._on_capture_failed)
        self._capture_worker.captured.connect(self._capture_thread.quit)
        self._capture_worker.failed.connect(self._capture_thread.quit)
        self._capture_thread.finished.connect(self._cleanup_capture_thread)
        self._capture_thread.start()

    def _cleanup_capture_thread(self) -> None:
        if self._capture_thread:
            self._capture_thread.deleteLater()
        if self._capture_worker:
            self._capture_worker.deleteLater()
        self._capture_thread = None
        self._capture_worker = None

    @Slot(object)
    def _on_captured(self, img: np.ndarray) -> None:
        self._screen = img
        self.view.set_image(img)
        h, w = img.shape[:2]
        size_text = f"{w} x {h}"
        self.size_label.setText(f"Size: {size_text}")
        if hasattr(self, "preview_size_label"):
            self.preview_size_label.setText(size_text)
        for sp in (self.region_x, self.region_y, self.region_w, self.region_h,
                   self.tap_x, self.tap_y,
                   self.swipe_x1, self.swipe_y1, self.swipe_x2, self.swipe_y2):
            sp.setMaximum(max(w, h))

    @Slot(str)
    def _on_capture_failed(self, msg: str) -> None:
        log_error(f"Capture failed: {msg}")
        self.statusBar().showMessage(f"Capture failed: {msg}")

    # ----- point / color -----

    @Slot(int, int)
    def _on_point_picked(self, x: int, y: int) -> None:
        self.point_x.setText(str(x))
        self.point_y.setText(str(y))
        self.tap_x.setValue(x)
        self.tap_y.setValue(y)
        if self._screen is not None:
            b, g, r = self._screen[y, x][:3]
            r, g, b = int(r), int(g), int(b)
            hex_s = f"#{r:02X}{g:02X}{b:02X}"
            self.color_hex.setText(hex_s)
            self.color_rgb.setText(f"{r}, {g}, {b}")
            self.color_swatch.setStyleSheet(
                f"QFrame {{ background: {hex_s}; "
                f"border: 1px solid {C.BORDER}; border-radius: 4px; }}"
            )
        self.statusBar().showMessage(f"Picked ({x}, {y})")

    def _copy_xy(self) -> None:
        x, y = self.point_x.text(), self.point_y.text()
        if not x or not y:
            return
        QGuiApplication.clipboard().setText(f"{x}, {y}")
        self.statusBar().showMessage("Copied x,y")

    def _copy_hex(self) -> None:
        v = self.color_hex.text()
        if not v:
            return
        QGuiApplication.clipboard().setText(v)
        self.statusBar().showMessage("Copied HEX")

    def _tap_picked(self) -> None:
        if not self.controller.device:
            self.statusBar().showMessage("No device")
            return
        try:
            x = int(self.point_x.text() or "0")
            y = int(self.point_y.text() or "0")
        except ValueError:
            return
        ok = self.controller.tap(x, y)
        if ok:
            log_success(f"Tapped ({x}, {y})")
        else:
            log_error(f"Tap failed at ({x}, {y})")

    # ----- region -----

    @Slot(int, int, int, int)
    def _on_region_picked(self, x: int, y: int, w: int, h: int) -> None:
        self.region_x.setValue(x)
        self.region_y.setValue(y)
        self.region_w.setValue(w)
        self.region_h.setValue(h)
        self._sync_tap_to_region_center(x, y, w, h)
        self.statusBar().showMessage(
            f"Region {x},{y} {w}x{h} - tap target = center ({x + w // 2}, {y + h // 2})"
        )

    def _sync_tap_to_region_center(self, x: int, y: int, w: int, h: int) -> None:
        """Update Tap X/Y + the picked-point fields to the region's center."""
        cx = x + w // 2
        cy = y + h // 2
        self.tap_x.setValue(cx)
        self.tap_y.setValue(cy)
        self.point_x.setText(str(cx))
        self.point_y.setText(str(cy))
        # Sample center pixel color too, so the swatch reflects the region.
        if self._screen is not None and 0 <= cy < self._screen.shape[0] and 0 <= cx < self._screen.shape[1]:
            b, g, r = self._screen[cy, cx][:3]
            r, g, b = int(r), int(g), int(b)
            hex_s = f"#{r:02X}{g:02X}{b:02X}"
            self.color_hex.setText(hex_s)
            self.color_rgb.setText(f"{r}, {g}, {b}")
            self.color_swatch.setStyleSheet(
                f"QFrame {{ background: {hex_s}; "
                f"border: 1px solid {C.BORDER}; border-radius: 4px; }}"
            )

    def _apply_manual_region(self) -> None:
        if self._screen is None:
            return
        x = self.region_x.value()
        y = self.region_y.value()
        w = self.region_w.value()
        h = self.region_h.value()
        if w <= 0 or h <= 0:
            return
        self.view._region = (x, y, w, h)  # noqa: SLF001 - intentional sync
        self.view._last_point = None  # noqa: SLF001
        self.view.update()
        self._sync_tap_to_region_center(x, y, w, h)

    def _clear_region(self) -> None:
        self.view._region = None  # noqa: SLF001
        self.view.update()
        for sp in (self.region_x, self.region_y, self.region_w, self.region_h):
            sp.setValue(0)

    def _save_region(self) -> None:
        if self._screen is None:
            QMessageBox.information(self, "Save region", "Capture a screenshot first.")
            return
        region = self.view.selected_region()
        if not region:
            QMessageBox.information(self, "Save region", "Select a region first.")
            return
        x, y, w, h = region
        crop = self._screen[y:y + h, x:x + w].copy()
        suggested = os.path.join(
            _ensure_out_dir(), f"region_{_ts()}_{w}x{h}.png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save region", suggested, "PNG (*.png)"
        )
        if not path:
            return
        ok = cv2.imwrite(path, crop)
        if ok:
            log_success(f"Saved region: {path}")
        else:
            log_error(f"Failed to write {path}")

    # ----- save full / load -----

    def _save_full(self) -> None:
        if self._screen is None:
            QMessageBox.information(self, "Save", "Capture a screenshot first.")
            return
        suggested = os.path.join(_ensure_out_dir(), f"screenshot_{_ts()}.png")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save screenshot", suggested, "PNG (*.png)"
        )
        if not path:
            return
        if cv2.imwrite(path, self._screen):
            log_success(f"Saved: {path}")
        else:
            log_error(f"Failed to write {path}")

    def _load_image_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", _ensure_out_dir(), "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            log_error(f"Failed to load {path}")
            return
        self._on_captured(img)
        log_info(f"Loaded image: {path}")

    # ----- template matching -----

    def _browse_template(self) -> None:
        start = self.template_path_edit.text() or os.path.join(_PROJECT_ROOT, "assets")
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick template", start, "PNG (*.png)"
        )
        if not path:
            return
        self.template_path_edit.setText(path)
        self._template_path = path

    def _run_match(self, all_matches: bool) -> None:
        if self._screen is None:
            QMessageBox.information(self, "Template", "Capture a screenshot first.")
            return
        path = self.template_path_edit.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "Template", "Pick a valid template path.")
            return
        grayscale = self.grayscale_chk.isChecked()
        threshold = float(self.threshold_spin.value())
        multiscale = self.multiscale_chk.isChecked()

        tpl = self.matcher.load(path, grayscale=grayscale)
        if tpl is None:
            log_error(f"Could not load template: {path}")
            return
        th, tw = tpl.shape[:2]
        self._last_match_template_size = (tw, th)

        rects: List[Tuple[int, int, int, int, float]] = []
        if all_matches:
            results = self.matcher.match_all(
                self._screen, tpl, threshold=threshold, use_grayscale=grayscale
            )
            for cx, cy, conf in results:
                x = max(0, cx - tw // 2)
                y = max(0, cy - th // 2)
                rects.append((x, y, tw, th, float(conf)))
            self.match_result_label.setText(f"Found {len(results)} match(es).")
            log_info(f"match_all -> {len(results)} hit(s) (thr={threshold:.2f})")
        else:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2] if multiscale else None
            res = self.matcher.match(
                self._screen, tpl,
                threshold=threshold,
                use_grayscale=grayscale,
                multi_scale=multiscale,
                scales=scales,
            )
            if res is None:
                self.match_result_label.setText(
                    f"No match >= {threshold:.2f}."
                )
                self.view.clear_overlay()
                return
            cx, cy, conf, scale = res
            sw = int(tw * scale)
            sh = int(th * scale)
            x = max(0, cx - sw // 2)
            y = max(0, cy - sh // 2)
            rects.append((x, y, sw, sh, float(conf)))
            self.match_result_label.setText(
                f"Match: center=({cx},{cy}) conf={conf:.3f} scale={scale:.2f}"
            )
            log_info(
                f"match -> ({cx},{cy}) conf={conf:.3f} scale={scale:.2f}"
            )

        self.view.set_match_overlay(rects)

    # ----- tap / swipe -----

    def _send_tap_manual(self) -> None:
        if not self.controller.device:
            self.statusBar().showMessage("No device")
            return
        x = self.tap_x.value()
        y = self.tap_y.value()
        if self.controller.tap(x, y):
            log_success(f"Tapped ({x}, {y})")

    def _send_swipe(self) -> None:
        if not self.controller.device:
            self.statusBar().showMessage("No device")
            return
        ok = self.controller.swipe(
            self.swipe_x1.value(), self.swipe_y1.value(),
            self.swipe_x2.value(), self.swipe_y2.value(),
            self.swipe_dur.value(),
        )
        if ok:
            log_success(
                f"Swiped ({self.swipe_x1.value()},{self.swipe_y1.value()}) -> "
                f"({self.swipe_x2.value()},{self.swipe_y2.value()})"
            )

    # ----- log plumbing -----

    _LEVEL_COLORS = {
        "error":   C.ERR,
        "warning": C.WARN,
        "success": C.OK,
        "info":    C.INFO,
        "state":   "#7e22ce",
        "quest":   "#a21caf",
        "normal":  C.TEXT,
    }

    def _on_log(self, level: str, message: str) -> None:
        # Marshal across threads to the GUI.
        ts = time.strftime("%H:%M:%S")
        color = self._LEVEL_COLORS.get(level, C.TEXT)
        safe = (
            message.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
        )
        self.log_signal.emit(
            f'<span style="color:{C.TEXT_MUTED}">[{ts}]</span> '
            f'<span style="color:{color};font-weight:700">[{level.upper()}]</span> '
            f'<span style="color:{C.TEXT}">{safe}</span>'
        )

    @Slot(str)
    def _append_log(self, html: str) -> None:
        self.log_view.appendHtml(html)

    # ----- shutdown -----

    def closeEvent(self, ev) -> None:  # noqa: N802
        try:
            remove_log_subscriber(self._on_log)
        except Exception:
            pass
        if self._auto_timer.isActive():
            self._auto_timer.stop()
        if hasattr(self, "_info_timer") and self._info_timer.isActive():
            self._info_timer.stop()
        if self._capture_thread is not None:
            self._capture_thread.quit()
            self._capture_thread.wait(2000)
        if self._info_thread is not None:
            self._info_thread.quit()
            self._info_thread.wait(2000)
        super().closeEvent(ev)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    # Native palette + QSS for a coherent light theme that matches the
    # main game-automation GUI.
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(C.BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(C.PANEL))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(C.PANEL_ALT))
    palette.setColor(QPalette.ColorRole.Text, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(C.PANEL))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(C.SLATE_BG))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(C.TEXT))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f9fafb"))
    app.setPalette(palette)
    app.setStyleSheet(DEV_QSS)

    win = DevHelper()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
