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
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import (
    QObject,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QPalette,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableWidget,
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
# Palette
# ---------------------------------------------------------------------------

class C:
    BG          = "#ececec"
    PANEL       = "#ffffff"
    PANEL_ALT   = "#f5f5f5"
    BORDER      = "#cccccc"

    TEXT        = "#111111"
    TEXT_DIM    = "#555555"
    TEXT_MUTED  = "#888888"

    ACCENT      = "#3b82f6"
    ACCENT_BG   = "#eff6ff"

    OK          = "#16a34a"
    OK_BG       = "#dcfce7"
    WARN        = "#ea580c"
    WARN_BG     = "#fff7ed"
    ERR         = "#dc2626"
    ERR_BG      = "#fef2f2"
    INFO        = "#2563eb"
    INFO_BG     = "#eff6ff"
    SLATE_BG    = "#e8eaed"
    SLATE_FG    = "#555555"


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
}


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

QLabel, QCheckBox {{
    background: transparent;
}}

QToolTip {{
    background-color: {C.TEXT};
    color: #fafafa;
    border: 1px solid {C.TEXT};
    padding: 3px 6px;
    border-radius: 2px;
    font-size: 11px;
}}

QFrame#panel {{
    background-color: {C.PANEL};
    border: 1px solid {C.BORDER};
}}

QLabel#title {{
    font-size: 14px;
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
    padding: 5px 12px;
    border-radius: 3px;
    font-weight: 600;
    font-size: 12px;
}}
QPushButton:hover    {{ background-color: #e0e0e0; border-color: #aaaaaa; }}
QPushButton:pressed  {{ background-color: #d0d0d0; }}
QPushButton:disabled {{ color: {C.TEXT_MUTED}; background-color: #f5f5f5; border-color: #e0e0e0; }}

QPushButton#btnStart {{
    background-color: {C.OK};
    color: white;
    border: 1px solid {C.OK};
    padding: 5px 16px;
    font-size: 12px;
}}
QPushButton#btnStart:hover    {{ background-color: #15803d; }}
QPushButton#btnStart:pressed  {{ background-color: #166534; }}
QPushButton#btnStart:disabled {{ background-color: #bbf7d0; color: #86efac; }}

QPushButton#btnPause {{
    background-color: {C.WARN_BG};
    color: {C.WARN};
    border: 1px solid #fed7aa;
    padding: 5px 16px;
    font-size: 12px;
}}
QPushButton#btnPause:hover    {{ background-color: #fed7aa; }}
QPushButton#btnPause:pressed  {{ background-color: #fdba74; }}
QPushButton#btnPause:disabled {{ background-color: #fff7ed; color: #fdba74; }}

QPushButton#btnStop {{
    background-color: {C.ERR_BG};
    color: {C.ERR};
    border: 1px solid #fecaca;
    padding: 5px 16px;
    font-size: 12px;
}}
QPushButton#btnStop:hover    {{ background-color: #fecaca; }}
QPushButton#btnStop:pressed  {{ background-color: #fca5a5; }}
QPushButton#btnStop:disabled {{ background-color: #fff5f5; color: #fca5a5; }}

QPushButton.smallBtn {{
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.TEXT_DIM};
    padding: 3px 8px;
    border-radius: 2px;
    font-size: 11px;
    font-weight: 600;
}}
QPushButton.smallBtn:hover {{ background-color: #e0e0e0; color: {C.TEXT}; }}
QPushButton.smallBtn:disabled {{ color: {C.TEXT_MUTED}; }}

QPushButton.chip {{
    border-radius: 8px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
    background-color: transparent;
    border: 1px solid {C.BORDER};
    color: {C.TEXT_MUTED};
}}
QPushButton.chip:hover {{ background-color: #e0e0e0; }}
QPushButton.chip:checked {{ color: white; border-color: transparent; }}
QPushButton.chip:checked[level="info"]    {{ background-color: {C.INFO}; }}
QPushButton.chip:checked[level="success"] {{ background-color: {C.OK}; }}
QPushButton.chip:checked[level="warning"] {{ background-color: {C.WARN}; }}
QPushButton.chip:checked[level="error"]   {{ background-color: {C.ERR}; }}

QTableWidget {{
    background-color: {C.PANEL};
    alternate-background-color: {C.PANEL_ALT};
    gridline-color: {C.BORDER};
    border: 1px solid {C.BORDER};
    font-size: 12px;
}}
QHeaderView::section {{
    background-color: {C.PANEL_ALT};
    color: {C.TEXT_DIM};
    padding: 4px 6px;
    border: none;
    border-bottom: 1px solid {C.BORDER};
    font-weight: 700;
    font-size: 11px;
}}

QProgressBar {{
    background-color: #e0e0e0;
    border: none;
    border-radius: 2px;
    text-align: center;
    color: transparent;
    height: 7px;
    max-height: 7px;
}}
QProgressBar::chunk {{
    background-color: {C.ACCENT};
    border-radius: 2px;
}}
QProgressBar#headerProgress::chunk {{
    background-color: {C.OK};
}}

QPlainTextEdit#logView {{
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #333;
    border-radius: 2px;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 11px;
    padding: 4px 6px;
}}

QCheckBox {{
    color: {C.TEXT};
    spacing: 2px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 2px;
    border: 1px solid #aaaaaa;
    background: {C.PANEL};
}}
QCheckBox::indicator:hover {{ border-color: {C.ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {C.ACCENT};
    border-color: {C.ACCENT};
}}

QTabWidget::pane {{
    border: 1px solid {C.BORDER};
    background: {C.PANEL};
}}
QTabBar::tab {{
    background: {C.PANEL_ALT};
    border: 1px solid {C.BORDER};
    padding: 5px 12px;
    margin-right: 1px;
    font-weight: 600;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background: {C.PANEL};
    border-bottom-color: {C.PANEL};
    color: {C.ACCENT};
}}
QTabBar::tab:hover {{ background: #e0e0e0; }}

QStatusBar {{
    background-color: {C.PANEL};
    color: {C.TEXT_DIM};
    border-top: 1px solid {C.BORDER};
    padding: 1px 6px;
    font-size: 11px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {C.TEXT_DIM}; padding: 0 4px; }}

QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: #c0c0c0;
    border-radius: 2px;
    min-height: 14px;
}}
QScrollBar::handle:vertical:hover {{ background: #a0a0a0; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 6px; background: transparent; margin: 0px; }}
QScrollBar::handle:horizontal {{ background: #c0c0c0; border-radius: 2px; min-width: 14px; }}
QScrollBar::handle:horizontal:hover {{ background: #a0a0a0; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
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
_HEADER_RUN   = 3


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
        self._activities: List[Activity] = self.automation.get_activities()

        self._seq_rows: Dict[str, Dict[str, Any]] = {}
        self._bg_rows: Dict[str, Dict[str, Any]] = {}

        self._log_buffer: List[tuple] = []
        self._max_log_entries = 2000
        self._log_show = {"info": True, "success": True, "warning": True, "error": True}

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
        self.setFixedSize(414, 816)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(5, 3, 5, 1)
        root.setSpacing(3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_tabs(), 3)
        root.addWidget(self._build_log(), 2)
        self._build_status_bar()

    def _build_header(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(8, 5, 8, 4)
        outer.setSpacing(3)

        # Title + Status
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        t = QLabel(self.title)
        t.setObjectName("title")
        r1.addWidget(t)
        r1.addStretch(1)
        self.status_value = QLabel("READY")
        self.status_value.setStyleSheet(f"color:{C.TEXT}; font-weight:700; font-size:12px;")
        r1.addWidget(self.status_value)
        outer.addLayout(r1)

        # Progress + Elapsed
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self.header_progress_count = QLabel("0/0")
        self.header_progress_count.setStyleSheet(f"color:{C.TEXT_DIM}; font-weight:600; font-size:11px;")
        self.header_progress = QProgressBar()
        self.header_progress.setObjectName("headerProgress")
        self.header_progress.setRange(0, 100)
        self.header_progress.setValue(0)
        self.header_progress.setTextVisible(False)
        self.header_progress.setFixedHeight(7)
        r2.addWidget(self.header_progress_count)
        r2.addWidget(self.header_progress, 1)

        self.elapsed_timer = ElapsedTimer()
        self.elapsed_timer.setStyleSheet(
            f"color:{C.TEXT_DIM}; font-weight:600; font-size:11px;"
            "font-family: 'Consolas', monospace;"
            f"padding: 1px 3px; background-color: {C.PANEL_ALT};"
            f"border: 1px solid {C.BORDER}; border-radius: 2px;"
        )
        r2.addWidget(self.elapsed_timer)
        outer.addLayout(r2)

        # Buttons + info
        r3 = QHBoxLayout()
        r3.setSpacing(4)

        self.btn_start = QPushButton("Start")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.clicked.connect(self._cb_start)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("btnPause")
        self.btn_pause.clicked.connect(self._cb_pause)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.clicked.connect(self._cb_stop)

        r3.addWidget(self.btn_start)
        r3.addWidget(self.btn_pause)
        r3.addWidget(self.btn_stop)
        r3.addStretch(1)

        self.header_subtitle = QLabel("")
        self.header_subtitle.setObjectName("subtitle")
        r3.addWidget(self.header_subtitle)
        r3.addSpacing(4)

        self.dev_value = QLabel("No device")
        self.dev_value.setStyleSheet(f"color:{C.ERR}; font-size:11px; font-weight:600;")
        r3.addWidget(self.dev_value)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.setProperty("class", "smallBtn")
        self.btn_refresh.clicked.connect(self._cb_refresh_devices)
        r3.addWidget(self.btn_refresh)
        outer.addLayout(r3)

        return panel

    # ---- tabs --------------------------------------------------------------

    def _build_tabs(self) -> QWidget:
        seq = [a for a in self._activities if not a.background]
        bg  = [a for a in self._activities if a.background]

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_table_tab(seq, "seq"), f"Seq ({len(seq)})")
        self.tabs.addTab(self._build_table_tab(bg, "bg"),   f"Bg ({len(bg)})")
        return self.tabs

    def _build_table_tab(self, acts: List[Activity], kind: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        # Actions row
        ar = QHBoxLayout()
        ar.setSpacing(3)
        lbl = QLabel("One-time tasks" if kind == "seq" else "Loop tasks")
        lbl.setObjectName("subtitle")
        ar.addWidget(lbl)
        ar.addStretch(1)

        all_btn = QPushButton("All")
        all_btn.setProperty("class", "smallBtn")
        none_btn = QPushButton("None")
        none_btn.setProperty("class", "smallBtn")
        ar.addWidget(all_btn)
        ar.addWidget(none_btn)
        layout.addLayout(ar)

        rows = self._seq_rows if kind == "seq" else self._bg_rows
        if kind == "seq":
            all_btn.clicked.connect(lambda: self._cb_select_all(True))
            none_btn.clicked.connect(lambda: self._cb_select_all(False))
        else:
            all_btn.clicked.connect(lambda: self._cb_select_all_bg(True))
            none_btn.clicked.connect(lambda: self._cb_select_all_bg(False))

        if not acts:
            empty = QLabel("None")
            empty.setStyleSheet(f"color:{C.TEXT_MUTED}; font-size:10px; padding: 10px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty)
            layout.addStretch(1)
            return page

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["", "Name", "Status", ""])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setShowGrid(True)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setRowCount(len(acts))
        table.verticalHeader().setDefaultSectionSize(32)
        table.setFrameShape(QFrame.Shape.NoFrame)

        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(_HEADER_CHECK, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_HEADER_NAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_HEADER_STATE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_HEADER_RUN, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(_HEADER_CHECK, 26)
        table.setColumnWidth(_HEADER_STATE, 80)
        table.setColumnWidth(_HEADER_RUN, 38)

        for row, act in enumerate(acts):
            cb = QCheckBox()
            cb.setChecked(act.enabled)
            cb.toggled.connect(
                lambda checked, aid=act.id: self._cb_toggle_activity(aid, checked)
            )
            table.setCellWidget(row, _HEADER_CHECK, self._center(cb))

            nw = QWidget()
            nl = QVBoxLayout(nw)
            nl.setContentsMargins(4, 1, 4, 1)
            nl.setSpacing(0)
            nm = QLabel(act.name)
            nm.setStyleSheet(f"color:{C.TEXT}; font-weight:600; font-size:12px;")
            nl.addWidget(nm)
            table.setCellWidget(row, _HEADER_NAME, nw)

            pill = QLabel()
            self._apply_pill(pill, act.status.value)
            table.setCellWidget(row, _HEADER_STATE, self._center(pill))

            run_btn = QPushButton("Run")
            run_btn.setProperty("class", "smallBtn")
            run_btn.setToolTip(f"Run only: {act.name}")
            run_btn.clicked.connect(
                lambda _checked=False, aid=act.id: self._cb_run_single(aid)
            )
            table.setCellWidget(row, _HEADER_RUN, self._center(run_btn))

            rows[act.id] = {"checkbox": cb, "pill": pill, "run_btn": run_btn, "name": act.name}

        layout.addWidget(table, 1)
        if kind == "seq":
            self.seq_table = table
        else:
            self.bg_table = table
        return page

    # ---- log ---------------------------------------------------------------

    def _build_log(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 3, 6, 4)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(3)

        ll = QLabel("LOG")
        ll.setStyleSheet(f"color:{C.TEXT}; font-weight:700; font-size:11px;")
        head.addWidget(ll)
        head.addStretch(1)

        for lvl, label in [("info","Inf"), ("success","OK"), ("warning","Wrn"), ("error","Err")]:
            chip = QPushButton(label)
            chip.setProperty("class", "chip")
            chip.setProperty("level", lvl)
            chip.setCheckable(True)
            chip.setChecked(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.toggled.connect(lambda c, l=lvl: self._set_log_filter(l, c))
            head.addWidget(chip)

        clr = QPushButton("Clr")
        clr.setFlat(True)
        clr.setStyleSheet(
            f"QPushButton {{ color:{C.TEXT_MUTED}; background:transparent;"
            "border:none; padding:1px 4px; font-weight:600; font-size:10px; }}"
            f"QPushButton:hover {{ color:{C.TEXT}; background:{C.PANEL_ALT}; }}"
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
        self.sb_device = QLabel("Dev: —")
        sb.addWidget(self.sb_activity, 1)
        sb.addPermanentWidget(self.sb_device)

    @staticmethod
    def _center(w: QWidget) -> QWidget:
        wrap = QWidget()
        l = QHBoxLayout(wrap)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(w, 0, Qt.AlignmentFlag.AlignCenter)
        return wrap

    # ----- log --------------------------------------------------------------

    def _set_log_filter(self, level: str, visible: bool) -> None:
        self._log_show[level] = bool(visible)
        self._rebuild_log()

    def _rebuild_log(self) -> None:
        self.log_view.clear()
        for ts, lvl, msg in self._log_buffer:
            if self._log_show.get(lvl, True):
                self._render_line(ts, lvl, msg)

    def _append_log(self, level: str, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_buffer.append((ts, level, msg))
        if len(self._log_buffer) > self._max_log_entries:
            del self._log_buffer[: len(self._log_buffer) - self._max_log_entries]
        if self._log_show.get(level, True):
            self._render_line(ts, level, msg)

    def _render_line(self, ts: str, level: str, msg: str) -> None:
        pfx = {"info": "INF", "success": "OK ", "warning": "WRN", "error": "ERR"}.get(level, "INF")
        c = _LOG_COLORS.get(level, C.INFO)
        safe = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        html = (
            f'<span style="color:{C.TEXT_MUTED};">[{ts}]</span> '
            f'<span style="color:{c};font-weight:700;">{pfx}</span> '
            f'<span>{safe}</span>'
        )
        self.log_view.appendHtml(html)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    # ----- updaters ---------------------------------------------------------

    @staticmethod
    def _apply_pill(pill: QLabel, status: str) -> None:
        bg, fg = _STATUS_PILL.get(status, _STATUS_PILL["pending"])
        pill.setText(status.upper())
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet(
            f"background-color:{bg}; color:{fg};"
            "padding:2px 8px; border-radius:5px; font-weight:700; font-size:10px;"
        )

    def _set_status(self, label: str) -> None:
        self.status_value.setText(label)
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

    def _update_status_bar(self) -> None:
        if self._is_running:
            cur = self.automation.get_current_activity()
            if cur:
                self.sb_activity.setText(f"Running: {cur.name}")
                self.header_subtitle.setText(cur.name)
            elif self._is_paused:
                self.sb_activity.setText("Paused")
                self.header_subtitle.setText("Paused")
            else:
                self.sb_activity.setText("Running")
                self.header_subtitle.setText("")
        else:
            self.sb_activity.setText("Idle")
            self.header_subtitle.setText("")

    def _refresh_button_state(self) -> None:
        self.btn_start.setEnabled(not self._is_running)
        self.btn_pause.setEnabled(self._is_running)
        self.btn_stop.setEnabled(self._is_running)
        self.btn_pause.setText("Resume" if self._is_paused else "Pause")

        if not self._is_running:
            self._set_status("READY")
        elif self._is_paused:
            self._set_status("PAUSED")
        else:
            self._set_status("RUNNING")

        for act in self._activities:
            row = (self._bg_rows if act.background else self._seq_rows).get(act.id)
            if row:
                row["checkbox"].setEnabled((not self._is_running) or act.background)

        solo_active = bool(self._single_run_thread and self._single_run_thread.is_alive())
        run_ok = (not self._is_running) and (not solo_active)
        for rows in (self._seq_rows, self._bg_rows):
            for row in rows.values():
                btn = row.get("run_btn")
                if btn:
                    btn.setEnabled(run_ok)

        self._update_progress()
        self._update_status_bar()

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
            log_error(f"Pause error: {e}")

    def _cb_stop(self) -> None:
        if not self._is_running:
            return
        try:
            self.automation.stop()
        except Exception as e:
            log_error(f"Stop error: {e}")

    def _cb_toggle_activity(self, aid: str, checked: bool) -> None:
        try:
            self.automation.set_activity_enabled(aid, checked)
            for act in self._activities:
                if act.id == aid:
                    act.enabled = checked
                    break
        except Exception as e:
            log_error(f"Toggle error: {e}")

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

    def _cb_refresh_devices(self) -> None:
        self.btn_refresh.setEnabled(False)
        self.btn_refresh.setText("...")
        self._kick_device_status_refresh(deep=True)

    # ----- signal slots -----------------------------------------------------

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
        self._update_activity_status(data["id"], "completed" if data["success"] else "failed")
        self._update_progress()

    @Slot(dict)
    def _on_activity_failed(self, data: dict) -> None:
        self._update_activity_status(data["id"], "failed")
        self._update_progress()

    @Slot(str, float)
    def _on_progress(self, activity_id: str, progress: float) -> None:
        pass

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
        if s.get("connected"):
            label = s.get("device_name") or s.get("device_id") or "OK"
            self.dev_value.setText(label)
            self.dev_value.setStyleSheet(f"color:{C.OK}; font-size:11px; font-weight:600;")
            self.sb_device.setText(f"Dev: {label}")
        else:
            self.dev_value.setText("No device")
            self.dev_value.setStyleSheet(f"color:{C.ERR}; font-size:11px; font-weight:600;")
            self.sb_device.setText("Dev: —")
        self.btn_refresh.setEnabled(True)
        self.btn_refresh.setText("Refresh")

    def _update_activity_status(self, aid: str, status: str) -> None:
        for rows in (self._seq_rows, self._bg_rows):
            r = rows.get(aid)
            if r:
                self._apply_pill(r["pill"], status)
                break
        self._update_progress()

    def _periodic_refresh(self) -> None:
        self._kick_device_status_refresh(deep=False)

    def _kick_device_status_refresh(self, deep: bool = False) -> None:
        if getattr(self, "_closing", False):
            return
        with self._device_status_lock:
            if self._device_status_thread and self._device_status_thread.is_alive():
                return
            def _worker() -> None:
                a = self.automation.adb
                try:
                    if deep or not a.is_connected():
                        a.check_adb_connection() if deep else a.quick_refresh()
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
        try:
            if self._is_running:
                self.automation.stop()
        except Exception:
            pass
        try:
            remove_log_subscriber(self._on_log_bus)
        except Exception:
            pass
        super().closeEvent(event)


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
    app.setStyleSheet(QSS)

    game = game_class()
    window = GameAutomationWindow(game, title)
    window.show()
    window.raise_()
    window.activateWindow()
    app.exec()


if __name__ == "__main__":
    print("Import and call run_with_pyside(GameClass, title).")
