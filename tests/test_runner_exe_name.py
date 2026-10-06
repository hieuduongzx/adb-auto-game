import os
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "packaging"))

import build_runner as br  # noqa: E402
from src import runner_update  # noqa: E402


class TestRunnerExeName(unittest.TestCase):
    def test_built_exe_carries_runner_in_its_name(self):
        self.assertEqual(br.runner_exe_name("BrownDust2"), "BrownDust2-Runner.exe")
        self.assertEqual(runner_update.runner_exe_name({"appName": "BrownDust2"}), "BrownDust2-Runner.exe")
        self.assertEqual(runner_update.legacy_exe_name({"appName": "BrownDust2"}), "BrownDust2.exe")

    def test_update_zip_also_carries_the_pre_rename_exe(self):
        tmp = tempfile.mkdtemp(prefix="m2k_exe_")
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        folder = os.path.join(tmp, "Game-Runner")
        os.makedirs(os.path.join(folder, "_internal"))
        with open(os.path.join(folder, "Game-Runner.exe"), "wb") as fh:
            fh.write(b"MZ")
        zip_path = os.path.join(tmp, "u.zip")
        br._zip_runner(folder, zip_path, "Game")
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        # An old Runner refuses a package without its own exe name.
        self.assertIn("Game-Runner.exe", names)
        self.assertIn("Game.exe", names)

    def test_zip_name_matches_a_sanitised_app_name(self):
        tmp = tempfile.mkdtemp(prefix="m2k_exe_")
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        folder = os.path.join(tmp, "Runner")
        os.makedirs(folder)
        with open(os.path.join(folder, "Brown_Dust_2-Runner.exe"), "wb") as fh:
            fh.write(b"MZ")
        zip_path = os.path.join(tmp, "u.zip")
        br._zip_runner(folder, zip_path, "Brown Dust 2!")
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        self.assertIn("Brown_Dust_2-Runner.exe", names)
        self.assertIn("Brown_Dust_2.exe", names)

    def test_build_verifies_the_renamed_exe(self):
        # Regression: build() checked for "<Name>.exe" while the spec emits
        # "<Name>-Runner.exe", so every build failed its own output check.
        src = (__import__("pathlib").Path(__file__).parents[1]
               / "packaging" / "build_runner.py").read_text(encoding="utf-8")
        self.assertNotIn('app_name + ".exe"', src)
        self.assertIn("runner_exe_name(app_name)", src)

    def test_legacy_exe_hands_over_to_the_renamed_one(self):
        tmp = tempfile.mkdtemp(prefix="m2k_exe_")
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        for name in ("Game.exe", "Game-Runner.exe"):
            open(os.path.join(tmp, name), "wb").close()
        with mock.patch.object(runner_update, "is_frozen", return_value=True), \
             mock.patch.object(sys, "executable", os.path.join(tmp, "Game.exe")), \
             mock.patch("subprocess.Popen") as popen:
            self.assertTrue(runner_update.migrate_exe_name({"appName": "Game"}))
        self.assertEqual(popen.call_args.args[0][0], os.path.join(tmp, "Game-Runner.exe"))

    def test_renamed_exe_keeps_running(self):
        tmp = tempfile.mkdtemp(prefix="m2k_exe_")
        self.addCleanup(__import__("shutil").rmtree, tmp, True)
        open(os.path.join(tmp, "Game-Runner.exe"), "wb").close()
        with mock.patch.object(runner_update, "is_frozen", return_value=True), \
             mock.patch.object(sys, "executable", os.path.join(tmp, "Game-Runner.exe")), \
             mock.patch("subprocess.Popen") as popen:
            self.assertFalse(runner_update.migrate_exe_name({"appName": "Game"}))
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
