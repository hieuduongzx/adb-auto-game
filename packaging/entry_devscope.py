"""Frozen entry point for ``DevScope.exe`` (device inspector app).

Not included in the default ``apps_build.spec`` (Workflow2k-only packaging).
Kept so DevScope can be re-added to the build without rewiring imports.
"""
from __future__ import annotations

import os
import sys

if not getattr(sys, "frozen", False):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (_ROOT, os.path.join(_ROOT, "apps")):
        if _p not in sys.path:
            sys.path.insert(0, _p)


def main() -> None:
    import devscope
    out_dir = sys.argv[1] if len(sys.argv) > 1 else None
    devscope.run(out_dir)


if __name__ == "__main__":
    main()
