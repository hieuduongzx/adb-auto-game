"""
Convenience entrypoint that delegates to ``launcher.py``.

Kept for backward compatibility. Prefer ``python launcher.py`` going forward.
"""
import sys

from launcher import main

if __name__ == "__main__":
    sys.exit(main())
