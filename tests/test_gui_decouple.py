"""Verify the GUI bridge uses public automation methods (Phase 7)."""
import unittest

from tests import _bootstrap  # noqa: F401
from src.gui.pywebview_gui import AutomationAPI


class _FakeAutomation:
    """Minimal stand-in recording the public calls the GUI should make."""

    def __init__(self):
        self.stop_calls = 0
        self.bg_calls = []

    def stop(self):
        self.stop_calls += 1

    def set_background_enabled(self, enabled):
        self.bg_calls.append(enabled)


class TestGuiDecoupling(unittest.TestCase):
    def _api(self):
        return AutomationAPI(_FakeAutomation(), "Test")

    def test_close_delegates_to_stop(self):
        api = self._api()
        api._close()
        self.assertTrue(api._closing)
        self.assertEqual(api.automation.stop_calls, 1)

    def test_toggle_background_uses_public_method(self):
        api = self._api()
        self.assertTrue(api.toggle_background(True))
        self.assertEqual(api.automation.bg_calls, [True])
        self.assertTrue(api._bg_running)
        # Toggling to the same state is a no-op (no extra call).
        self.assertTrue(api.toggle_background(True))
        self.assertEqual(api.automation.bg_calls, [True])
        # Turn off.
        self.assertTrue(api.toggle_background(False))
        self.assertEqual(api.automation.bg_calls, [True, False])
        self.assertFalse(api._bg_running)


if __name__ == "__main__":
    unittest.main()
