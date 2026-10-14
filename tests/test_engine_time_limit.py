"""An activity's time limit stops a stuck activity and lets the sequence go on."""
import time
import unittest
from unittest import mock

from src.workflow import engine as E


def _act(aid, graph, limit=0, retries=1):
    return {"id": aid, "name": aid, "type": "sequence", "enabled": True,
            "maxRetries": retries, "timeLimit": limit, "graph": graph}


STUCK = {"nodes": [{"id": "s", "type": "start"},
                   {"id": "w", "type": "wait", "params": {"seconds": 60}},
                   {"id": "e", "type": "end"}],
         "edges": [{"from": "s", "to": "w"}, {"from": "w", "to": "e"}]}
QUICK = {"nodes": [{"id": "s", "type": "start"}, {"id": "e", "type": "end"}],
         "edges": [{"from": "s", "to": "e"}]}


class TimeLimitTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, "ADBGameAutomation"):
            self.engine = E.WorkflowEngine()
        self.done = []
        self.crashes = []
        self.engine.on("on_activity_complete", lambda act, ok: self.done.append((act["id"], ok)))
        self.engine.on("on_activity_crash", lambda act, crash: self.crashes.append(crash))
        self.engine._wait_to_run = mock.Mock(wraps=self.engine._wait_to_run)

    def run_flow(self, *acts):
        self.engine.load({"activities": list(acts)})
        self.engine.running = True
        t0 = time.monotonic()
        with mock.patch.object(E.WorkflowEngine, "_time_limit_seconds",
                               staticmethod(lambda act: float(act.get("timeLimit") or 0))):
            self.engine._run_sequence()
        return time.monotonic() - t0

    def test_stuck_activity_fails_at_its_limit_and_the_next_one_runs(self):
        took = self.run_flow(_act("stuck", STUCK, limit=0.4, retries=3), _act("next", QUICK))
        self.assertLess(took, 5)
        self.assertEqual(self.done, [("stuck", False), ("next", True)])
        self.assertEqual(self.crashes[0]["reason"], "time_limit")
        self.assertEqual(self.crashes[0]["node"], "w")          # the block it was stuck on

    def test_no_limit_means_no_watchdog(self):
        self.assertEqual(E.WorkflowEngine._time_limit_seconds({"timeLimit": 0}), 0)
        self.assertEqual(E.WorkflowEngine._time_limit_seconds({"timeLimit": "x"}), 0)
        self.assertEqual(E.WorkflowEngine._time_limit_seconds({"timeLimit": "1.5"}), 90)
        self.run_flow(_act("quick", QUICK))
        self.assertEqual(self.done, [("quick", True)])

    def test_paused_time_does_not_count(self):
        self.engine.load({"activities": []})
        start = self.engine._active_clock()
        self.engine.pause()
        time.sleep(0.3)
        self.assertLess(self.engine._active_clock() - start, 0.1)
        self.engine.resume()
        time.sleep(0.1)
        self.assertGreaterEqual(self.engine._active_clock() - start, 0.09)

    def test_parallel_branches_share_the_limit(self):
        par = {"nodes": [{"id": "s", "type": "start"},
                         {"id": "p", "type": "parallel", "params": {"count": 2}},
                         {"id": "w1", "type": "wait", "params": {"seconds": 60}},
                         {"id": "w2", "type": "wait", "params": {"seconds": 60}}],
               "edges": [{"from": "s", "to": "p"}, {"from": "p", "fromPort": "1", "to": "w1"},
                         {"from": "p", "fromPort": "2", "to": "w2"}]}
        took = self.run_flow(_act("par", par, limit=0.4))
        self.assertLess(took, 5)
        self.assertEqual(self.done, [("par", False)])


if __name__ == "__main__":
    unittest.main()
