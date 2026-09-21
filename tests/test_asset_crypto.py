"""Tests for src/utils/asset_crypto.py — the light obfuscation applied to a
packaged Runner's bundled workflow.json + template images — and the two
runtime loaders that transparently decrypt it (WorkflowEngine.load_file,
TemplateMatcher.load)."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import asset_crypto as ac  # noqa: E402
from src.workflow.engine import WorkflowEngine  # noqa: E402
from src.core.adb.auto.template_matcher import TemplateMatcher  # noqa: E402


class AssetCryptoRoundTripTests(unittest.TestCase):
    def test_round_trip_bytes(self):
        for data in (b"", b"x", b"hello world" * 100, os.urandom(5000)):
            cipher = ac.encrypt_bytes(data)
            self.assertTrue(cipher.startswith(ac.MAGIC))
            self.assertTrue(ac.is_encrypted(cipher))
            self.assertEqual(ac.decrypt_bytes(cipher), data)
            self.assertEqual(ac.maybe_decrypt(cipher), data)

    def test_plain_bytes_pass_through_maybe_decrypt(self):
        for data in (b"", b"plain json {}", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50):
            self.assertFalse(ac.is_encrypted(data))
            self.assertEqual(ac.maybe_decrypt(data), data)

    def test_decrypt_bytes_rejects_plain_data(self):
        with self.assertRaises(ValueError):
            ac.decrypt_bytes(b"not encrypted")

    def test_encrypting_the_same_bytes_twice_differs(self):
        data = b"same plaintext"
        self.assertNotEqual(ac.encrypt_bytes(data), ac.encrypt_bytes(data))

    def test_encrypt_file_is_idempotent(self):
        tmp = Path(tempfile.mkdtemp(prefix="ac_test_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        f = tmp / "a.png"
        f.write_bytes(b"raw image bytes")
        self.assertTrue(ac.encrypt_file(str(f)))
        once = f.read_bytes()
        self.assertTrue(ac.is_encrypted(once))
        self.assertFalse(ac.encrypt_file(str(f)))  # already encrypted -> no-op
        self.assertEqual(f.read_bytes(), once)
        self.assertEqual(ac.decrypt_bytes(f.read_bytes()), b"raw image bytes")

    def test_encrypt_tree_only_touches_matching_extensions(self):
        tmp = Path(tempfile.mkdtemp(prefix="ac_test_"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "sub").mkdir()
        png = tmp / "sub" / "crop.png"
        png.write_bytes(b"img")
        txt = tmp / "notes.txt"
        txt.write_bytes(b"leave me alone")
        n = ac.encrypt_tree(str(tmp))
        self.assertEqual(n, 1)
        self.assertTrue(ac.is_encrypted(png.read_bytes()))
        self.assertEqual(txt.read_bytes(), b"leave me alone")


class WorkflowLoadFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ac_flow_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_loads_plain_json_unchanged(self):
        flow = {"name": "demo", "activities": []}
        path = self.tmp / "workflow.json"
        path.write_text(json.dumps(flow), encoding="utf-8")
        self.assertEqual(WorkflowEngine.load_file(str(path)), flow)

    def test_loads_encrypted_json(self):
        flow = {"name": "demo", "activities": [{"id": "a1"}]}
        path = self.tmp / "workflow.json"
        path.write_bytes(ac.encrypt_bytes(json.dumps(flow).encode("utf-8")))
        self.assertEqual(WorkflowEngine.load_file(str(path)), flow)


class TemplateMatcherLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ac_tpl_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        import numpy as np
        import cv2
        self.np = np
        self.cv2 = cv2
        img = np.zeros((6, 6, 3), dtype=np.uint8)
        img[:, :] = (10, 20, 30)
        ok, buf = cv2.imencode(".png", img)
        assert ok
        self.png_bytes = buf.tobytes()

    def test_loads_plain_template(self):
        path = self.tmp / "t.png"
        path.write_bytes(self.png_bytes)
        matcher = TemplateMatcher()
        loaded = matcher.load(str(path))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.shape[:2], (6, 6))

    def test_loads_encrypted_template(self):
        path = self.tmp / "t.png"
        path.write_bytes(ac.encrypt_bytes(self.png_bytes))
        matcher = TemplateMatcher()
        loaded = matcher.load(str(path))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.shape[:2], (6, 6))

    def test_missing_template_returns_none(self):
        matcher = TemplateMatcher()
        self.assertIsNone(matcher.load(str(self.tmp / "missing.png")))


if __name__ == "__main__":
    unittest.main()
