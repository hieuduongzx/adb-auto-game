# PP-OCRv5 Mobile ONNX Runtime Design

## Objective

Replace Macro2k's Paddle/PaddleOCR runtime with ONNX Runtime while preserving
the current `ppocr_v5_mobile` model ID and all OCR behavior visible to
workflows. The packaged Runner must perform recognition offline without text
detection and should shrink from roughly 610 MiB to 195–230 MiB.

## Constraints

- OCR receives a user-selected screen region that contains one text line or
  label. It must not run a detector.
- Keep the model registry and selectors in Designer, Preview, and DevScope so
  another recognition model can be added later.
- Existing workflow values, including legacy `tesseract`, `easyocr`, and
  `paddleocr`, continue migrating to `ppocr_v5_mobile`.
- The Runner must include the recognition model and character dictionary. A
  clean machine must not need Internet access on first use.
- The ONNX graph must come from PaddlePaddle's official
  `PP-OCRv5_mobile_rec_onnx` release. Its dictionary comes from the matching
  official Paddle inference model. LunaTranslator files may be inspected as an
  architectural reference but will not be copied into Macro2k.

## Runtime architecture

`PPOCRv5MobileBackend` remains the registered backend and keeps its public
contract. Its implementation changes from `paddleocr.TextRecognition` to a
small ONNX recognition pipeline:

1. Load bundled `rec.onnx` with ONNX Runtime's CPU execution provider.
2. Accept the existing BGR crop without swapping color channels, matching the
   official model's `DecodeImage(img_mode="BGR")` preprocessing.
3. Resize the crop to the model's fixed height while preserving aspect ratio;
   pad the remaining width and normalize pixels exactly as the official model
   configuration specifies.
4. Run the recognition session without detection or orientation models.
5. Decode the CTC output with the bundled dictionary, collapse repeated token
   IDs, remove blanks, and return the recognized text.
6. Apply Macro2k's existing optional character whitelist after decoding.

The backend resolves assets through `bundle_dir()` so the same code works from
source and from a PyInstaller Runner. Unknown future model IDs remain
unavailable instead of silently selecting a different model.

## Model assets and conversion

Runtime assets live under:

```text
assets/ocr/ppocr_v5_mobile/
  rec.onnx
  dict.txt
  model.json
```

`model.json` records model name, source, input size, normalization parameters,
blank-token handling, and expected ONNX input/output names. This avoids hidden
constants in the inference code and gives future registry entries the same
asset contract.

A development-only exporter combines PaddlePaddle's official ONNX graph with
the dictionary embedded in the matching official Paddle model, validates the
graph contract, and records both hashes. Paddle and Paddle2ONNX are not runtime
or build dependencies.

## Dependencies and packaging

- Add `onnxruntime` as the sole OCR runtime dependency.
- Remove `paddlepaddle`, `paddleocr`, and `paddlex` from runtime requirements.
- Remove Paddle package collection from both PyInstaller specs.
- Collect ONNX Runtime and bundle the three model assets explicitly.
- Keep the isolated PyInstaller scratch directories and final EXE validation
  already added to prevent concurrent builds from deleting one another.

No detection model, DirectML runtime, CUDA runtime, training modules, Pandas,
Hugging Face clients, or Paddle headers are shipped.

## Error handling

Initialization errors identify the missing asset, incompatible ONNX graph, or
runtime loading failure and include the active Python executable in source
mode. OCR calls return an empty string after logging the error, preserving the
engine's existing safe behavior.

Invalid or empty crops return an empty string without invoking ONNX Runtime.
Inputs wider than the supported width are proportionally resized rather than
cropped, so text is not silently discarded.

## Verification

Implementation follows red-green TDD:

- Unit tests verify preprocessing shape, padding, normalization, CTC blank and
  repeat decoding, whitelist behavior, legacy model migration, and registry
  compatibility.
- Golden crop tests run the bundled ONNX model and assert expected recognition
  output for representative Latin text and digits.
- During migration, the same crop set is run through Paddle and ONNX; unexpected
  output differences block removal of Paddle.
- Packaging tests assert Paddle/PaddleOCR/PaddleX are absent, ONNX Runtime and
  model assets are present, and every successful build contains its EXE.
- Build BrownDust2 Runner, launch it as a smoke test, exercise one OCR region,
  and report the exact final folder size.

## Acceptance criteria

- Designer and source runtime recognize the existing OCR fixtures with ONNX.
- A clean packaged Runner recognizes text without downloading files.
- No Paddle, PaddleOCR, PaddleX, Tesseract, or EasyOCR runtime remains.
- The model dropdown still contains `PP-OCRv5 Mobile` and remains registry
  driven.
- BrownDust2 Runner is no larger than 250 MiB on disk, excluding game-specific
  `requirements/` files.
- All Python and JavaScript regression tests pass.
