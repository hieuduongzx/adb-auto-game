"""Small recognition-only PP-OCRv5 Mobile ONNX runtime."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

from src.utils import bundle_dir


def preprocess_bgr(
    crop: np.ndarray,
    *,
    height: int = 48,
    base_width: int = 320,
    max_width: int = 3200,
) -> np.ndarray:
    """Match PaddleOCR's dynamic-width BGR resize and normalization."""
    if not isinstance(crop, np.ndarray) or crop.size == 0:
        raise ValueError("OCR crop must be a non-empty BGR or grayscale image")
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    if crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError("OCR crop must be a non-empty BGR or grayscale image")
    if crop.shape[0] <= 0 or crop.shape[1] <= 0:
        raise ValueError("OCR crop must be a non-empty BGR or grayscale image")

    ratio = crop.shape[1] / float(crop.shape[0])
    canvas_width = min(max_width, max(base_width, int(height * ratio)))
    resized_width = min(canvas_width, max(1, int(np.ceil(height * ratio))))
    resized = cv2.resize(crop, (resized_width, height)).astype(np.float32)
    resized = (resized.transpose((2, 0, 1)) / 255.0 - 0.5) / 0.5
    tensor = np.zeros((1, 3, height, canvas_width), dtype=np.float32)
    tensor[0, :, :, :resized_width] = resized
    return tensor


def decode_ctc(
    scores: np.ndarray,
    characters: Sequence[str],
    blank_index: int = 0,
) -> str:
    """Decode the first CTC batch; Paddle appends ASCII space after its dict."""
    values = np.asarray(scores)
    if values.ndim == 3:
        values = values[0]
    if values.ndim != 2 or values.shape[0] == 0:
        return ""

    token_ids = np.argmax(values, axis=-1)
    output: list[str] = []
    previous = None
    space_index = len(characters) + 1
    for raw_token in token_ids:
        token = int(raw_token)
        repeated = token == previous
        previous = token
        if repeated or token == blank_index:
            continue
        if 1 <= token <= len(characters):
            output.append(characters[token - 1])
        elif token == space_index:
            output.append(" ")
    return "".join(output)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PPOCRv5Recognizer:
    """Load the bundled official ONNX graph and recognize one text crop."""

    def __init__(self, asset_dir: os.PathLike[str] | str | None = None) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("ONNX Runtime is not installed") from exc

        self.asset_dir = Path(
            asset_dir
            if asset_dir is not None
            else Path(bundle_dir()) / "assets" / "ocr" / "ppocr_v5_mobile"
        )
        manifest_path = self.asset_dir / "model.json"
        model_path = self.asset_dir / "rec.onnx"
        dictionary_path = self.asset_dir / "dict.txt"
        for path in (manifest_path, model_path, dictionary_path):
            if not path.is_file():
                raise FileNotFoundError(f"OCR asset is missing: {path}")

        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("model_id") != "ppocr_v5_mobile":
            raise ValueError("OCR manifest has an incompatible model_id")
        expected_hashes = self.manifest.get("sha256", {})
        for path in (model_path, dictionary_path):
            expected = expected_hashes.get(path.name)
            actual = _sha256(path)
            if not expected or actual != expected:
                raise ValueError(f"OCR asset checksum mismatch: {path}")

        self.characters = tuple(
            dictionary_path.read_text(encoding="utf-8").splitlines()
        )
        character_count = int(self.manifest.get("character_count", -1))
        if len(self.characters) != character_count:
            raise ValueError(
                f"OCR dictionary has {len(self.characters)} entries; "
                f"expected {character_count}"
            )

        options = ort.SessionOptions()
        options.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._input_name = str(self.manifest["input_name"])
        self._output_name = str(self.manifest["output_name"])
        if self._session.get_inputs()[0].name != self._input_name:
            raise ValueError("OCR graph input does not match model.json")
        output = self._session.get_outputs()[0]
        if output.name != self._output_name:
            raise ValueError("OCR graph output does not match model.json")
        expected_classes = int(self.manifest["output_class_count"])
        if output.shape[-1] != expected_classes:
            raise ValueError("OCR graph class count does not match model.json")

    def read(self, crop: np.ndarray) -> str:
        tensor = preprocess_bgr(
            crop,
            height=int(self.manifest["input_height"]),
            base_width=int(self.manifest["base_width"]),
            max_width=int(self.manifest["max_width"]),
        )
        scores = self._session.run(
            [self._output_name], {self._input_name: tensor}
        )[0]
        return decode_ctc(
            scores,
            self.characters,
            blank_index=int(self.manifest["blank_index"]),
        )


__all__ = ["PPOCRv5Recognizer", "decode_ctc", "preprocess_bgr"]
