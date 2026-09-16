"""Build Macro2k's offline OCR payload from official PaddlePaddle files.

The runtime never imports Paddle.  This development tool combines the
official PP-OCRv5 Mobile recognition ONNX graph with the character dictionary
embedded in the official Paddle inference model's ``config.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


MODEL_ID = "ppocr_v5_mobile"
SOURCE_MODEL = "PP-OCRv5_mobile_rec"
EXPECTED_CHARACTER_COUNT = 18_383
OFFICIAL_ONNX_REPOSITORY = (
    "https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_rec_onnx"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_assets(source: Path, converted_model: Path, output: Path) -> dict[str, Any]:
    """Write and validate the three files consumed by Macro2k's OCR runtime."""
    import onnxruntime as ort

    source = source.resolve()
    converted_model = converted_model.resolve()
    config_path = source / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Official model config is missing: {config_path}")
    if not converted_model.is_file():
        raise FileNotFoundError(f"Official ONNX model is missing: {converted_model}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    source_name = str(config.get("Global", {}).get("model_name", ""))
    if source_name != SOURCE_MODEL:
        raise ValueError(
            f"Expected official model {SOURCE_MODEL!r}, found {source_name!r}"
        )
    characters = config.get("PostProcess", {}).get("character_dict")
    if not isinstance(characters, list) or len(characters) != EXPECTED_CHARACTER_COUNT:
        count = len(characters) if isinstance(characters, list) else "invalid"
        raise ValueError(
            f"Expected {EXPECTED_CHARACTER_COUNT} dictionary entries, found {count}"
        )
    if not all(isinstance(character, str) and character for character in characters):
        raise ValueError("The official character dictionary contains an empty entry")

    output.mkdir(parents=True, exist_ok=True)
    model_path = output / "rec.onnx"
    dictionary_path = output / "dict.txt"
    shutil.copyfile(converted_model, model_path)
    dictionary_path.write_text("\n".join(characters) + "\n", encoding="utf-8")

    session_options = ort.SessionOptions()
    session_options.log_severity_level = 3
    session = ort.InferenceSession(
        str(model_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    if len(session.get_inputs()) != 1 or len(session.get_outputs()) != 1:
        raise ValueError("PP-OCRv5 recognition graph must have one input and one output")
    output_classes = session.get_outputs()[0].shape[-1]
    expected_classes = len(characters) + 2  # CTC blank + Paddle's ASCII space.
    if output_classes != expected_classes:
        raise ValueError(
            f"Expected {expected_classes} output classes, found {output_classes}"
        )

    manifest: dict[str, Any] = {
        "model_id": MODEL_ID,
        "source_model": SOURCE_MODEL,
        "source_repository": OFFICIAL_ONNX_REPOSITORY,
        "input_height": 48,
        "base_width": 320,
        "max_width": 3200,
        "color_order": "BGR",
        "normalization": {"scale": 1.0 / 255.0, "mean": 0.5, "std": 0.5},
        "blank_index": 0,
        "use_space_char": True,
        "character_count": len(characters),
        "output_class_count": output_classes,
        "input_name": session.get_inputs()[0].name,
        "output_name": session.get_outputs()[0].name,
        "sha256": {
            "rec.onnx": _sha256(model_path),
            "dict.txt": _sha256(dictionary_path),
        },
    }
    (output / "model.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create Macro2k's PP-OCRv5 Mobile ONNX runtime assets."
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="Official Paddle model folder"
    )
    parser.add_argument(
        "--model", required=True, type=Path, help="Official recognition ONNX graph"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Destination asset folder"
    )
    args = parser.parse_args()
    manifest = export_assets(args.source, args.model, args.output)
    print(
        f"Exported {manifest['source_model']} to {args.output} "
        f"({manifest['character_count']} characters)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
