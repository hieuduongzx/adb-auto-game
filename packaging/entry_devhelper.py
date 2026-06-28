"""Frozen entry point for ``dev_helper.exe`` (the Dev Helper tool)."""
from __future__ import annotations

import os
import sys

if not getattr(sys, "frozen", False):
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _p in (_ROOT, os.path.join(_ROOT, "tools")):
        if _p not in sys.path:
            sys.path.insert(0, _p)


def main() -> None:
    import dev_helper
    out_dir = sys.argv[1] if len(sys.argv) > 1 else None
    dev_helper.run(out_dir)


if __name__ == "__main__":
    main()
