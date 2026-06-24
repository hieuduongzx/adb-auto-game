"""State-machine tests for the unified stop / background semantics.

Pins the fixes for the background/pause/stop inconsistencies:
- a global ``_stop_event`` aborts wait_*/safe_sleep independently of ``running``
  (so background handlers work when the sequential queue isn't running),
- ``safe_sleep`` freezes on pause and bails on stop,
- the GUI Stop is available for a background-only session.
"""
import threading
import time
import unittest

from tests import _bootstrap  # noqa: F401
from src.core.adb.auto.automation import ADBGameAutomation
from src.core.adb.auto.config import Config
from src.game_core.base_game import BaseGameAutomation
from src.gui.pywebview_gui import AutomationAPI


class TestStopSignalAbortsWaits(unittest.TestCase):
    def test_wait_for_template_bails_when_stop_set(self):
        auto = ADBGameAutomation.__new__(ADBGameAutomation)
        auto.config = Config()
        auto._stop_event = threading.Event()
        auto._stop_event.set()
        t0 = time.time()
        self.assertIsNone(auto.wait_for_template("x.png", timeout=5))
        self.assertLess(time.time() - t0, 0.5)  # returned immediately, not after 5s


class TestSafeSleep(unittest.TestCase):
    def _duck(self):
        # safe_sleep only touches _stop_event / _pause_event; call it unbound on
        # a duck object so we don't need a concrete (non-abstract) game.
        class _D:
            pass
        d = _D()
        d._stop_event = threading.Event()
        d._pause_event = threading.Event()
        d._pause_event.set()
        return d

    def test_sleeps_full_duration_without_running_flag(self):
        # No `running` attribute at all -> background-context sleep must still work.
        d = self._duck()
        t0 = time.time()
        BaseGameAutomation.safe_sleep(d, 0.2)
        self.assertGreaterEqual(time.time() - t0, 0.18)

    def test_returns_fast_when_stopped(self):
        d = self._duck()
        d._stop_event.set()
        t0 = time.time()
        BaseGameAutomation.safe_sleep(d, 5)
        self.assertLess(time.time() - t0, 0.2)


class TestGuiUnifiedStop(unittest.TestCase):
    class _FakeAutomation:
        def __init__(self):
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    def test_stop_available_for_background_only(self):
        api = AutomationAPI(self._FakeAutomation(), "T")
        api._is_running = False
        api._bg_running = True  # background-only session
        self.assertTrue(api.stop())
        self.assertEqual(api.automation.stop_calls, 1)

    def test_stop_noop_when_fully_idle(self):
        api = AutomationAPI(self._FakeAutomation(), "T")
        api._is_running = False
        api._bg_running = False
        self.assertFalse(api.stop())
        self.assertEqual(api.automation.stop_calls, 0)


if __name__ == "__main__":
    unittest.main()
