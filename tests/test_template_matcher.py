"""TemplateMatcher.match / match_all: coarse-to-fine search, flat templates,
the hue check and region handling — all on synthetic frames."""
import os
import sys
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.adb.auto.template_matcher import TemplateMatcher  # noqa: E402


def textured_screen(w=1600, h=900, seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 255, (h, w, 3), dtype=np.uint8)
    return cv2.GaussianBlur(noise, (5, 5), 0)


def button(color, w=120, h=60):
    img = np.full((h, w, 3), 20, np.uint8)
    cv2.rectangle(img, (8, 8), (w - 8, h - 8), color, -1)
    cv2.putText(img, "OK", (w // 2 - 22, h // 2 + 12), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (255, 255, 255), 2)
    return img


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.m = TemplateMatcher()

    def test_pyramid_finds_exact_pixel(self):
        screen = textured_screen()
        tpl = screen[400:460, 700:820].copy()
        res = self.m.match(screen, tpl, threshold=0.9)
        self.assertIsNotNone(res)
        cx, cy, conf, scale = res
        self.assertEqual((cx, cy), (760, 430))
        self.assertGreater(conf, 0.99)

    def test_pyramid_agrees_with_full_search_at_odd_offset(self):
        screen = textured_screen(seed=3)
        tpl = screen[333:371, 517:601].copy()          # odd origin, odd size
        res = self.m.match(screen, tpl, threshold=0.9)
        self.assertEqual(res[:2], (517 + 84 // 2, 333 + 38 // 2))

    def test_small_template_uses_full_search(self):
        screen = textured_screen(seed=1)
        tpl = screen[100:116, 200:216].copy()
        res = self.m.match(screen, tpl, threshold=0.9)
        self.assertEqual(res[:2], (208, 108))

    def test_miss_returns_none(self):
        screen = textured_screen(seed=2)
        tpl = textured_screen(seed=9)[0:60, 0:120].copy()
        self.assertIsNone(self.m.match(screen, tpl, threshold=0.8))

    def test_flat_template_does_not_match_everywhere(self):
        screen = textured_screen()
        flat = np.full((40, 80, 3), (40, 200, 90), np.uint8)
        self.assertIsNone(self.m.match(screen, flat, threshold=0.8))
        screen[500:540, 300:380] = (40, 200, 90)
        res = self.m.match(screen, flat, threshold=0.8)
        self.assertEqual(res[:2], (340, 520))

    def test_greyed_out_button_is_rejected(self):
        red = button((0, 0, 230))
        grey = button((120, 120, 120))
        screen = np.full((900, 1600, 3), 30, np.uint8)
        screen[100:160, 100:220] = grey
        self.assertIsNone(self.m.match(screen, red, threshold=0.6))
        # without the hue check it would have been accepted
        self.assertIsNotNone(self.m.match(screen, red, threshold=0.6, verify_color=False))

    def test_wrong_hue_gives_way_to_right_one(self):
        red = button((0, 0, 230))
        screen = np.full((900, 1600, 3), 30, np.uint8)
        screen[100:160, 100:220] = button((120, 120, 120))
        screen[600:660, 1200:1320] = button((0, 0, 140))   # dimmed red
        res = self.m.match(screen, red, threshold=0.7)
        self.assertEqual(res[:2], (1260, 630))

    def test_multi_scale_finds_enlarged_template(self):
        screen = textured_screen(seed=4)
        tpl = screen[300:360, 400:520].copy()
        big = cv2.resize(screen, None, fx=1.2, fy=1.2, interpolation=cv2.INTER_LINEAR)
        res = self.m.match(big, tpl, threshold=0.8, multi_scale=True,
                           scales=[1.0, 1.1, 1.2, 1.3])
        self.assertIsNotNone(res)
        cx, cy, _, scale = res
        self.assertEqual(scale, 1.2)
        self.assertLessEqual(abs(cx - 552), 2)
        self.assertLessEqual(abs(cy - 396), 2)

    def test_region_full_width_partial_height_is_honoured(self):
        screen = np.full((900, 1600, 3), 30, np.uint8)
        tpl = button((0, 200, 0))
        screen[100:160, 100:220] = tpl
        screen[700:760, 100:220] = tpl
        res = self.m.match(screen, tpl, threshold=0.9, region=(0, 600, 1600, 300))
        self.assertEqual(res[:2], (160, 730))


class MatchAllTests(unittest.TestCase):
    def setUp(self):
        self.m = TemplateMatcher()

    def test_region_and_hue(self):
        tpl = button((0, 200, 0))
        screen = np.full((900, 1600, 3), 30, np.uint8)
        for x in (100, 400, 700):
            screen[100:160, x:x + 120] = tpl
        screen[100:160, 1000:1120] = button((200, 0, 200))   # same shape, wrong hue
        hits = self.m.match_all(screen, tpl, threshold=0.6)
        self.assertEqual(sorted(h[0] for h in hits), [160, 460, 760])
        hits = self.m.match_all(screen, tpl, threshold=0.9, region=(350, 50, 500, 200))
        self.assertEqual(sorted((h[0], h[1]) for h in hits), [(460, 130), (760, 130)])


if __name__ == "__main__":
    unittest.main()
