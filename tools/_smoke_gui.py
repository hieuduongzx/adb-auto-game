"""Smoke test: instantiate GameAutomationWindow with a mock automation
to verify the UI builds and all widgets wire up without errors.

Run with: python tools/_smoke_gui.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import QApplication

from src.games.base_game import Activity, ActivityStatus
from src.gui.pyside_gui import GameAutomationWindow, run_with_pyside


@dataclass
class _MockAdb:
    def is_connected(self) -> bool:
        return False

    def quick_refresh(self) -> None:
        pass

    def check_adb_connection(self) -> None:
        pass

    def get_status_summary(self) -> Dict[str, Any]:
        return {
            "connected": False,
            "device_id": None,
            "device_name": None,
            "app_package": None,
            "app_name": None,
        }


class _MockAutomation:
    def __init__(self):
        self.adb = _MockAdb()
        self._activities = [
            Activity(id="seq1", name="Sequential One",
                     description="First sequential task", enabled=True),
            Activity(id="seq2", name="Sequential Two",
                     description="Second sequential task", enabled=True),
            Activity(id="seq3", name="Sequential Three (no desc)",
                     enabled=False),
            Activity(id="bg1", name="Background Watcher",
                     description="Polls in background", enabled=True,
                     background=True, poll_interval=2.0),
            Activity(id="bg2", name="Auto Dismiss Dialogs",
                     enabled=False, background=True),
        ]
        self._callbacks: Dict[str, list] = {}

    def get_activities(self) -> List[Activity]:
        return list(self._activities)

    def register_callback(self, event, cb):
        self._callbacks.setdefault(event, []).append(cb)

    def reset_activities(self):
        for a in self._activities:
            a.reset()

    def start(self):
        pass

    def pause(self): pass

    def resume(self): pass

    def stop(self):
        for cbs in self._callbacks.get("on_stop", []):
            cbs()

    def set_activity_enabled(self, aid, enabled):
        for a in self._activities:
            if a.id == aid:
                a.enabled = enabled

    def run_single_activity(self, aid):
        pass

    def get_performance_metrics(self) -> Dict[str, Any]:
        return {
            "template_matches": 42,
            "template_failures": 3,
            "success_rate": 0.933,
            "avg_match_time": 0.187,
            "total_operations": 45,
        }

    def get_current_activity(self) -> Optional[Activity]:
        return None


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet("")  # let run_with_pyside set it
    win = GameAutomationWindow(_MockAutomation(), "Smoke Test GUI")
    win.show()
    # Process events briefly so widgets lay out, then close.
    for _ in range(20):
        app.processEvents()
    # Exercise a few interactions to make sure slots don't throw.
    win._cb_select_all_seq(True)
    win._cb_select_all_seq(False)
    win._set_log_search("xyz")
    win._set_log_search("")
    win._cb_filter_warning.toggle()
    win._cb_filter_warning.toggle()
    win._cb_clear_log()
    win._update_header_progress()
    win._update_status_bar()
    win._refresh_button_state()
    # Simulate device status coming in.
    win._on_device_status({
        "connected": True, "device_id": "emulator-5554",
        "device_name": "BlueStacks", "app_package": "com.game.x",
        "app_name": "GameX",
    })
    win._on_automation_start()
    win._on_activity_start({"id": "seq1", "name": "Sequential One", "status": "running"})
    win._on_progress("seq1", 55.0)
    win._on_activity_complete({"id": "seq1", "name": "Sequential One", "success": True, "status": "completed"})
    win._on_automation_stop()
    app.processEvents()
    print("SMOKE OK: window built and interactions ran without exception")
    win.close()


if __name__ == "__main__":
    main()
