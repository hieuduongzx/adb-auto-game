"""Pin the pure string parsers in ADBController (no device needed)."""
import unittest

from tests import _bootstrap  # noqa: F401
from src.core.adb.controller import (
    _extract_package_from_focus_line,
    ADBController,
)


class TestFocusLineParsing(unittest.TestCase):
    def test_extracts_package_from_focus_line(self):
        line = "  mCurrentFocus=Window{a1b2 u0 com.example.app/.MainActivity}"
        self.assertEqual(
            _extract_package_from_focus_line(line), "com.example.app"
        )

    def test_returns_none_without_slash(self):
        self.assertIsNone(_extract_package_from_focus_line("no slash here"))

    def test_returns_none_for_null_token(self):
        self.assertIsNone(
            _extract_package_from_focus_line("mCurrentFocus=null/")
        )

    def test_requires_dotted_package(self):
        # token before '/' has no dot -> not a package
        self.assertIsNone(_extract_package_from_focus_line("foo bar/Activity"))


class TestResolveActivityParsing(unittest.TestCase):
    def test_format_cmp_intent_line(self):
        out = (
            "PING Intent { act=android.intent.action.MAIN "
            "cmp=com.game.pkg/.Main }"
        )
        self.assertEqual(
            ADBController._parse_resolve_activity(out, "com.game.pkg"),
            "com.game.pkg/.Main",
        )

    def test_format_bare_component_line(self):
        out = "priority=0\ncom.game.pkg/com.game.pkg.MainActivity"
        self.assertEqual(
            ADBController._parse_resolve_activity(out, "com.game.pkg"),
            "com.game.pkg/com.game.pkg.MainActivity",
        )

    def test_empty_output(self):
        self.assertEqual(ADBController._parse_resolve_activity("", "x"), "")

    def test_no_match(self):
        self.assertEqual(
            ADBController._parse_resolve_activity("nothing useful", "com.x"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
