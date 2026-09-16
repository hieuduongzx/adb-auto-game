# PP-OCRv5 Mobile ONNX Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace PaddleOCR with a bundled, recognition-only PP-OCRv5 Mobile ONNX runtime and keep each standalone Runner at or below 250 MiB excluding game requirements.

**Architecture:** A focused `ppocr_onnx.py` module owns model metadata, BGR preprocessing, ONNX Runtime inference, and CTC decoding. The existing OCR registry and `OCRReader` facade remain stable while `PPOCRv5MobileBackend` delegates to that module. The repository payload combines PaddlePaddle's official ONNX graph with its matching official dictionary; Paddle is absent from runtime requirements and builds.

**Tech Stack:** Python 3.10, NumPy, OpenCV, ONNX Runtime CPU, PyInstaller, `unittest`

**Spec:** `docs/superpowers/specs/2026-09-16-ppocrv5-onnx-runtime-design.md`

## Global Constraints

- OCR receives one user-selected text line or label and must not run detection or orientation models.
- Keep model ID `ppocr_v5_mobile`, label `PP-OCRv5 Mobile`, and the registry-driven selectors.
- Legacy values `tesseract`, `easyocr`, `paddleocr`, `auto`, and empty strings migrate to `ppocr_v5_mobile`.
- The Runner must work offline and bundle `rec.onnx`, `dict.txt`, and `model.json`.
- The graph must come from PaddlePaddle's official `PP-OCRv5_mobile_rec_onnx` release and the dictionary from the matching official Paddle model; LunaTranslator files are reference only.
- Preserve BGR channel order, resize to height 48, preserve aspect ratio, pad on the right, normalize to `[-1, 1]`, and cap input width at 3200.
- Runtime dependencies must not contain Paddle, PaddleOCR, PaddleX, Tesseract, or EasyOCR.
- BrownDust2 Runner must be no larger than 250 MiB excluding `requirements/`.

## File Structure

- Create `tools/export_ppocrv5_mobile_onnx.py`: reproducible development-only exporter for the official Paddle cache, dictionary, hashes, and metadata.
- Create `assets/ocr/ppocr_v5_mobile/{rec.onnx,dict.txt,model.json}`: offline runtime payload.
- Create `src/core/adb/auto/ppocr_onnx.py`: ONNX model loading, preprocessing, inference, and CTC decoding.
- Modify `src/core/adb/auto/ocr.py`: keep the public registry/facade and replace PaddleOCR calls with `PPOCRv5Recognizer`.
- Modify `requirements.txt`: replace Paddle packages with ONNX Runtime CPU.
- Modify `packaging/runner_build.spec` and `packaging/apps_build.spec`: collect ONNX Runtime and OCR assets, and stop collecting Paddle packages.
- Modify `packaging/build_runner.py`: validate the final OCR payload and report application size separately from game requirements.
- Modify `packaging/build.md`, `packaging/README.md`, and `README.md`: document offline ONNX OCR and the conversion-only workflow.
- Rewrite `tests/test_ocr.py`: pure preprocessing/decoder tests, registry migration tests, and a real ONNX recognition test.
- Create `tests/fixtures/ocr/score_42.png`: deterministic golden line crop.
- Extend `tests/test_build_publish.py`: final-folder OCR payload and size validation tests.

---

### Task 1: Export and validate official ONNX assets

**Files:**
- Create: `tools/export_ppocrv5_mobile_onnx.py`
- Create: `assets/ocr/ppocr_v5_mobile/rec.onnx`
- Create: `assets/ocr/ppocr_v5_mobile/dict.txt`
- Create: `assets/ocr/ppocr_v5_mobile/model.json`
- Create: `tests/test_ocr_assets.py`

**Interfaces:**
- Consumes: official cache folder containing `inference.json`, `inference.pdiparams`, and `config.json`.
- Produces: `export_assets(source: Path, converted_model: Path, output: Path) -> dict`; manifest fields `model_id`, `source_model`, `input_height`, `base_width`, `max_width`, `color_order`, `normalization`, `blank_index`, `character_count`, `input_name`, `output_name`, and SHA-256 hashes.

- [ ] **Step 1: Install conversion/runtime tooling into the development environment**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install "onnxruntime==1.23.2" "onnx==1.17.0"
```

Download `inference.onnx` from PaddlePaddle's official
`PP-OCRv5_mobile_rec_onnx` repository. Do not add Paddle or Paddle2ONNX to
`requirements.txt`.

- [ ] **Step 2: Write the failing asset-contract test**

```python
class OCRAssetTests(unittest.TestCase):
    def test_offline_model_payload_is_loadable_and_self_consistent(self):
        manifest = json.loads((ASSET_DIR / "model.json").read_text("utf-8"))
        chars = (ASSET_DIR / "dict.txt").read_text("utf-8").splitlines()
        session = ort.InferenceSession(str(ASSET_DIR / "rec.onnx"), providers=["CPUExecutionProvider"])
        self.assertEqual(manifest["model_id"], "ppocr_v5_mobile")
        self.assertEqual(manifest["source_model"], "PP-OCRv5_mobile_rec")
        self.assertEqual(manifest["color_order"], "BGR")
        self.assertEqual(manifest["input_height"], 48)
        self.assertEqual(manifest["character_count"], 18383)
        self.assertEqual(len(chars), 18383)
        self.assertEqual(session.get_inputs()[0].name, manifest["input_name"])
        self.assertEqual(session.get_outputs()[0].name, manifest["output_name"])
```

- [ ] **Step 3: Run the asset test and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_ocr_assets -v`

Expected: FAIL because `assets/ocr/ppocr_v5_mobile/model.json` does not exist.

- [ ] **Step 4: Implement the exporter and generate the payload**

The exporter must read `PostProcess.character_dict` from `config.json`, write one UTF-8 character per line, inspect the converted graph with ONNX Runtime, calculate file hashes with `hashlib.sha256`, and write this metadata shape:

```python
manifest = {
    "model_id": "ppocr_v5_mobile",
    "source_model": "PP-OCRv5_mobile_rec",
    "input_height": 48,
    "base_width": 320,
    "max_width": 3200,
    "color_order": "BGR",
    "normalization": {"scale": 1.0 / 255.0, "mean": 0.5, "std": 0.5},
    "blank_index": 0,
    "character_count": len(characters),
    "input_name": session.get_inputs()[0].name,
    "output_name": session.get_outputs()[0].name,
    "sha256": {"rec.onnx": sha256(model), "dict.txt": sha256(dictionary)},
}
```

Call the exporter with the matching official Paddle cache and official ONNX graph. The exporter must reject a source model name other than `PP-OCRv5_mobile_rec`, any dictionary count other than 18,383, and a graph whose output is not 18,385 classes.

```powershell
.\.venv\Scripts\python.exe tools\export_ppocrv5_mobile_onnx.py `
  --source "$env:USERPROFILE\.paddlex\official_models\PP-OCRv5_mobile_rec" `
  --model build\PP-OCRv5_mobile_rec_official.onnx `
  --output assets\ocr\ppocr_v5_mobile
```

- [ ] **Step 5: Run the asset test and verify GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_ocr_assets -v`

Expected: PASS; ONNX Runtime loads the bundled graph and manifest names match its input/output tensors.

- [ ] **Step 6: Commit the asset unit**

```powershell
git add tools/export_ppocrv5_mobile_onnx.py assets/ocr/ppocr_v5_mobile tests/test_ocr_assets.py
git commit -m "feat: bundle PP-OCRv5 Mobile ONNX assets"
```

### Task 2: Implement preprocessing and CTC recognition

**Files:**
- Create: `src/core/adb/auto/ppocr_onnx.py`
- Rewrite: `tests/test_ocr.py`
- Create: `tests/fixtures/ocr/score_42.png`

**Interfaces:**
- Consumes: asset directory produced by Task 1, BGR or grayscale NumPy crop.
- Produces: `preprocess_bgr(crop: np.ndarray, *, height: int, base_width: int, max_width: int) -> np.ndarray`; `decode_ctc(scores: np.ndarray, characters: Sequence[str], blank_index: int = 0) -> str`; `PPOCRv5Recognizer.read(crop: np.ndarray) -> str`.

- [ ] **Step 1: Write failing preprocessing tests**

Use a literal two-color BGR crop and assert that the result has shape `(1, 3, 48, 320)`, keeps channel 0 in channel 0, normalizes black to `-1.0`, white to `1.0`, and pads the right side with zeros. Add a wide `(48, 800, 3)` crop test asserting shape `(1, 3, 48, 800)`, and an over-wide crop test asserting width 3200.

- [ ] **Step 2: Run preprocessing tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_ocr.OCRPreprocessTests -v`

Expected: ERROR because `src.core.adb.auto.ppocr_onnx` is missing.

- [ ] **Step 3: Implement minimal BGR preprocessing**

```python
def preprocess_bgr(crop, *, height=48, base_width=320, max_width=3200):
    if crop.ndim == 2:
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    if crop.ndim != 3 or crop.shape[2] != 3 or crop.size == 0:
        raise ValueError("OCR crop must be a non-empty BGR or grayscale image")
    ratio = crop.shape[1] / float(crop.shape[0])
    canvas_width = min(max_width, max(base_width, int(height * ratio)))
    resized_width = min(canvas_width, max(1, int(np.ceil(height * ratio))))
    resized = cv2.resize(crop, (resized_width, height)).astype(np.float32)
    resized = (resized.transpose(2, 0, 1) / 255.0 - 0.5) / 0.5
    tensor = np.zeros((1, 3, height, canvas_width), dtype=np.float32)
    tensor[0, :, :, :resized_width] = resized
    return tensor
```

- [ ] **Step 4: Verify preprocessing GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_ocr.OCRPreprocessTests -v`

Expected: PASS.

- [ ] **Step 5: Write failing CTC decoder tests**

Build literal score tensors whose argmax IDs are `[0, 1, 1, 0, 2, 2, 3]`; with characters `("A", "B", "C")`, assert `ABC`. Add cases proving that blanks separate repeated characters (`[1, 0, 1] -> "AA"`) and out-of-range IDs are ignored without shifting valid character indices.

- [ ] **Step 6: Run decoder tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_ocr.OCRCTCDecoderTests -v`

Expected: FAIL because `decode_ctc` is missing.

- [ ] **Step 7: Implement CTC decoding and the recognizer**

`decode_ctc` must take argmax across the final score axis, skip blank ID 0, collapse only adjacent repeated IDs, and map token ID `n` to `characters[n - 1]`. `PPOCRv5Recognizer` resolves `assets/ocr/ppocr_v5_mobile` below `bundle_dir()`, loads and validates `model.json`, verifies both asset hashes, creates one CPU `InferenceSession`, calls `preprocess_bgr`, runs the manifest input/output names, and returns decoded text. Add explicit empty, zero-height, and malformed-channel tests proving those inputs raise before `session.run`.

- [ ] **Step 8: Add and run a real-model golden test**

Generate `tests/fixtures/ocr/score_42.png` once with OpenCV text rendering. First record Paddle's output for that exact file, then assert the bundled ONNX recognizer returns the same non-empty text. Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ocr -v
```

Expected: PASS, including real ONNX inference.

- [ ] **Step 9: Commit the inference unit**

```powershell
git add src/core/adb/auto/ppocr_onnx.py tests/test_ocr.py tests/fixtures/ocr/score_42.png
git commit -m "feat: recognize cropped text with ONNX Runtime"
```

### Task 3: Replace the Paddle backend without changing callers

**Files:**
- Modify: `src/core/adb/auto/ocr.py`
- Modify: `tests/test_ocr.py`

**Interfaces:**
- Consumes: `PPOCRv5Recognizer()` and `.read(crop)` from Task 2.
- Produces: unchanged `OCRReader`, `OCRBackend`, registry constants, and `PPOCRv5MobileBackend.read(crop, whitelist=None) -> str` APIs.

- [ ] **Step 1: Write failing facade tests**

Add tests that instantiate the real default `OCRReader`, assert `backend_name == "ppocr_v5_mobile"`, recognize the golden crop through `read_text`, apply whitelist after decoding, and verify all legacy names still resolve to the same registered backend. Assert an unknown future model ID remains unavailable instead of falling back. Patch only `bundle_dir()` in the missing-asset test and assert initialization is unavailable and reads return an empty string.

- [ ] **Step 2: Run facade tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_ocr.OCRModelTests -v`

Expected: FAIL because the current backend imports PaddleOCR and does not use bundled ONNX assets.

- [ ] **Step 3: Replace backend implementation**

Remove `paddleocr.TextRecognition`, `_result_text`, and Paddle-specific help text. Initialize `PPOCRv5Recognizer`; log the exact missing asset or ONNX Runtime load error plus `sys.executable` in source mode; keep safe empty-string behavior. Keep `_MODEL_REGISTRY`, model labels, migration, crop handling, and all public method signatures unchanged.

- [ ] **Step 4: Run facade and workflow regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_ocr -v
node --test tests/test_node_modes_and_logs.cjs
```

Expected: both commands PASS.

- [ ] **Step 5: Commit the backend migration**

```powershell
git add src/core/adb/auto/ocr.py tests/test_ocr.py
git commit -m "refactor: switch OCR backend from Paddle to ONNX"
```

### Task 4: Make packaged applications carry only ONNX OCR

**Files:**
- Modify: `requirements.txt`
- Modify: `packaging/runner_build.spec`
- Modify: `packaging/apps_build.spec`
- Modify: `packaging/build_runner.py`
- Modify: `tests/test_build_publish.py`

**Interfaces:**
- Consumes: `assets/ocr/ppocr_v5_mobile` and installed `onnxruntime`.
- Produces: `_validate_ocr_payload(final: str) -> None`; `_app_size_mb(final: str) -> float`; packaged asset location `<contents>/assets/ocr/ppocr_v5_mobile`.

- [ ] **Step 1: Write failing final-folder validation tests**

Create a temporary Runner layout with `_internal/assets/ocr/ppocr_v5_mobile` and `_internal/onnxruntime`. Assert validation passes. Remove `rec.onnx` and assert the error names it. Add `_internal/paddle` and assert the error identifies the forbidden package. Create a 1 MiB `requirements/game.bin` and assert `_app_size_mb` excludes it.

- [ ] **Step 2: Run packaging tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_build_publish.TestOcrPackaging -v`

Expected: FAIL because `_validate_ocr_payload` and `_app_size_mb` do not exist.

- [ ] **Step 3: Update runtime dependency and PyInstaller specs**

Replace the Paddle requirement block with `onnxruntime==1.23.2`. Change third-party collection from Paddle packages to `onnxruntime`. Add `assets/ocr/ppocr_v5_mobile` to both specs' data files under the same relative path. Add `paddle`, `paddleocr`, and `paddlex` to `excludes` as a defensive guard.

- [ ] **Step 4: Implement and call final-folder validation**

After `_trim_build(final)` and before publishing, require the three OCR assets and ONNX Runtime package, reject top-level or contents-directory folders named `paddle`, `paddleocr`, or `paddlex`, and log `_app_size_mb(final)` separately from `requirements/`. Raise if application size exceeds 250 MiB so an oversized release cannot be published silently.

- [ ] **Step 5: Verify packaging unit GREEN**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_build_publish.TestOcrPackaging -v`

Expected: PASS.

- [ ] **Step 6: Commit packaging changes**

```powershell
git add requirements.txt packaging/runner_build.spec packaging/apps_build.spec packaging/build_runner.py tests/test_build_publish.py
git commit -m "build: package lightweight ONNX OCR runtime"
```

### Task 5: Document, verify, build, and measure

**Files:**
- Modify: `README.md`
- Modify: `packaging/README.md`
- Modify: `packaging/build.md`

**Interfaces:**
- Consumes: completed runtime and packaging tasks.
- Produces: reproducible developer instructions and measured BrownDust2 Runner evidence.

- [ ] **Step 1: Update documentation**

Document that PP-OCRv5 Mobile recognition is offline and recognition-only, ONNX Runtime is the only OCR runtime dependency, model selectors remain registry-driven, and `tools/export_ppocrv5_mobile_onnx.py` regenerates the manifest/dictionary around PaddlePaddle's official ONNX graph.

- [ ] **Step 2: Run the complete regression suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$cjs = Get-ChildItem tests\*.cjs | ForEach-Object FullName
node --test $cjs
```

Expected: all Python and JavaScript tests PASS with zero failures.

- [ ] **Step 3: Build BrownDust2 Runner from the project venv**

Run:

```powershell
.\.venv\Scripts\python.exe packaging\build_runner.py --workflow workflows\BrownDust2 --name BrownDust2 --version 1.0.0 --out dist --verbose
```

Expected: exit code 0, `dist/BrownDust2-Runner/BrownDust2.exe` exists, payload validation passes, and the logged application size is at most 250 MiB.

- [ ] **Step 4: Inspect the actual build and smoke-test startup/OCR**

Calculate exact byte sizes for the full folder, `_internal`, `onnxruntime`, OCR assets, and `requirements/`. Search the built tree for Paddle/Tesseract/EasyOCR names and require no runtime matches. Launch `BrownDust2.exe`, require it to remain alive for eight seconds, then stop it. Exercise the bundled OCR model against the golden crop from a clean subprocess whose current directory is outside the repository.

- [ ] **Step 5: Commit documentation and final corrections**

```powershell
git add README.md packaging/README.md packaging/build.md
git commit -m "docs: describe offline ONNX OCR packaging"
```

- [ ] **Step 6: Final verification and requirement audit**

Re-run the complete Python/JavaScript suite after the final commit, inspect `git diff` for accidental Paddle runtime references, and check every acceptance criterion in the design spec against command output before reporting completion.
