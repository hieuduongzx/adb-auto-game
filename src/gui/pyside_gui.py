"""
PySide6-based GUI for game automation - Classic narrow auto-game trainer style.

Vertical compact layout - narrow like old-school auto game tools.

Layout::

    +--------------------------+
    |  Title            STATUS |
    |  3/7 █████░░░  00:00:00 |
    |  [Start] [Pause] [Stop] |
    +--------------------------+
    |  [Sequential] [Backgrnd] |
    |   checkbox | name | stat |
    +--------------------------+
    |  LOG [search] [clr]      |
    |   monospace terminal      |
    +--------------------------+
    |  status bar               |
    +--------------------------+
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QObject,
    QSize,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDoubleValidator,
    QFontDatabase,
    QIcon,
    QPalette,
)

import qtawesome as qta
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from src.game_core.base_game import Activity, BaseGameAutomation
from src.utils import (
    add_log_subscriber,
    log_error,
    log_info,
    log_success,
    log_warning,
    remove_log_subscriber,
)


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

class C:
    BG          = "#eceff3"
    PANEL       = "#ffffff"
    PANEL_ALT   = "#f3f5f9"
    SURFACE     = "#f7f9fc"
    BORDER      = "#dde2e9"
    LINE        = "#e9edf2"

    TEXT        = "#16202c"
    TEXT_DIM    = "#48535f"
    TEXT_MUTED  = "#69737e"

    ACCENT      = "#2f6fed"
    ACCENT_HOVER = "#2a63d4"
    ACCENT_BG   = "#e9f1ff"

    OK          = "#15924e"
    OK_HOVER    = "#127a41"
    OK_BG       = "#e4f6ec"
    WARN        = "#c2620f"
    WARN_BG     = "#fdf0e1"
    ERR         = "#c92a2a"
    ERR_BG      = "#fdeaea"
    INFO        = "#2f6fed"
    INFO_BG     = "#e9f1ff"

    LOG_BG      = "#181c22"
    LOG_TEXT    = "#d6dbe2"
    LOG_MUTED   = "#8a95a1"


_STATUS_PILL: Dict[str, tuple] = {
    "pending":   ("#eef2f7", "#3f4b58", "#dde4ec", "Chưa làm"),
    "running":   ("#fff4d6", "#8a5300", "#f1dca6", "Đang chạy"),
    "completed": ("#e4f6ec", "#0f7a3d", "#c5ebd5", "Xong"),
    "failed":    ("#fdeaea", "#b42424", "#f4cccc", "Lỗi"),
    "skipped":   ("#eef1f4", "#5b6670", "#dee3e8", "Bỏ qua"),
}

_LOG_COLORS: Dict[str, str] = {
    "info":    "#6fb3ff",
    "success": "#5fd28a",
    "warning": "#f2b65a",
    "error":   "#ff7b72",
}


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

_ICON_SIZE = QSize(14, 14)
_ICON_MAP = {
    "play": "fa5s.play",
    "pause": "fa5s.pause",
    "stop": "fa5s.stop",
    "settings": "fa5s.cog",
    "refresh": "fa5s.sync-alt",
    "back": "fa5s.chevron-left",
}
_ICON_CACHE: Dict[tuple, QIcon] = {}


def _make_icon(name: str, color: str) -> QIcon:
    key = (name, color)
    cached = _ICON_CACHE.get(key)
    if cached is not None:
        return cached
    icon = qta.icon(_ICON_MAP[name], color=color)
    _ICON_CACHE[key] = icon
    return icon


def _set_button_icon(btn: QPushButton, name: str, color: str, size: QSize = _ICON_SIZE) -> None:
    btn.setIcon(_make_icon(name, color))
    btn.setIconSize(size)


def _check_icon_path() -> str:
    path = Path(tempfile.gettempdir()) / "adb_auto_game_check.png"
    if not path.exists():
        qta.icon("fa5s.check", color="#ffffff").pixmap(QSize(11, 11)).save(str(path), "PNG")
    return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class ElapsedTimer(QLabel):
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


# ---------------------------------------------------------------------------
# QSS
# ---------------------------------------------------------------------------

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
    color: #ffffff;
    border: none;
    padding: 5px 9px;
    border-radius: 5px;
    font-size: 11px;
}}

QFrame#panel {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
    border-radius: 8px;
}}

QLabel#title {{
    font-size: 14px;
    font-weight: 700;
    color: {C.TEXT};
}}
QLabel#subtitle {{
    color: {C.TEXT_DIM};
    font-size: 11px;
}}

QPushButton {{
    background-color: {C.SURFACE};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px 11px;
    font-weight: 600;
    font-size: 12px;
}}
QPushButton:hover    {{ background-color: {C.PANEL_ALT}; border-color: #cdd4dd; }}
QPushButton:focus    {{ border-color: {C.ACCENT}; }}
QPushButton:pressed  {{ background-color: {C.LINE}; }}
QPushButton:disabled {{ color: {C.TEXT_MUTED}; background-color: {C.PANEL_ALT}; border-color: {C.LINE}; }}

QPushButton#btnStart {{
    background-color: {C.OK};
    color: #ffffff;
    border: 1px solid {C.OK};
    padding: 5px 14px;
    font-weight: 700;
}}
QPushButton#btnStart:hover    {{ background-color: {C.OK_HOVER}; border-color: {C.OK_HOVER}; }}
QPushButton#btnStart:pressed  {{ background-color: #0f6837; border-color: #0f6837; }}
QPushButton#btnStart:disabled {{ background-color: #b9e3c8; color: #eafaf0; border-color: #b9e3c8; }}

QPushButton#btnPause {{
    background-color: {C.WARN_BG};
    color: {C.WARN};
    border: 1px solid #f1dcc1;
    padding: 5px 14px;
    font-weight: 700;
}}
QPushButton#btnPause:hover    {{ background-color: #fae3c8; border-color: #e9cba6; }}
QPushButton#btnPause:pressed  {{ background-color: #f5d4ad; }}
QPushButton#btnPause:disabled {{ background-color: {C.PANEL_ALT}; color: #d9b48a; border-color: {C.LINE}; }}

QPushButton#btnStop {{
    background-color: {C.ERR_BG};
    color: {C.ERR};
    border: 1px solid #f3cccc;
    padding: 5px 14px;
    font-weight: 700;
}}
QPushButton#btnStop:hover    {{ background-color: #fbdcdc; border-color: #edbcbc; }}
QPushButton#btnStop:pressed  {{ background-color: #f7caca; }}
QPushButton#btnStop:disabled {{ background-color: {C.PANEL_ALT}; color: #e2a3a3; border-color: {C.LINE}; }}

QPushButton#btnBack {{
    background-color: {C.SURFACE};
    color: {C.TEXT_DIM};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px 12px;
    font-weight: 600;
}}
QPushButton#btnBack:hover {{ background-color: {C.PANEL_ALT}; color: {C.TEXT}; }}

QPushButton.smallBtn {{
    background-color: {C.SURFACE};
    border: 1px solid {C.BORDER};
    border-radius: 5px;
    color: {C.TEXT_DIM};
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton.smallBtn:hover {{ background-color: {C.ACCENT_BG}; color: {C.ACCENT}; border-color: #bcd4ff; }}
QPushButton.smallBtn:disabled {{ color: {C.TEXT_MUTED}; }}

QPushButton#btnPlay {{
    background-color: transparent;
    color: {C.OK};
    border: none;
    border-radius: 5px;
    padding: 0px;
    font-size: 13px;
}}
QPushButton#btnPlay:hover {{ background-color: {C.OK_BG}; color: {C.OK_HOVER}; }}
QPushButton#btnPlay:disabled {{ color: #a7d6ba; background-color: transparent; }}

QPushButton#btnSettings {{
    background-color: transparent;
    color: {C.TEXT_MUTED};
    border: none;
    border-radius: 5px;
    padding: 0px;
    font-size: 13px;
}}
QPushButton#btnSettings:hover {{ background-color: {C.PANEL_ALT}; color: {C.TEXT}; }}
QPushButton#btnSettings:disabled {{ color: {C.TEXT_MUTED}; background-color: transparent; }}

QPushButton#btnDevice {{
    background-color: transparent;
    color: {C.TEXT_DIM};
    border: none;
    border-radius: 5px;
    padding: 0px;
    font-size: 13px;
}}
QPushButton#btnDevice:hover {{ background-color: {C.PANEL_ALT}; color: {C.TEXT}; }}
QPushButton#btnDevice:disabled {{ color: {C.TEXT_MUTED}; background-color: transparent; }}

QComboBox#deviceCombo {{
    background-color: {C.SURFACE};
    color: {C.TEXT};
    border: 1px solid #cfd6df;
    border-radius: 5px;
    padding: 2px 22px 2px 8px;
    font-size: 11px;
    font-weight: 600;
    min-width: 170px;
    min-height: 18px;
}}
QComboBox#deviceCombo:hover {{ background-color: {C.PANEL}; border-color: #b9c5d2; }}
QComboBox#deviceCombo:focus {{ background-color: {C.PANEL}; border-color: {C.ACCENT}; }}
QComboBox#deviceCombo:disabled {{ color: {C.TEXT_MUTED}; background-color: {C.PANEL_ALT}; }}

QComboBox#deviceCombo::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border: none;
    border-left: 1px solid #d8dee6;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    background-color: transparent;
}}
QComboBox#deviceCombo::drop-down:hover {{
    background-color: {C.ACCENT_BG};
}}
QComboBox#deviceCombo::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.TEXT_DIM};
    width: 0;
    height: 0;
}}
QComboBox#deviceCombo::down-arrow:hover {{
    border-top-color: {C.ACCENT};
}}
QComboBox#deviceCombo:disabled::down-arrow {{
    border-top-color: {C.TEXT_MUTED};
}}

QComboBox#deviceCombo QAbstractItemView {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 7px;
    padding: 4px;
    outline: none;
    selection-background-color: {C.ACCENT_BG};
    selection-color: {C.ACCENT};
    font-size: 11px;
}}
QComboBox#deviceCombo QAbstractItemView::item {{
    padding: 4px 8px;
    min-height: 22px;
    border-radius: 4px;
}}
QComboBox#deviceCombo QAbstractItemView::item:hover {{
    background-color: {C.PANEL_ALT};
}}
QComboBox#deviceCombo QAbstractItemView::item:selected {{
    background-color: {C.ACCENT_BG};
    color: {C.ACCENT};
}}

QComboBox#settingCombo {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px 24px 4px 8px;
    font-size: 12px;
    font-weight: 600;
    min-height: 22px;
}}
QComboBox#settingCombo:hover {{ border-color: #c6cfda; }}
QComboBox#settingCombo:focus {{ border-color: {C.ACCENT}; }}
QComboBox#settingCombo::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
    border-left: 1px solid {C.BORDER};
}}
QComboBox#settingCombo::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {C.TEXT_DIM};
    width: 0;
    height: 0;
}}
QComboBox#settingCombo QAbstractItemView {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    selection-background-color: {C.ACCENT_BG};
    selection-color: {C.ACCENT};
    outline: none;
}}

QTableWidget {{
    background-color: {C.PANEL};
    alternate-background-color: {C.SURFACE};
    gridline-color: transparent;
    border: none;
    font-size: 12px;
    outline: none;
}}
QTableWidget::item {{
    border: none;
    border-bottom: 1px solid {C.LINE};
    padding: 0px;
}}
QHeaderView::section {{
    background-color: {C.SURFACE};
    color: {C.TEXT_DIM};
    padding: 3px 6px;
    border: none;
    border-bottom: 1px solid {C.BORDER};
    font-weight: 700;
    font-size: 11px;
}}

QCheckBox {{
    color: {C.TEXT};
    font-weight: 600;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {C.BORDER};
    border-radius: 4px;
    background-color: {C.PANEL};
}}
QCheckBox::indicator:hover {{
    border-color: {C.ACCENT};
    background-color: {C.SURFACE};
}}
QCheckBox::indicator:checked {{
    background-color: {C.ACCENT};
    border-color: {C.ACCENT};
    image: url("__CHECK_ICON__");
}}
QCheckBox::indicator:disabled {{
    background-color: {C.PANEL_ALT};
    border-color: {C.LINE};
}}

QProgressBar {{
    background-color: {C.LINE};
    border: none;
    border-radius: 4px;
    text-align: center;
    color: transparent;
    height: 7px;
    max-height: 7px;
}}
QProgressBar::chunk {{
    background-color: {C.ACCENT};
    border-radius: 4px;
}}
QProgressBar#headerProgress {{
    background-color: #d7e6d9;
}}
QProgressBar#headerProgress::chunk {{
    background-color: {C.OK};
    border-radius: 4px;
}}
QProgressBar#rowProgress {{
    background-color: {C.LINE};
    border: none;
    border-radius: 3px;
    height: 6px;
    max-height: 6px;
}}
QProgressBar#rowProgress::chunk {{
    background-color: {C.ACCENT};
    border-radius: 3px;
}}

QPlainTextEdit#logView {{
    background-color: {C.LOG_BG};
    color: {C.LOG_TEXT};
    border: 1px solid #2a2f37;
    border-radius: 6px;
    font-family: "Cascadia Mono", "Consolas", "Courier New", monospace;
    font-size: 11px;
    padding: 5px 7px;
    selection-background-color: #2f4360;
    selection-color: #ffffff;
}}

QTabWidget::pane {{
    border: 1px solid {C.BORDER};
    border-radius: 8px;
    background: {C.PANEL};
    top: -1px;
}}
QTabBar {{
    qproperty-drawBase: 0;
}}
QTabBar::tab {{
    background: transparent;
    color: {C.TEXT_DIM};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 6px 12px 5px 12px;
    margin-right: 2px;
    font-weight: 700;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    color: {C.ACCENT};
    border-bottom: 2px solid {C.ACCENT};
}}
QTabBar::tab:hover:!selected {{ color: {C.TEXT}; }}

QDialog#settingsDialog {{
    background-color: {C.PANEL};
}}

QLabel#settingLabel {{
    color: {C.TEXT};
    font-weight: 600;
    font-size: 12px;
}}

QLineEdit#settingInput {{
    background-color: {C.PANEL};
    color: {C.TEXT};
    border: 1px solid {C.BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 12px;
    selection-background-color: {C.ACCENT};
    selection-color: #ffffff;
}}
QLineEdit#settingInput:hover {{
    border: 1px solid #c6cfda;
}}
QLineEdit#settingInput:focus {{
    border: 1px solid {C.ACCENT};
}}
QLineEdit#settingInput:disabled {{
    background-color: {C.PANEL_ALT};
    color: {C.TEXT_MUTED};
}}
QLabel#settingHint {{
    color: {C.TEXT_MUTED};
    font-size: 11px;
}}

QStatusBar {{
    background-color: {C.PANEL};
    color: {C.TEXT_DIM};
    border-top: 1px solid {C.BORDER};
    padding: 2px 6px;
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {C.TEXT_DIM}; padding: 0 4px; }}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #c4ccd6;
    border-radius: 4px;
    min-height: 18px;
}}
QScrollBar::handle:vertical:hover {{ background: #aab4c0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: #c4ccd6; border-radius: 4px; min-width: 18px; }}
QScrollBar::handle:horizontal:hover {{ background: #aab4c0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""


# ---------------------------------------------------------------------------
# Bridge
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
# Main window
# ---------------------------------------------------------------------------

_HEADER_CHECK = 0
_HEADER_NAME  = 1
_HEADER_STATE = 2
_HEADER_PROG  = 3
_HEADER_RUN   = 4


class GameAutomationWindow(QMainWindow):

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
        self._bg_master_running = False
        self._activities: List[Activity] = self.automation.get_activities()

        self._seq_rows: Dict[str, Dict[str, Any]] = {}
        self._bg_rows: Dict[str, Dict[str, Any]] = {}

        self._log_buffer: List[tuple] = []
        self._max_log_entries = 2000

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

        self._device_list: List[Dict[str, str]] = []
        self._selected_serial: Optional[str] = None
        self._device_status_serial: Optional[str] = None

        self._automation_thread: Optional[threading.Thread] = None
        self._single_run_thread: Optional[threading.Thread] = None
        self._single_run_id: Optional[str] = None
        self._device_status_thread: Optional[threading.Thread] = None
        self._device_status_lock = threading.Lock()
        self._closing = False

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._periodic_refresh)
        self._timer.start()

        self._build_ui()
        log_info("UI built")
        self._register_callbacks()
        self._refresh_button_state()
        QTimer.singleShot(200, lambda: self._kick_device_status_refresh(deep=True))

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
        a.register_callback("on_progress",
                            lambda aid, p: self._sig.progress.emit(aid, float(p)))
        a.register_callback("on_error",
                            lambda err: self._sig.error.emit(str(err)))
        a.register_callback("on_status_change",
                            lambda status: self._sig.status_change.emit(status))
        add_log_subscriber(self._on_log_bus)

    def _on_log_bus(self, level: str, message: str) -> None:
        bucket = {
            "info": "info", "success": "success", "warning": "warning",
            "error": "error", "state": "info", "quest": "info", "normal": "info",
        }.get(level, "info")
        self._sig.log_message.emit(bucket, message)

    # ----- UI ---------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle(self.title)
        self.setFixedWidth(420)
        self.setMinimumHeight(640)
        self.resize(420, 820)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 4)
        root.setSpacing(8)

        root.addWidget(self._build_header())
        root.addWidget(self._build_tabs(), 3)
        root.addWidget(self._build_log(), 2)
        self._build_status_bar()

    def _build_header(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(10, 8, 10, 6)
        outer.setSpacing(4)

        self.status_value = QLabel("READY")
        self.status_value.setStyleSheet(f"color:{C.TEXT_DIM}; font-weight:600; font-size:11px;")

        # Row 1: Title + Progress + Elapsed
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        t = QLabel(self.title)
        t.setObjectName("title")
        r2.addWidget(t)
        r2.addStretch(1)

        self.header_progress_count = QLabel("0/0")
        self.header_progress_count.setStyleSheet(f"color:{C.TEXT_DIM}; font-weight:600; font-size:11px;")
        r2.addWidget(self.header_progress_count)
        self.header_progress = QProgressBar()
        self.header_progress.setObjectName("headerProgress")
        self.header_progress.setRange(0, 100)
        self.header_progress.setValue(0)
        self.header_progress.setTextVisible(False)
        self.header_progress.setFixedHeight(6)
        r2.addWidget(self.header_progress, 1)

        self.elapsed_timer = ElapsedTimer()
        self.elapsed_timer.setStyleSheet(
            f"color:{C.TEXT_DIM}; font-weight:600; font-size:11px;"
            "font-family: 'Consolas', monospace;"
        )
        r2.addWidget(self.elapsed_timer)
        r2.addWidget(self.status_value)
        outer.addLayout(r2)

        # Row 2: Buttons (sequential + background toggle)
        r3 = QHBoxLayout()
        r3.setSpacing(6)

        # Sequential controls
        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setToolTip("Start")
        _set_button_icon(self.btn_start, "play", "#ffffff")
        self.btn_start.clicked.connect(self._cb_start)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("btnPause")
        _set_button_icon(self.btn_pause, "pause", C.WARN)
        self.btn_pause.clicked.connect(self._cb_pause)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setToolTip("Stop")
        _set_button_icon(self.btn_stop, "stop", C.ERR)
        self.btn_stop.clicked.connect(self._cb_stop)

        r3.addWidget(self.btn_start)
        r3.addWidget(self.btn_pause)
        r3.addWidget(self.btn_stop)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color:{C.BORDER};")
        sep.setFixedWidth(1)
        r3.addWidget(sep)

        # Background master toggle
        self.bg_master_cb = QCheckBox("Background")
        self.bg_master_cb.setToolTip("Background tasks")
        self.bg_master_cb.toggled.connect(self._cb_toggle_background_master)
        r3.addWidget(self.bg_master_cb)

        r3.addStretch(1)
        outer.addLayout(r3)

        return panel

    # ---- tabs --------------------------------------------------------------

    def _build_tabs(self) -> QWidget:
        seq = [a for a in self._activities if not a.background]
        bg  = [a for a in self._activities if a.background]

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_table_tab(seq, "seq"), f"Sequential ({len(seq)})")
        self.tabs.addTab(self._build_table_tab(bg, "bg"),   f"Background ({len(bg)})")
        self.tabs.addTab(self._build_settings_tab(), "Cài đặt")
        return self.tabs

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        panel = QFrame()
        panel.setObjectName("panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(8)

        title = QLabel("Debug")
        title.setObjectName("title")
        panel_layout.addWidget(title)

        self.debug_mode_cb = QCheckBox("Debug template")
        debug_mode = bool(self.automation.get_ui_setting("debug_mode", self.automation.is_debug))
        debug_fail = bool(self.automation.get_ui_setting("debug_fail_mode", self.automation.is_debug_fail))
        self.debug_mode_cb.setChecked(debug_mode)
        self.debug_mode_cb.toggled.connect(self._cb_debug_mode_toggled)
        panel_layout.addWidget(self.debug_mode_cb)

        self.debug_fail_cb = QCheckBox("Debug template fail")
        self.debug_fail_cb.setChecked(debug_fail)
        self.debug_fail_cb.toggled.connect(self._cb_debug_fail_toggled)
        panel_layout.addWidget(self.debug_fail_cb)
        self.automation.set_debug_mode(debug_mode, debug_fail)

        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    def _build_table_tab(self, acts: List[Activity], kind: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 4, 4, 2)
        layout.setSpacing(4)

        # Header bar for the list view
        list_header = QHBoxLayout()
        list_header.setSpacing(4)
        lbl = QLabel("One-time tasks" if kind == "seq" else "Loop tasks")
        lbl.setObjectName("subtitle")
        list_header.addWidget(lbl)
        list_header.addStretch(1)

        all_btn = QPushButton("All")
        all_btn.setProperty("class", "smallBtn")
        none_btn = QPushButton("None")
        none_btn.setProperty("class", "smallBtn")
        list_header.addWidget(all_btn)
        list_header.addWidget(none_btn)
        layout.addLayout(list_header)

        rows = self._seq_rows if kind == "seq" else self._bg_rows
        if kind == "seq":
            all_btn.clicked.connect(lambda: self._cb_select_all(True))
            none_btn.clicked.connect(lambda: self._cb_select_all(False))
        else:
            all_btn.clicked.connect(lambda: self._cb_select_all_bg(True))
            none_btn.clicked.connect(lambda: self._cb_select_all_bg(False))

        if not acts:
            empty = QLabel("No tasks in this list")
            empty.setStyleSheet(f"color:{C.TEXT_MUTED}; font-size:11px; padding: 16px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
            layout.addStretch(1)
            return page

        # Stacked container for list and inline settings
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(4)
        layout.addLayout(stack, 1)

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["", "Name", "Status", "Prog", ""])
        table.horizontalHeader().setVisible(False)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setRowCount(len(acts))
        table.verticalHeader().setDefaultSectionSize(24)
        table.setFrameShape(QFrame.Shape.NoFrame)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(_HEADER_CHECK, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_HEADER_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_HEADER_STATE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_HEADER_PROG, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_HEADER_RUN, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(_HEADER_CHECK, 24)
        table.setColumnWidth(_HEADER_STATE, 74)
        table.setColumnWidth(_HEADER_PROG, 54)
        table.setColumnWidth(_HEADER_RUN, 52)

        for row, act in enumerate(acts):
            cb = QCheckBox()
            cb.setChecked(act.enabled)
            cb.toggled.connect(
                lambda checked, aid=act.id: self._cb_toggle_activity(aid, checked)
            )
            table.setCellWidget(row, _HEADER_CHECK, self._center(cb))

            nw = QWidget()
            nl = QVBoxLayout(nw)
            nl.setContentsMargins(2, 0, 2, 0)
            nl.setSpacing(0)
            nm = QLabel(act.name)
            nm.setStyleSheet(f"color:{C.TEXT}; font-weight:500; font-size:12px;")
            nl.addWidget(nm)
            table.setCellWidget(row, _HEADER_NAME, nw)

            pill = QLabel()
            self._apply_pill(pill, act.status.value)
            table.setCellWidget(row, _HEADER_STATE, self._center(pill))

            prog = QProgressBar()
            prog.setObjectName("rowProgress")
            prog.setRange(0, 100)
            prog.setValue(int(act.progress))
            prog.setTextVisible(False)
            prog.setFixedHeight(6)
            table.setCellWidget(row, _HEADER_PROG, self._center(prog))

            # Action column: play icon + optional settings gear for background tasks.
            btn_wrap = QWidget()
            btn_layout = QHBoxLayout(btn_wrap)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(2)

            play_btn = QPushButton()
            play_btn.setObjectName("btnPlay")
            play_btn.setToolTip("Run")
            play_btn.setFixedSize(20, 20)
            _set_button_icon(play_btn, "play", C.OK, QSize(13, 13))
            play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            play_btn.clicked.connect(
                lambda _checked=False, aid=act.id: self._cb_run_single(aid)
            )
            btn_layout.addWidget(play_btn, 0, Qt.AlignmentFlag.AlignCenter)

            settings_btn = None
            has_settings = bool(act.custom_settings) or act.background
            if has_settings:
                settings_btn = QPushButton()
                settings_btn.setObjectName("btnSettings")
                settings_btn.setToolTip("Settings")
                settings_btn.setFixedSize(20, 20)
                _set_button_icon(settings_btn, "settings", C.TEXT_MUTED, QSize(13, 13))
                settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                settings_btn.clicked.connect(
                    lambda _checked=False, aid=act.id, k=kind: self._cb_show_activity_settings(aid, k)
                )
                btn_layout.addWidget(settings_btn, 0, Qt.AlignmentFlag.AlignCenter)

            btn_layout.addStretch(1)
            table.setCellWidget(row, _HEADER_RUN, btn_wrap)

            rows[act.id] = {
                "checkbox": cb, "pill": pill, "prog": prog,
                "run_btn": play_btn, "settings_btn": settings_btn,
                "name": act.name, "background": act.background,
                "poll_interval": act.poll_interval,
            }

        stack.addWidget(table)

        # Inline settings panel (hidden by default)
        settings_panel = self._build_inline_settings_panel(kind, rows)
        settings_panel.setVisible(False)
        stack.addWidget(settings_panel)

        if kind == "seq":
            self.seq_table = table
            self.seq_settings_panel = settings_panel
            self.seq_stack = stack
        else:
            self.bg_table = table
            self.bg_settings_panel = settings_panel
            self.bg_stack = stack
        return page

    def _build_inline_settings_panel(self, kind: str, rows: Dict[str, Dict[str, Any]]) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)

        back_btn = QPushButton("Back")
        back_btn.setObjectName("btnBack")
        _set_button_icon(back_btn, "back", C.TEXT_DIM, QSize(13, 13))
        back_btn.clicked.connect(lambda _checked=False, k=kind: self._cb_hide_activity_settings(k))
        header.addWidget(back_btn)

        title = QLabel("Settings")
        title.setObjectName("title")
        header.addWidget(title, 1)
        layout.addLayout(header)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        layout.addLayout(body, 1)

        panel._kind = kind
        panel._rows = rows
        panel._title = title
        panel._body = body
        panel._active_widgets: Dict[str, Any] = {}

        return panel

    @staticmethod
    def _format_setting_value(value: float) -> str:
        """Format numeric setting values without spinner noise."""
        if abs(value - int(value)) < 0.000001:
            return str(int(value))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _make_numeric_input(
        self,
        value: float,
        min_value: float,
        max_value: float,
        suffix: str = "",
        width: int = 92,
    ) -> QLineEdit:
        input_box = QLineEdit()
        input_box.setObjectName("settingInput")
        input_box.setFixedWidth(width)
        input_box.setAlignment(Qt.AlignmentFlag.AlignRight)
        input_box.setText(self._format_setting_value(value))
        if suffix:
            input_box.setPlaceholderText(suffix.strip())
        validator = QDoubleValidator(min_value, max_value, 4, input_box)
        validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        input_box.setValidator(validator)
        return input_box

    def _read_numeric_input(
        self,
        input_box: QLineEdit,
        min_value: float,
        max_value: float,
    ) -> Optional[float]:
        raw = input_box.text().strip().replace(",", ".")
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        value = max(min_value, min(value, max_value))
        input_box.setText(self._format_setting_value(value))
        return value

    def _cb_debug_mode_toggled(self, checked: bool) -> None:
        fail_mode = self.debug_fail_cb.isChecked() if hasattr(self, "debug_fail_cb") else self.automation.is_debug_fail
        self.automation.set_debug_mode(bool(checked), bool(fail_mode))
        self.automation.set_ui_setting("debug_mode", bool(checked))

    def _cb_debug_fail_toggled(self, checked: bool) -> None:
        debug_mode = self.debug_mode_cb.isChecked() if hasattr(self, "debug_mode_cb") else self.automation.is_debug
        self.automation.set_debug_mode(bool(debug_mode), bool(checked))
        self.automation.set_ui_setting("debug_fail_mode", bool(checked))

    def _commit_settings_interval(self) -> None:
        panel = getattr(self, "_active_settings_panel", None)
        activity_id = getattr(self, "_active_settings_activity_id", None)
        if not panel or not activity_id:
            return
        widgets = getattr(panel, "_active_widgets", {})
        input_box = widgets.get("interval_input")
        if input_box is None:
            return
        interval = self._read_numeric_input(input_box, 0.05, 999999.0)
        if interval is None:
            return
        if self.automation.set_activity_poll_interval(activity_id, interval):
            rows = panel._rows
            row = rows.get(activity_id)
            if row:
                row["poll_interval"] = interval
            act = self.automation.get_activity(activity_id)
            if act:
                log_info(f"Updated '{act.name}' interval to {interval:.2f}s")

    def _cb_show_activity_settings(self, activity_id: str, kind: str) -> None:
        rows = self._bg_rows if kind == "bg" else self._seq_rows
        row = rows.get(activity_id)
        if not row:
            return
        act = self.automation.get_activity(activity_id)
        if not act:
            return

        panel = self.bg_settings_panel if kind == "bg" else self.seq_settings_panel
        table = self.bg_table if kind == "bg" else self.seq_table

        table.setVisible(False)
        panel.setVisible(True)

        self._active_settings_panel = panel
        self._active_settings_activity_id = activity_id
        panel._rows = rows

        panel._title.setText(act.name)

        body = panel._body
        self._clear_layout(body)
        widgets: Dict[str, Any] = {}
        panel._active_widgets = widgets

        if act.background:
            self._build_interval_section(body, act, widgets)

        for spec in act.custom_settings:
            self._build_custom_setting(body, activity_id, spec, widgets)

        body.addStretch(1)

    def _build_interval_section(
        self, body: QVBoxLayout, act: Activity, widgets: Dict[str, Any]
    ) -> None:
        """Build the poll-interval input row without +/- spinner buttons."""
        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel("Interval")
        lbl.setObjectName("settingLabel")
        lbl.setMinimumWidth(86)
        row.addWidget(lbl)

        input_box = self._make_numeric_input(act.poll_interval, 0.05, 999999.0, "s")
        input_box.editingFinished.connect(self._commit_settings_interval)
        row.addWidget(input_box)

        unit = QLabel("seconds")
        unit.setObjectName("settingHint")
        row.addWidget(unit)
        row.addStretch(1)
        body.addLayout(row)

        widgets["interval_input"] = input_box

    def _build_custom_setting(
        self, body: QVBoxLayout, activity_id: str, spec: Dict[str, Any], widgets: Dict[str, Any]
    ) -> None:
        """Build a single custom setting as a plain numeric input row."""
        key = spec.get("key")
        label_text = spec.get("label", key)
        min_value = float(spec.get("min", 0.0))
        max_value = float(spec.get("max", 100.0))
        suffix = spec.get("suffix", "")

        act = self.automation.get_activity(activity_id)
        current = float(act.custom_values.get(key, spec.get("default", min_value))) if act else float(spec.get("default", min_value))

        row = QHBoxLayout()
        row.setSpacing(8)

        lbl = QLabel(str(label_text))
        lbl.setObjectName("settingLabel")
        lbl.setMinimumWidth(86)
        row.addWidget(lbl)

        input_box = self._make_numeric_input(current, min_value, max_value, suffix)
        row.addWidget(input_box)

        hint_text = suffix or f"{self._format_setting_value(min_value)} - {self._format_setting_value(max_value)}"
        hint = QLabel(hint_text)
        hint.setObjectName("settingHint")
        row.addWidget(hint)
        row.addStretch(1)
        body.addLayout(row)

        def _commit() -> None:
            value = self._read_numeric_input(input_box, min_value, max_value)
            if value is None:
                return
            self.automation.set_custom_setting(activity_id, key, value)

        input_box.editingFinished.connect(_commit)
        widgets.setdefault("custom", {})[key] = {"input": input_box}

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        """Remove all widgets/sub-layouts from ``layout``."""
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            else:
                sub = item.layout()
                if sub is not None:
                    GameAutomationWindow._clear_layout(sub)

    def _cb_hide_activity_settings(self, kind: str) -> None:
        panel = self.bg_settings_panel if kind == "bg" else self.seq_settings_panel
        table = self.bg_table if kind == "bg" else self.seq_table
        panel.setVisible(False)
        table.setVisible(True)
        self._active_settings_panel = None
        self._active_settings_activity_id = None

    # ---- log ---------------------------------------------------------------

    def _build_log(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(4)

        ll = QLabel("LOG")
        ll.setStyleSheet(f"color:{C.TEXT}; font-weight:700; font-size:11px;")
        head.addWidget(ll)
        head.addStretch(1)

        clr = QPushButton("Clear")
        clr.setFlat(True)
        clr.setStyleSheet(
            f"QPushButton {{ color:{C.TEXT_MUTED}; background:transparent;"
            "border:none; padding:1px 4px; font-weight:600; font-size:10px; }}"
            f"QPushButton:hover {{ color:{C.TEXT}; }}"
        )
        clr.setCursor(Qt.CursorShape.PointingHandCursor)
        clr.clicked.connect(self._cb_clear_log)
        head.addWidget(clr)
        layout.addLayout(head)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("logView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self._max_log_entries)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(8)
        self.log_view.setFont(mono)
        layout.addWidget(self.log_view, 1)

        self._append_log("info", "Ready")
        return panel

    def _build_status_bar(self) -> None:
        sb = QStatusBar(self)
        sb.setSizeGripEnabled(False)
        self.setStatusBar(sb)
        self.sb_activity = QLabel("Idle")
        self.sb_device_label = QLabel("Device")

        self.device_combo = QComboBox()
        self.device_combo.setObjectName("deviceCombo")
        self.device_combo.setToolTip("Device")
        self.device_combo.setEnabled(False)
        self.device_combo.activated.connect(self._cb_device_selected)

        self.btn_refresh = QPushButton()
        self.btn_refresh.setObjectName("btnDevice")
        self.btn_refresh.setToolTip("Refresh")
        self.btn_refresh.setFixedSize(22, 20)
        _set_button_icon(self.btn_refresh, "refresh", C.TEXT_DIM, QSize(14, 14))
        self.btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh.clicked.connect(self._cb_refresh_devices)

        sb.addWidget(self.sb_activity, 1)
        sb.addPermanentWidget(self.sb_device_label)
        sb.addPermanentWidget(self.device_combo)
        sb.addPermanentWidget(self.btn_refresh)

    @staticmethod
    def _center(w: QWidget) -> QWidget:
        wrap = QWidget()
        l = QHBoxLayout(wrap)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(w, 0, Qt.AlignmentFlag.AlignCenter)
        return wrap

    # ----- log --------------------------------------------------------------

    def _append_log(self, level: str, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_buffer.append((ts, level, msg))
        if len(self._log_buffer) > self._max_log_entries:
            del self._log_buffer[: len(self._log_buffer) - self._max_log_entries]
        self._render_line(ts, level, msg)

    def _render_line(self, ts: str, level: str, msg: str) -> None:
        pfx = {"info": "INF", "success": "OK ", "warning": "WRN", "error": "ERR"}.get(level, "INF")
        c = _LOG_COLORS.get(level, _LOG_COLORS["info"])
        safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = (
            f'<span style="color:{C.LOG_MUTED};">[{ts}]</span> '
            f'<span style="color:{c};font-weight:700;">{pfx}</span> '
            f'<span style="color:{C.LOG_TEXT};">{safe}</span>'
        )
        self.log_view.appendHtml(html)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    # ----- updaters ---------------------------------------------------------

    @staticmethod
    def _apply_pill(pill: QLabel, status: str) -> None:
        bg, fg, border, text = _STATUS_PILL.get(status, _STATUS_PILL["pending"])
        pill.setText(text)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet(
            f"background-color:{bg}; color:{fg}; border:1px solid {border};"
            "border-radius:9px; padding:2px 8px; font-weight:600; font-size:11px;"
        )

    def _set_status(self, label: str) -> None:
        color = {
            "READY": C.TEXT_DIM, "RUNNING": C.OK, "PAUSED": C.WARN,
            "STOPPED": C.ERR, "ERROR": C.ERR,
        }.get(label, C.TEXT)
        self.status_value.setText(label)
        self.status_value.setStyleSheet(f"color:{color}; font-weight:700; font-size:12px;")
        self.setWindowTitle(f"{self.title} - {label}")

    def _update_progress(self) -> None:
        seq = [a for a in self._activities if not a.background]
        if not seq:
            total = done = 0
        else:
            total = len(seq)
            done = sum(1 for a in seq if a.status.value in ("completed", "skipped"))
        self.header_progress_count.setText(f"{done}/{total}")
        self.header_progress.setValue(int(done / total * 100) if total else 0)

    def _refresh_button_state(self) -> None:
        self.btn_start.setEnabled(not self._is_running)
        self.btn_pause.setEnabled(self._is_running or self._bg_master_running)
        self.btn_stop.setEnabled(self._is_running)
        self.btn_pause.setText("Resume" if self._is_paused else "Pause")
        _set_button_icon(self.btn_pause, "play" if self._is_paused else "pause", C.WARN)

        if not self._is_running and not self._bg_master_running:
            self._set_status("READY")
        elif self._is_paused:
            self._set_status("PAUSED")
        else:
            self._set_status("RUNNING")

        for act in self._activities:
            row = (self._bg_rows if act.background else self._seq_rows).get(act.id)
            if row:
                row["checkbox"].setEnabled(True)

        solo_active = bool(self._single_run_thread and self._single_run_thread.is_alive())
        run_ok = (not self._is_running) and (not solo_active)
        for rows in (self._seq_rows, self._bg_rows):
            for row in rows.values():
                btn = row.get("run_btn")
                if btn:
                    btn.setEnabled(run_ok)

        self._update_progress()

    # ----- slots ------------------------------------------------------------

    def _cb_start(self) -> None:
        if self._is_running:
            return
        try:
            self.automation.reset_activities()
            for act in self._activities:
                if not act.background:
                    self._update_activity_status(act.id, "pending")
            self._automation_thread = threading.Thread(
                target=self.automation.start, daemon=True,
            )
            self._automation_thread.start()
            self._is_running = True
            self._is_paused = False
            self.elapsed_timer.reset()
            self.elapsed_timer.start()
            self._refresh_button_state()
        except Exception as e:
            log_error(f"Start error: {e}")

    def _cb_toggle_background_master(self, checked: bool) -> None:
        """Enable/disable all background activities at once."""
        if checked == self._bg_master_running:
            return
        try:
            if checked:
                # Ensure ADB + capture are ready for background workers.
                self.automation._ensure_runtime_ready()
                self.automation._start_all_background_activities()
                self._bg_master_running = True
                self._is_paused = False
                log_success("Background tasks started")
            else:
                self.automation._stop_all_background_activities()
                self._bg_master_running = False
                log_info("Background tasks stopped")
            self._refresh_button_state()
        except Exception as e:
            log_error(f"Background toggle error: {e}")
            self.bg_master_cb.blockSignals(True)
            self.bg_master_cb.setChecked(self._bg_master_running)
            self.bg_master_cb.blockSignals(False)

    def _cb_pause(self) -> None:
        if not self._is_running and not self._bg_master_running:
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
            log_error(f"Pause error: {e}")

    def _cb_stop(self) -> None:
        if not self._is_running:
            return
        try:
            self.automation.stop_sequential()
        except Exception as e:
            log_error(f"Stop error: {e}")

    def _cb_toggle_activity(self, aid: str, checked: bool) -> None:
        try:
            is_bg = any(a.background for a in self._activities if a.id == aid)
            if is_bg:
                # Background toggles call join() on worker threads which can
                # block for up to 2 s — run off the UI thread to avoid a freeze.
                threading.Thread(
                    target=self._do_toggle_activity, args=(aid, checked),
                    daemon=True,
                ).start()
            else:
                self._do_toggle_activity(aid, checked)
        except Exception as e:
            log_error(f"Toggle error: {e}")

    def _do_toggle_activity(self, aid: str, checked: bool) -> None:
        self.automation.set_activity_enabled(aid, checked)
        for act in self._activities:
            if act.id == aid:
                act.enabled = checked
                break

    def _cb_select_all(self, enabled: bool) -> None:
        for act in self._activities:
            if act.background:
                continue
            row = self._seq_rows.get(act.id)
            if row and row["checkbox"].isChecked() != enabled:
                row["checkbox"].setChecked(enabled)

    def _cb_select_all_bg(self, enabled: bool) -> None:
        for act in self._activities:
            if not act.background:
                continue
            row = self._bg_rows.get(act.id)
            if row and row["checkbox"].isChecked() != enabled:
                row["checkbox"].setChecked(enabled)

    def _cb_run_single(self, activity_id: str) -> None:
        if self._is_running:
            log_error("Cannot run single while automation is running.")
            return
        if self._single_run_thread and self._single_run_thread.is_alive():
            log_error("Another single run in progress.")
            return
        self._single_run_id = activity_id
        self._set_run_btns(False)
        self._update_activity_status(activity_id, "pending")
        def _runner() -> None:
            try:
                self.automation.run_single_activity(activity_id)
            except Exception as e:
                log_error(f"Single run error: {e}")
            finally:
                self._sig.single_run_finished.emit(activity_id)
        self._single_run_thread = threading.Thread(
            target=_runner, name=f"solo-{activity_id}", daemon=True,
        )
        self._single_run_thread.start()

    def _set_run_btns(self, enabled: bool) -> None:
        for rows in (self._seq_rows, self._bg_rows):
            for row in rows.values():
                btn = row.get("run_btn")
                if btn:
                    btn.setEnabled(enabled)
        self.btn_start.setEnabled(enabled and not self._is_running)

    def _cb_clear_log(self) -> None:
        self._log_buffer.clear()
        self.log_view.clear()
        self._append_log("info", "Cleared")

    def _cb_device_selected(self, index: int) -> None:
        if not self._device_list or index < 0 or index >= len(self._device_list):
            return
        serial = self._device_list[index].get("serial")
        if not serial:
            return
        self._selected_serial = serial
        self.automation.adb.device_id = serial
        # Try to connect to the chosen device off the UI thread.
        def _connect() -> None:
            try:
                if self.automation.adb.select_device(serial):
                    s = self.automation.adb.get_status_summary()
                    if not getattr(self, "_closing", False):
                        try:
                            self._sig.device_status.emit(s)
                        except RuntimeError:
                            pass
            except Exception as e:
                log_error(f"Device select error: {e}")
        threading.Thread(target=_connect, name="select-device", daemon=True).start()

    def _cb_refresh_devices(self) -> None:
        # Reuse the periodic deep refresh path so the combo is repopulated
        # automatically and never stuck on "No device".
        self.btn_refresh.setEnabled(False)
        self._kick_device_status_refresh(deep=True)

    # ----- signal slots -----------------------------------------------------

    @Slot()
    def _on_automation_stop(self) -> None:
        self._is_running = False
        self._is_paused = False
        self.elapsed_timer.stop()
        self._refresh_button_state()

    @Slot()
    def _on_automation_start(self) -> None:
        self._is_running = True
        self._is_paused = False
        self.elapsed_timer.reset()
        self.elapsed_timer.start()
        self._refresh_button_state()

    @Slot(dict)
    def _on_activity_start(self, data: dict) -> None:
        self._update_activity_status(data["id"], "running")

    @Slot(dict)
    def _on_activity_complete(self, data: dict) -> None:
        self._update_activity_status(data["id"], "completed" if data["success"] else "failed")
        self._update_progress()

    @Slot(dict)
    def _on_activity_failed(self, data: dict) -> None:
        self._update_activity_status(data["id"], "failed")
        self._update_progress()

    @Slot(str, float)
    def _on_progress(self, activity_id: str, progress: float) -> None:
        self._update_activity_progress(activity_id, progress)

    @Slot(str)
    def _on_error(self, _msg: str) -> None:
        pass

    @Slot(dict)
    def _on_status_change(self, status: dict) -> None:
        self._is_paused = bool(status.get("paused", False))
        self._refresh_button_state()

    @Slot(str, str)
    def _on_log_message(self, level: str, msg: str) -> None:
        self._append_log(level, msg)

    @Slot(str)
    def _on_single_run_finished(self, _aid: str) -> None:
        self._single_run_id = None
        self._single_run_thread = None
        self._set_run_btns(True)
        self._update_progress()

    @Slot(dict)
    def _on_device_status(self, s: dict) -> None:
        # Only touch the combo when the signal actually carries a device list.
        # Status-summary signals (no "device_list" key) only update the bar.
        if "device_list" in s:
            device_list = s.get("device_list") or []
            selected_serial = s.get("selected_serial") or self._selected_serial
            connected_serial = self._device_status_serial

            # Rebuild only when the set of serials actually changed, so we
            # don't blow away the user's open dropdown every 2s.
            new_serials = [d.get("serial", "") for d in device_list]
            old_serials = [self.device_combo.itemData(i) or "" for i in range(self.device_combo.count())]
            if new_serials != old_serials:
                self.device_combo.blockSignals(True)
                self.device_combo.clear()
                self._device_list = device_list
                selected_index = 0
                for i, dev in enumerate(device_list):
                    label = dev.get("name") or dev.get("serial") or "Device"
                    serial = dev.get("serial", "")
                    display = f"{label} ({serial})" if serial else label
                    self.device_combo.addItem(display, serial)
                    if serial:
                        if serial == connected_serial:
                            selected_index = i
                        elif selected_serial and serial == selected_serial and not connected_serial:
                            selected_index = i
                self.device_combo.setCurrentIndex(selected_index)
                self.device_combo.blockSignals(False)
            else:
                self._device_list = device_list
                # Just refresh the selection highlight without rebuilding.
                idx = self.device_combo.findData(selected_serial or connected_serial or "")
                if idx >= 0:
                    self.device_combo.blockSignals(True)
                    self.device_combo.setCurrentIndex(idx)
                    self.device_combo.blockSignals(False)

            self.device_combo.setEnabled(bool(device_list))

            # If no device is currently connected, try connecting the saved/preferred one.
            if not connected_serial and selected_serial and not self._is_running:
                self._selected_serial = selected_serial
                self.automation.adb.device_id = selected_serial
                threading.Thread(
                    target=self._connect_saved_device,
                    name="connect-saved-device",
                    daemon=True,
                ).start()

        # Track the currently connected serial so list signals can highlight it.
        if s.get("connected"):
            self._device_status_serial = s.get("device_id")
            label = s.get("device_name") or s.get("device_id") or "OK"
            if not self.device_combo.count():
                self.device_combo.addItem(label, s.get("device_id"))
                self.device_combo.setEnabled(True)
        else:
            if not self.device_combo.count():
                self.device_combo.addItem("No device", "")
                self.device_combo.setEnabled(False)
        self.btn_refresh.setEnabled(True)

    def _connect_saved_device(self) -> None:
        if not self._selected_serial:
            return
        try:
            self.automation.adb.select_device(self._selected_serial)
            s = self.automation.adb.get_status_summary()
            if not getattr(self, "_closing", False):
                try:
                    self._sig.device_status.emit(s)
                except RuntimeError:
                    pass
        except Exception as e:
            log_warning(f"Could not reconnect to saved device: {e}")

    def _update_activity_status(self, aid: str, status: str) -> None:
        for rows in (self._seq_rows, self._bg_rows):
            r = rows.get(aid)
            if r:
                self._apply_pill(r["pill"], status)
                prog = r.get("prog")
                if prog is not None:
                    if status == "completed":
                        prog.setValue(100)
                    elif status in ("pending", "failed", "skipped"):
                        prog.setValue(0)
                break
        self._update_progress()

    def _update_activity_progress(self, aid: str, progress: float) -> None:
        for rows in (self._seq_rows, self._bg_rows):
            r = rows.get(aid)
            if r:
                prog = r.get("prog")
                if prog is not None:
                    prog.setValue(int(progress))
                break

    def _periodic_refresh(self) -> None:
        self._kick_device_status_refresh(deep=True)

    def _kick_device_status_refresh(self, deep: bool = False) -> None:
        if getattr(self, "_closing", False):
            return
        with self._device_status_lock:
            if self._device_status_thread and self._device_status_thread.is_alive():
                return
            def _worker() -> None:
                a = self.automation.adb
                try:
                    # Always list available devices so the combo stays up to
                    # date and we never block on console input.
                    devices = a.list_devices()
                    if devices:
                        self._sig.device_status.emit({
                            "connected": False,
                            "device_list": devices,
                            "selected_serial": self._selected_serial,
                        })
                        # Only (re)connect when nothing is currently connected
                        # or the current connection is to a different device.
                        if self._selected_serial:
                            if a.device is None or a.device_id != self._selected_serial:
                                a.select_device(self._selected_serial)
                    elif deep:
                        # Fallback to old connect flow when nothing is listed.
                        a.check_adb_connection()

                    a.quick_refresh()
                    s = a.get_status_summary()
                except Exception:
                    s = {"connected": False, "device_id": None, "device_name": None,
                         "app_package": None, "app_name": None}
                if not getattr(self, "_closing", False):
                    try:
                        self._sig.device_status.emit(s)
                    except RuntimeError:
                        pass
            t = threading.Thread(target=_worker, name="dev-status", daemon=True)
            self._device_status_thread = t
            t.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        event.accept()
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            self.elapsed_timer.stop()
        except Exception:
            pass
        try:
            if self._is_running:
                self.automation.running = False
                self.automation._paused = False
                try:
                    self.automation._pause_event.set()
                except Exception:
                    pass
                self.automation.stop_continuous_capture()
        except Exception:
            pass
        try:
            if self._bg_master_running:
                self.automation._stop_all_background_activities()
        except Exception:
            pass
        try:
            self.automation.visualizer.close()
        except Exception:
            pass
        try:
            self.automation._executor.shutdown(wait=False)
        except Exception:
            pass
        try:
            remove_log_subscriber(self._on_log_bus)
        except Exception:
            pass
        try:
            QApplication.quit()
        except Exception:
            pass
        try:
            super().closeEvent(event)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def run_with_pyside(game_class, title: str = "Game Automation") -> None:
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
    app.setStyleSheet(QSS.replace("__CHECK_ICON__", _check_icon_path()))

    game = game_class()
    window = GameAutomationWindow(game, title)
    window.show()
    window.raise_()
    window.activateWindow()
    app.exec()


if __name__ == "__main__":
    print("Import and call run_with_pyside(GameClass, title).")
