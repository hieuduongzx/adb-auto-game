import os
import shutil
import subprocess
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

import src.utils as utils


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows batch launchers")
class LauncherPythonTests(unittest.TestCase):
    def _run_launcher(self, batch_name: str, app_name: str) -> Path:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            shutil.copy2(ROOT / batch_name, tmp / batch_name)

            scripts = tmp / ".venv" / "Scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(ROOT / ".venv" / "Scripts" / "python.exe", scripts / "python.exe")
            shutil.copy2(ROOT / ".venv" / "pyvenv.cfg", tmp / ".venv" / "pyvenv.cfg")

            apps = tmp / "apps"
            apps.mkdir()
            (apps / app_name).write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "Path(__file__).resolve().parents[1].joinpath('chosen.txt').write_text(sys.executable)\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                ["cmd.exe", "/d", "/c", batch_name],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            return Path((tmp / "chosen.txt").read_text(encoding="utf-8")).resolve()

    def test_hub_launcher_prefers_project_virtualenv(self):
        chosen = self._run_launcher("run_hub.bat", "workflow_hub.py")
        self.assertEqual(chosen.name.lower(), "python.exe")
        self.assertEqual(chosen.parent.name.lower(), "scripts")
        self.assertEqual(chosen.parent.parent.name.lower(), ".venv")

    def test_designer_launcher_prefers_project_virtualenv(self):
        chosen = self._run_launcher("run_designer.bat", "workflow_designer.py")
        self.assertEqual(chosen.name.lower(), "python.exe")
        self.assertEqual(chosen.parent.name.lower(), "scripts")
        self.assertEqual(chosen.parent.parent.name.lower(), ".venv")

    def test_source_hub_opens_sibling_tools_with_project_virtualenv(self):
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            scripts = tmp / ".venv" / "Scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(ROOT / ".venv" / "Scripts" / "python.exe", scripts / "python.exe")
            shutil.copy2(ROOT / ".venv" / "pyvenv.cfg", tmp / ".venv" / "pyvenv.cfg")

            apps = tmp / "apps"
            apps.mkdir()
            output = tmp / "chosen.txt"
            (apps / "probe.py").write_text(
                "from pathlib import Path\n"
                "import sys\n"
                "Path(sys.argv[1]).write_text(sys.executable)\n",
                encoding="utf-8",
            )

            system_python = Path(os.environ.get("LOCALAPPDATA", "C:/")) / (
                "Programs/Python/Python310/python.exe"
            )
            self.assertTrue(system_python.is_file(), system_python)
            app_map = {"probe": ("Probe.exe", os.path.join("apps", "probe.py"))}
            with (
                mock.patch.object(utils, "_SOURCE_ROOT", str(tmp)),
                mock.patch.object(utils, "_APP_MAP", app_map),
                mock.patch.object(utils.sys, "executable", str(system_python)),
            ):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", ResourceWarning)
                    utils.launch_tool("probe", [str(output)])

            for _ in range(100):
                if output.is_file():
                    break
                time.sleep(0.05)
            self.assertTrue(output.is_file(), "probe child did not run")
            chosen = Path(output.read_text(encoding="utf-8")).resolve()
            self.assertEqual(chosen.parent.name.lower(), "scripts")
            self.assertEqual(chosen.parent.parent.name.lower(), ".venv")


if __name__ == "__main__":
    unittest.main()
