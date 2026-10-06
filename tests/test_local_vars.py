"""Tests for the Designer's local (test) variable overrides (local_vars.json)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import local_vars


def _flow():
    return {
        "name": "T",
        "globals": [
            {"name": "isHome", "type": "bool", "value": True},
            {"name": "cfg", "type": "text", "value": "d",
             "children": [{"name": "speed", "type": "number", "value": 1}]},
        ],
        "activities": [{
            "id": "act_home",
            "vars": [
                {"name": "user", "type": "text", "value": "default"},
                {"name": "mode", "type": "select", "value": "A", "options": ["A", "B"],
                 "optionChildren": {"B": [{"name": "lives", "type": "number", "value": 3}]}},
            ],
        }],
    }


class LocalVarsTests(unittest.TestCase):
    def test_apply_overrides_globals_activity_and_nested(self):
        flow = _flow()
        data = {
            "globals": {"isHome": False, "cfg.speed": 9},
            "activities": {"act_home": {"user": "tester", "mode": "B", "mode.B.lives": 1}},
        }
        applied = local_vars.apply(flow, data)
        self.assertEqual(applied, 5)
        self.assertIs(flow["globals"][0]["value"], False)
        self.assertEqual(flow["globals"][1]["children"][0]["value"], 9)
        self.assertEqual(flow["activities"][0]["vars"][0]["value"], "tester")
        self.assertEqual(flow["activities"][0]["vars"][1]["value"], "B")
        self.assertEqual(flow["activities"][0]["vars"][1]["optionChildren"]["B"][0]["value"], 1)

    def test_unknown_keys_are_ignored(self):
        flow = _flow()
        applied = local_vars.apply(flow, {"globals": {"nope": 1},
                                          "activities": {"ghost": {"x": 1}}})
        self.assertEqual(applied, 0)
        self.assertIs(flow["globals"][0]["value"], True)

    def test_clean_drops_malformed(self):
        cleaned = local_vars.clean({"globals": "bad", "activities": {"a": 1, "b": {"x": 2}}})
        self.assertEqual(cleaned, {"globals": {}, "activities": {"b": {"x": 2}}})
        self.assertEqual(local_vars.clean(None), {"globals": {}, "activities": {}})

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow_path = str(Path(tmp) / "workflow.json")
            Path(flow_path).write_text("{}", encoding="utf-8")
            data = {"globals": {"a": 1}, "activities": {"act": {"b": "x"}}}
            self.assertTrue(local_vars.save(flow_path, data))
            sidecar = Path(tmp) / "local_vars.json"
            self.assertTrue(sidecar.is_file())
            self.assertEqual(json.loads(sidecar.read_text(encoding="utf-8"))["version"], 1)
            loaded = local_vars.load(flow_path)
            self.assertEqual(loaded["globals"], {"a": 1})
            self.assertEqual(loaded["activities"], {"act": {"b": "x"}})

    def test_load_missing_or_bad_returns_empty(self):
        self.assertEqual(local_vars.load(""), {})
        self.assertEqual(local_vars.load("Z:/nope/workflow.json"), {})


if __name__ == "__main__":
    unittest.main()
