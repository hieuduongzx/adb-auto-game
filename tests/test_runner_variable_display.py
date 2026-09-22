"""Exercise Runner variable methods without starting its native window/devices."""
import ast
import copy
import threading
import unittest
from pathlib import Path


source = ast.parse((Path(__file__).parents[1] / "apps/workflow_runner.py").read_text(encoding="utf-8"))
names = {"_apply_runner_config", "_activities_payload", "set_activity_var",
         "_each_activity_var", "_var_payload"}
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
            _each_activity_var = namespace["_each_activity_var"]
            _var_payload = namespace["_var_payload"]

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
                   for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in {"_seed_var", "_compare", "_resolve_value", "_a_set_var", "_coerce", "_truthy"}]
        scope = {"Dict": dict, "Any": object, "log_info": lambda message: None}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "engine.py", "exec"), scope)
        engine = type("Engine", (), {name: scope[name] for name in ("_seed_var", "_compare", "_resolve_value", "_a_set_var", "_coerce", "_truthy")})()
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
        values.clear()
        engine._seed_var({"name": "mode", "type": "select", "value": "Hard", "options": ["Easy", "Hard"],
                          "children": [{"name": "shared", "type": "bool", "value": True}],
                          "optionChildren": {
                              "Easy": [{"name": "lives", "type": "number", "value": 3}],
                              "Hard": [{"name": "lives", "type": "number", "value": 1}],
                          }}, values)
        self.assertEqual(values["mode"], "Hard")
        self.assertIs(values["mode.shared"], True)
        self.assertNotIn("mode.Easy.lives", values)
        self.assertEqual(values["mode.Hard.lives"], 1)
        values.clear()
        engine._seed_var({"name": "mode", "type": "select", "display": "toggle-group", "multiple": True,
                          "value": ["Easy", "Hard"], "options": ["Easy", "Hard"],
                          "optionChildren": {
                              "Easy": [{"name": "lives", "type": "number", "value": 3}],
                              "Hard": [{"name": "lives", "type": "number", "value": 1}],
                          }}, values)
        self.assertEqual(values["mode.Easy.lives"], 3)
        self.assertEqual(values["mode.Hard.lives"], 1)

    def test_changing_a_select_swaps_its_option_children(self):
        tree = ast.parse((Path(__file__).parents[1] / "src/workflow/engine.py").read_text(encoding="utf-8"))
        wanted = {"_seed_var", "_set_var", "_sync_option_children", "_select_defs", "_coerce", "_truthy"}
        methods = [node for cls in tree.body if isinstance(cls, ast.ClassDef)
                   for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        scope = {"Dict": dict, "List": list, "Any": object, "log_info": lambda message: None, "Optional": object}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "engine.py", "exec"), scope)
        engine = type("Engine", (), {name: scope[name] for name in wanted})()
        element = {"name": "element", "type": "select", "value": "Fire", "options": ["Fire", "Water"],
                   "optionChildren": {"Fire": [{"name": "dmg", "type": "number", "value": 3}],
                                      "Water": [{"name": "wet", "type": "bool", "value": True}]}}
        engine.flow = {"globals": [], "activities": [{"vars": [element]}]}
        engine._globals = {}
        engine._ctx = type("Ctx", (), {})()
        engine._emit = lambda *args: None
        engine._vars = {}
        engine._seed_var(element, engine._vars)
        engine._set_var("element", "Water")
        self.assertEqual(engine._vars["element"], "Water")
        self.assertNotIn("element.Fire.dmg", engine._vars)
        self.assertIs(engine._vars["element.Water.wet"], True)

    def test_option_child_saves_under_its_value(self):
        runner = self.runner()
        var = runner.flow["activities"][0]["vars"][0]
        var["optionChildren"] = {"Hard": [{"name": "lives", "type": "number", "value": 1}]}
        self.assertTrue(runner.set_activity_var("act", "difficulty.Hard.lives", 9))
        self.assertEqual(var["optionChildren"]["Hard"][0]["value"], 9)
        self.assertEqual(runner.saved["activities"]["act"]["vars"]["difficulty.Hard.lives"], 9)
        restored = self.runner(saved=runner.saved)
        restored.flow["activities"][0]["vars"][0]["optionChildren"] = {
            "Hard": [{"name": "lives", "type": "number", "value": 1}]}
        restored._apply_runner_config()
        self.assertEqual(restored.flow["activities"][0]["vars"][0]["optionChildren"]["Hard"][0]["value"], 9)
        payload = runner._activities_payload()[0]["vars"][0]
        self.assertEqual(payload["optionChildren"]["Hard"][0]["name"], "lives")
        self.assertEqual(payload["value"], "Normal")

    def test_invalid_default_and_stale_saved_choice_fall_back(self):
        for saved in ({}, {"activities": {"act": {"vars": {"difficulty": "removed"}}}}):
            runner = self.runner(value="removed", saved=saved)
            runner._apply_runner_config()
            self.assertEqual(runner.flow["activities"][0]["vars"][0]["value"], "Easy")


if __name__ == "__main__":
    unittest.main()
