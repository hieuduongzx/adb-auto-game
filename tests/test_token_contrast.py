"""WCAG contrast of the shared colour tokens, in both themes.

Parses apps/web/shared/tokens.css (the light :root block and the dark
override), resolves var() references, blends translucent tints over the panel
colour they sit on, and checks every text/background pairing the suite uses.
Pure Python, so it runs in CI next to the rest of the regression suite.
"""
import re
import unittest
from pathlib import Path

TOKENS = Path(__file__).resolve().parents[1] / "apps" / "web" / "shared" / "tokens.css"

# (foreground, background, minimum ratio)
PAIRS = [
    ("--ink", "--bg", 4.5), ("--ink", "--panel", 4.5),
    ("--dim", "--panel", 4.5), ("--dim", "--bg", 4.5),
    ("--muted", "--panel", 4.5), ("--muted", "--bg", 4.5),
    ("--muted", "--surface", 4.5), ("--muted", "--alt", 4.5),
    ("--accent", "--panel", 4.5), ("--accent", "--bg", 4.5), ("--accent", "--accent-bg", 4.5),
    ("--accent-hover", "--accent-bg", 4.5), ("--accent-soft", "--accent-bg", 3.0),
    ("--on-accent", "--accent", 4.5), ("--on-ok", "--ok", 4.5), ("--on-err", "--err", 4.5),
    ("--ok-ink", "--ok-bg", 4.5), ("--ok", "--panel", 4.5),
    ("--warn", "--warn-bg", 4.5), ("--warn", "--panel", 4.5),
    ("--err", "--err-bg", 4.5), ("--err", "--panel", 4.5),
    ("--win32", "--win32-bg", 4.5),
    ("--log-ink", "--log-bg", 4.5), ("--log-muted", "--log-bg", 4.5),
]


def _block(css, selector):
    start = css.index(selector + " {")
    return css[start:css.index("\n}", start)]


def _decls(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", re.sub(r"/\*.*?\*/", "", block, flags=re.S)))


def _rgba(value, table, depth=0):
    value = value.strip()
    ref = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if ref:
        assert depth < 10, value
        return _rgba(table[ref.group(1)], table, depth + 1)
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (1.0,)
    m = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    assert m, f"unsupported colour {value!r}"
    parts = [p.strip() for p in m.group(1).split(",")]
    return tuple(float(p) for p in parts[:3]) + ((float(parts[3]) if len(parts) > 3 else 1.0),)


def _over(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def _lum(c):
    def ch(x):
        x /= 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


class TokenContrastTests(unittest.TestCase):
    def setUp(self):
        css = TOKENS.read_text(encoding="utf-8")
        self.light = _decls(_block(css, ":root"))
        self.dark = dict(self.light, **_decls(_block(css, ':root[data-theme="dark"]')))

    def _check(self, table, theme):
        panel = _rgba(table["--panel"], table)
        failures = []
        for fg_name, bg_name, minimum in PAIRS:
            bg = _over(_rgba(table[bg_name], table), panel)
            fg = _over(_rgba(table[fg_name], table), bg)
            ratio = _ratio(fg, bg)
            if ratio < minimum:
                failures.append(f"{theme}: {fg_name} on {bg_name} = {ratio:.2f} < {minimum}")
        self.assertEqual(failures, [])

    def test_light_theme_text_pairs_meet_contrast_minimums(self):
        self._check(self.light, "light")

    def test_dark_theme_text_pairs_meet_contrast_minimums(self):
        self._check(self.dark, "dark")


if __name__ == "__main__":
    unittest.main()
