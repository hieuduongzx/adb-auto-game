"""Tests for the shared key-name tables and the engine's node log context.

Stdlib only (``unittest``), matching the run command in the README:

    python -m unittest discover -s tests -v
"""
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.keynames import (  # noqa: E402
    android_key_is_known,
    android_key_name,
    describe_key_event,
    vk_combo,
    vk_is_known,
    vk_name,
)
from src.workflow.engine import WorkflowEngine  # noqa: E402
from src import utils as u  # noqa: E402


class TestVkNames(unittest.TestCase):
    def test_named_codes(self):
        self.assertEqual(vk_name(0x0D), "Enter")
        self.assertEqual(vk_name(0x1B), "Escape")
        self.assertEqual(vk_name(0x20), "Space")
        self.assertEqual(vk_name(0x26), "↑ Up")

    def test_generated_ranges(self):
        self.assertEqual(vk_name(0x41), "A")
        self.assertEqual(vk_name(0x5A), "Z")
        self.assertEqual(vk_name(0x30), "0")
        self.assertEqual(vk_name(0x70), "F1")
        self.assertEqual(vk_name(0x7B), "F12")

    def test_unknown_code_degrades_to_vk_form(self):
        # A code outside the table must still identify itself rather than
        # render as an empty string.
        self.assertEqual(vk_name(0xFE), "VK254")
        self.assertEqual(vk_name("junk"), "VKjunk")
        self.assertFalse(vk_is_known(0xFE))
        self.assertTrue(vk_is_known(0x0D))

    def test_combo_prints_only_set_modifiers(self):
        self.assertEqual(vk_combo(0x41), "A")
        self.assertEqual(vk_combo(0x41, shift=True), "Shift+A")
        self.assertEqual(vk_combo(0x41, ctrl=True, shift=True), "Ctrl+Shift+A")
        # Modifier order is fixed regardless of how the flags are passed.
        self.assertEqual(vk_combo(0x41, win=True, alt=True, ctrl=True), "Ctrl+Alt+Win+A")


class TestAndroidKeyNames(unittest.TestCase):
    def test_numeric_and_named_forms_agree(self):
        for form in (4, "4", "BACK", "back", "KEYCODE_BACK"):
            self.assertEqual(android_key_name(form), "BACK", form)

    def test_unknown_input_passes_through(self):
        # The `key` block's field is free text, so an unrecognised entry has to
        # survive to the log rather than be swallowed.
        self.assertEqual(android_key_name("BACKK"), "BACKK")
        self.assertEqual(android_key_name(9999), "9999")
        self.assertFalse(android_key_is_known("BACKK"))
        self.assertFalse(android_key_is_known(9999))
        self.assertTrue(android_key_is_known("KEYCODE_HOME"))

    def test_bool_is_not_a_keycode(self):
        # bool is an int subclass; True must not be read as keycode 1.
        self.assertFalse(android_key_is_known(True))
        self.assertEqual(android_key_name(True), "True")

    def test_empty_input(self):
        self.assertEqual(android_key_name(""), "")
        self.assertFalse(android_key_is_known(""))


class TestDescribeKeyEvent(unittest.TestCase):
    def test_win_modes(self):
        self.assertEqual(describe_key_event("win", 0x0D, "press", 80), "Enter pressed for 80ms")
        self.assertEqual(describe_key_event("win", 0x0D, "down"), "Enter held down")
        self.assertEqual(describe_key_event("win", 0x0D, "up"), "Enter released")
        self.assertEqual(describe_key_event("win", 0x0D, "press"), "Enter")

    def test_android_ignores_mode(self):
        self.assertEqual(describe_key_event("android", 4, "down"), "BACK")


class _StubEngine(WorkflowEngine):
    """A WorkflowEngine with just enough state to drive ``_walk``.

    ``_walk`` is the only place the engine attributes a log line to a block, so
    exercising it directly is what proves the attribution works — no device,
    no workflow file, no threads.
    """

    def __init__(self):
        self._ctx = threading.local()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()          # the walk blocks on this gate; set == not paused
        self._debug_step = False
        self._debug_gate = threading.Event()
        self.callbacks = {}
        self._actions = {}
        self._functions = {}
        self._fatal = ""

    def _emit(self, event, *args):
        pass


def _graph():
    """``start → unknown-block → end``.

    The middle block is a type the engine does not know on purpose: it is the
    shortest path through ``_walk`` that actually logs a line, so the test
    proves the attribution without needing a device, an action handler or a
    real run.
    """
    nodes = {
        "s": {"id": "s", "type": "start", "params": {}},
        "n1": {"id": "n1", "type": "khong_co_block_nay", "params": {}},
        "e": {"id": "e", "type": "end", "params": {}},
    }
    edges = [
        {"from": "s", "fromPort": "out", "to": "n1"},
        {"from": "n1", "fromPort": "out", "to": "e"},
    ]
    return nodes, WorkflowEngine._build_adjacency(edges)


class TestLogNodeContext(unittest.TestCase):
    def setUp(self):
        self.seen = []
        self._cb = lambda level, msg, meta: self.seen.append(meta.get("node"))
        u.add_log_subscriber(self._cb, with_meta=True)
        u.set_log_node(None)

    def tearDown(self):
        u.remove_log_subscriber(self._cb)
        u.set_log_node(None)

    def test_meta_carries_node(self):
        u.set_log_node("n7")
        u.log_info("hello")
        self.assertEqual(self.seen[-1], "n7")

    def test_clearing_removes_node(self):
        u.set_log_node("n7")
        u.set_log_node(None)
        u.log_info("hello")
        self.assertIsNone(self.seen[-1])

    def test_walk_stamps_the_block_it_enters(self):
        nodes, adj = _graph()
        eng = _StubEngine()
        # A reused worker thread would still hold the previous activity's block.
        u.set_log_node("left-over")
        eng._walk(nodes, adj, "n1", {}, 0)
        self.assertEqual(self.seen, ["n1"],
                         "walk must attribute lines to the block it ran")
        # Entering the next block re-points the context; it is never left
        # dangling on a block that has finished.
        self.assertEqual(u.get_log_node(), "e")


if __name__ == "__main__":
    unittest.main()
