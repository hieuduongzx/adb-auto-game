"""Behavioral tests for BackgroundWorkerManager (Phase 5)."""
import threading
import time
import unittest

from tests import _bootstrap  # noqa: F401
from src.game_core.background_workers import BackgroundWorkerManager
from src.game_core.activity import Activity, ActivityStatus


def _wait_until(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class TestBackgroundWorkerManager(unittest.TestCase):
    def _make(self, handler, paused=False):
        self.paused = paused
        self.ready_calls = 0

        def ensure_ready():
            self.ready_calls += 1
            return True

        return BackgroundWorkerManager(
            handler_resolver=lambda aid: handler,
            is_paused=lambda: self.paused,
            ensure_ready=ensure_ready,
        )

    def test_runs_handler_until_stopped(self):
        ticks = {"n": 0}
        act = Activity(id="bg", name="BG", background=True, poll_interval=0.01)
        mgr = self._make(lambda: ticks.__setitem__("n", ticks["n"] + 1))

        self.assertTrue(mgr.start(act))
        self.assertTrue(_wait_until(lambda: ticks["n"] >= 3))
        self.assertTrue(mgr.is_running("bg"))
        self.assertEqual(self.ready_calls, 1)  # ensure_ready called once on start

        mgr.stop(act)
        self.assertFalse(mgr.is_running("bg"))
        self.assertEqual(act.status, ActivityStatus.PENDING)

    def test_pause_suspends_ticks(self):
        ticks = {"n": 0}
        act = Activity(id="bg", name="BG", background=True, poll_interval=0.01)
        mgr = self._make(lambda: ticks.__setitem__("n", ticks["n"] + 1), paused=True)

        mgr.start(act)
        time.sleep(0.1)
        self.assertEqual(ticks["n"], 0)  # paused -> no ticks

        self.paused = False
        self.assertTrue(_wait_until(lambda: ticks["n"] >= 2))
        mgr.stop(act)

    def test_handler_exception_does_not_kill_worker(self):
        ticks = {"n": 0}

        def handler():
            ticks["n"] += 1
            raise RuntimeError("boom")

        act = Activity(id="bg", name="BG", background=True, poll_interval=0.01)
        mgr = self._make(handler)
        mgr.start(act)
        self.assertTrue(_wait_until(lambda: ticks["n"] >= 3))  # keeps ticking
        mgr.stop(act)

    def test_start_non_background_returns_false(self):
        act = Activity(id="seq", name="Seq", background=False)
        mgr = self._make(lambda: None)
        self.assertFalse(mgr.start(act))

    def test_missing_handler_aborts_cleanly(self):
        act = Activity(id="bg", name="BG", background=True, poll_interval=0.01)
        mgr = BackgroundWorkerManager(
            handler_resolver=lambda aid: None,
            is_paused=lambda: False,
            ensure_ready=lambda: True,
        )
        mgr.start(act)
        self.assertTrue(_wait_until(lambda: not mgr.is_running("bg")))

    def test_stop_all_joins_everything(self):
        act1 = Activity(id="a", name="A", background=True, poll_interval=0.01)
        act2 = Activity(id="b", name="B", background=True, poll_interval=0.01)
        mgr = self._make(lambda: None)
        mgr.start_all([act1, act2])
        self.assertTrue(_wait_until(lambda: mgr.is_running("a") and mgr.is_running("b")))
        mgr.stop_all()
        self.assertFalse(mgr.is_running("a"))
        self.assertFalse(mgr.is_running("b"))


if __name__ == "__main__":
    unittest.main()
