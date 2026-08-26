"""Tests for src.utils naming / path helpers."""
import os
import re
import unittest

from tests._loader import ROOT  # noqa: F401  (ensures src.* importable)

from src.utils import confined_path, sanitize_name, slugify_workflow_name, ts_stamp


class TestSanitizeName(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(sanitize_name("Cherry Tale"), "Cherry_Tale")

    def test_none_and_empty(self):
        self.assertEqual(sanitize_name(None), "")
        self.assertEqual(sanitize_name("   "), "")

    def test_strips_leading_dots(self):
        self.assertEqual(sanitize_name("..hidden name.."), "hidden_name")

    def test_unicode_collapses(self):
        self.assertEqual(sanitize_name("game #1 (test)"), "game_1_test")


class TestSlugifyWorkflowName(unittest.TestCase):
    def test_similar_names_never_collide(self):
        a = slugify_workflow_name("A B")
        b = slugify_workflow_name("A_B")
        self.assertNotEqual(a.lower(), b.lower())

    def test_deterministic(self):
        self.assertEqual(slugify_workflow_name("Cherry Tale"),
                         slugify_workflow_name("Cherry Tale"))

    def test_reserved_device_names_prefixed(self):
        slug = slugify_workflow_name("CON")
        self.assertTrue(slug.upper().startswith("_CON"), slug)

    def test_empty_falls_back(self):
        self.assertTrue(slugify_workflow_name("").startswith("workflow_"))
        self.assertTrue(slugify_workflow_name("///").startswith("workflow_"))

    def test_filesystem_safe(self):
        slug = slugify_workflow_name('weird: name? * "x"')
        self.assertIsNone(re.search(r'[<>:"/\\|?*]', slug), slug)


class TestTsStamp(unittest.TestCase):
    def test_format(self):
        self.assertRegex(ts_stamp(), r"^\d{8}_\d{6}$")


class TestConfinedPath(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.root = tempfile.mkdtemp(prefix="m2k_confine_")
        self.inner = os.path.join(self.root, "sub")
        os.makedirs(self.inner, exist_ok=True)
        self.file = os.path.join(self.inner, "a.png")
        with open(self.file, "w") as fh:
            fh.write("x")

    def test_allows_inside(self):
        got = confined_path(self.root, self.file)
        self.assertIsNotNone(got)

    def test_blocks_escape(self):
        outside = os.path.join(os.path.dirname(self.root), "evil.png")
        with open(outside, "w") as fh:
            fh.write("x")
        try:
            self.assertIsNone(confined_path(self.root, outside))
            self.assertIsNone(confined_path(self.root, "..\\evil.png"))
        finally:
            os.remove(outside)

    def test_extension_filter(self):
        other = os.path.join(self.root, "script.exe")
        with open(other, "w") as fh:
            fh.write("x")
        self.assertIsNone(confined_path(self.root, other, (".png",)))
        self.assertIsNotNone(confined_path(self.root, self.file, (".png",)))

    def test_root_itself_rejected(self):
        self.assertIsNone(confined_path(self.root, self.root))


if __name__ == "__main__":
    unittest.main()
