"""Run the Hub layout-contract tests (tests/test_hub_grid.cjs) from pytest.

Those contracts span hub.css, hub.js and index.html at once and are written in
Node's own test runner, next to the other JS-level test in this folder. This
wrapper keeps them in the suite that `pytest tests` already runs.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")
SCRIPT = Path(__file__).with_name("test_hub_grid.cjs")


@unittest.skipIf(NODE is None, "node is not available")
class HubUiTests(unittest.TestCase):
    def test_hub_layout_contracts(self):
        proc = subprocess.run(
            [NODE, str(SCRIPT)], capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        self.assertEqual(proc.returncode, 0, "\n" + proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
