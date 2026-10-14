"""UI copy is English (docs/PRODUCT.md): no Vietnamese in web UI string literals.

Comments may stay in either language; anything quoted in apps/web — labels,
titles, toasts, dialog text — is what the operator reads.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIETNAMESE = re.compile(
    r"[ăâđêôơưàảãáạằẳẵắặầẩẫấậèẻẽéẹềểễếệìỉĩíịòỏõóọồổỗốộờởỡớợùủũúụừửữứựỳỷỹýỵ]", re.I)
LITERAL = re.compile(r"([\"'`])((?:\.|(?!\1).)*)\1")


def ui_literals(path: Path):
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(("//", "<!--", "*", "/*")):
            continue
        code = re.sub(r"(^|[^:])//.*$", r"\1", line)     # trailing comment, not a URL
        for match in LITERAL.finditer(code):
            yield number, match.group(2)


class UiLanguageTests(unittest.TestCase):
    def test_web_ui_strings_are_english(self):
        files = [*ROOT.glob("apps/web/**/*.js"), *ROOT.glob("apps/web/**/*.html")]
        offenders = [f"{path.relative_to(ROOT)}:{number}: {text[:80]}"
                     for path in files for number, text in ui_literals(path)
                     if VIETNAMESE.search(text)]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
