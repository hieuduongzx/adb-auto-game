"""Tests for src.core.adb.device_info pure helpers."""
import os
import tempfile
import unittest

import numpy as np

from src.core.adb.device_info import (
    check_color_at,
    delete_asset,
    ensure_region_in_filename,
    list_image_assets,
    pixel_color,
)


def _img():
    # 10x10 BGR image, all pixels blue-ish (BGR 200, 30, 40).
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    img[:, :] = (200, 30, 40)
    return img


class TestPixelColor(unittest.TestCase):
    def test_in_bounds(self):
        got = pixel_color(_img(), 10, 10, 3, 4)
        self.assertEqual(got["hex"], "#281EC8")   # RGB of (B200,G30,R40)
        self.assertEqual(got["rgb"], "40, 30, 200")

    def test_out_of_bounds(self):
        self.assertEqual(pixel_color(None, 0, 0, 0, 0)["hex"], "")
        self.assertEqual(pixel_color(_img(), 10, 10, 99, 0)["hex"], "")


class TestCheckColorAt(unittest.TestCase):
    def test_match_within_tolerance(self):
        res = check_color_at(_img(), 10, 10, 5, 5, "#281EC8", tolerance=10)
        self.assertTrue(res["match"])

    def test_mismatch(self):
        res = check_color_at(_img(), 10, 10, 5, 5, "#FFFFFF", tolerance=10)
        self.assertFalse(res["match"])

    def test_invalid_hex(self):
        res = check_color_at(_img(), 10, 10, 5, 5, "#FFF", tolerance=10)
        self.assertFalse(res["match"])
        self.assertEqual(res.get("error"), "Invalid hex")

    def test_no_screen(self):
        res = check_color_at(None, 0, 0, 0, 0, "#000000")
        self.assertEqual(res.get("error"), "No screenshot")


class TestEnsureRegionInFilename(unittest.TestCase):
    def test_appends_when_missing(self):
        self.assertEqual(
            ensure_region_in_filename("C:/out/hero.png", 10, 20, 30, 40),
            "C:/out/hero_10_20_30_40.png")

    def test_keeps_existing_suffix(self):
        path = "C:/out/hero_10_20_30_40.png"
        self.assertEqual(ensure_region_in_filename(path, 1, 2, 3, 4), path)

    def test_decimal_suffix_counts(self):
        # The coordinate regex allows a decimal tail on the last group.
        path = "C:/out/hero_1_2_3_4.5"
        self.assertEqual(ensure_region_in_filename(path, 9, 9, 9, 9), path)


class TestAssetLibrary(unittest.TestCase):
    def setUp(self):
        import cv2
        self.root = tempfile.mkdtemp(prefix="m2k_assets_")
        self.sub = os.path.join(self.root, "pkg")
        os.makedirs(self.sub, exist_ok=True)
        img = np.zeros((4, 6, 3), dtype=np.uint8)
        self.assertTrue(cv2.imwrite(os.path.join(self.root, "a.png"), img))
        self.assertTrue(cv2.imwrite(os.path.join(self.sub, "b.jpg"), img))
        with open(os.path.join(self.root, "notes.txt"), "w") as fh:
            fh.write("skip me")

    def test_list_recursive_and_filtered(self):
        items = list_image_assets(self.root)
        names = {it["name"].replace("\\", "/") for it in items}
        self.assertIn("a.png", names)
        self.assertIn("pkg/b.jpg", names)
        self.assertNotIn("notes.txt", names)

    def test_list_missing_dir(self):
        self.assertEqual(list_image_assets(os.path.join(self.root, "nope")), [])

    def test_delete_confined_only(self):
        rel = os.path.join("pkg", "b.jpg")
        self.assertTrue(delete_asset(self.root, os.path.join(self.root, rel)))
        self.assertFalse(os.path.exists(os.path.join(self.root, rel)))
        # Outside the root → refused.
        outside = os.path.join(tempfile.gettempdir(), "m2k_outside.png")
        with open(outside, "wb") as fh:
            fh.write(b"x")
        try:
            self.assertFalse(delete_asset(self.root, outside))
            self.assertTrue(os.path.exists(outside))
        finally:
            os.remove(outside)


if __name__ == "__main__":
    unittest.main()
