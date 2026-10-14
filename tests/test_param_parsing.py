"""Node params can arrive as strings (Runner overrides, hand-edited JSON)."""
import unittest
from unittest import mock

from src.workflow import engine as E


class ParamParsingTests(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, "ADBGameAutomation"):
            self.engine = E.WorkflowEngine()

    def test_string_false_does_not_invert_a_condition(self):
        self.engine._find_template = mock.Mock(return_value=(5, 6, 0.9))
        for raw, expected in (("false", True), ("true", False), (False, True), ("0", True), ("", True)):
            with self.subTest(negate=raw):
                self.assertIs(self.engine._eval_condition(
                    "if_image", {"template": "a.png", "negate": raw}), expected)

    def test_blank_or_bad_branch_count_falls_back_to_the_default(self):
        pc = E.WorkflowEngine._port_count
        self.assertEqual(pc({"count": ""}, 3), 3)
        self.assertEqual(pc({"count": "x"}, 2), 2)
        self.assertEqual(pc({"count": "4"}, 3), 4)
        self.assertEqual(pc({"count": 0}, 3), 1)
        self.assertEqual(pc({}, 3), 3)

    def test_parallel_with_blank_count_still_runs_its_branches(self):
        ran = []
        self.engine._actions["log"] = lambda node, p: ran.append(node["id"]) or True
        graph = {"nodes": [{"id": "s", "type": "start"},
                           {"id": "p", "type": "parallel", "params": {"count": ""}},
                           {"id": "a", "type": "log", "params": {}}, {"id": "b", "type": "log", "params": {}}],
                 "edges": [{"from": "s", "to": "p"}, {"from": "p", "fromPort": "1", "to": "a"},
                           {"from": "p", "fromPort": "3", "to": "b"}]}
        self.engine._run_graph(graph)
        self.assertCountEqual(ran, ["a", "b"])


if __name__ == "__main__":
    unittest.main()


class PausedWaitTests(unittest.TestCase):
    """A paused run must not act: a Tap image mid-wait holds until Resume."""

    def setUp(self):
        with mock.patch.object(E, "ADBGameAutomation"):
            self.engine = E.WorkflowEngine()

    def test_no_probe_while_paused_and_paused_time_is_not_spent(self):
        import threading
        import time
        probes = []
        self.engine.auto.find_template.side_effect = lambda *a, **k: probes.append(1) or None
        self.engine._pause.clear()
        out = []
        t = threading.Thread(target=lambda: out.append(
            self.engine._wait_for_template("x.png", timeout=0.3, report=False)))
        t.start()
        time.sleep(0.5)                      # longer than the timeout, all paused
        self.assertEqual(probes, [])
        self.assertTrue(t.is_alive())
        self.engine._pause.set()
        t.join(3)
        self.assertEqual(out, [None])
        self.assertGreaterEqual(len(probes), 1)

    def test_found_while_running_returns_the_hit(self):
        self.engine.auto.find_template.return_value = (3, 4, 0.9)
        self.assertEqual(self.engine._wait_for_template("x.png", timeout=1, report=False), (3, 4, 0.9))

    def test_stop_ends_a_paused_wait(self):
        import threading
        self.engine.auto.find_template.return_value = None
        self.engine._pause.clear()
        threading.Timer(0.2, self.engine._stop.set).start()
        self.assertIsNone(self.engine._wait_for_template("x.png", timeout=30, report=False))
