"""
GUI Game Launcher — Select a game and launch its PySide6 or C++ Qt GUI automation.

Usage::

    python launcher_gui.py

A compact dialog lists all discovered games.  Double-click or press the
launch button to open the full automation window for the selected game.

If ``adb-auto-game.exe`` (C++ Qt build) exists in the project root it will
be used; otherwise falls back to the PySide6 GUI.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict

# ---------------------------------------------------------------------------
# Project root setup (mirrors launcher.py)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from launcher import load_game_class, scan_games
from src.gui.pyside_gui import C, QSS, run_with_pyside
from src.utils import log_error, log_info


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class GameLauncherDialog(QDialog):
    """Modal dialog that lets the user pick a game and launch its GUI.

    After the user confirms, the chosen game info is available via
    :attr:`selected_info` and :attr:`selected_display`.
    """

    def __init__(self, games: Dict[str, Dict[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._games = games
        self._names = list(games.keys())
        self.selected_info: Dict[str, str] | None = None
        self.selected_display: str = ""
        self._build_ui()

    # -- UI construction -------------------------------------------------------

    def _build_ui(self) -> None:
        self.setWindowTitle("ADB Game Automation — Launcher")
        self.setFixedSize(380, 440)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ---- header ----------------------------------------------------------
        header = QFrame()
        header.setObjectName("panel")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(2)

        title = QLabel("Select a Game")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(title)

        sub = QLabel("Choose a game to launch its automation GUI")
        sub.setObjectName("subtitle")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hl.addWidget(sub)

        root.addWidget(header)

        # ---- game list -------------------------------------------------------
        self._list = QListWidget()
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setAlternatingRowColors(True)
        self._list.setSpacing(1)
        self._list.doubleClicked.connect(self._on_launch)

        for name in self._names:
            display = self._games[name]["display_name"]
            item = QListWidgetItem(f"  {display}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSizeHint(item.sizeHint().grownBy(QMargins(0, 0, 0, 6)))
            self._list.addItem(item)

        if self._names:
            self._list.setCurrentRow(0)

        root.addWidget(self._list, 1)

        # ---- buttons ---------------------------------------------------------
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._launch_btn = QPushButton("Launch with GUI")
        self._launch_btn.setObjectName("btnStart")
        self._launch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._launch_btn.clicked.connect(self._on_launch)

        exit_btn = QPushButton("Exit")
        exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        exit_btn.clicked.connect(self.reject)

        btn_row.addStretch(1)
        btn_row.addWidget(self._launch_btn)
        btn_row.addWidget(exit_btn)
        root.addLayout(btn_row)

    # -- actions ---------------------------------------------------------------

    def _on_launch(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return

        name: str = item.data(Qt.ItemDataRole.UserRole)
        info = self._games[name]
        game_class = load_game_class(info)
        if game_class is None:
            log_error(f"Failed to load {info['display_name']}")
            QMessageBox.critical(
                self, "Error",
                f"Could not load game module for:\n{info['display_name']}",
            )
            return

        # Stash selection so main() can launch the game *after* the dialog
        # loop exits.  We must NOT launch inside the dialog handler because
        # run_with_pyside calls app.exec() and we'd be re-entering the event
        # loop from within the dialog's own event-handling stack.
        self.selected_info = info
        self.selected_display = f"{info['display_name']} Automation"
        self.accept()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _launch_cpp_gui(exe_path: Path, info: Dict[str, str], dialog: GameLauncherDialog) -> None:
    """Spawn the C++ Qt GUI executable as a separate process."""
    python_exe = sys.executable
    module_path = info["module_path"]
    title = dialog.selected_display

    cmd = [
        str(exe_path),
        "--game", module_path,
        "--title", title,
        "--python", python_exe,
    ]
    log_info(f"Launching C++ GUI: {' '.join(cmd)}")
    try:
        subprocess.Popen(cmd, cwd=str(_PROJECT_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        log_error(f"Failed to launch C++ GUI: {e}")
        QMessageBox.critical(
            dialog, "Launch Error",
            f"Could not start C++ GUI:\n{e}\n\n"
            "Falling back to PySide6 GUI."
        )
        game_class = load_game_class(info)
        if game_class:
            _launch_pyside(game_class, dialog)


def _launch_pyside(game_class, dialog: GameLauncherDialog) -> None:
    """Fallback: launch the PySide6 GUI in-process."""
    run_with_pyside(game_class, dialog.selected_display)


def _apply_theme(app: QApplication) -> None:
    """Mirror the palette + stylesheet from pyside_gui."""
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

    # Reuse the main QSS but add a couple of launcher-specific tweaks.
    launcher_qss = QSS + f"""
    QListWidget {{
        background-color: {C.PANEL};
        border: 1px solid {C.BORDER};
        border-radius: 6px;
        font-size: 13px;
        padding: 4px;
    }}
    QListWidget::item {{
        padding: 6px 8px;
        border-radius: 4px;
        color: {C.TEXT};
    }}
    QListWidget::item:selected {{
        background-color: {C.ACCENT_BG};
        color: {C.ACCENT};
        font-weight: 600;
    }}
    QListWidget::item:hover {{
        background-color: {C.PANEL_ALT};
    }}
    QListWidget::item:alternate {{
        background-color: {C.PANEL_ALT};
    }}
    """
    app.setStyleSheet(launcher_qss)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    _apply_theme(app)

    games = scan_games()
    if not games:
        QMessageBox.warning(
            None, "No Games Found",
            "No game directories were detected under src/games/.\n\n"
            "Add a game directory with a matching Python module and try again.",
        )
        return 1

    dialog = GameLauncherDialog(games)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0

    # Dialog accepted — launch the selected game GUI.
    info = dialog.selected_info
    if info is None:
        return 0

    game_class = load_game_class(info)
    if game_class is None:
        return 1

    # Launch: prefer C++ Qt GUI exe, fall back to PySide6
    exe_path = _PROJECT_ROOT / "adb-auto-game.exe"
    if exe_path.exists():
        _launch_cpp_gui(exe_path, info, dialog)
    else:
        _launch_pyside(game_class, dialog)
    return 0


if __name__ == "__main__":
    sys.exit(main())
