"""Pin the (0,0) screen-size safeguards added in Phase 8 (B1)."""
import unittest

from tests import _bootstrap  # noqa: F401
from src.core.adb.controller import ADBController
from src.core.adb.auto.automation import ADBGameAutomation


class TestScreenSizeValidation(unittest.TestCase):
    def test_controller_get_screen_size_no_device(self):
        ctrl = ADBController.__new__(ADBController)
        ctrl.device = None
        self.assertEqual(ctrl.get_screen_size(), (0, 0))

    def _auto_with_size(self, size):
        auto = ADBGameAutomation.__new__(ADBGameAutomation)
        auto.get_screen_size = lambda: size
        return auto

    def test_center_point_zero_when_unknown(self):
        auto = self._auto_with_size((0, 0))
        self.assertEqual(auto.get_center_point(), (0, 0))

    def test_random_point_zero_when_unknown(self):
        # Must not call random.randint(0, 0..) blindly / negative bound.
        auto = self._auto_with_size((0, 0))
        self.assertEqual(auto.get_random_point(), (0, 0))

    def test_center_point_normal(self):
        auto = self._auto_with_size((1080, 1920))
        self.assertEqual(auto.get_center_point(), (540, 960))


if __name__ == "__main__":
    unittest.main()
