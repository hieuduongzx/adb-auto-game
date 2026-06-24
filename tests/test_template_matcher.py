"""Pin TemplateMatcher FIFO cache eviction."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import cv2

from tests import _bootstrap  # noqa: F401
from src.core.adb.auto.template_matcher import TemplateMatcher


class TestTemplateMatcherCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_png(self, name: str) -> str:
        path = self.tmp / name
        img = np.zeros((12, 12, 3), dtype=np.uint8)
        cv2.imwrite(str(path), img)
        return str(path)

    def test_fifo_eviction_caps_cache_size(self):
        matcher = TemplateMatcher(cache_size=2)
        p1 = self._make_png("a.png")
        p2 = self._make_png("b.png")
        p3 = self._make_png("c.png")

        matcher.load(p1)
        matcher.load(p2)
        matcher.load(p3)  # should evict the oldest (p1)

        stats = matcher.get_cache_stats()
        self.assertEqual(stats["cache_size"], 2)
        self.assertEqual(stats["max_size"], 2)
        keys = stats["templates"]
        self.assertNotIn(f"{p1}_False", keys)  # p1 evicted (FIFO)
        self.assertIn(f"{p3}_False", keys)

    def test_load_missing_returns_none(self):
        matcher = TemplateMatcher(cache_size=2)
        self.assertIsNone(matcher.load(str(self.tmp / "does_not_exist.png")))

    def test_match_finds_template_at_known_location(self):
        # Build a screen with a distinctive 20x20 patch at (60, 40).
        screen = np.zeros((100, 120, 3), dtype=np.uint8)
        patch = np.full((20, 20, 3), 200, dtype=np.uint8)
        patch[5:15, 5:15] = 30  # inner square so the patch isn't flat
        screen[40:60, 60:80] = patch

        matcher = TemplateMatcher()
        hit = matcher.match(screen, patch, threshold=0.9)
        self.assertIsNotNone(hit)
        cx, cy, conf, scale = hit
        self.assertAlmostEqual(cx, 70, delta=2)  # center of (60..80)
        self.assertAlmostEqual(cy, 50, delta=2)  # center of (40..60)
        self.assertGreaterEqual(conf, 0.9)

    def test_match_all_dedupes_with_nms(self):
        screen = np.zeros((100, 200, 3), dtype=np.uint8)
        patch = np.full((20, 20, 3), 200, dtype=np.uint8)
        patch[5:15, 5:15] = 30
        screen[40:60, 20:40] = patch
        screen[40:60, 150:170] = patch  # second instance, far apart

        matcher = TemplateMatcher()
        hits = matcher.match_all(screen, patch, threshold=0.9)
        self.assertEqual(len(hits), 2)


if __name__ == "__main__":
    unittest.main()
