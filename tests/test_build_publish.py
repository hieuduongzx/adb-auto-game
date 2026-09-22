"""Tests for the Runner build's GitHub publish step (packaging/build_runner.py).

A publish that fails *after* a successful build is the expensive kind. A Runner
zip is ~67 MB, so over a home uplink the upload takes minutes — but ``_gh``
used the preflight's 20-second leash for it too, and every publish died with
``gh release create ... timed out after 20.0 seconds`` once the build (and the
zip) were already done. These tests pin the upload to its own, far longer
timeout, and check that a timeout says how to recover: ``gh`` creates the
release *before* it uploads the file, so a killed upload can leave a published
tag with no asset, which the next run refuses as "already published".

The module is loaded by path: the repo's ``packaging/`` folder is a namespace
package, and the PyPI ``packaging`` distribution would win the import.

Stdlib only (``unittest`` + ``unittest.mock``), matching the run command in the
README:

    python -m unittest discover -s tests -v
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _load_build_runner():
    """packaging/build_runner.py, imported without going through ``packaging``."""
    path = _ROOT / "packaging" / "build_runner.py"
    spec = importlib.util.spec_from_file_location("build_runner_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


br = _load_build_runner()


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["gh"], 0, stdout, "")


class TestGhTimeouts(unittest.TestCase):
    """``_gh`` must survive whatever gh does, and label a timeout as one."""

    def test_timeout_is_its_own_exit_code(self):
        with mock.patch("subprocess.run",
                        side_effect=subprocess.TimeoutExpired(["gh"], 20.0)):
            result = br._gh(["auth", "status"])
        self.assertEqual(result.returncode, br._GH_TIMEOUT)
        self.assertNotEqual(br._GH_TIMEOUT, 127)   # 127 means "gh is missing"

    def test_missing_cli_is_127(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("gh")):
            self.assertEqual(br._gh(["auth", "status"]).returncode, 127)

    def test_default_timeout_is_the_short_preflight_leash(self):
        with mock.patch("subprocess.run", return_value=_ok()) as run:
            br._gh(["release", "view", "runner-X-v1.0.0", "--repo", "o/r"])
        self.assertEqual(run.call_args.kwargs["timeout"], br.PREFLIGHT_TIMEOUT)


class TestPublish(unittest.TestCase):
    """The upload itself: long timeout, and a recovery path when it expires."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m2k_publish_")
        self.addCleanup(self._cleanup)
        # A stand-in for dist/<Name>-Runner, with something to zip.
        self.final = os.path.join(self.tmp, "Game-Runner")
        os.makedirs(os.path.join(self.final, "_internal"))
        with open(os.path.join(self.final, "_internal", "app.dll"), "wb") as fh:
            fh.write(b"x" * 1024)

    def _cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, True)

    def _publish(self, gh_result):
        with mock.patch.object(br, "publish_checks", return_value=[]), \
             mock.patch.object(br, "_gh", return_value=gh_result) as gh, \
             mock.patch.object(br, "log"), mock.patch.object(br, "progress"):
            try:
                url = br.publish(self.final, "Game", "Game", "1.0.22", "o/r")
            except RuntimeError as exc:
                return gh, exc
            return gh, url

    def test_upload_gets_the_long_timeout(self):
        gh, url = self._publish(_ok())
        self.assertTrue(url.endswith("/releases/tag/runner-Game-v1.0.22"))
        self.assertEqual(gh.call_args.kwargs["timeout"], br.UPLOAD_TIMEOUT)
        # 67 MB in 20 s needs a ~27 Mbit/s uplink; the upload leash must be
        # minutes, not the preflight's seconds.
        self.assertGreater(br.UPLOAD_TIMEOUT, 600)
        self.assertEqual(gh.call_args.args[0][:3], ["release", "create",
                                                    "runner-Game-v1.0.22"])
        zip_path = os.path.join(self.tmp, "Game-Runner-1.0.22.zip")
        self.assertTrue(os.path.isfile(zip_path), "the update package wasn't zipped")

    def test_timeout_says_how_to_recover(self):
        _gh, result = self._publish(subprocess.CompletedProcess(["gh"], br._GH_TIMEOUT, "", ""))
        self.assertIsInstance(result, RuntimeError)
        message = str(result)
        self.assertIn("timed out", message)
        # gh may have created the tag without the file: name the check and the fix.
        self.assertIn("gh release view runner-Game-v1.0.22 --repo o/r", message)
        self.assertIn("gh release delete runner-Game-v1.0.22 --repo o/r --yes", message)

    def test_a_real_gh_error_is_reported_verbatim(self):
        _gh, result = self._publish(subprocess.CompletedProcess(["gh"], 1, "", "HTTP 422: already_exists"))
        self.assertIsInstance(result, RuntimeError)
        self.assertIn("already_exists", str(result))


class TestOcrPackaging(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="m2k_ocr_package_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.contents = Path(self.tmp) / "_internal"
        self.assets = self.contents / "assets" / "ocr" / "ppocr_v5_mobile"
        self.assets.mkdir(parents=True)
        for name in ("rec.onnx", "dict.txt", "model.json"):
            (self.assets / name).write_bytes(b"ocr")
        (self.contents / "onnxruntime").mkdir()

    def test_ocr_nodes_do_not_require_the_removed_tesseract_vendor(self):
        flow = {
            "controller": "win32",
            "capture": "scrcpy",
            "activities": [{
                "graph": {"nodes": [{"type": "if_text"}]},
            }],
        }
        self.assertNotIn("tesseract", br.VENDOR_TOOLS)
        self.assertNotIn("tesseract", br.compute_vendor_needs(flow))

    def test_final_runner_contains_offline_onnx_payload(self):
        br._validate_ocr_payload(self.tmp)

    def test_missing_ocr_asset_names_the_missing_file(self):
        (self.assets / "rec.onnx").unlink()
        with self.assertRaisesRegex(RuntimeError, "rec[.]onnx"):
            br._validate_ocr_payload(self.tmp)

    def test_removed_ocr_runtime_is_rejected(self):
        (self.contents / "paddle").mkdir()
        with self.assertRaisesRegex(RuntimeError, "paddle"):
            br._validate_ocr_payload(self.tmp)

    def test_application_size_excludes_game_requirements(self):
        (self.contents / "runtime.bin").write_bytes(b"x" * 1024 * 1024)
        requirements = Path(self.tmp) / "requirements"
        requirements.mkdir()
        (requirements / "game.bin").write_bytes(b"x" * 2 * 1024 * 1024)

        self.assertAlmostEqual(br._app_size_mb(self.tmp), 1.0, delta=0.01)


class TestBuildScratch(unittest.TestCase):
    def test_concurrent_builds_never_share_pyinstaller_scratch(self):
        factory = getattr(br, "_make_build_scratch", None)
        self.assertIsNotNone(factory, "build scratch factory is missing")
        with tempfile.TemporaryDirectory(prefix="m2k_build_root_") as root, \
             mock.patch.object(br, "ROOT", root):
            first = factory()
            second = factory()
            self.addCleanup(__import__("shutil").rmtree, first[0], True)
            self.addCleanup(__import__("shutil").rmtree, second[0], True)
            self.assertNotEqual(first[0], second[0])
            self.assertNotEqual(first[1], second[1])
            self.assertNotEqual(first[2], second[2])
            for scratch, stage, work in (first, second):
                self.assertEqual(Path(stage).parent, Path(scratch))
                self.assertEqual(Path(work).parent, Path(scratch))


class TestFrozenBuildRoots(unittest.TestCase):
    """A frozen Hub runs build_runner.py from the copy bundled in its exe.

    That copy sits inside the bundle, which has no vendor/ and no dist/. The
    checkout being built is the working directory the Hub launches it in, so the
    script has to split "where my own files are" from "the checkout".
    """

    def test_checkout_is_the_working_directory_when_the_bundle_has_no_vendor(self):
        with tempfile.TemporaryDirectory() as bundle, tempfile.TemporaryDirectory() as checkout:
            os.makedirs(os.path.join(checkout, "vendor"))
            with mock.patch.object(br, "__file__", os.path.join(bundle, "packaging", "build_runner.py")), \
                 mock.patch.object(br.os, "getcwd", return_value=checkout):
                script_root, checkout_root = br._resolve_roots()
            self.assertEqual(script_root, bundle)
            self.assertEqual(checkout_root, checkout)

    def test_a_source_checkout_is_its_own_root(self):
        with tempfile.TemporaryDirectory() as checkout:
            os.makedirs(os.path.join(checkout, "vendor"))
            with mock.patch.object(br, "__file__", os.path.join(checkout, "packaging", "build_runner.py")):
                script_root, checkout_root = br._resolve_roots()
            self.assertEqual(script_root, checkout)
            self.assertEqual(checkout_root, checkout)

    def test_output_lands_in_the_checkout_dist_not_the_bundle(self):
        with tempfile.TemporaryDirectory() as bundle, tempfile.TemporaryDirectory() as checkout:
            os.makedirs(os.path.join(checkout, "dist"))
            with mock.patch.object(br, "ROOT", bundle), \
                 mock.patch.object(br.os, "getcwd", return_value=checkout):
                self.assertEqual(br._output_root(""), os.path.join(checkout, "dist"))
            self.assertEqual(br._output_root(os.path.join(checkout, "custom")),
                             os.path.join(checkout, "custom"))

if __name__ == "__main__":
    unittest.main()
