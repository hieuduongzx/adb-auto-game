"""Pin the OCRReader facade contract after the backend-strategy refactor."""
import unittest

import numpy as np

from tests import _bootstrap  # noqa: F401
from src.core.adb.auto import ocr as ocr_mod
from src.core.adb.auto.ocr import (
    OCRReader, OCRBackend, create_backend, KNOWN_BACKENDS,
    TesseractBackend, EasyOCRBackend, PaddleOCRBackend, _apply_whitelist,
)


class _FakeBackend(OCRBackend):
    name = "fake"

    def __init__(self):
        super().__init__()
        self.read_calls = []

    def init(self):
        self.available = True
        return True

    def read(self, crop, *, lang=None, whitelist=None, config=None, psm=None):
        self.read_calls.append({"shape": crop.shape, "lang": lang,
                                "whitelist": whitelist, "config": config, "psm": psm})
        return "  hello  "


class TestFactory(unittest.TestCase):
    def test_factory_known_backends(self):
        self.assertIsInstance(create_backend("tesseract"), TesseractBackend)
        self.assertIsInstance(create_backend("easyocr"), EasyOCRBackend)
        self.assertIsInstance(create_backend("paddleocr"), PaddleOCRBackend)

    def test_factory_unknown_returns_none(self):
        self.assertIsNone(create_backend("bogus"))

    def test_known_backends_tuple(self):
        self.assertEqual(KNOWN_BACKENDS, ("tesseract", "easyocr", "paddleocr"))


class TestWhitelist(unittest.TestCase):
    def test_apply_whitelist_filters(self):
        self.assertEqual(_apply_whitelist("a1b2/c", "12/"), "12/")

    def test_apply_whitelist_passthrough_when_empty(self):
        self.assertEqual(_apply_whitelist("anything", None), "anything")


class TestReaderFacade(unittest.TestCase):
    def _reader_with_fake(self):
        reader = OCRReader.__new__(OCRReader)
        reader.default_lang = "eng"
        reader._default_config = "--oem 3 --psm 7"
        reader._tesseract_cmd = None
        reader._backend_name = "fake"
        reader._backend = _FakeBackend()
        reader._available = reader._backend.init()
        return reader

    def test_read_text_crops_preprocesses_and_strips(self):
        reader = self._reader_with_fake()
        screen = np.zeros((40, 40, 3), dtype=np.uint8)
        out = reader.read_text(screen, region=(0, 0, 20, 20), whitelist="helo")
        self.assertEqual(out, "hello")  # stripped
        self.assertEqual(len(reader._backend.read_calls), 1)
        self.assertEqual(reader._backend.read_calls[0]["whitelist"], "helo")

    def test_read_text_empty_when_unavailable(self):
        reader = self._reader_with_fake()
        reader._available = False
        self.assertEqual(reader.read_text(np.zeros((4, 4, 3), np.uint8)), "")

    def test_set_backend_rejects_unknown(self):
        reader = self._reader_with_fake()
        self.assertFalse(reader.set_backend("nope"))

    def test_static_crop_available(self):
        # automation.py calls OCRReader._crop directly; keep it static.
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        self.assertEqual(OCRReader._crop(img, (0, 0, 4, 4)).shape, (4, 4, 3))


if __name__ == "__main__":
    unittest.main()
