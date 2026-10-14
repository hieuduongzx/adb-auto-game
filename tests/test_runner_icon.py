"""Test icon identity without starting WebView or connecting devices."""
import ast
import os
import unittest

from runner_source import runner_methods


class RunnerIconTests(unittest.TestCase):
    def icon_key(self, path="", info=None):
        methods = runner_methods("_icon_key")
        namespace = {"os": os}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "runner", "exec"), namespace)
        runner = type("Runner", (), {"_icon_key": namespace["_icon_key"]})()
        runner.flow_path = path
        runner._runner_info = info or {}
        return runner._icon_key()

    def test_hub_workflow_uses_parent_folder(self):
        self.assertEqual(self.icon_key(os.path.join("workflows", "GirlWars", "GirlWars.json")), "GirlWars")

    def test_packaged_runner_prefers_build_folder(self):
        self.assertEqual(self.icon_key("workflow.json", {"folder": "BrownDust2"}), "BrownDust2")

    def test_no_workflow_has_empty_key(self):
        self.assertEqual(self.icon_key(), "")


if __name__ == "__main__":
    unittest.main()
