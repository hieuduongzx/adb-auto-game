"""Frozen entry point for a **single-workflow** Runner build.

Unlike ``entry_designer.py`` (which hosts Hub + Designer + Runner via CLI
switches), this entry ships ONE workflow and nothing else: it launches the
Runner GUI directly, auto-loading the workflow bundled into the build.

The workflow (``workflow.json`` + its ``templates/`` folder) is packaged under
``<_MEIPASS>/workflow/`` by :mod:`packaging.build_runner`. The Runner writes its
per-workflow config to ``data_root()`` as usual, so the bundled (read-only) copy
only supplies the graph + template images.

Built by ``python packaging/build_runner.py --workflow workflows/<Name>`` — see
that module. From source this file just runs the runner on the bundled folder
(handy for a smoke test).
"""
from __future__ import annotations

import os
import sys


# When run from source, make the repo + apps/ importable. In a frozen build
# everything is already on the bundled path, so this is a no-op.
if not getattr(sys, "frozen", False):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (_ROOT, os.path.join(_ROOT, "apps")):
        if _p not in sys.path:
            sys.path.insert(0, _p)


def _find_bundled_workflow() -> str | None:
    """Absolute path to the workflow JSON packaged into this build (or None).

    Looks in ``<bundle_dir>/workflow/`` for ``workflow.json`` first, then any
    ``*.json``. Falls back to a path passed on argv for a source smoke test.
    """
    from src.utils import bundle_dir

    folder = os.path.join(bundle_dir(), "workflow")
    if os.path.isdir(folder):
        primary = os.path.join(folder, "workflow.json")
        if os.path.isfile(primary):
            return primary
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".json"):
                return os.path.join(folder, name)
    # Source smoke test: ``python packaging/entry_runner_single.py <flow.json>``
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        return os.path.abspath(sys.argv[1])
    return None


def main() -> None:
    from workflow_runner import run as run_runner

    flow = _find_bundled_workflow()
    run_runner(flow)


if __name__ == "__main__":
    main()
