import unittest
from unittest import mock

from src.workflow import engine as E


class TestTextPatterns(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(E, 'ADBGameAutomation'):
            self.engine = E.WorkflowEngine()
        self.engine._ensure_ready = mock.Mock(return_value=True)
        self.engine._sleep = mock.Mock()

    # ── shared extraction helper ────────────────────────────────────────────

    def test_apply_pattern_returns_the_capture_group(self):
        self.assertEqual(
            self.engine._apply_pattern("ROUND 5/10", r"(\d+)/(\d+)", 2), "10")

    def test_apply_pattern_without_pattern_returns_the_whole_text(self):
        self.assertEqual(self.engine._apply_pattern("  hello  ", "", 1), "hello")

    def test_apply_pattern_without_a_match_is_empty(self):
        self.assertEqual(self.engine._apply_pattern("ROUND FIVE", r"\d+", 1), "")

    def test_apply_pattern_with_an_out_of_range_group_falls_back_to_group_zero(self):
        self.assertEqual(
            self.engine._apply_pattern("ROUND 5/10", r"\d+/\d+", 9), "5/10")

    def test_apply_pattern_with_an_invalid_regex_is_none(self):
        self.assertIsNone(self.engine._apply_pattern("anything", "(", 1))

    # ── reader nodes ────────────────────────────────────────────────────────

    def test_read_var_extracts_the_pattern_group_into_the_variable(self):
        self.engine.auto.read_text.return_value = "ROUND 5/10"

        self.assertTrue(self.engine._a_read_var({}, {
            "name": "round", "pattern": r"(\d+)/\d+", "group": 1,
        }))

        self.assertEqual(self.engine._vars["round"], 5)

    def test_read_var_without_pattern_keeps_the_whole_recognised_text(self):
        self.engine.auto.read_text.return_value = "  ROUND 5/10 "

        self.engine._a_read_var({}, {"name": "raw"})

        self.assertEqual(self.engine._vars["raw"], "ROUND 5/10")

    def test_read_var_with_an_invalid_regex_stores_empty_instead_of_crashing(self):
        self.engine.auto.read_text.return_value = "ROUND 5/10"

        self.assertTrue(self.engine._a_read_var({}, {"name": "bad", "pattern": "("}))

        self.assertEqual(self.engine._vars["bad"], "")

    def test_adb_shell_extracts_the_pattern_group_from_stdout(self):
        self.engine.auto.adb.device = mock.Mock()
        self.engine.auto.adb.device.shell.return_value = "noise\n5/10\n"

        self.assertTrue(self.engine._a_adb_shell({}, {
            "command": "dumpsys", "name": "ratio",
            "pattern": r"(\d+)/\d+", "group": 1,
        }))

        self.assertEqual(self.engine._vars["ratio"], 5)

    def test_format_var_extracts_the_pattern_group_from_the_formatted_string(self):
        self.engine._vars.update({"round": 3, "total": 5})

        self.engine._a_format_var({}, {
            "name": "label", "template": "Round {round}/{total}",
            "pattern": r"Round (\d+)/", "group": 1,
        })

        self.assertEqual(self.engine._vars["label"], "3")

    def test_win_info_extracts_the_pattern_group_from_the_property(self):
        self.engine._controller = "win32"
        self.engine.auto.adb.window_info.return_value = {"title": "Game v1.2.3"}

        self.engine._a_win_info({}, {
            "name": "version", "prop": "title",
            "pattern": r"v(\d+\.\d+\.\d+)", "group": 1,
        })

        self.assertEqual(self.engine._vars["version"], "1.2.3")

    def test_parse_var_still_extracts_after_sharing_the_helper(self):
        self.engine._vars["src"] = "ROUND 7/10"

        self.assertTrue(self.engine._a_parse_var({}, {
            "name": "out", "source": "var", "fromVar": "src",
            "pattern": r"(\d+)/\d+", "group": 1,
        }))

        self.assertEqual(self.engine._vars["out"], 7)

    # ── OCR match nodes ─────────────────────────────────────────────────────

    def test_if_text_pattern_mode_asks_ocr_for_a_regex_match(self):
        self.engine.auto.region_find_text.return_value = (True, "ROUND 5/10")

        self.assertTrue(self.engine._eval_condition("if_text", {
            "match": "pattern", "pattern": r"\d+/\d+",
            "x": 0, "y": 0, "w": 200, "h": 80,
        }))

        self.engine.auto.region_find_text.assert_called_once_with(
            r"\d+/\d+", region=(0, 0, 200, 80), whitelist=None, regex=True)

    def test_if_text_defaults_to_a_literal_substring_match(self):
        self.engine.auto.region_find_text.return_value = (True, "ROUND 5/10")

        self.assertTrue(self.engine._eval_condition("if_text", {
            "text": "5/10", "x": 0, "y": 0, "w": 200, "h": 80,
        }))

        self.engine.auto.region_find_text.assert_called_once_with(
            "5/10", region=(0, 0, 200, 80), whitelist=None, regex=False)

    def test_tap_text_pattern_mode_taps_when_the_regex_matches(self):
        self.engine.auto.region_find_text.return_value = (True, "ROUND 5/10")

        self.assertTrue(self.engine._eval_condition("tap_text", {
            "match": "pattern", "pattern": r"\d+/\d+", "text": "",
            "x": 100, "y": 200, "w": 300, "h": 80, "timeout": 0,
        }))

        self.engine.auto.region_find_text.assert_called_once_with(
            r"\d+/\d+", region=(100, 200, 300, 80), whitelist=None, regex=True)
        self.engine.auto.tap.assert_called_once_with(250, 240, tap_count=1)

    def test_wait_text_pattern_mode_negate_returns_when_it_disappears(self):
        self.engine.auto.ocr.available = True
        self.engine.auto.region_find_text.return_value = (False, "nothing here")

        self.assertTrue(self.engine._eval_condition("wait_text", {
            "match": "pattern", "pattern": r"\d+/\d+", "negate": True,
            "x": 0, "y": 0, "w": 200, "h": 80, "timeout": 0,
        }))

        self.engine.auto.region_find_text.assert_called_once_with(
            r"\d+/\d+", region=(0, 0, 200, 80), whitelist=None, regex=True)

    def test_loop_until_text_pattern_mode_probes_with_a_regex(self):
        self.engine.auto.region_find_text.return_value = (True, "BATTLE 12")

        self.assertTrue(self.engine._loop_until_hit("loop_until_text", {
            "match": "pattern", "pattern": r"BATTLE \d+",
            "x": 0, "y": 0, "w": 200, "h": 80,
        }))

        self.engine.auto.region_find_text.assert_called_once_with(
            r"BATTLE \d+", region=(0, 0, 200, 80), whitelist=None, regex=True)


if __name__ == "__main__":
    unittest.main()
