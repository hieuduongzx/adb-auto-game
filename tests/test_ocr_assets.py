import hashlib
import json
import unittest
from pathlib import Path

import onnxruntime as ort


ROOT = Path(__file__).resolve().parent.parent
ASSET_DIR = ROOT / "assets" / "ocr" / "ppocr_v5_mobile"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OCRAssetTests(unittest.TestCase):
    def test_offline_model_payload_is_loadable_and_self_consistent(self):
        manifest = json.loads(
            (ASSET_DIR / "model.json").read_text(encoding="utf-8")
        )
        characters = (ASSET_DIR / "dict.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        session_options = ort.SessionOptions()
        session_options.log_severity_level = 3
        session = ort.InferenceSession(
            str(ASSET_DIR / "rec.onnx"),
            sess_options=session_options,
            providers=["CPUExecutionProvider"],
        )

        self.assertEqual(manifest["model_id"], "ppocr_v5_mobile")
        self.assertEqual(manifest["source_model"], "PP-OCRv5_mobile_rec")
        self.assertEqual(manifest["color_order"], "BGR")
        self.assertEqual(manifest["input_height"], 48)
        self.assertEqual(manifest["base_width"], 320)
        self.assertEqual(manifest["max_width"], 3200)
        self.assertEqual(manifest["blank_index"], 0)
        self.assertTrue(manifest["use_space_char"])
        self.assertEqual(manifest["character_count"], 18_383)
        self.assertEqual(manifest["output_class_count"], 18_385)
        self.assertEqual(len(characters), 18_383)
        self.assertEqual(session.get_inputs()[0].name, manifest["input_name"])
        self.assertEqual(session.get_outputs()[0].name, manifest["output_name"])
        self.assertEqual(session.get_outputs()[0].shape[-1], 18_385)
        self.assertEqual(
            _sha256(ASSET_DIR / "rec.onnx"), manifest["sha256"]["rec.onnx"]
        )
        self.assertEqual(
            _sha256(ASSET_DIR / "dict.txt"), manifest["sha256"]["dict.txt"]
        )


if __name__ == "__main__":
    unittest.main()
