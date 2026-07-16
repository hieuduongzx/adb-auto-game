"""Frozen entry point for ``Macro2k.exe``.

Default behaviour opens the **Hub** (workflow dashboard). Switches:

- ``--designer [flow.json]`` — Workflow Designer (optionally with a file open)
- ``--runner [flow.json]``   — Workflow Runner GUI (optionally auto-load a flow)

The Hub's *Edit* / *Run* buttons relaunch this same executable with those
flags (see :func:`src.utils.launch_tool`).

This module is the PyInstaller analysis entry point; the static imports below
pull the hub, designer, and runner (and their dependency trees) into the build.
"""
from __future__ import annotations

import os
import sys

# When run from source (e.g. ``python packaging/entry_designer.py`` for a smoke
# test) make the repo + apps/ importable. In a frozen build everything is
# already on the bundled path, so this is a no-op.
if not getattr(sys, "frozen", False):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (_ROOT, os.path.join(_ROOT, "apps")):
        if _p not in sys.path:
            sys.path.insert(0, _p)


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "--runner":
        flow = argv[1] if len(argv) > 1 else None
        from workflow_runner import run as run_runner
        run_runner(flow)
    elif argv and argv[0] == "--designer":
        flow = argv[1] if len(argv) > 1 else None
        from workflow_designer import run as run_designer
        run_designer(flow)
    else:
        import workflow_hub
        workflow_hub.run()


if __name__ == "__main__":
    main()
