"""Designer breakpoints: a test run holds before a flagged block."""
import threading
import time
import unittest
from unittest import mock

from src.workflow import engine as E


def _graph():
    return {"nodes": [{"id": "s", "type": "start"},
                      {"id": "a", "type": "set_var", "params": {"name": "x", "value": "1"}},
                      {"id": "b", "type": "set_var", "breakpoint": True,
                       "params": {"name": "y", "value": "2"}},
                      {"id": "c", "type": "set_var", "params": {"name": "z", "value": "3"}},
                      {"id": "e", "type": "end"}],
            "edges": [{"from": "s", "to": "a"}, {"from": "a", "to": "b"},
                      {"from": "b", "to": "c"}, {"from": "c", "to": "e"}]}


class BreakpointTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, "ADBGameAutomation"):
            self.engine = E.WorkflowEngine()
        self.engine._ensure_ready = mock.Mock(return_value=True)
        self.hits = []
        self.done = []
        self.engine.on("on_breakpoint", self.hits.append)
        self.engine.on("on_node_done", lambda nid, st, port: self.done.append(nid))

    def start(self):
        self.engine.load({"activities": [{"id": "act", "graph": _graph()}]})
        self.assertTrue(self.engine.start_graph(_graph(), "s"))

    def wait_for(self, cond, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.01)
        return False

    def test_runner_ignores_breakpoints(self):
        self.start()
        self.assertTrue(self.wait_for(lambda: not self.engine.running))
        self.assertEqual(self.hits, [])
        self.assertIn("c", self.done)

    def test_holds_before_the_block_then_steps_and_continues(self):
        self.engine.honor_breakpoints = True
        self.start()
        self.assertTrue(self.wait_for(lambda: self.hits == ["b"]))
        time.sleep(0.1)
        self.assertNotIn("b", self.done)          # held *before* b ran
        self.engine.debug_next()                   # step: b runs, then holds at c
        self.assertTrue(self.wait_for(lambda: "b" in self.done))
        time.sleep(0.1)
        self.assertNotIn("c", self.done)
        self.engine.debug_continue()               # run on to the end
        self.assertTrue(self.wait_for(lambda: not self.engine.running))
        self.assertIn("c", self.done)

    def test_stop_at_a_breakpoint_does_not_run_the_block(self):
        self.engine.honor_breakpoints = True
        self.start()
        self.assertTrue(self.wait_for(lambda: self.hits == ["b"]))
        threading.Thread(target=self.engine.stop, daemon=True).start()
        self.assertTrue(self.wait_for(lambda: not self.engine.running))
        time.sleep(0.1)
        self.assertNotIn("b", self.done)
        self.assertFalse(self.engine._debug_step)


if __name__ == "__main__":
    unittest.main()
