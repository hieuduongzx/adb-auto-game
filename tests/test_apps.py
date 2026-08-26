"""Smoke tests: every app module must import cleanly (catches broken imports
after refactors) and the Runner's per-workflow config path must be unique per
workflow name."""
import os
import unittest

from tests._loader import load_app_module


class TestAppImports(unittest.TestCase):
    def test_adb_tool_imports(self):
        load_app_module("adb_tool_under_test", "adb_tool.py")

    def test_devscope_imports(self):
        mod = load_app_module("devscope_under_test", "devscope.py")
        self.assertTrue(hasattr(mod.DevScopeAPI, "_info_worker"))

    def test_workflow_hub_imports(self):
        load_app_module("workflow_hub_smoke", "workflow_hub.py")

    def test_workflow_runner_imports(self):
        load_app_module("workflow_runner_under_test", "workflow_runner.py")

    def test_workflow_designer_imports(self):
        mod = load_app_module("workflow_designer_under_test",
                              "workflow_designer.py")
        self.assertTrue(hasattr(mod.WorkflowDesignerAPI, "match_template"))


class TestRunnerConfigPath(unittest.TestCase):
    def test_distinct_names_distinct_paths(self):
        runner = load_app_module("workflow_runner_slug", "workflow_runner.py")
        api_cls = runner.WorkflowRunnerAPI
        # _config_path_for_flow only uses its arguments + data_root(), so it
        # can be exercised without constructing the API/engine.
        a = api_cls._config_path_for_flow(None, {"name": "A B"}, "a.json")
        b = api_cls._config_path_for_flow(None, {"name": "A_B"}, "b.json")
        self.assertNotEqual(os.path.normcase(a), os.path.normcase(b))
        # Same name → same path (stable across runs).
        a2 = api_cls._config_path_for_flow(None, {"name": "A B"}, "x.json")
        self.assertEqual(os.path.normcase(a), os.path.normcase(a2))
        # Unnamed flow falls back to the file stem.
        c = api_cls._config_path_for_flow(None, {}, r"C:\wf\My Flow.json")
        self.assertIn("My_Flow_", c)


if __name__ == "__main__":
    unittest.main()
