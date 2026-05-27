"""
PySide6-based GUI for game automation - Premium light SaaS dashboard.

Modern, native-looking front-end for any :class:`BaseGameAutomation`. Same
callback contract as the previous DearPyGui / webview GUIs - drop-in
replacement.

Layout::

    +-------------------------------------------------------------+
    |  Title / subtitle    STATUS: ● READY    [Start][Pause][Stop]|
    +-------------------------------------------------------------+
    |  SEQUENTIAL (n)             |  BACKGROUND (n)              |
    |   table with progress bars  |   rows with iOS toggles      |
    +-------------------------------------------------------------+
    |  LOG  [Info][Warn][Err]     |  METRICS                     |
    |   monospace terminal        |   2x2 micro-card grid        |
    +-------------------------------------------------------------+

Usage::

    from src.games.bd2.bd2 import BD2
    from src.gui.pyside_gui import run_with_pyside

    run_with_pyside(BD2, "BD2 Automation")
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QObject,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
    Property,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QPainter,
    QPalette,
    QPen,
    QBrush,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.games.base_game import Activity, BaseGameAutomation
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    remove_log_subscriber,
)


# ---------------------------------------------------------------------------
# Palette - premium light SaaS
# ---------------------------------------------------------------------------

class C:
    # Surfaces
    BG          = "#f3f4f6"   # window background (ultra-light gray)
    PANEL       = "#ffffff"   # cards (pure white)
    PANEL_ALT   = "#f8f9fa"   # zebra rows / inner subtle bg
    PANEL_HI    = "#f1f3f5"   # hovered surfaces
    BORDER      = "#e5e7eb"   # hairline borders

    # Text
    TEXT        = "#111827"   # near-black charcoal
    TEXT_DIM    = "#4b5563"   # secondary
    TEXT_MUTED  = "#9ca3af"   # tertiary / labels

    # Accents
    ACCENT      = "#4f46e5"   # slate blue (primary)
    ACCENT_DIM  = "#3730a3"

    OK          = "#059669"   # emerald-600
    OK_BG       = "#d1fae5"   # emerald-100
    WARN        = "#b45309"   # amber-700 text
    WARN_BG     = "#fef3c7"   # amber-100
    ERR         = "#b91c1c"   # red-700 text
    ERR_BG      = "#fee2e2"   # red-100
    INFO        = "#1d4ed8"   # blue-700
    INFO_BG     = "#dbeafe"   # blue-100
    SLATE_BG    = "#e0e7ff"   # indigo-100 (pending pill)
    SLATE_FG    = "#3730a3"   # indigo-700


# Status -> (background, foreground) for activity badges. Soft pills, dark
# text, high contrast for readability.
_STATUS_PILL: Dict[str, tuple] = {
    "pending":   (C.SLATE_BG, C.SLATE_FG),
    "running":   (C.INFO_BG, C.INFO),
    "completed": (C.OK_BG, C.OK),
    "failed":    (C.ERR_BG, C.ERR),
    "skipped":   (C.WARN_BG, C.WARN),
}

_LOG_COLORS: Dict[str, str] = {
    "info":    C.INFO,
    "success": C.OK,
    "warning": C.WARN,
    "error":   C.ERR,
    "state":   "#7e22ce",
    "quest":   "#a21caf",
    "normal":  C.TEXT,
}


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------

class PulsingDot(QWidget):
    """A small filled circle that gently pulses opacity. Used as the status
    indicator next to STATUS: READY / RUNNING / etc.
    """

    def __init__(self, color: str = C.OK, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self._opacity = 1.0
        self.setFixedSize(12, 12)

        self._anim = QPropertyAnimation(self, b"opacity", self)
        self._anim.setDuration(1400)
        self._anim.setStartValue(1.0)
        self._anim.setKeyValueAt(0.5, 0.35)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)
        self._anim.start()

    def setColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    # ``opacity`` exposed as a Qt property so QPropertyAnimation can drive it.
    def getOpacity(self) -> float:
        return self._opacity

    def setOpacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    opacity = Property(float, getOpacity, setOpacity)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self._color)
        c.setAlphaF(self._opacity)
        p.setBrush(QBrush(c))
        p.setPen(Qt.PenStyle.NoPen)
        # Small filled circle, padded inside the widget rect.
        p.drawEllipse(2, 2, self.width() - 4, self.height() - 4)


class PlayButton(QPushButton):
    """Circular Run-once button with a hand-drawn play triangle.

    Painting the triangle ourselves avoids the unicode ``▶`` character
    rendering inconsistencies across system fonts.
    """

    SIZE = 30  # diameter

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", "playBtn")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        # Let the stylesheet paint the circular background/border first.
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Triangle that fits inside the circle. Slight rightward bias so it
        # looks visually centred (the right vertex is the longest reach).
        cx = self.width() / 2
        cy = self.height() / 2
        r = 5.0  # half-size of the triangle bounding box

        if self.isEnabled():
            color = QColor(C.ACCENT_DIM if self.isDown() else C.ACCENT)
        else:
            color = QColor(C.TEXT_MUTED)

        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        from PySide6.QtGui import QPolygonF
        from PySide6.QtCore import QPointF
        p.drawPolygon(QPolygonF([
            QPointF(cx - r * 0.6, cy - r),
            QPointF(cx - r * 0.6, cy + r),
            QPointF(cx + r,       cy),
        ]))


class ToggleSwitch(QCheckBox):
    """iOS-style toggle switch.

    Behaves like a QCheckBox (so it plugs straight into the existing
    enable/disable callbacks) but paints itself as a pill with a sliding
    knob. Animates between states.
    """

    TRACK_W = 40
    TRACK_H = 22
    KNOB_M  = 2  # margin from track edge to knob

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.TRACK_W, self.TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Hide the default indicator entirely; we paint our own.
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }"
                           "QCheckBox { spacing: 0px; }")

        # Knob position is animated between the off (left) and on (right)
        # ends of the track. We store progress in [0..1] so painting is
        # simple and the animation is resolution-independent.
        self._progress = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._on_toggled)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # QCheckBox's default behaviour only toggles when the cursor is
        # over the indicator rect. Because we collapsed the indicator to
        # 0x0 (we paint our own track), the default hit-test never
        # matches. Make the whole widget the hit target instead.
        if (event.button() == Qt.MouseButton.LeftButton
                and self.isEnabled()
                and self.rect().contains(event.position().toPoint())):
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Space / Enter activate the toggle for keyboard users.
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return,
                           Qt.Key.Key_Enter):
            if self.isEnabled():
                self.setChecked(not self.isChecked())
                event.accept()
                return
        super().keyPressEvent(event)

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._progress)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def getProgress(self) -> float:
        return self._progress

    def setProgress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = Property(float, getProgress, setProgress)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.TRACK_W, self.TRACK_H)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Track colour interpolates between OFF (gray) and ON (emerald).
        off = QColor("#d1d5db")
        on  = QColor(C.OK)
        track = self._lerp_color(off, on, self._progress)
        if not self.isEnabled():
            track.setAlphaF(0.45)

        p.setBrush(QBrush(track))
        p.setPen(Qt.PenStyle.NoPen)
        rect = QRect(0, 0, self.TRACK_W, self.TRACK_H)
        radius = self.TRACK_H / 2
        p.drawRoundedRect(rect, radius, radius)

        # Knob slides along the track.
        knob_d = self.TRACK_H - 2 * self.KNOB_M
        x_off = self.KNOB_M
        x_on  = self.TRACK_W - self.KNOB_M - knob_d
        x = x_off + (x_on - x_off) * self._progress
        knob_color = QColor("white")
        if not self.isEnabled():
            knob_color.setAlphaF(0.85)
        p.setBrush(QBrush(knob_color))
        # Subtle shadow for depth.
        shadow = QColor(0, 0, 0, 30)
        p.setPen(QPen(shadow, 1))
        p.drawEllipse(int(x), self.KNOB_M, knob_d, knob_d)

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        t = max(0.0, min(1.0, t))
        return QColor(
            int(a.red()   + (b.red()   - a.red())   * t),
            int(a.green() + (b.green() - a.green()) * t),
            int(a.blue()  + (b.blue()  - a.blue())  * t),
        )


# ---------------------------------------------------------------------------
# QSS - premium light SaaS theme
# ---------------------------------------------------------------------------

QSS = f"""
QMainWindow {{
    background-color: {C.BG};
}}

QWidget {{
    color: {C.TEXT};
    font-family: "Inter", "Segoe UI", "Helvetica Neue", Arial;
    font-size: 13px;
}}

QLabel, QCheckBox {{
    background: transparent;
}}

/* Tooltips */
QToolTip {{
    background-color: {C.TEXT};
    color: #f9fafb;
    border: 1px solid {C.TEXT};
    padding: 6px 9px;
    border-radius: 4px;
    font-size: 12px;
}}

/* Cards */
QFrame#card {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 12px;
}}
QFrame#microCard {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 10px;
}}

/* Typography */
QLabel#title {{
    font-size: 18px;
    font-weight: 700;
    color: {C.TEXT};
    letter-spacing: -0.2px;
}}
QLabel#subtitle {{
    color: {C.TEXT_MUTED};
    font-size: 12px;
}}
QLabel#sectionTitle {{
    color: {C.TEXT};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}}
QLabel#sectionCount {{
    color: {C.TEXT_MUTED};
    font-weight: 600;
    font-size: 13px;
}}
QLabel#sectionSub {{
    color: {C.TEXT_MUTED};
    font-size: 12px;
}}

/* Header status indicator text */
QLabel#statusLabel {{
    color: {C.TEXT_MUTED};
    font-size: 11px;
    letter-spacing: 0.8px;
    font-weight: 700;
}}
QLabel#statusValue {{
    color: {C.TEXT};
    font-weight: 700;
    font-size: 13px;
    letter-spacing: 0.4px;
}}

/* Default button */
QPushButton {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 8px 16px;
    border-radius: 18px;
    font-weight: 600;
}}
QPushButton:hover    {{ background-color: {C.PANEL_HI}; }}
QPushButton:pressed  {{ background-color: #e5e7eb; }}
QPushButton:disabled {{ color: {C.TEXT_MUTED}; background-color: #fafafa;
                         border: 1px solid #f1f3f5; }}

/* Per-row icon button (Run-once) - circular ghost-style with accent hover */
QPushButton.iconBtn {{
    border-radius: 15px;
    padding: 0;
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.ACCENT};
    font-size: 12px;
    font-weight: 700;
}}
QPushButton.iconBtn:hover {{
    background-color: {C.SLATE_BG};
    border-color: {C.ACCENT};
    color: {C.ACCENT_DIM};
}}
QPushButton.iconBtn:pressed {{
    background-color: #c7d2fe;
}}
QPushButton.iconBtn:disabled {{
    background-color: transparent;
    border: 1px solid #f1f3f5;
    color: {C.TEXT_MUTED};
}}

/* Custom-painted Run-once button: PlayButton draws the triangle in
   paintEvent; we just style the circular background here. */
QPushButton.playBtn {{
    border-radius: 15px;
    padding: 0;
    background-color: transparent;
    border: 1px solid {C.BORDER};
}}
QPushButton.playBtn:hover {{
    background-color: {C.SLATE_BG};
    border-color: {C.ACCENT};
}}
QPushButton.playBtn:pressed {{
    background-color: #c7d2fe;
    border-color: {C.ACCENT_DIM};
}}
QPushButton.playBtn:disabled {{
    background-color: transparent;
    border: 1px solid #f1f3f5;
}}

/* Compact ghost button (e.g. header Refresh) */
QPushButton.ghostBtn {{
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.TEXT_DIM};
    padding: 5px 12px;
    border-radius: 14px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton.ghostBtn:hover {{
    background-color: {C.PANEL_HI};
    color: {C.TEXT};
    border-color: {C.TEXT_MUTED};
}}
QPushButton.ghostBtn:pressed {{ background-color: #e5e7eb; }}
QPushButton.ghostBtn:disabled {{ color: {C.TEXT_MUTED}; border-color: {C.BORDER}; }}

/* Pill control buttons (Start/Pause/Stop) */
QPushButton#btnStart {{
    background-color: {C.OK};
    border: 1px solid {C.OK};
    color: white;
    padding: 9px 22px;
}}
QPushButton#btnStart:hover    {{ background-color: #047857; border-color: #047857; }}
QPushButton#btnStart:pressed  {{ background-color: #065f46; border-color: #065f46; }}
QPushButton#btnStart:disabled {{ background-color: #d1fae5; border-color: #d1fae5; color: #6ee7b7; }}

QPushButton#btnPause {{
    background-color: {C.WARN_BG};
    border: 1px solid {C.WARN_BG};
    color: {C.WARN};
    padding: 9px 22px;
}}
QPushButton#btnPause:hover    {{ background-color: #fde68a; border-color: #fde68a; }}
QPushButton#btnPause:pressed  {{ background-color: #fcd34d; border-color: #fcd34d; }}
QPushButton#btnPause:disabled {{ background-color: #fef3c7; border-color: #fef3c7; color: #fcd34d; }}

QPushButton#btnStop {{
    background-color: {C.ERR_BG};
    border: 1px solid {C.ERR_BG};
    color: {C.ERR};
    padding: 9px 22px;
}}
QPushButton#btnStop:hover    {{ background-color: #fecaca; border-color: #fecaca; }}
QPushButton#btnStop:pressed  {{ background-color: #fca5a5; border-color: #fca5a5; }}
QPushButton#btnStop:disabled {{ background-color: #fee2e2; border-color: #fee2e2; color: #fca5a5; }}

/* Log filter chips - QPushButton (checkable) styled as pills */
QPushButton.chip {{
    border-radius: 11px;
    padding: 3px 11px;
    font-size: 12px;
    font-weight: 600;
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.TEXT_MUTED};
}}
QPushButton.chip:hover {{
    background-color: {C.PANEL_ALT};
}}
QPushButton.chip:checked[level="info"]    {{ background-color: {C.INFO_BG}; color: {C.INFO}; border-color: {C.INFO_BG}; }}
QPushButton.chip:checked[level="warning"] {{ background-color: {C.WARN_BG}; color: {C.WARN}; border-color: {C.WARN_BG}; }}
QPushButton.chip:checked[level="error"]   {{ background-color: {C.ERR_BG};  color: {C.ERR};  border-color: {C.ERR_BG}; }}

/* Tables */
QTableWidget {{
    background-color: {C.PANEL};
    alternate-background-color: {C.PANEL_ALT};
    gridline-color: transparent;
    border: none;
    selection-background-color: transparent;
    selection-color: {C.TEXT};
}}
QHeaderView::section {{
    background-color: {C.PANEL};
    color: {C.TEXT_MUTED};
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {C.BORDER};
    font-weight: 700;
    font-size: 11px;
    letter-spacing: 0.6px;
    text-transform: uppercase;
}}
QTableCornerButton::section {{
    background-color: {C.PANEL};
    border: none;
    border-bottom: 1px solid {C.BORDER};
}}

/* Progress bars - sleek thin */
QProgressBar {{
    background-color: #eef0f3;
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 6px;
    max-height: 6px;
}}
QProgressBar::chunk {{
    background-color: {C.ACCENT};
    border-radius: 4px;
}}

/* Log */
QPlainTextEdit#logView {{
    background-color: {C.PANEL_ALT};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 8px;
    font-family: "JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New";
    font-size: 12px;
    padding: 10px 12px;
    selection-background-color: {C.SLATE_BG};
}}

/* Native checkbox indicator (sequential rows) */
QCheckBox {{
    color: {C.TEXT};
    spacing: 0px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid #d1d5db;
    background: {C.PANEL};
}}
QCheckBox::indicator:hover {{
    border: 1px solid {C.ACCENT};
}}
QCheckBox::indicator:checked {{
    background: {C.ACCENT};
    border: 1px solid {C.ACCENT};
    image: none;
}}

/* Splitters and scrollbars */
QSplitter::handle {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: #d1d5db;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #9ca3af; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 4px; }}
QScrollBar::handle:horizontal {{ background: #d1d5db; border-radius: 4px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: #9ca3af; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


# ---------------------------------------------------------------------------
# Bridge: marshals callbacks from the automation thread onto Qt's main loop
# via signals (which are thread-safe across QObject boundaries).
# ---------------------------------------------------------------------------

class _Signals(QObject):
    automation_start    = Signal()
    automation_stop     = Signal()
    activity_start      = Signal(dict)
    activity_complete   = Signal(dict)
    activity_failed     = Signal(dict)
    progress            = Signal(str, float)
    error               = Signal(str)
    status_change       = Signal(dict)
    log_message         = Signal(str, str)
    single_run_finished = Signal(str)
    device_status       = Signal(dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_card_shadow(widget: QWidget) -> None:
    """Apply a soft drop shadow to a card-style frame."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 4)
    shadow.setColor(QColor(0, 0, 0, 22))   # rgba(0,0,0,0.085)
    widget.setGraphicsEffect(shadow)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class GameAutomationWindow(QMainWindow):
    """Main window for a :class:`BaseGameAutomation`."""

    COL_SEQ_ENABLED  = 0
    COL_SEQ_NAME     = 1
    COL_SEQ_PROGRESS = 2
    COL_SEQ_STATUS   = 3
    COL_SEQ_RUN      = 4

    COL_BG_NAME    = 0
    COL_BG_TOGGLE  = 1

    def __init__(
        self,
        automation: BaseGameAutomation,
        title: str = "Game Automation",
    ) -> None:
        super().__init__()
        self.automation = automation
        self.title = title

        self._is_running = False
        self._is_paused = False
        self._activities: List[Activity] = self.automation.get_activities()

        self._seq_rows: Dict[str, Dict[str, Any]] = {}
        self._bg_rows: Dict[str, Dict[str, Any]] = {}

        # Log filter buffer: keep all entries internally so toggling a
        # filter back on restores history.
        self._log_buffer: List[tuple] = []
        self._max_log_entries = 2000
        self._log_show = {"info": True, "warning": True, "error": True}

        self._sig = _Signals()
        self._sig.automation_start.connect(self._on_automation_start)
        self._sig.automation_stop.connect(self._on_automation_stop)
        self._sig.activity_start.connect(self._on_activity_start)
        self._sig.activity_complete.connect(self._on_activity_complete)
        self._sig.activity_failed.connect(self._on_activity_failed)
        self._sig.progress.connect(self._on_progress)
        self._sig.error.connect(self._on_error)
        self._sig.status_change.connect(self._on_status_change)
        self._sig.log_message.connect(self._on_log_message)
        self._sig.single_run_finished.connect(self._on_single_run_finished)
        self._sig.device_status.connect(self._on_device_status)

        self._automation_thread: Optional[threading.Thread] = None
        self._single_run_thread: Optional[threading.Thread] = None
        self._single_run_id: Optional[str] = None
        self._device_status_thread: Optional[threading.Thread] = None
        self._device_status_lock = threading.Lock()
        self._closing = False

        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self._periodic_refresh)
        self._timer.start()

        self._build_ui()
        self._register_callbacks()
        self._refresh_button_state()
        # Kick an initial deep refresh so the header shows real status as
        # soon as the window appears (worker runs off the GUI thread).
        QTimer.singleShot(150, lambda: self._kick_device_status_refresh(deep=True))

    # ----- callback wiring --------------------------------------------------

    def _register_callbacks(self) -> None:
        a = self.automation
        a.register_callback("on_start", lambda: self._sig.automation_start.emit())
        a.register_callback("on_stop",  lambda: self._sig.automation_stop.emit())
        a.register_callback(
            "on_activity_start",
            lambda act: self._sig.activity_start.emit({
                "id": act.id, "name": act.name, "status": act.status.value,
            }),
        )
        a.register_callback(
            "on_activity_complete",
            lambda act, success: self._sig.activity_complete.emit({
                "id": act.id, "name": act.name, "success": success,
                "status": act.status.value,
            }),
        )
        a.register_callback(
            "on_activity_failed",
            lambda act, err: self._sig.activity_failed.emit({
                "id": act.id, "name": act.name, "error": str(err),
            }),
        )
        a.register_callback(
            "on_progress",
            lambda aid, p: self._sig.progress.emit(aid, float(p)),
        )
        a.register_callback("on_error",
                            lambda err: self._sig.error.emit(str(err)))
        a.register_callback("on_status_change",
                            lambda status: self._sig.status_change.emit(status))

        add_log_subscriber(self._on_log_bus)

    def _on_log_bus(self, level: str, message: str) -> None:
        bucket = {
            "info":    "info",
            "success": "success",
            "warning": "warning",
            "error":   "error",
            "state":   "info",
            "quest":   "info",
            "normal":  "info",
        }.get(level, "info")
        self._sig.log_message.emit(bucket, message)

    # ----- UI construction --------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(self.title)
        self.resize(1320, 820)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        root.addWidget(self._build_header())
        root.addWidget(self._build_activities_split(), 3)
        root.addWidget(self._build_bottom_row(), 2)

    # ---- header ------------------------------------------------------------

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 14, 16, 12)
        outer.setSpacing(10)

        # ---- Top row: title + status pill + control buttons ----
        top = QHBoxLayout()
        top.setSpacing(16)

        # Left: title + subtitle
        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel(self.title)
        title.setObjectName("title")
        subtitle = QLabel("ADB game automation control panel")
        subtitle.setObjectName("subtitle")
        left.addWidget(title)
        left.addWidget(subtitle)
        top.addLayout(left)

        top.addStretch(1)

        # Status indicator (label, dot, value text)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        status_lbl = QLabel("STATUS")
        status_lbl.setObjectName("statusLabel")
        self.status_dot = PulsingDot(C.OK)
        self.status_value = QLabel("READY")
        self.status_value.setObjectName("statusValue")
        status_row.addWidget(status_lbl)
        status_row.addSpacing(2)
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_value)
        top.addLayout(status_row)

        top.addSpacing(20)

        # Control buttons
        self.btn_start = QPushButton("▶  Start")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setMinimumHeight(34)
        self.btn_start.clicked.connect(self._cb_start)

        self.btn_pause = QPushButton("⏸  Pause")
        self.btn_pause.setObjectName("btnPause")
        self.btn_pause.setMinimumHeight(34)
        self.btn_pause.clicked.connect(self._cb_pause)

        self.btn_stop = QPushButton("■  Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setMinimumHeight(34)
        self.btn_stop.clicked.connect(self._cb_stop)

        top.addWidget(self.btn_start)
        top.addWidget(self.btn_pause)
        top.addWidget(self.btn_stop)

        outer.addLayout(top)

        # Hairline divider between rows.
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(
            f"background-color: {C.BORDER}; border: none; max-height: 1px;"
        )
        outer.addWidget(sep)

        # ---- Bottom row: emulator + app + refresh ----
        info = QHBoxLayout()
        info.setSpacing(20)

        # Device cluster
        dev_label = QLabel("EMULATOR")
        dev_label.setObjectName("statusLabel")
        self.dev_dot = PulsingDot(C.TEXT_MUTED)
        self.dev_value = QLabel("Not connected")
        self.dev_value.setStyleSheet(f"color:{C.TEXT};font-weight:600;")
        info.addWidget(dev_label)
        info.addSpacing(2)
        info.addWidget(self.dev_dot)
        info.addWidget(self.dev_value)

        info.addSpacing(8)

        # App cluster
        app_label = QLabel("APP")
        app_label.setObjectName("statusLabel")
        self.app_value = QLabel("—")
        self.app_value.setStyleSheet(f"color:{C.TEXT_DIM};")
        info.addWidget(app_label)
        info.addWidget(self.app_value, 1)

        info.addStretch(1)

        # Refresh button (compact)
        self.btn_refresh = QPushButton("⟳  Refresh")
        self.btn_refresh.setProperty("class", "ghostBtn")
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.setToolTip("Re-check connected emulators / devices")
        self.btn_refresh.clicked.connect(self._cb_refresh_devices)
        info.addWidget(self.btn_refresh)

        outer.addLayout(info)

        return card

    # ---- activities split --------------------------------------------------

    def _build_activities_split(self) -> QWidget:
        seq_acts = [a for a in self._activities if not a.background]
        bg_acts  = [a for a in self._activities if a.background]

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_sequential_panel(seq_acts))
        splitter.addWidget(self._build_background_panel(bg_acts))
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setHandleWidth(14)
        splitter.setChildrenCollapsible(False)
        return splitter

    @staticmethod
    def _section_header(title: str, count: int, sub: str) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(8)
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        c = QLabel(f"({count})")
        c.setObjectName("sectionCount")
        s = QLabel(sub)
        s.setObjectName("sectionSub")
        head.addWidget(t)
        head.addWidget(c)
        head.addSpacing(8)
        head.addWidget(s)
        head.addStretch(1)
        return head

    def _build_sequential_panel(self, acts: List[Activity]) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(8)

        layout.addLayout(self._section_header(
            "SEQUENTIAL", len(acts), "Run once in order, top to bottom"
        ))

        if not acts:
            empty = QLabel("No sequential activities.")
            empty.setStyleSheet(f"color:{C.TEXT_MUTED};")
            layout.addWidget(empty)
            layout.addStretch(1)
            return card

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(
            ["", "Activity", "Progress", "Status", ""]
        )
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setRowCount(len(acts))
        table.verticalHeader().setDefaultSectionSize(48)
        table.setFrameShape(QFrame.Shape.NoFrame)

        header = table.horizontalHeader()
        header.setSectionResizeMode(self.COL_SEQ_ENABLED,
                                    QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_SEQ_NAME,
                                    QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_SEQ_PROGRESS,
                                    QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_SEQ_STATUS,
                                    QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(self.COL_SEQ_RUN,
                                    QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(self.COL_SEQ_ENABLED, 44)
        table.setColumnWidth(self.COL_SEQ_PROGRESS, 240)
        table.setColumnWidth(self.COL_SEQ_STATUS, 130)
        table.setColumnWidth(self.COL_SEQ_RUN, 50)

        for row, act in enumerate(acts):
            self._populate_seq_row(table, row, act)

        layout.addWidget(table, 1)
        self.seq_table = table
        return card

    def _populate_seq_row(self, table: QTableWidget, row: int,
                          act: Activity) -> None:
        # Col 0: enabled checkbox
        cb = QCheckBox()
        cb.setChecked(act.enabled)
        cb.toggled.connect(
            lambda checked, aid=act.id: self._cb_toggle_activity(aid, checked)
        )
        table.setCellWidget(row, self.COL_SEQ_ENABLED,
                            self._center(cb))

        # Col 1: name (description on hover)
        name = QLabel(act.name)
        name.setStyleSheet(f"color:{C.TEXT};font-weight:600;")
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if act.description:
            name.setToolTip(act.description)
        name_wrap = self._padded(name, h=10)
        if act.description:
            name_wrap.setToolTip(act.description)
        table.setCellWidget(row, self.COL_SEQ_NAME, name_wrap)

        # Col 2: progress + percentage label side by side
        prog_wrap = QWidget()
        prog_layout = QHBoxLayout(prog_wrap)
        prog_layout.setContentsMargins(8, 0, 8, 0)
        prog_layout.setSpacing(8)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(int(act.progress))
        progress.setTextVisible(False)
        progress.setFixedHeight(6)
        progress.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Fixed)
        pct_label = QLabel(f"{int(act.progress)}%")
        pct_label.setStyleSheet(f"color:{C.TEXT_MUTED};font-size:11px;font-weight:600;")
        pct_label.setFixedWidth(36)
        pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_layout.addWidget(progress, 1)
        prog_layout.addWidget(pct_label)
        table.setCellWidget(row, self.COL_SEQ_PROGRESS, prog_wrap)

        # Col 3: status pill (soft background + dark text)
        pill = QLabel()
        self._apply_status_pill_style(pill, act.status.value)
        table.setCellWidget(row, self.COL_SEQ_STATUS,
                            self._center(pill))

        # Col 4: Run-once button - executes only this activity.
        run_btn = PlayButton()
        run_btn.setToolTip("Run only this activity once")
        run_btn.clicked.connect(
            lambda _checked=False, aid=act.id: self._cb_run_single(aid)
        )
        table.setCellWidget(row, self.COL_SEQ_RUN,
                            self._center(run_btn))

        self._seq_rows[act.id] = {
            "checkbox": cb,
            "progress": progress,
            "pct": pct_label,
            "pill": pill,
            "run_btn": run_btn,
        }

    def _build_background_panel(self, acts: List[Activity]) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(8)

        layout.addLayout(self._section_header(
            "BACKGROUND", len(acts), "Loop in own thread"
        ))

        if not acts:
            empty = QLabel("No background activities.")
            empty.setStyleSheet(f"color:{C.TEXT_MUTED};")
            layout.addWidget(empty)
            layout.addStretch(1)
            return card

        # Background tasks: a simple list of name + iOS toggle. Shows clean.
        list_wrap = QWidget()
        list_layout = QVBoxLayout(list_wrap)
        list_layout.setContentsMargins(0, 4, 0, 0)
        list_layout.setSpacing(2)

        for idx, act in enumerate(acts):
            row_widget = QFrame()
            row_widget.setStyleSheet(
                "QFrame { border-radius: 8px; }"
                f"QFrame:hover {{ background-color: {C.PANEL_ALT}; }}"
            )
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(10, 10, 10, 10)
            row.setSpacing(10)

            name = QLabel(act.name)
            name.setStyleSheet(f"color:{C.TEXT};font-weight:600;")
            if act.description:
                name.setToolTip(act.description)

            toggle = ToggleSwitch()
            toggle.setChecked(act.enabled)
            toggle.toggled.connect(
                lambda checked, aid=act.id: self._cb_toggle_activity(aid, checked)
            )
            if act.description:
                toggle.setToolTip(act.description)

            row.addWidget(name, 1)
            row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
            list_layout.addWidget(row_widget)
            # ``_refresh_button_state`` looks up the toggle by activity id
            # under the same ``checkbox`` key the sequential rows use, so
            # both panels share the same enable/disable logic.
            self._bg_rows[act.id] = {"checkbox": toggle}

        list_layout.addStretch(1)
        layout.addWidget(list_wrap, 1)
        return card

    # ---- bottom: log + metrics --------------------------------------------

    def _build_bottom_row(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_log_panel())
        splitter.addWidget(self._build_metrics_panel())
        splitter.setStretchFactor(0, 75)
        splitter.setStretchFactor(1, 25)
        splitter.setHandleWidth(14)
        splitter.setChildrenCollapsible(False)

        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.addWidget(splitter)
        wrap.setMinimumHeight(240)
        wrap.setMaximumHeight(330)
        return wrap

    def _build_log_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("LOG")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addSpacing(10)

        # Filter chips
        self.cb_filter_info    = self._make_chip("Info",    "info",    True)
        self.cb_filter_warning = self._make_chip("Warning", "warning", True)
        self.cb_filter_error   = self._make_chip("Error",   "error",   True)
        self.cb_filter_info.toggled.connect(    lambda c: self._set_log_filter("info", c))
        self.cb_filter_warning.toggled.connect( lambda c: self._set_log_filter("warning", c))
        self.cb_filter_error.toggled.connect(   lambda c: self._set_log_filter("error", c))

        head.addWidget(self.cb_filter_info)
        head.addWidget(self.cb_filter_warning)
        head.addWidget(self.cb_filter_error)
        head.addStretch(1)

        clear_btn = QPushButton("Clear")
        clear_btn.setFlat(True)
        clear_btn.setStyleSheet(
            f"QPushButton {{ color: {C.TEXT_MUTED}; background: transparent;"
            "border: none; padding: 4px 8px; font-weight: 600; font-size: 12px; }"
            f"QPushButton:hover {{ color: {C.TEXT}; }}"
        )
        clear_btn.clicked.connect(self._cb_clear_log)
        head.addWidget(clear_btn)
        layout.addLayout(head)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self._max_log_entries)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(10)
        self.log_view.setFont(mono)
        layout.addWidget(self.log_view, 1)

        self._append_log("info", "Ready to start automation")
        return card

    @staticmethod
    def _make_chip(label: str, level: str, default: bool) -> QPushButton:
        chip = QPushButton(label)
        chip.setProperty("class", "chip")
        chip.setProperty("level", level)
        chip.setCheckable(True)
        chip.setChecked(default)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        return chip

    def _build_metrics_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(10)

        title = QLabel("METRICS")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setContentsMargins(0, 0, 0, 0)

        self.metric_success  = self._make_metric_card("Success rate", "—", C.OK)
        self.metric_matches  = self._make_metric_card("Matches",      "0", C.ACCENT)
        self.metric_failures = self._make_metric_card("Failures",     "0", C.ERR)
        self.metric_avg_time = self._make_metric_card("Avg time",     "0.000s", C.TEXT)

        grid.addWidget(self.metric_success["card"],  0, 0)
        grid.addWidget(self.metric_matches["card"],  0, 1)
        grid.addWidget(self.metric_failures["card"], 1, 0)
        grid.addWidget(self.metric_avg_time["card"], 1, 1)

        outer.addLayout(grid, 1)
        return card

    @staticmethod
    def _make_metric_card(label: str, default: str, value_color: str) -> Dict[str, QLabel]:
        card = QFrame()
        card.setObjectName("microCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        lbl = QLabel(label.upper())
        lbl.setStyleSheet(
            f"color:{C.TEXT_MUTED}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 0.6px;"
        )
        val = QLabel(default)
        val.setStyleSheet(f"color:{value_color}; font-size: 18px; font-weight: 700;")

        layout.addWidget(lbl)
        layout.addWidget(val)
        layout.addStretch(1)
        return {"card": card, "label": lbl, "value": val}

    # ---- small layout helpers ---------------------------------------------

    @staticmethod
    def _center(widget: QWidget) -> QWidget:
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
        return wrap

    @staticmethod
    def _padded(widget: QWidget, h: int = 0, v: int = 0) -> QWidget:
        wrap = QWidget()
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(h, v, h, v)
        layout.addWidget(widget)
        return wrap

    # ----- log handling -----------------------------------------------------

    def _set_log_filter(self, level: str, visible: bool) -> None:
        self._log_show[level] = bool(visible)
        self.log_view.clear()
        for ts, lvl, msg in self._log_buffer:
            if self._is_level_visible(lvl):
                self._render_log_line(ts, lvl, msg)

    def _is_level_visible(self, level: str) -> bool:
        if level == "warning":
            return self._log_show["warning"]
        if level == "error":
            return self._log_show["error"]
        return self._log_show["info"]

    def _append_log(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_buffer.append((ts, level, message))
        if len(self._log_buffer) > self._max_log_entries:
            del self._log_buffer[: len(self._log_buffer) - self._max_log_entries]
        if self._is_level_visible(level):
            self._render_log_line(ts, level, message)

    def _render_log_line(self, ts: str, level: str, message: str) -> None:
        prefix = {
            "info":    "INFO",
            "success": "OK  ",
            "warning": "WARN",
            "error":   "ERR ",
            "state":   "STAT",
            "quest":   "QST ",
            "normal":  "    ",
        }.get(level, "INFO")
        color = _LOG_COLORS.get(level, _LOG_COLORS["info"])
        safe_msg = (message
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
        html = (
            f'<span style="color:{C.TEXT_MUTED};">[{ts}]</span> '
            f'<span style="color:{color};font-weight:700;">{prefix}</span> '
            f'<span style="color:{C.TEXT};">{safe_msg}</span>'
        )
        self.log_view.appendHtml(html)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ----- updaters ---------------------------------------------------------

    @staticmethod
    def _apply_status_pill_style(pill: QLabel, status: str) -> None:
        bg, fg = _STATUS_PILL.get(status, _STATUS_PILL["pending"])
        pill.setText(status.upper())
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet(
            f"background-color:{bg}; color:{fg};"
            "padding:4px 12px; border-radius:10px; font-weight:700;"
            "font-size:11px; letter-spacing: 0.5px;"
        )

    def _set_status_header(self, label: str, dot_color: str) -> None:
        self.status_value.setText(label)
        self.status_dot.setColor(dot_color)

    def _refresh_button_state(self) -> None:
        self.btn_start.setEnabled(not self._is_running)
        self.btn_pause.setEnabled(self._is_running)
        self.btn_stop.setEnabled(self._is_running)
        self.btn_pause.setText("▶  Resume" if self._is_paused else "⏸  Pause")

        if not self._is_running:
            self._set_status_header("READY", C.OK)
        elif self._is_paused:
            self._set_status_header("PAUSED", C.WARN)
        else:
            self._set_status_header("RUNNING", C.ACCENT)

        # Lock sequential checkboxes while running. Background toggles stay
        # interactive so users can flip skip-dialog etc on the fly.
        for act in self._activities:
            if act.background:
                row = self._bg_rows.get(act.id)
            else:
                row = self._seq_rows.get(act.id)
            if not row:
                continue
            cb = row["checkbox"]
            cb.setEnabled((not self._is_running) or act.background)

        # Per-row Run-once buttons: disabled while the main loop runs or
        # while another single-activity run is in flight.
        single_run_active = bool(
            self._single_run_thread and self._single_run_thread.is_alive()
        )
        run_btns_enabled = (not self._is_running) and (not single_run_active)
        for row in self._seq_rows.values():
            btn = row.get("run_btn")
            if btn is not None:
                btn.setEnabled(run_btns_enabled)

    # ----- button slots -----------------------------------------------------

    def _cb_start(self) -> None:
        if self._is_running:
            return
        try:
            self.automation.reset_activities()
            for act in self._activities:
                if not act.background:
                    self._update_activity_status(act.id, "pending")
                    self._update_activity_progress(act.id, 0.0)

            self._automation_thread = threading.Thread(
                target=self.automation.start,
                daemon=True,
            )
            self._automation_thread.start()

            self._is_running = True
            self._is_paused = False
            self._refresh_button_state()
        except Exception as e:
            log_error(f"Failed to start automation: {e}")

    def _cb_pause(self) -> None:
        if not self._is_running:
            return
        try:
            if self._is_paused:
                self.automation.resume()
                self._is_paused = False
            else:
                self.automation.pause()
                self._is_paused = True
            self._refresh_button_state()
        except Exception as e:
            log_error(f"Pause/resume error: {e}")

    def _cb_stop(self) -> None:
        if not self._is_running:
            return
        try:
            self.automation.stop()
        except Exception as e:
            log_error(f"Stop error: {e}")

    def _cb_toggle_activity(self, activity_id: str, checked: bool) -> None:
        try:
            self.automation.set_activity_enabled(activity_id, checked)
            for act in self._activities:
                if act.id == activity_id:
                    act.enabled = checked
                    break
        except Exception as e:
            log_error(f"Toggle error: {e}")

    def _cb_run_single(self, activity_id: str) -> None:
        """Run only the named activity, in its own thread.

        Refuses if the main automation loop or another single-run is
        already in progress. The button stays disabled for the duration of
        the run and is re-enabled from the GUI thread when it finishes.
        """
        if self._is_running:
            log_error("Cannot run single activity while automation is running.")
            return
        if self._single_run_thread and self._single_run_thread.is_alive():
            log_error(
                "Another single-activity run is already in progress; "
                "wait for it to finish."
            )
            return

        self._single_run_id = activity_id
        self._set_single_run_buttons_enabled(False)
        # Reset the row visually before the worker starts.
        self._update_activity_status(activity_id, "pending")
        self._update_activity_progress(activity_id, 0.0)

        def _runner() -> None:
            try:
                self.automation.run_single_activity(activity_id)
            except Exception as e:
                log_error(f"Single-run error in {activity_id}: {e}")
            finally:
                # Re-enable buttons on the GUI thread once the worker is done.
                self._sig.single_run_finished.emit(activity_id)

        self._single_run_thread = threading.Thread(
            target=_runner,
            name=f"single-{activity_id}",
            daemon=True,
        )
        self._single_run_thread.start()

    def _set_single_run_buttons_enabled(self, enabled: bool) -> None:
        """Enable/disable every Run-single button at once.

        While one activity is running on demand we disable all of them so
        the user can't queue up overlapping single runs.
        """
        for row in self._seq_rows.values():
            btn = row.get("run_btn")
            if btn is not None:
                btn.setEnabled(enabled)
        # The big Start button is also gated while a single-run is going.
        self.btn_start.setEnabled(enabled and not self._is_running)

    def _cb_clear_log(self) -> None:
        self._log_buffer.clear()
        self.log_view.clear()
        self._append_log("info", "Log cleared")

    # ----- automation signal slots -----------------------------------------

    @Slot()
    def _on_automation_start(self) -> None:
        self._is_running = True
        self._is_paused = False
        self._refresh_button_state()

    @Slot()
    def _on_automation_stop(self) -> None:
        self._is_running = False
        self._is_paused = False
        self._refresh_button_state()

    @Slot(dict)
    def _on_activity_start(self, data: dict) -> None:
        self._update_activity_status(data["id"], "running")

    @Slot(dict)
    def _on_activity_complete(self, data: dict) -> None:
        status = "completed" if data["success"] else "failed"
        self._update_activity_status(data["id"], status)

    @Slot(dict)
    def _on_activity_failed(self, data: dict) -> None:
        self._update_activity_status(data["id"], "failed")

    @Slot(str, float)
    def _on_progress(self, activity_id: str, progress: float) -> None:
        self._update_activity_progress(activity_id, progress)

    @Slot(str)
    def _on_error(self, _message: str) -> None:
        pass  # already in log via global bus

    @Slot(dict)
    def _on_status_change(self, status: dict) -> None:
        self._is_paused = bool(status.get("paused", False))
        self._refresh_button_state()

    @Slot(str, str)
    def _on_log_message(self, level: str, message: str) -> None:
        self._append_log(level, message)

    @Slot(str)
    def _on_single_run_finished(self, _activity_id: str) -> None:
        self._single_run_id = None
        self._single_run_thread = None
        # Re-enable Run buttons (Start button state is controlled by
        # _refresh_button_state which respects _is_running too).
        self._set_single_run_buttons_enabled(True)

    @Slot(dict)
    def _on_device_status(self, summary: dict) -> None:
        connected = bool(summary.get("connected"))
        device_id = summary.get("device_id")
        device_name = summary.get("device_name")
        app_pkg = summary.get("app_package")
        app_name = summary.get("app_name")

        # Device line
        if connected:
            label = device_name or device_id or "Connected"
            if device_id and device_name and device_name != device_id:
                label = f"{device_name}  ({device_id})"
            self.dev_value.setText(label)
            self.dev_value.setStyleSheet(f"color:{C.TEXT};font-weight:600;")
            self.dev_dot.setColor(C.OK)
        else:
            self.dev_value.setText("Not connected")
            self.dev_value.setStyleSheet(f"color:{C.TEXT_MUTED};font-weight:600;")
            self.dev_dot.setColor(C.TEXT_MUTED)

        # App line
        if connected and app_pkg:
            text = app_name or app_pkg
            if app_name and app_pkg and app_name != app_pkg:
                text = f"{app_name}  ({app_pkg})"
            self.app_value.setText(text)
            self.app_value.setStyleSheet(f"color:{C.TEXT};")
        else:
            self.app_value.setText("—")
            self.app_value.setStyleSheet(f"color:{C.TEXT_MUTED};")

        # Re-enable refresh button
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("⟳  Refresh")

    # ----- per-row updates --------------------------------------------------

    def _update_activity_status(self, aid: str, status: str) -> None:
        row = self._seq_rows.get(aid)
        if row:
            self._apply_status_pill_style(row["pill"], status)

    def _update_activity_progress(self, aid: str, progress: float) -> None:
        row = self._seq_rows.get(aid)
        if not row:
            return
        v = int(max(0.0, min(100.0, progress)))
        row["progress"].setValue(v)
        row["pct"].setText(f"{v}%")

    def _update_bg_badge(self, aid: str, live: bool) -> None:
        # Background panel uses iOS toggles - no live badge to update,
        # but we keep the method for API parity with previous GUIs.
        pass

    # ----- periodic refresh -------------------------------------------------

    def _periodic_refresh(self) -> None:
        try:
            metrics = self.automation.get_performance_metrics() or {}
        except Exception:
            metrics = {}

        success_rate = metrics.get("success_rate", 0.0) or 0.0
        self.metric_success["value"].setText(f"{success_rate * 100:.1f}%")
        self.metric_matches["value"].setText(str(metrics.get("template_matches", 0) or 0))
        self.metric_failures["value"].setText(str(metrics.get("template_failures", 0) or 0))
        self.metric_avg_time["value"].setText(
            f"{(metrics.get('avg_match_time') or 0):.3f}s"
        )

        # Re-poll device status in the background. We use a worker thread
        # because ADB shell calls can block for a few seconds, especially
        # the first time after a device disconnects.
        self._kick_device_status_refresh(deep=False)

    # ----- device / app status ---------------------------------------------

    def _kick_device_status_refresh(self, deep: bool = False) -> None:
        """Spawn a worker (if one isn't already running) to fetch device
        status off the GUI thread and emit the result via signal.

        ``deep=True`` runs the full ``check_adb_connection`` flow including
        port scanning. ``deep=False`` only re-uses an existing connection
        or quickly re-lists the already-known devices.
        """
        # Don't spawn new workers once the window is closing - the signal
        # bridge would already be torn down by the time the worker
        # finished, and ``emit`` would raise RuntimeError on a deleted
        # source.
        if getattr(self, "_closing", False):
            return
        with self._device_status_lock:
            if (self._device_status_thread is not None
                    and self._device_status_thread.is_alive()):
                return

            def _worker() -> None:
                adb = self.automation.adb
                try:
                    if deep or not adb.is_connected():
                        if deep:
                            adb.check_adb_connection()
                        else:
                            adb.quick_refresh()
                    summary = adb.get_status_summary()
                except Exception as e:
                    summary = {
                        "connected": False,
                        "device_id": None,
                        "device_name": None,
                        "app_package": None,
                        "app_name": None,
                        "error": str(e),
                    }
                # Bail out if the window is going away. Touching ``_sig``
                # after the C++ object is destroyed throws RuntimeError.
                if getattr(self, "_closing", False):
                    return
                try:
                    self._sig.device_status.emit(summary)
                except RuntimeError:
                    pass

            t = threading.Thread(
                target=_worker,
                name="device-status",
                daemon=True,
            )
            self._device_status_thread = t
            t.start()

    def _cb_refresh_devices(self) -> None:
        """Manual Refresh button handler.

        Triggers a full reconnect (port scan + handshake). The button is
        disabled while the worker runs so users don't queue up duplicates.
        """
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("⟳  Scanning…")
        log_info("Refreshing device list...")
        self._kick_device_status_refresh(deep=True)

    # ----- shutdown ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        # Mark the window as closing so background workers (device-status
        # refresh, log subscriber) skip emitting into a destroyed signal.
        self._closing = True
        try:
            if self._is_running:
                self.automation.stop()
        except Exception as e:
            log_error(f"Error stopping automation on exit: {e}")
        try:
            remove_log_subscriber(self._on_log_bus)
        except Exception:
            pass
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Convenience entry points
# ---------------------------------------------------------------------------

def run_with_pyside(game_class, title: str = "Game Automation") -> None:
    """Instantiate ``game_class`` and launch the PySide6 interface."""
    log_info(f"Starting PySide GUI: {title}")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    # Native palette + QSS for a coherent light theme.
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
    app.setPalette(palette)
    app.setStyleSheet(QSS)

    game = game_class()
    window = GameAutomationWindow(game, title)
    window.show()
    app.exec()


if __name__ == "__main__":
    print(
        "This is a PySide6 GUI module. "
        "Import and call run_with_pyside(GameClass, title)."
    )
