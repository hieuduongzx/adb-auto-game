import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.core.adb.auto.ocr import KNOWN_BACKENDS, OCRReader
from src.core.adb.auto.ppocr_onnx import (
    PPOCRv5Recognizer,
    decode_ctc,
    preprocess_bgr,
)


ROOT = Path(__file__).resolve().parent.parent


def _scores_for(token_ids, class_count):
    scores = np.zeros((1, len(token_ids), class_count), dtype=np.float32)
    for index, token_id in enumerate(token_ids):
        scores[0, index, token_id] = 1.0
    return scores


class OCRPreprocessTests(unittest.TestCase):
    def test_bgr_channels_normalization_and_right_padding_match_paddle(self):
        crop = np.empty((24, 48, 3), dtype=np.uint8)
        crop[:, :] = (255, 0, 128)

        tensor = preprocess_bgr(crop)

        self.assertEqual(tensor.shape, (1, 3, 48, 320))
        self.assertEqual(tensor.dtype, np.float32)
        self.assertAlmostEqual(float(tensor[0, 0, 0, 0]), 1.0, places=6)
        self.assertAlmostEqual(float(tensor[0, 1, 0, 0]), -1.0, places=6)
        self.assertAlmostEqual(float(tensor[0, 2, 0, 0]), 1 / 255, places=6)
        self.assertTrue(np.all(tensor[0, :, :, 96:] == 0.0))

    def test_dynamic_width_preserves_wide_text_and_caps_extreme_regions(self):
        wide = np.zeros((48, 800, 3), dtype=np.uint8)
        extreme = np.zeros((10, 1000, 3), dtype=np.uint8)

        self.assertEqual(preprocess_bgr(wide).shape, (1, 3, 48, 800))
        self.assertEqual(preprocess_bgr(extreme).shape, (1, 3, 48, 3200))

    def test_invalid_crops_are_rejected_before_inference(self):
        invalid = (
            np.zeros((0, 10, 3), dtype=np.uint8),
            np.zeros((10, 0, 3), dtype=np.uint8),
            np.zeros((10, 10, 4), dtype=np.uint8),
        )
        for crop in invalid:
            with self.subTest(shape=crop.shape), self.assertRaises(ValueError):
                preprocess_bgr(crop)


class OCRCTCDecoderTests(unittest.TestCase):
    def test_blank_and_adjacent_duplicates_are_removed(self):
        scores = _scores_for([0, 1, 1, 0, 2, 2, 3], 5)
        self.assertEqual(decode_ctc(scores, ("A", "B", "C")), "ABC")

    def test_blank_separates_repeated_characters(self):
        scores = _scores_for([1, 0, 1], 5)
        self.assertEqual(decode_ctc(scores, ("A", "B", "C")), "AA")

    def test_ascii_space_is_the_class_after_the_dictionary(self):
        scores = _scores_for([1, 4, 2], 5)
        self.assertEqual(decode_ctc(scores, ("A", "B", "C")), "A B")

    def test_out_of_range_ids_do_not_shift_valid_characters(self):
        scores = _scores_for([1, 5, 2], 6)
        self.assertEqual(decode_ctc(scores, ("A", "B", "C")), "AB")


class OCRONNXIntegrationTests(unittest.TestCase):
    def test_official_model_matches_paddle_on_the_golden_crop(self):
        crop = cv2.imread(str(ROOT / "tests" / "fixtures" / "ocr" / "score_42.png"))
        self.assertIsNotNone(crop)

        recognizer = PPOCRv5Recognizer()

        self.assertEqual(recognizer.read(crop), "SCORE 42")


class _Result:
    json = {"res": {"rec_text": "Score 42!", "rec_score": 0.98}}


class _TextRecognition:
    init_kwargs = None
    last_input = None

    def __init__(self, **kwargs):
        type(self).init_kwargs = kwargs

    def predict(self, *, input, batch_size=1):
        type(self).last_input = input.copy()
        return [_Result()]


class OCRModelTests(unittest.TestCase):
    def setUp(self):
        _TextRecognition.init_kwargs = None
        _TextRecognition.last_input = None
        self.paddleocr = types.SimpleNamespace(TextRecognition=_TextRecognition)

    def test_default_reader_uses_ppocr_v5_mobile_recognition_only(self):
        with patch.dict(sys.modules, {"paddleocr": self.paddleocr}):
            reader = OCRReader()
            screen = np.zeros((24, 48, 3), dtype=np.uint8)
            text = reader.read_text(
                screen, region=(7, 5, 20, 10), whitelist="Score 42"
            )

        self.assertEqual(KNOWN_BACKENDS, ("ppocr_v5_mobile",))
        self.assertEqual(reader.backend_name, "ppocr_v5_mobile")
        self.assertEqual(
            _TextRecognition.init_kwargs,
            {
                "model_name": "PP-OCRv5_mobile_rec",
                "device": "cpu",
                "enable_mkldnn": False,
            },
        )
        self.assertEqual(_TextRecognition.last_input.shape, (10, 20, 3))
        self.assertEqual(text, "Score 42")

    def test_legacy_backend_names_migrate_to_the_only_registered_model(self):
        with patch.dict(sys.modules, {"paddleocr": self.paddleocr}):
            for old_name in ("tesseract", "easyocr", "paddleocr", ""):
                with self.subTest(old_name=old_name):
                    reader = OCRReader(backend=old_name)
                    self.assertEqual(reader.backend_name, "ppocr_v5_mobile")


if __name__ == "__main__":
    unittest.main()
