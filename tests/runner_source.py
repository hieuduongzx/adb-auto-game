"""Find Runner API methods in source, wherever the class keeps them.

WorkflowRunnerAPI is assembled from mixins (apps/runner/*.py). Tests that
exercise a method without building the whole Runner exec it out of the source;
this collects the method from whichever file defines it.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_FILES = [ROOT / "apps" / "workflow_runner.py", *sorted((ROOT / "apps" / "runner").glob("*.py"))]


def runner_source() -> str:
    """Every Runner source file, concatenated (for text assertions)."""
    return "\n".join(path.read_text(encoding="utf-8") for path in RUNNER_FILES)


def runner_methods(*names):
    """The ``ast.FunctionDef`` of each named Runner method, in *names* order."""
    found = {}
    for path in RUNNER_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for node in cls.body:
                if isinstance(node, ast.FunctionDef) and node.name in names:
                    found.setdefault(node.name, node)
    missing = [name for name in names if name not in found]
    assert not missing, f"Runner methods not found: {missing}"
    return [found[name] for name in names]
