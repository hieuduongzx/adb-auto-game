"""Verify region_contains_text delegates to OCRReader.contains_text (Phase 1)."""
import unittest

import numpy as np

from tests import _bootstrap  # noqa: F401
from src.core.adb.auto.automation import ADBGameAutomation


class _RecordingOCR:
    def __init__(self):
        self.calls = []
        self.result = True

    def contains_text(self, screen, needle, **kwargs):
        self.calls.append((needle, kwargs))
        return self.result


class TestRegionContainsText(unittest.TestCase):
    def _make_auto(self):
        auto = ADBGameAutomation.__new__(ADBGameAutomation)  # skip __init__/device
        auto.latest_screen = np.zeros((10, 10, 3), dtype=np.uint8)
        import threading
        auto.screen_lock = threading.Lock()
        auto.ocr = _RecordingOCR()
        return auto

    def test_delegates_with_args(self):
        auto = self._make_auto()
        out = auto.region_contains_text(
            "0/5", region=(1, 2, 3, 4), whitelist="0123456789/",
        )
        self.assertTrue(out)
        self.assertEqual(len(auto.ocr.calls), 1)
        needle, kwargs = auto.ocr.calls[0]
        self.assertEqual(needle, "0/5")
        self.assertEqual(kwargs["region"], (1, 2, 3, 4))
        self.assertEqual(kwargs["whitelist"], "0123456789/")
        self.assertIn("case_sensitive", kwargs)
        self.assertIn("normalize_whitespace", kwargs)

    def test_returns_false_when_no_screen(self):
        auto = self._make_auto()
        auto.latest_screen = None
        self.assertFalse(auto.region_contains_text("x", region=(0, 0, 1, 1)))


if __name__ == "__main__":
    unittest.main()
