"""A full Start can repeat the sequence: N rounds, or until stopped."""
import threading
import time
import unittest
from unittest import mock

from src.workflow import engine as E


def _flow(*names, background=False):
    acts = []
    for name in names:
        acts.append({"id": name, "name": name, "type": "sequence", "enabled": True,
                     "graph": {"nodes": [{"id": "s", "type": "start"}, {"id": "e", "type": "end"}],
                               "edges": [{"from": "s", "fromPort": "out", "to": "e"}]}})
    if background:
        acts.append({"id": "bg", "name": "bg", "type": "background", "enabled": True,
                     "graph": {"nodes": [{"id": "s", "type": "start"}], "edges": []}})
    return {"name": "Rounds", "activities": acts}


class EngineRoundsTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, "ADBGameAutomation"):
            self.engine = E.WorkflowEngine()
        self.runs = []
        self.rounds = []
        self.engine.on("on_activity_complete", lambda act, ok: self.runs.append(act["id"]))
        self.engine.on("on_round", self.rounds.append)
        sleep = mock.patch.object(E.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def run_sequence(self, flow):
        self.engine.load(flow)
        self.engine.running = True
        self.engine._run_sequence()

    def test_default_is_a_single_pass_without_round_events(self):
        self.run_sequence(_flow("a", "b"))
        self.assertEqual(self.runs, ["a", "b"])
        self.assertEqual(self.rounds, [])

    def test_count_repeats_the_whole_sequence(self):
        self.engine.configure_rounds(3, 0)
        self.run_sequence(_flow("a", "b"))
        self.assertEqual(self.runs, ["a", "b"] * 3)
        running = [r["round"] for r in self.rounds if r["phase"] == "running"]
        self.assertEqual(running, [1, 2, 3])
        self.assertTrue(all(r["total"] == 3 for r in self.rounds))

    def test_rest_is_announced_between_rounds_only(self):
        self.engine.configure_rounds(2, 30)
        with mock.patch.object(self.engine, "_rest_between_rounds") as rest:
            self.run_sequence(_flow("a"))
        rest.assert_called_once_with(30.0)
        phases = [r["phase"] for r in self.rounds]
        self.assertEqual(phases, ["running", "resting", "running"])

    def test_until_stopped_keeps_going_until_stop(self):
        self.engine.configure_rounds(0, 0)

        def stop_after_four(act, ok):
            if len(self.runs) >= 4:
                self.engine._stop.set()
        self.engine.on("on_activity_complete", stop_after_four)
        self.run_sequence(_flow("a"))
        self.assertEqual(self.runs, ["a"] * 4)
        self.assertTrue(all(r["total"] == 0 for r in self.rounds))

    def test_nothing_enabled_does_not_spin(self):
        self.engine.configure_rounds(0, 0)
        flow = _flow("a")
        flow["activities"][0]["enabled"] = False
        self.run_sequence(flow)
        self.assertEqual(self.runs, [])
        self.assertEqual(len([r for r in self.rounds if r["phase"] == "running"]), 1)

    def test_bad_values_fall_back_safely(self):
        self.assertEqual(self.engine.configure_rounds("x", "y"), {"rounds": 1, "rest": 0.0})
        self.assertEqual(self.engine.configure_rounds(-4, -1), {"rounds": 0, "rest": 0.0})
        self.assertEqual(self.engine.configure_rounds("5", float("inf")), {"rounds": 5, "rest": 0.0})


class RestBetweenRoundsTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, "ADBGameAutomation"):
            self.engine = E.WorkflowEngine()

    def test_stop_ends_the_rest_at_once(self):
        threading.Timer(0.15, self.engine._stop.set).start()
        t0 = time.monotonic()
        self.engine._rest_between_rounds(30)
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_pause_holds_the_countdown(self):
        self.engine._pause.clear()
        threading.Timer(0.4, self.engine._pause.set).start()
        t0 = time.monotonic()
        self.engine._rest_between_rounds(0.3)
        self.assertGreaterEqual(time.monotonic() - t0, 0.6)

    def test_duration_words(self):
        d = E.WorkflowEngine._duration
        self.assertEqual([d(45), d(60), d(90), d(3600), d(5400)], ["45s", "1m", "1m 30s", "1h", "1h 30m"])


if __name__ == "__main__":
    unittest.main()
