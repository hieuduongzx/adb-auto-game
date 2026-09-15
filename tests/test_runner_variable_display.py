"""Exercise Runner variable methods without starting its native window/devices."""
import ast
import copy
import threading
import unittest
from pathlib import Path


source = ast.parse((Path(__file__).parents[1] / "apps/workflow_runner.py").read_text(encoding="utf-8"))
names = {"_apply_runner_config", "_activities_payload", "set_activity_var"}
methods = [node for cls in source.body if isinstance(cls, ast.ClassDef)
           for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
namespace = {"List": list, "CAPTURE_BACKENDS": ()}
exec(compile(ast.Module(body=methods, type_ignores=[]), "workflow_runner.py", "exec"), namespace)


class RunnerVariableDisplayTests(unittest.TestCase):
    def runner(self, value="Normal", saved=None):
        class Runner:
            _apply_runner_config = namespace["_apply_runner_config"]
            _activities_payload = namespace["_activities_payload"]
            set_activity_var = namespace["set_activity_var"]

            def _runtime_settings_for_activity(self, activity):
                return []

            def _graph_nodes(self):
                return []

            def _activity_runner_config(self, activity_id):
                return self._runner_config.setdefault("activities", {}).setdefault(activity_id, {})

            def _save_runner_config(self):
                self.saved = copy.deepcopy(self._runner_config)

        runner = Runner()
        runner.flow = {"activities": [{"id": "act", "vars": [{"name": "difficulty", "type": "select",
            "display": "toggle-group", "value": value, "options": ["Easy", "Normal", "Hard"]}]}]}
        runner._runner_config = saved or {}
        runner._runner_config_lock = threading.RLock()
        return runner

    def test_payload_carries_display_and_selected_value(self):
        var = self.runner()._activities_payload()[0]["vars"][0]
        self.assertEqual(var["display"], "toggle-group")
        self.assertEqual(var["value"], "Normal")

    def test_choice_is_saved_and_restored(self):
        runner = self.runner()
        self.assertTrue(runner.set_activity_var("act", "difficulty", "Hard"))
        restored = self.runner(saved=runner.saved)
        restored._apply_runner_config()
        self.assertEqual(restored.flow["activities"][0]["vars"][0]["value"], "Hard")

    def test_invalid_choice_cannot_clear_selection(self):
        runner = self.runner()
        self.assertFalse(runner.set_activity_var("act", "difficulty", "removed"))
        self.assertEqual(runner.flow["activities"][0]["vars"][0]["value"], "Normal")

    def test_multiple_choices_save_restore_and_allow_empty(self):
        runner = self.runner()
        var = runner.flow["activities"][0]["vars"][0]
        var["multiple"] = True
        self.assertTrue(runner.set_activity_var("act", "difficulty", ["Easy", "Hard"]))
        runner._apply_runner_config()
        self.assertEqual(var["value"], ["Easy", "Hard"])
        self.assertTrue(runner._activities_payload()[0]["vars"][0]["multiple"])
        self.assertFalse(runner.set_activity_var("act", "difficulty", ["missing"]))
        self.assertFalse(runner.set_activity_var("act", "difficulty", "Easy"))
        self.assertTrue(runner.set_activity_var("act", "difficulty", []))

    def test_dropdown_never_accepts_multiple_even_with_stale_flag(self):
        runner = self.runner()
        var = runner.flow["activities"][0]["vars"][0]
        var.update(display="dropdown", multiple=True, value=["Normal", "Hard"])
        runner._apply_runner_config()
        self.assertEqual(var["value"], "Normal")
        self.assertFalse(runner.set_activity_var("act", "difficulty", ["Easy", "Hard"]))
        self.assertTrue(runner.set_activity_var("act", "difficulty", "Hard"))

    def test_engine_keeps_choices_as_list_and_checks_whole_options(self):
        tree = ast.parse((Path(__file__).parents[1] / "src/workflow/engine.py").read_text(encoding="utf-8"))
        methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
                   for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {"_seed_var", "_compare", "_resolve_value", "_a_set_var", "_coerce"}]
        scope = {"Dict": dict, "Any": object, "log_info": lambda message: None}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "engine.py", "exec"), scope)
        engine = type("Engine", (), {name: scope[name] for name in ("_seed_var", "_compare", "_resolve_value", "_a_set_var", "_coerce")})()
        values = {}
        engine._seed_var({"name": "mode", "type": "select", "display": "toggle-group", "multiple": True,
                          "options": ["Hard", "Very Hard"], "value": ["Very Hard"]}, values)
        self.assertEqual(values["mode"], ["Very Hard"])
        self.assertFalse(engine._compare(values["mode"], "contains", "Hard"))
        self.assertTrue(engine._compare(values["mode"], "contains", "Very Hard"))
        engine._vars = values
        engine._set_var = lambda name, value: values.update({name: value})
        engine._a_set_var({}, {"name": "mode", "value": ["Hard", "Very Hard"]})
        self.assertEqual(values["mode"], ["Hard", "Very Hard"])
        self.assertTrue(engine._compare(values["mode"], "contains", "Hard"))
        self.assertTrue(engine._compare(values["mode"], "==", ["Hard", "Very Hard"]))
        engine._a_set_var({}, {"name": "mode", "value": []})
        self.assertEqual(values["mode"], [])

    def test_invalid_default_and_stale_saved_choice_fall_back(self):
        for saved in ({}, {"activities": {"act": {"vars": {"difficulty": "removed"}}}}):
            runner = self.runner(value="removed", saved=saved)
            runner._apply_runner_config()
            self.assertEqual(runner.flow["activities"][0]["vars"][0]["value"], "Easy")


if __name__ == "__main__":
    unittest.main()
