"""
PySide6-based GUI for game automation - Premium light SaaS dashboard.

Modern, native-looking front-end for any :class:`BaseGameAutomation`. Same
callback contract as the previous DearPyGui / webview GUIs - drop-in
replacement.

Layout::

    +-------------------------------------------------------------+
    |  [Logo] Title / subtitle   ● STATUS   [▶ Start][⏸][■]      |
    |   Progress 3/7 ▓▓▓░░░░░  Elapsed 00:12:34   [⟳ Refresh]    |
    +-------------------------------------------------------------+
    |  SEQUENTIAL (n)  [All][None]   |  BACKGROUND (n)            |
    |   table with progress bars     |   rows with iOS toggles    |
    +-------------------------------------------------------------+
    |  LOG  [search…] [Info][OK][Warn][Err] [Clear] | METRICS     |
    |   monospace terminal                           | 2x3 cards   |
    +-------------------------------------------------------------+
    |  status bar: activity • device • app • elapsed              |
    +-------------------------------------------------------------+

Usage::

    from src.games.bd2.bd2 import BD2
    from src.gui.pyside_gui import run_with_pyside

    run_with_pyside(BD2, "BD2 Automation")
"""
from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QObject,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
    Property,
    QPointF,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPolygonF,
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
    QLineEdit,
    QMainWindow,
    QMenu,
    QMenuBar,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
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
    BG          = "#f4f5f7"   # window background (ultra-light gray)
    PANEL       = "#ffffff"   # cards (pure white)
    PANEL_ALT   = "#f8f9fb"   # zebra rows / inner subtle bg
    PANEL_HI    = "#f1f3f5"   # hovered surfaces
    BORDER      = "#e6e8ec"   # hairline borders
    BORDER_HI   = "#d1d5db"   # emphasized border

    # Text
    TEXT        = "#0f172a"   # near-black slate
    TEXT_DIM    = "#475569"   # secondary
    TEXT_MUTED  = "#94a3b8"   # tertiary / labels

    # Accents
    ACCENT      = "#4f46e5"   # indigo-600 (primary)
    ACCENT_DIM  = "#3730a3"
    ACCENT_BG   = "#eef2ff"   # indigo-50

    OK          = "#059669"   # emerald-600
    OK_BG       = "#d1fae5"   # emerald-100
    OK_DIM      = "#047857"
    WARN        = "#b45309"   # amber-700 text
    WARN_BG     = "#fef3c7"   # amber-100
    ERR         = "#b91c1c"   # red-700 text
    ERR_BG      = "#fee2e2"   # red-100
    INFO        = "#1d4ed8"   # blue-700
    INFO_BG     = "#dbeafe"   # blue-100
    SLATE_BG    = "#e0e7ff"   # indigo-100 (pending pill)
    SLATE_FG    = "#3730a3"   # indigo-700

    SHADOW      = "#0f172a"   # shadow base (used with alpha)


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
# Vector icons - drawn with QPainter so we don't depend on system fonts for
# unicode glyphs (which render inconsistently across platforms).
# ---------------------------------------------------------------------------

class Icon(QWidget):
    """A small vector icon painted via QPainter.

    Recognised names: ``play``, ``pause``, ``stop``, ``refresh``,
    ``search``, ``clear``, ``check``, ``controller``, ``clock``,
    ``device``, ``app``. Unknown names render nothing.
    """

    def __init__(
        self,
        name: str,
        size: int = 16,
        color: str = C.TEXT,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._size = size
        self._color = QColor(color)
        self.setFixedSize(size, size)

    def setColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def setName(self, name: str) -> None:
        self._name = name
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._size, self._size)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QColor(self._color)
        p.setBrush(QBrush(c))
        p.setPen(QPen(c, 1.6, Qt.PenStyle.SolidLine,
                      Qt.PenStyle.RoundCap, Qt.PenStyle.RoundJoin))
        w = self.width()
        h = self.height()
        m = w * 0.18  # margin so glyphs don't touch edges
        name = self._name
        if name == "play":
            path = QPainterPath()
            path.moveTo(w - m, h / 2)
            path.lineTo(m, m)
            path.lineTo(m, h - m)
            path.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)
        elif name == "pause":
            p.setPen(Qt.PenStyle.NoPen)
            bw = (w - 2 * m) / 3
            p.drawRoundedRect(QRectF(m, m, bw, h - 2 * m), 1.5, 1.5)
            p.drawRoundedRect(QRectF(w - m - bw, m, bw, h - 2 * m), 1.5, 1.5)
        elif name == "stop":
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(m, m, w - 2 * m, h - 2 * m), 2.5, 2.5)
        elif name == "refresh":
            r = (w - 2 * m) / 2
            cx = w / 2
            cy = h / 2
            p.setBrush(Qt.BrushStyle.NoBrush)
            # Arc covering ~300deg, leaving a gap at the top-right.
            p.drawArc(QRectF(cx - r, cy - r, 2 * r, 2 * r),
                      30 * 16, 300 * 16)
            # Arrowhead at the open end.
            p.setBrush(QBrush(c))
            p.setPen(Qt.PenStyle.NoPen)
            arrow = QPolygonF([
                QPointF(w - m, m + 1),
                QPointF(w - m, m + 6),
                QPointF(w - m - 5, m + 1),
            ])
            p.drawPolygon(arrow)
        elif name == "search":
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = (w - 2 * m) / 2
            cx = m + r
            cy = m + r
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.drawLine(QPointF(cx + r * 0.7, cy + r * 0.7),
                       QPointF(w - m, h - m))
        elif name == "clear":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(m, m), QPointF(w - m, h - m))
            p.drawLine(QPointF(w - m, m), QPointF(m, h - m))
        elif name == "check":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(m, h * 0.55), QPointF(w * 0.42, h - m))
            p.drawLine(QPointF(w * 0.42, h - m), QPointF(w - m, m + 1))
        elif name == "controller":
            # Stylised game controller silhouette.
            p.setPen(Qt.PenStyle.NoPen)
            rx = w * 0.32
            ry = h * 0.22
            cx = w / 2
            cy = h / 2 + 1
            p.drawRoundedRect(QRectF(cx - rx, cy - ry, 2 * rx, 2 * ry),
                              ry, ry)
            # D-pad dots + action dots in a contrasting colour.
            p.setBrush(QBrush(QColor(C.PANEL)))
            dot = 1.8
            for dx in (-1, 1):
                for dy in (-1, 1):
                    p.drawEllipse(QPointF(cx + dx * rx * 0.45,
                                          cy + dy * ry * 0.55), dot, dot)
        elif name == "clock":
            r = (w - 2 * m) / 2
            cx = w / 2
            cy = h / 2
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.7))
            p.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.55, cy))
        elif name == "device":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(m, m, w - 2 * m, h - 2 * m), 2, 2)
            p.drawLine(QPointF(w * 0.4, h - m), QPointF(w * 0.6, h - m))
        elif name == "app":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(m, m, w - 2 * m, h - 2 * m), 2.5, 2.5)


class IconButton(QPushButton):
    """A compact button that pairs a vector :class:`Icon` with an optional
    text label. Used for the primary Start/Pause/Stop controls and the
    header Refresh button.
    """

    def __init__(
        self,
        icon_name: str,
        label: str = "",
        icon_size: int = 14,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._icon = Icon(icon_name, icon_size, C.PANEL, self)
        self._label = label
        if label:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(10, 0, 12, 0)
            lay.setSpacing(7)
            lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignVCenter)
            txt = QLabel(label)
            txt.setObjectName("iconLabel")
            lay.addWidget(txt, 0, Qt.AlignmentFlag.AlignVCenter)
        else:
            lay = QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)

    def setIconColor(self, color: str) -> None:
        self._icon.setColor(color)

    def setIconName(self, name: str) -> None:
        self._icon.setName(name)

    def setLabel(self, label: str) -> None:
        self._label = label
        # Find the QLabel child and update it.
        for child in self.findChildren(QLabel):
            if child.objectName() == "iconLabel":
                child.setText(label)
                break


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
        p.drawEllipse(2, 2, self.width() - 4, self.height() - 4)


class PlayButton(QPushButton):
    """Circular Run-once button with a hand-drawn play triangle."""

    SIZE = 30

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", "playBtn")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r = 5.0

        if self.isEnabled():
            color = QColor(C.ACCENT_DIM if self.isDown() else C.ACCENT)
        else:
            color = QColor(C.TEXT_MUTED)

        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
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
    KNOB_M  = 2

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.TRACK_W, self.TRACK_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QCheckBox::indicator { width: 0px; height: 0px; }"
                           "QCheckBox { spacing: 0px; }")

        self._progress = 1.0 if self.isChecked() else 0.0
        self._anim = QPropertyAnimation(self, b"progress", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.toggled.connect(self._on_toggled)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and self.isEnabled()
                and self.rect().contains(event.position().toPoint())):
            self.setChecked(not self.isChecked())
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
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

        knob_d = self.TRACK_H - 2 * self.KNOB_M
        x_off = self.KNOB_M
        x_on  = self.TRACK_W - self.KNOB_M - knob_d
        x = x_off + (x_on - x_off) * self._progress
        knob_color = QColor("white")
        if not self.isEnabled():
            knob_color.setAlphaF(0.85)
        p.setBrush(QBrush(knob_color))
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


class ElapsedTimer(QLabel):
    """A label that shows elapsed time as ``HH:MM:SS`` and ticks every
    second while running. Call :meth:`start` when automation begins and
    :meth:`stop` when it ends.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__("00:00:00", parent)
        self._start: Optional[float] = None
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._start = time.monotonic()
        self._tick()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self._start is not None:
            self._start = None

    def reset(self) -> None:
        self.stop()
        self.setText("00:00:00")

    def _tick(self) -> None:
        if self._start is None:
            return
        elapsed = int(time.monotonic() - self._start)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        self.setText(f"{h:02d}:{m:02d}:{s:02d}")


class StatCard(QFrame):
    """A metric micro-card with an optional left accent bar, a small
    uppercase label, and a large coloured value.
    """

    def __init__(
        self,
        label: str,
        value: str,
        value_color: str = C.TEXT,
        accent: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("microCard")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        if accent:
            bar = QFrame()
            bar.setFixedWidth(3)
            bar.setStyleSheet(
                f"background-color:{accent}; border:none;"
                "border-top-left-radius:10px; border-bottom-left-radius:10px;"
            )
            outer.addWidget(bar)

        body = QWidget()
        body.setProperty("class", "statBody")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(3)

        self._label = QLabel(label.upper())
        self._label.setStyleSheet(
            f"color:{C.TEXT_MUTED}; font-size:10px; font-weight:700;"
            "letter-spacing:0.7px;"
        )
        self._value = QLabel(value)
        self._value.setStyleSheet(
            f"color:{value_color}; font-size:18px; font-weight:700;"
            "letter-spacing:-0.2px;"
        )
        lay.addWidget(self._label)
        lay.addWidget(self._value)
        lay.addStretch(1)

        outer.addWidget(body, 1)

    def setValue(self, text: str) -> None:
        self._value.setText(text)

    def setValueColor(self, color: str) -> None:
        self._value.setStyleSheet(
            f"color:{color}; font-size:18px; font-weight:700;"
            "letter-spacing:-0.2px;"
        )

    def setLabel(self, text: str) -> None:
        self._label.setText(text.upper())


class SearchField(QLineEdit):
    """A rounded search input with a leading search icon and a trailing
    clear button. Emits ``textChanged`` like a normal QLineEdit.
    """

    def __init__(self, placeholder: str = "Search…",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("searchField")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(False)  # we paint our own clear icon
        self._search_icon = Icon("search", 13, C.TEXT_MUTED, self)
        self._clear_btn = QPushButton(self)
        self._clear_btn.setProperty("class", "fieldClear")
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.setToolTip("Clear search")
        self._clear_btn.setVisible(False)
        self._clear_btn.clicked.connect(lambda: self.setText(""))

        self.textChanged.connect(self._on_text_changed)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        ih = 13
        iy = (self.height() - ih) // 2
        self._search_icon.setGeometry(8, iy, ih, ih)
        # Move text right so it doesn't overlap the search icon.
        self.setTextMargins(26, 0, 24, 0)
        bw = 16
        bx = self.width() - bw - 6
        by = (self.height() - bw) // 2
        self._clear_btn.setGeometry(bx, by, bw, bw)

    def _on_text_changed(self, text: str) -> None:
        self._clear_btn.setVisible(bool(text))

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        # Repaint the clear button as an "X" via a child Icon-style overlay.
        # We cheat: the clear button itself is transparent and we paint the
        # X on top of the QLineEdit in the clear-btn rect.
        if self._clear_btn.isVisible():
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            c = QColor(C.TEXT_MUTED)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(c, 1.4, Qt.PenStyle.SolidLine,
                          Qt.PenStyle.RoundCap, Qt.PenStyle.RoundJoin))
            r = self._clear_btn.geometry()
            m = 3
            p.drawLine(QPointF(r.left() + m, r.top() + m),
                       QPointF(r.right() - m, r.bottom() - m))
            p.drawLine(QPointF(r.right() - m, r.top() + m),
                       QPointF(r.left() + m, r.bottom() - m))


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

QMenuBar {{
    background-color: {C.PANEL};
    border-bottom: 1px solid {C.BORDER};
    padding: 2px 6px;
    spacing: 4px;
}}
QMenuBar::item {{
    padding: 5px 10px;
    background: transparent;
    border-radius: 6px;
    color: {C.TEXT_DIM};
    font-weight: 600;
}}
QMenuBar::item:selected {{
    background-color: {C.PANEL_HI};
    color: {C.TEXT};
}}
QMenu {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 22px 6px 14px;
    border-radius: 6px;
    color: {C.TEXT};
}}
QMenu::item:selected {{
    background-color: {C.ACCENT_BG};
    color: {C.ACCENT_DIM};
}}
QMenu::separator {{
    height: 1px;
    background-color: {C.BORDER};
    margin: 4px 8px;
}}

QToolTip {{
    background-color: {C.TEXT};
    color: #f9fafb;
    border: 1px solid {C.TEXT};
    padding: 6px 9px;
    border-radius: 6px;
    font-size: 12px;
}}

/* Cards */
QFrame#card {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 14px;
}}
QFrame#microCard {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 10px;
}}
QFrame#microCard:hover {{
    border-color: {C.BORDER_HI};
}}

/* Logo badge */
QFrame#logoBadge {{
    background-color: {C.ACCENT};
    border-radius: 14px;
}}

/* Typography */
QLabel#title {{
    font-size: 19px;
    font-weight: 700;
    color: {C.TEXT};
    letter-spacing: -0.3px;
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
    color: {C.PANEL};
    background-color: {C.TEXT_MUTED};
    font-weight: 700;
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 9px;
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

/* Icon button label */
QLabel#iconLabel {{
    color: white;
    font-weight: 600;
    font-size: 13px;
}}

/* Default button */
QPushButton {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    padding: 8px 16px;
    border-radius: 8px;
    font-weight: 600;
}}
QPushButton:hover    {{ background-color: {C.PANEL_HI}; border-color: {C.BORDER_HI}; }}
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
    background-color: {C.ACCENT_BG};
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
    background-color: {C.ACCENT_BG};
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

/* Compact ghost button (e.g. header Refresh, Select all/None) */
QPushButton.ghostBtn {{
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.TEXT_DIM};
    padding: 5px 11px;
    border-radius: 7px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton.ghostBtn:hover {{
    background-color: {C.PANEL_HI};
    color: {C.TEXT};
    border-color: {C.BORDER_HI};
}}
QPushButton.ghostBtn:pressed {{ background-color: #e5e7eb; }}
QPushButton.ghostBtn:disabled {{ color: {C.TEXT_MUTED}; border-color: {C.BORDER}; }}

/* Clear-button inside the search field - fully transparent, the field
   paints the X glyph itself. */
QPushButton.fieldClear {{
    background-color: transparent;
    border: none;
    padding: 0;
    margin: 0;
}}

/* Pill control buttons (Start/Pause/Stop) - filled, white text */
QPushButton#btnStart, QPushButton#btnPause, QPushButton#btnStop {{
    border-radius: 8px;
    padding: 0 16px;
}}
QPushButton#btnStart {{
    background-color: {C.OK};
    border: 1px solid {C.OK};
}}
QPushButton#btnStart:hover    {{ background-color: {C.OK_DIM}; border-color: {C.OK_DIM}; }}
QPushButton#btnStart:pressed  {{ background-color: #065f46; border-color: #065f46; }}
QPushButton#btnStart:disabled {{ background-color: #d1fae5; border-color: #d1fae5; }}
QPushButton#btnStart:disabled QLabel#iconLabel {{ color: #6ee7b7; }}

QPushButton#btnPause {{
    background-color: {C.WARN_BG};
    border: 1px solid #fde68a;
}}
QPushButton#btnPause:hover    {{ background-color: #fde68a; border-color: #fde68a; }}
QPushButton#btnPause:pressed  {{ background-color: #fcd34d; border-color: #fcd34d; }}
QPushButton#btnPause:disabled {{ background-color: #fef9e7; border-color: #fef9e7; }}
QPushButton#btnPause QLabel#iconLabel {{ color: {C.WARN}; }}
QPushButton#btnPause:disabled QLabel#iconLabel {{ color: #fcd34d; }}

QPushButton#btnStop {{
    background-color: {C.ERR_BG};
    border: 1px solid #fecaca;
}}
QPushButton#btnStop:hover    {{ background-color: #fecaca; border-color: #fecaca; }}
QPushButton#btnStop:pressed  {{ background-color: #fca5a5; border-color: #fca5a5; }}
QPushButton#btnStop:disabled {{ background-color: #feecec; border-color: #feecec; }}
QPushButton#btnStop QLabel#iconLabel {{ color: {C.ERR}; }}
QPushButton#btnStop:disabled QLabel#iconLabel {{ color: #fca5a5; }}

/* Search field */
QLineEdit#searchField {{
    background-color: {C.PANEL_ALT};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 8px;
    padding: 5px 24px 5px 26px;
    font-size: 12px;
    selection-background-color: {C.ACCENT_BG};
}}
QLineEdit#searchField:focus {{
    border-color: {C.ACCENT};
    background-color: {C.PANEL};
}}
QLineEdit#searchField:disabled {{
    color: {C.TEXT_MUTED};
    background-color: #fafafa;
}}

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
QPushButton.chip:checked[level="success"] {{ background-color: {C.OK_BG};   color: {C.OK};   border-color: {C.OK_BG}; }}
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
QProgressBar#headerProgress::chunk {{
    background-color: {C.OK};
}}

/* Log */
QPlainTextEdit#logView {{
    background-color: #fbfbfd;
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 8px;
    font-family: "JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New";
    font-size: 12px;
    padding: 10px 12px;
    selection-background-color: {C.ACCENT_BG};
}}

/* Native checkbox indicator (sequential rows) */
QCheckBox {{
    color: {C.TEXT};
    spacing: 0px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
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

/* Status bar */
QStatusBar {{
    background-color: {C.PANEL};
    color: {C.TEXT_DIM};
    border-top: 1px solid {C.BORDER};
    padding: 2px 10px;
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

QStatusBar QLabel {{
    color: {C.TEXT_DIM};
    padding: 0 8px;
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

def _add_card_shadow(widget: QWidget, blur: int = 24,
                     y: int = 6, alpha: int = 18) -> None:
    """Apply a soft drop shadow to a card-style frame."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y)
    shadow.setColor(QColor(C.SHADOW))
    shadow.setColor(QColor(15, 23, 42, alpha))
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
        # filter back on restores history. Search filters by substring.
        self._log_buffer: List[tuple] = []
        self._max_log_entries = 2000
        self._log_show = {
            "info": True, "success": True, "warning": True, "error": True,
        }
        self._log_search = ""

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
        self._build_actions()
        self._register_callbacks()
        self._refresh_button_state()
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
        self.resize(1360, 860)
        self.setMinimumSize(1120, 720)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(12)

        root.addWidget(self._build_header())
        root.addWidget(self._build_activities_split(), 3)
        root.addWidget(self._build_bottom_row(), 2)

        self._build_status_bar()

    # ---- menu + keyboard shortcuts ----------------------------------------

    def _build_actions(self) -> None:
        """Create QActions with shortcuts and attach them to a menu bar.

        QAction shortcuts work application-wide while the window is active
        and are also surfaced in the menu so users can discover them.
        """
        mb = self.menuBar()
        mb.setObjectName("menuBar")

        file_menu = mb.addMenu("File")
        self._act_start = QAction("Start", self)
        self._act_start.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._act_start.triggered.connect(self._cb_start)
        file_menu.addAction(self._act_start)

        self._act_pause = QAction("Pause / Resume", self)
        self._act_pause.setShortcut(QKeySequence("Space"))
        self._act_pause.triggered.connect(self._cb_pause)
        file_menu.addAction(self._act_pause)

        self._act_stop = QAction("Stop", self)
        self._act_stop.setShortcut(QKeySequence("Esc"))
        self._act_stop.triggered.connect(self._cb_stop)
        file_menu.addAction(self._act_stop)

        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.setShortcut(QKeySequence("Ctrl+Q"))
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        view_menu = mb.addMenu("View")
        refresh_act = QAction("Refresh devices", self)
        refresh_act.setShortcut(QKeySequence("F5"))
        refresh_act.triggered.connect(self._cb_refresh_devices)
        view_menu.addAction(refresh_act)

        clear_log_act = QAction("Clear log", self)
        clear_log_act.setShortcut(QKeySequence("Ctrl+L"))
        clear_log_act.triggered.connect(self._cb_clear_log)
        view_menu.addAction(clear_log_act)

        focus_search_act = QAction("Focus log search", self)
        focus_search_act.setShortcut(QKeySequence("Ctrl+F"))
        focus_search_act.triggered.connect(self._focus_log_search)
        view_menu.addAction(focus_search_act)

        help_menu = mb.addMenu("Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    def _show_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.about(
            self,
            "About",
            f"<h3>{self.title}</h3>"
            "<p>ADB game automation control panel.</p>"
            "<p>Built with PySide6.</p>"
            "<p><b>Shortcuts:</b><br>"
            "Ctrl+Shift+S &mdash; Start<br>"
            "Space &mdash; Pause / Resume<br>"
            "Esc &mdash; Stop<br>"
            "F5 &mdash; Refresh devices<br>"
            "Ctrl+L &mdash; Clear log<br>"
            "Ctrl+F &mdash; Focus log search<br>"
            "Ctrl+Q &mdash; Quit</p>",
        )

    # ---- header ------------------------------------------------------------

    def _build_header(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)

        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 16, 18, 14)
        outer.setSpacing(12)

        # ---- Top row: logo + title | status pill | control buttons ----
        top = QHBoxLayout()
        top.setSpacing(16)

        # Left: logo badge + title + subtitle
        logo = QFrame()
        logo.setObjectName("logoBadge")
        logo.setFixedSize(40, 40)
        logo_lay = QHBoxLayout(logo)
        logo_lay.setContentsMargins(0, 0, 0, 0)
        logo_icon = Icon("controller", 22, C.PANEL, logo)
        logo_lay.addWidget(logo_icon, 0, Qt.AlignmentFlag.AlignCenter)
        top.addWidget(logo, 0, Qt.AlignmentFlag.AlignVCenter)

        left = QVBoxLayout()
        left.setSpacing(2)
        title = QLabel(self.title)
        title.setObjectName("title")
        subtitle = QLabel("ADB game automation control panel")
        subtitle.setObjectName("subtitle")
        self.header_subtitle = subtitle
        left.addWidget(title)
        left.addWidget(subtitle)
        top.addLayout(left)

        top.addStretch(1)

        # Status indicator (label, dot, value text) inside a soft pill
        status_wrap = QFrame()
        status_wrap.setObjectName("statusPillWrap")
        status_wrap.setStyleSheet(
            f"QFrame#statusPillWrap {{ background-color: {C.PANEL_ALT};"
            f" border: 1px solid {C.BORDER}; border-radius: 18px;"
            " padding: 4px 14px; }}"
        )
        status_row = QHBoxLayout(status_wrap)
        status_row.setContentsMargins(14, 6, 14, 6)
        status_row.setSpacing(8)
        status_lbl = QLabel("STATUS")
        status_lbl.setObjectName("statusLabel")
        self.status_dot = PulsingDot(C.OK)
        self.status_value = QLabel("READY")
        self.status_value.setObjectName("statusValue")
        status_row.addWidget(status_lbl)
        status_row.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_row.addWidget(self.status_value)
        top.addWidget(status_wrap, 0, Qt.AlignmentFlag.AlignVCenter)

        top.addSpacing(12)

        # Control buttons
        self.btn_start = IconButton("play", "Start")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setIconColor(C.PANEL)
        self.btn_start.clicked.connect(self._cb_start)
        self.btn_start.setToolTip("Start automation (Ctrl+Shift+S)")

        self.btn_pause = IconButton("pause", "Pause")
        self.btn_pause.setObjectName("btnPause")
        self.btn_pause.setIconColor(C.WARN)
        self.btn_pause.clicked.connect(self._cb_pause)
        self.btn_pause.setToolTip("Pause / resume (Space)")

        self.btn_stop = IconButton("stop", "Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setIconColor(C.ERR)
        self.btn_stop.clicked.connect(self._cb_stop)
        self.btn_stop.setToolTip("Stop automation (Esc)")

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

        # ---- Bottom row: progress + elapsed | device + app + refresh ----
        info = QHBoxLayout()
        info.setSpacing(16)

        # Activity progress summary: "3 / 7" + mini progress bar
        prog_label = QLabel("PROGRESS")
        prog_label.setObjectName("statusLabel")
        self.header_progress_count = QLabel("0 / 0")
        self.header_progress_count.setStyleSheet(
            f"color:{C.TEXT}; font-weight:700; font-size:12px;"
        )
        self.header_progress = QProgressBar()
        self.header_progress.setObjectName("headerProgress")
        self.header_progress.setRange(0, 100)
        self.header_progress.setValue(0)
        self.header_progress.setTextVisible(False)
        self.header_progress.setFixedHeight(6)
        self.header_progress.setFixedWidth(140)
        info.addWidget(prog_label)
        info.addWidget(self.header_progress_count)
        info.addWidget(self.header_progress)

        info.addSpacing(10)

        # Elapsed timer
        elapsed_icon = Icon("clock", 13, C.TEXT_MUTED)
        elapsed_label = QLabel("ELAPSED")
        elapsed_label.setObjectName("statusLabel")
        self.elapsed_timer = ElapsedTimer()
        self.elapsed_timer.setStyleSheet(
            f"color:{C.TEXT_DIM}; font-weight:700; font-size:13px;"
            "font-family: 'JetBrains Mono', 'Cascadia Mono', 'Consolas', monospace;"
        )
        info.addWidget(elapsed_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        info.addWidget(elapsed_label)
        info.addWidget(self.elapsed_timer)

        info.addStretch(1)

        # Device cluster
        dev_label = QLabel("DEVICE")
        dev_label.setObjectName("statusLabel")
        self.dev_dot = PulsingDot(C.TEXT_MUTED)
        self.dev_value = QLabel("Not connected")
        self.dev_value.setStyleSheet(f"color:{C.TEXT_DIM};font-weight:600;")
        info.addWidget(dev_label)
        info.addWidget(self.dev_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        info.addWidget(self.dev_value)

        info.addSpacing(10)

        # App cluster
        app_label = QLabel("APP")
        app_label.setObjectName("statusLabel")
        self.app_value = QLabel("—")
        self.app_value.setStyleSheet(f"color:{C.TEXT_MUTED};")
        info.addWidget(app_label)
        info.addWidget(self.app_value)

        info.addSpacing(10)

        # Refresh button (compact)
        self.btn_refresh = IconButton("refresh", "Refresh", icon_size=13)
        self.btn_refresh.setProperty("class", "ghostBtn")
        self.btn_refresh.setStyleSheet(
            f"QPushButton.ghostBtn {{ background-color: transparent;"
            f" border: 1px solid {C.BORDER}; color: {C.TEXT_DIM};"
            " padding: 5px 12px; border-radius: 7px;"
            " font-size: 12px; font-weight: 600; }"
            f"QPushButton.ghostBtn:hover {{ background-color: {C.PANEL_HI};"
            f" color: {C.TEXT}; border-color: {C.BORDER_HI}; }}"
            f"QPushButton.ghostBtn:disabled {{ color: {C.TEXT_MUTED}; }}"
        )
        self.btn_refresh.setIconColor(C.TEXT_DIM)
        self.btn_refresh.setToolTip("Re-check connected emulators / devices (F5)")
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

    def _make_section_header(
        self,
        title: str,
        count: int,
        sub: str,
        actions: Optional[List[QWidget]] = None,
    ) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(10)
        t = QLabel(title)
        t.setObjectName("sectionTitle")
        c = QLabel(str(count))
        c.setObjectName("sectionCount")
        c.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c.setMinimumWidth(20)
        s = QLabel(sub)
        s.setObjectName("sectionSub")
        head.addWidget(t)
        head.addWidget(c)
        head.addSpacing(6)
        head.addWidget(s)
        head.addStretch(1)
        if actions:
            for w in actions:
                head.addWidget(w)
        return head

    def _build_sequential_panel(self, acts: List[Activity]) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        # Section header with All/None quick toggles.
        all_btn = QPushButton("All")
        all_btn.setProperty("class", "ghostBtn")
        all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        all_btn.setToolTip("Enable every sequential activity")
        all_btn.clicked.connect(lambda: self._cb_select_all_seq(True))

        none_btn = QPushButton("None")
        none_btn.setProperty("class", "ghostBtn")
        none_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        none_btn.setToolTip("Disable every sequential activity")
        none_btn.clicked.connect(lambda: self._cb_select_all_seq(False))

        layout.addLayout(self._make_section_header(
            "SEQUENTIAL", len(acts), "Run once in order",
            actions=[all_btn, none_btn],
        ))

        if not acts:
            layout.addSpacing(6)
            empty = QLabel("No sequential activities defined.")
            empty.setStyleSheet(
                f"color:{C.TEXT_MUTED}; font-size:12px; padding: 20px;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
        table.verticalHeader().setDefaultSectionSize(52)
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
        table.setColumnWidth(self.COL_SEQ_PROGRESS, 250)
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
        table.setCellWidget(row, self.COL_SEQ_ENABLED, self._center(cb))

        # Col 1: name + optional description (two-line cell)
        name_wrap = QWidget()
        name_lay = QVBoxLayout(name_wrap)
        name_lay.setContentsMargins(10, 6, 10, 6)
        name_lay.setSpacing(1)
        name = QLabel(act.name)
        name.setStyleSheet(f"color:{C.TEXT};font-weight:600;font-size:13px;")
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        name_lay.addWidget(name)
        if act.description:
            desc = QLabel(act.description)
            desc.setStyleSheet(
                f"color:{C.TEXT_MUTED}; font-size:11px;"
            )
            desc.setAlignment(Qt.AlignmentFlag.AlignLeft
                              | Qt.AlignmentFlag.AlignVCenter)
            name_wrap.setToolTip(act.description)
            name_lay.addWidget(desc)
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
        pct_label.setStyleSheet(
            f"color:{C.TEXT_MUTED};font-size:11px;font-weight:600;"
        )
        pct_label.setFixedWidth(36)
        pct_label.setAlignment(Qt.AlignmentFlag.AlignRight
                               | Qt.AlignmentFlag.AlignVCenter)
        prog_layout.addWidget(progress, 1)
        prog_layout.addWidget(pct_label)
        table.setCellWidget(row, self.COL_SEQ_PROGRESS, prog_wrap)

        # Col 3: status pill (soft background + dark text)
        pill = QLabel()
        self._apply_status_pill_style(pill, act.status.value)
        table.setCellWidget(row, self.COL_SEQ_STATUS, self._center(pill))

        # Col 4: Run-once button - executes only this activity.
        run_btn = PlayButton()
        run_btn.setToolTip("Run only this activity once")
        run_btn.clicked.connect(
            lambda _checked=False, aid=act.id: self._cb_run_single(aid)
        )
        table.setCellWidget(row, self.COL_SEQ_RUN, self._center(run_btn))

        self._seq_rows[act.id] = {
            "checkbox": cb,
            "progress": progress,
            "pct": pct_label,
            "pill": pill,
            "run_btn": run_btn,
            "name": act.name,
        }

    def _build_background_panel(self, acts: List[Activity]) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)

        layout.addLayout(self._make_section_header(
            "BACKGROUND", len(acts), "Loop in own thread"
        ))

        if not acts:
            layout.addSpacing(6)
            empty = QLabel("No background activities defined.")
            empty.setStyleSheet(
                f"color:{C.TEXT_MUTED}; font-size:12px; padding: 20px;"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
            layout.addStretch(1)
            return card

        list_wrap = QWidget()
        list_layout = QVBoxLayout(list_wrap)
        list_layout.setContentsMargins(0, 4, 0, 0)
        list_layout.setSpacing(4)

        for act in acts:
            row_widget = QFrame()
            row_widget.setProperty("class", "bgRow")
            row_widget.setStyleSheet(
                "QFrame.bgRow { border-radius: 8px; border: none; }"
                f"QFrame.bgRow:hover {{ background-color: {C.PANEL_ALT}; }}"
            )
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(10, 10, 10, 10)
            row.setSpacing(10)

            text_col = QVBoxLayout()
            text_col.setSpacing(1)
            name = QLabel(act.name)
            name.setStyleSheet(f"color:{C.TEXT};font-weight:600;font-size:13px;")
            text_col.addWidget(name)
            if act.description:
                desc = QLabel(act.description)
                desc.setStyleSheet(f"color:{C.TEXT_MUTED}; font-size:11px;")
                text_col.addWidget(desc)
                row_widget.setToolTip(act.description)
            row.addLayout(text_col, 1)

            # Live status text ("Running" / "Idle") that we update when the
            # toggle flips - clearer than just the toggle alone.
            bg_status = QLabel("Idle")
            bg_status.setStyleSheet(
                f"color:{C.TEXT_MUTED}; font-size:11px; font-weight:600;"
                "padding: 2px 8px; border-radius: 8px;"
                f"background-color: {C.PANEL_ALT};"
            )
            bg_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(bg_status, 0, Qt.AlignmentFlag.AlignVCenter)

            toggle = ToggleSwitch()
            toggle.setChecked(act.enabled)
            toggle.toggled.connect(
                lambda checked, aid=act.id: self._cb_toggle_activity(aid, checked)
            )
            if act.description:
                toggle.setToolTip(act.description)

            row.addWidget(toggle, 0, Qt.AlignmentFlag.AlignVCenter)
            list_layout.addWidget(row_widget)
            self._bg_rows[act.id] = {
                "checkbox": toggle,
                "status": bg_status,
                "name": act.name,
            }

        list_layout.addStretch(1)
        layout.addWidget(list_wrap, 1)
        return card

    # ---- bottom: log + metrics --------------------------------------------

    def _build_bottom_row(self) -> QWidget:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_log_panel())
        splitter.addWidget(self._build_metrics_panel())
        splitter.setStretchFactor(0, 72)
        splitter.setStretchFactor(1, 28)
        splitter.setHandleWidth(14)
        splitter.setChildrenCollapsible(False)

        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 0)
        wrap_layout.addWidget(splitter)
        wrap.setMinimumHeight(240)
        wrap.setMaximumHeight(340)
        return wrap

    def _build_log_panel(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        _add_card_shadow(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # Title row
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("LOG")
        title.setObjectName("sectionTitle")
        head.addWidget(title)
        head.addSpacing(6)

        # Search field (grows to fill)
        self.log_search = SearchField("Search log…")
        self.log_search.setFixedHeight(28)
        self.log_search.setPlaceholderText("Search log…")
        self.log_search.textChanged.connect(self._set_log_search)
        head.addWidget(self.log_search, 1)

        head.addSpacing(4)

        # Filter chips
        self.cb_filter_info    = self._make_chip("Info",    "info",    True)
        self.cb_filter_success = self._make_chip("OK",      "success", True)
        self.cb_filter_warning = self._make_chip("Warn",    "warning", True)
        self.cb_filter_error   = self._make_chip("Error",   "error",   True)
        self.cb_filter_info.toggled.connect(    lambda c: self._set_log_filter("info", c))
        self.cb_filter_success.toggled.connect( lambda c: self._set_log_filter("success", c))
        self.cb_filter_warning.toggled.connect( lambda c: self._set_log_filter("warning", c))
        self.cb_filter_error.toggled.connect(   lambda c: self._set_log_filter("error", c))

        head.addWidget(self.cb_filter_info)
        head.addWidget(self.cb_filter_success)
        head.addWidget(self.cb_filter_warning)
        head.addWidget(self.cb_filter_error)

        head.addSpacing(4)

        clear_btn = QPushButton("Clear")
        clear_btn.setFlat(True)
        clear_btn.setStyleSheet(
            f"QPushButton {{ color: {C.TEXT_MUTED}; background: transparent;"
            "border: none; padding: 4px 8px; font-weight: 600; font-size: 12px;"
            "border-radius: 4px; }"
            f"QPushButton:hover {{ color: {C.TEXT}; background: {C.PANEL_ALT}; }}"
        )
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setToolTip("Clear log (Ctrl+L)")
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

        self.metric_success  = self._make_stat_card("Success rate", "—", C.OK,   C.OK)
        self.metric_matches  = self._make_stat_card("Matches",      "0", C.ACCENT, C.ACCENT)
        self.metric_failures = self._make_stat_card("Failures",     "0", C.ERR,  C.ERR)
        self.metric_avg_time = self._make_stat_card("Avg time",     "0.000s", C.TEXT, None)
        self.metric_ops      = self._make_stat_card("Total ops",    "0", C.TEXT_DIM, None)
        self.metric_elapsed  = self._make_stat_card("Elapsed",      "00:00:00", C.TEXT, C.WARN)

        grid.addWidget(self.metric_success["card"],  0, 0)
        grid.addWidget(self.metric_matches["card"],  0, 1)
        grid.addWidget(self.metric_failures["card"], 1, 0)
        grid.addWidget(self.metric_avg_time["card"], 1, 1)
        grid.addWidget(self.metric_ops["card"],      2, 0)
        grid.addWidget(self.metric_elapsed["card"],  2, 1)

        outer.addLayout(grid, 1)
        return card

    @staticmethod
    def _make_stat_card(label: str, default: str, value_color: str,
                        accent: Optional[str]) -> Dict[str, Any]:
        card = StatCard(label, default, value_color=value_color, accent=accent)
        return {"card": card, "value": card}

    # ---- status bar --------------------------------------------------------

    def _build_status_bar(self) -> None:
        sb = QStatusBar(self)
        sb.setObjectName("statusBar")
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)

        self.sb_activity = QLabel("Idle")
        self.sb_device = QLabel("Device: not connected")
        self.sb_app = QLabel("App: —")

        sb.addWidget(self.sb_activity, 1)
        sb.addPermanentWidget(self.sb_device)
        sb.addPermanentWidget(self.sb_app)

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

    def _set_log_search(self, text: str) -> None:
        self._log_search = text.casefold()
        self.log_view.clear()
        for ts, lvl, msg in self._log_buffer:
            if self._is_line_visible(lvl, msg):
                self._render_log_line(ts, lvl, msg)

    def _set_log_filter(self, level: str, visible: bool) -> None:
        self._log_show[level] = bool(visible)
        self.log_view.clear()
        for ts, lvl, msg in self._log_buffer:
            if self._is_line_visible(lvl, msg):
                self._render_log_line(ts, lvl, msg)

    def _is_line_visible(self, level: str, message: str) -> bool:
        if not self._log_show.get(level, True):
            return False
        if self._log_search and self._log_search not in message.casefold():
            return False
        return True

    def _is_level_visible(self, level: str) -> bool:
        return self._log_show.get(level, True)

    def _append_log(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_buffer.append((ts, level, message))
        if len(self._log_buffer) > self._max_log_entries:
            del self._log_buffer[: len(self._log_buffer) - self._max_log_entries]
        if self._is_line_visible(level, message):
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

    def _focus_log_search(self) -> None:
        self.log_search.setFocus()
        self.log_search.selectAll()

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
        # Reflect state in the window title so it's visible in the
        # taskbar / window switcher too.
        self.setWindowTitle(f"{self.title}  •  {label}")

    def _update_header_progress(self) -> None:
        """Refresh the 'X / Y' progress summary in the header."""
        seq_rows = [a for a in self._activities if not a.background]
        if not seq_rows:
            total = done = 0
        else:
            total = len(seq_rows)
            done = sum(
                1 for a in seq_rows
                if a.status.value in ("completed", "skipped")
            )
        self.header_progress_count.setText(f"{done} / {total}")
        pct = int(done / total * 100) if total else 0
        self.header_progress.setValue(pct)

    def _update_status_bar(self) -> None:
        # Current activity
        if self._is_running:
            cur = self.automation.get_current_activity()
            if cur is not None:
                self.sb_activity.setText(f"Running: {cur.name}")
                self.header_subtitle.setText(f"Running: {cur.name}")
            elif self._is_paused:
                self.sb_activity.setText("Paused")
                self.header_subtitle.setText("Paused")
            else:
                self.sb_activity.setText("Running")
                self.header_subtitle.setText("Running automation")
        else:
            self.sb_activity.setText("Idle")
            self.header_subtitle.setText("ADB game automation control panel")

    def _refresh_button_state(self) -> None:
        self.btn_start.setEnabled(not self._is_running)
        self.btn_pause.setEnabled(self._is_running)
        self.btn_stop.setEnabled(self._is_running)
        self.btn_pause.setLabel("Resume" if self._is_paused else "Pause")
        self.btn_pause.setIconName("play" if self._is_paused else "pause")

        # Menu actions mirror the buttons.
        self._act_start.setEnabled(not self._is_running)
        self._act_pause.setEnabled(self._is_running)
        self._act_stop.setEnabled(self._is_running)
        self._act_pause.setText("Resume" if self._is_paused else "Pause")

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

        self._update_header_progress()
        self._update_status_bar()

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
            self.elapsed_timer.reset()
            self.elapsed_timer.start()
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
            # Update background live-status label.
            row = self._bg_rows.get(activity_id)
            if row and "status" in row:
                status_lbl = row["status"]
                if checked:
                    status_lbl.setText("Running")
                    status_lbl.setStyleSheet(
                        f"color:{C.OK}; font-size:11px; font-weight:600;"
                        "padding: 2px 8px; border-radius: 8px;"
                        f"background-color: {C.OK_BG};"
                    )
                else:
                    status_lbl.setText("Idle")
                    status_lbl.setStyleSheet(
                        f"color:{C.TEXT_MUTED}; font-size:11px; font-weight:600;"
                        "padding: 2px 8px; border-radius: 8px;"
                        f"background-color: {C.PANEL_ALT};"
                    )
        except Exception as e:
            log_error(f"Toggle error: {e}")

    def _cb_select_all_seq(self, enabled: bool) -> None:
        """Enable or disable every sequential activity at once.

        Background activities are left untouched - they're controlled by
        their own per-row toggles.
        """
        for act in self._activities:
            if act.background:
                continue
            row = self._seq_rows.get(act.id)
            if row and row["checkbox"].isChecked() != enabled:
                row["checkbox"].setChecked(enabled)

    def _cb_run_single(self, activity_id: str) -> None:
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
        self._update_activity_status(activity_id, "pending")
        self._update_activity_progress(activity_id, 0.0)

        def _runner() -> None:
            try:
                self.automation.run_single_activity(activity_id)
            except Exception as e:
                log_error(f"Single-run error in {activity_id}: {e}")
            finally:
                self._sig.single_run_finished.emit(activity_id)

        self._single_run_thread = threading.Thread(
            target=_runner,
            name=f"single-{activity_id}",
            daemon=True,
        )
        self._single_run_thread.start()

    def _set_single_run_buttons_enabled(self, enabled: bool) -> None:
        for row in self._seq_rows.values():
            btn = row.get("run_btn")
            if btn is not None:
                btn.setEnabled(enabled)
        self.btn_start.setEnabled(enabled and not self._is_running)
        self._act_start.setEnabled(enabled and not self._is_running)

    def _cb_clear_log(self) -> None:
        self._log_buffer.clear()
        self.log_view.clear()
        self._append_log("info", "Log cleared")

    # ----- automation signal slots -----------------------------------------

    @Slot()
    def _on_automation_start(self) -> None:
        self._is_running = True
        self._is_paused = False
        self.elapsed_timer.reset()
        self.elapsed_timer.start()
        self._refresh_button_state()

    @Slot()
    def _on_automation_stop(self) -> None:
        self._is_running = False
        self._is_paused = False
        self.elapsed_timer.stop()
        self._refresh_button_state()

    @Slot(dict)
    def _on_activity_start(self, data: dict) -> None:
        self._update_activity_status(data["id"], "running")
        self._update_status_bar()

    @Slot(dict)
    def _on_activity_complete(self, data: dict) -> None:
        status = "completed" if data["success"] else "failed"
        self._update_activity_status(data["id"], status)
        self._update_header_progress()

    @Slot(dict)
    def _on_activity_failed(self, data: dict) -> None:
        self._update_activity_status(data["id"], "failed")
        self._update_header_progress()

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
        self._set_single_run_buttons_enabled(True)
        self._update_header_progress()

    @Slot(dict)
    def _on_device_status(self, summary: dict) -> None:
        connected = bool(summary.get("connected"))
        device_id = summary.get("device_id")
        device_name = summary.get("device_name")
        app_pkg = summary.get("app_package")
        app_name = summary.get("app_name")

        if connected:
            label = device_name or device_id or "Connected"
            if device_id and device_name and device_name != device_id:
                label = f"{device_name}  ({device_id})"
            self.dev_value.setText(label)
            self.dev_value.setStyleSheet(f"color:{C.TEXT};font-weight:600;")
            self.dev_dot.setColor(C.OK)
            self.sb_device.setText(f"Device: {label}")
        else:
            self.dev_value.setText("Not connected")
            self.dev_value.setStyleSheet(
                f"color:{C.TEXT_MUTED};font-weight:600;"
            )
            self.dev_dot.setColor(C.TEXT_MUTED)
            self.sb_device.setText("Device: not connected")

        if connected and app_pkg:
            text = app_name or app_pkg
            if app_name and app_pkg and app_name != app_pkg:
                text = f"{app_name}  ({app_pkg})"
            self.app_value.setText(text)
            self.app_value.setStyleSheet(f"color:{C.TEXT};")
            self.sb_app.setText(f"App: {text}")
        else:
            self.app_value.setText("—")
            self.app_value.setStyleSheet(f"color:{C.TEXT_MUTED};")
            self.sb_app.setText("App: —")

        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setLabel("Refresh")

    # ----- per-row updates --------------------------------------------------

    def _update_activity_status(self, aid: str, status: str) -> None:
        row = self._seq_rows.get(aid)
        if row:
            self._apply_status_pill_style(row["pill"], status)
        self._update_header_progress()

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
        self.metric_success["value"].setValue(f"{success_rate * 100:.1f}%")
        self.metric_matches["value"].setValue(
            str(metrics.get("template_matches", 0) or 0)
        )
        self.metric_failures["value"].setValue(
            str(metrics.get("template_failures", 0) or 0)
        )
        self.metric_avg_time["value"].setValue(
            f"{(metrics.get('avg_match_time') or 0):.3f}s"
        )
        self.metric_ops["value"].setValue(
            str(metrics.get("total_operations", 0) or 0)
        )
        # Mirror the elapsed-timer widget into the metrics grid.
        self.metric_elapsed["value"].setValue(self.elapsed_timer.text())

        self._kick_device_status_refresh(deep=False)

    # ----- device / app status ---------------------------------------------

    def _kick_device_status_refresh(self, deep: bool = False) -> None:
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
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setLabel("Scanning…")
        log_info("Refreshing device list...")
        self._kick_device_status_refresh(deep=True)

    # ----- shutdown ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
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

    game = game_class()
    window = GameAutomationWindow(game, title)
    window.show()
    app.exec()


if __name__ == "__main__":
    print(
        "This is a PySide6 GUI module. "
        "Import and call run_with_pyside(GameClass, title)."
    )
