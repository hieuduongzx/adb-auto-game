"""Internal bootstrap for the Designer + Runner build option (no Hub)."""
import os
import sys

if not getattr(sys, 'frozen', False):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path[:0] = [root, os.path.join(root, 'apps')]


def main():
    from src.utils import unblock_bundled_files
    unblock_bundled_files()
    args = sys.argv[1:]
    if args and args[0] == '--runner':
        from workflow_runner import run
        run(args[1] if len(args) > 1 else None)
    else:
        from workflow_designer import run
        if args and args[0] == '--designer':
            args = args[1:]
        run(args[0] if args else None)


if __name__ == '__main__':
    main()
