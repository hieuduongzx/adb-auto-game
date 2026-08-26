"""Shared helpers for the test suite (stdlib only)."""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def load_app_module(module_name: str, filename: str):
    """Import an ``apps/*.py`` script by file path (they aren't a package).

    The app modules bootstrap ``src.*`` themselves, but the project root must
    already be importable — guaranteed by the sys.path insert above.
    """
    path = os.path.join(ROOT, "apps", filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
