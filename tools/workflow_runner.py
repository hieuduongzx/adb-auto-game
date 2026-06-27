"""Standalone launcher for the JSON Workflow Runner GUI.

Loads a workflow JSON (exported from the Workflow tab in
``tools/dev_helper.py``) and runs its sequence/background activities against a
connected device.

Run::

    python tools/workflow_runner.py
"""
from __future__ import annotations

import os
import sys

# Make ``src.*`` importable when launched from tools/.
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.gui.workflow_runner_gui import run

if __name__ == "__main__":
    # Optional: a flow JSON path to auto-load (the designer's "Chạy GUI" passes one).
    auto = sys.argv[1] if len(sys.argv) > 1 else None
    run(auto)
