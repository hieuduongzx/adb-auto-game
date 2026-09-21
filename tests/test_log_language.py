import ast
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
PYTHON_ROOTS = (ROOT / "src", ROOT / "apps")
WEB_ROOT = ROOT / "apps" / "web"
VIETNAMESE = re.compile(
    r"[ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯ"
    r"àáâãèéêìíòóôõùúăđĩũơư"
    r"Ạ-ỹ]"
)
LOG_CALLS = {
    "log_debug", "log_info", "log_success", "log_warning", "log_error",
}


def _literal_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
    return ""


def test_python_runtime_logs_are_english():
    violations = []
    for root in PYTHON_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                name = node.func.id if isinstance(node.func, ast.Name) else ""
                if name in LOG_CALLS and VIETNAMESE.search(_literal_text(node.args[0])):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not violations, "Vietnamese runtime logs:\n" + "\n".join(violations)


def test_web_status_messages_are_english():
    call_pattern = re.compile(r"(?:setStatus|appendLog)\s*\(([^\n;]+)")
    violations = []
    for path in WEB_ROOT.rglob("*.js"):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if call_pattern.search(line) and VIETNAMESE.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert not violations, "Vietnamese web status messages:\n" + "\n".join(violations)
