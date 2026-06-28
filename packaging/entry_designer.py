"""Frozen entry point for ``designer.exe``.

Default behaviour opens the **Workflow Designer**. When invoked with
``--runner [flow.json]`` it opens the **Workflow Runner** GUI instead — the
designer's *Chạy GUI* button relaunches this same executable in that mode
(see :func:`src.utils.launch_tool`).

This module is the PyInstaller analysis entry point; the static
``import workflow_designer`` / ``import src.gui.workflow_runner_gui`` below are
what pull those tools (and their whole dependency tree) into the build.
"""
from __future__ import annotations

import os
import sys

# When run from source (e.g. ``python packaging/entry_designer.py`` for a smoke
# test) make the repo + tools/ importable. In a frozen build everything is
# already on the bundled path, so this is a no-op.
if not getattr(sys, "frozen", False):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (_ROOT, os.path.join(_ROOT, "tools")):
        if _p not in sys.path:
            sys.path.insert(0, _p)


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "--runner":
        flow = argv[1] if len(argv) > 1 else None
        from src.gui.workflow_runner_gui import run as run_runner
        run_runner(flow)
    else:
        import workflow_designer
        workflow_designer.run()


if __name__ == "__main__":
    main()
