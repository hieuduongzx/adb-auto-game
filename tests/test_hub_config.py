"""Tests for WorkflowHubAPI pure helpers (autoclick config, workflow files)."""
import json
import os
import tempfile
import unittest

from tests._loader import load_app_module

hub = load_app_module("workflow_hub_under_test", "workflow_hub.py")


class TestNormaliseClickConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = hub.WorkflowHubAPI._normalise_click_config(None)
        self.assertEqual(cfg["intervalMs"], 250)
        self.assertTrue(cfg["infinite"])
        self.assertEqual(len(cfg["points"]), 1)

    def test_clamps_ranges(self):
        cfg = hub.WorkflowHubAPI._normalise_click_config({
            "intervalMs": -5, "startDelaySec": 99999, "count": 0,
        })
        self.assertEqual(cfg["intervalMs"], 10)
        self.assertEqual(cfg["startDelaySec"], 3600)
        self.assertEqual(cfg["count"], 1)

    def test_garbage_values_fall_back(self):
        cfg = hub.WorkflowHubAPI._normalise_click_config({
            "intervalMs": "abc", "count": None, "points": "nope",
        })
        self.assertEqual(cfg["intervalMs"], 250)
        self.assertEqual(cfg["count"], 100)
        self.assertEqual(len(cfg["points"]), 1)

    def test_point_normalisation_and_unique_ids(self):
        cfg = hub.WorkflowHubAPI._normalise_click_config({
            "points": [
                {"id": "bad id!", "x": "12.5", "y": -3,
                 "button": "middle", "clickType": "double"},
                {"id": "", "targetMode": "cursor"},
                {"id": "point-1"},   # duplicate id → renamed
            ],
        })
        ids = [p["id"] for p in cfg["points"]]
        self.assertEqual(len(ids), len(set(ids)))
        first = cfg["points"][0]
        self.assertEqual((first["x"], first["y"]), (12, -3))
        self.assertEqual(first["button"], "middle")
        self.assertEqual(first["clickType"], "double")
        second = cfg["points"][1]
        self.assertEqual(second["targetMode"], "cursor")

    def test_selected_point_must_exist(self):
        cfg = hub.WorkflowHubAPI._normalise_click_config({
            "selectedPointId": "ghost",
            "points": [{"id": "real"}],
        })
        self.assertEqual(cfg["selectedPointId"], "real")


class TestProfilePaths(unittest.TestCase):
    def test_profile_filename_sanitised(self):
        name = hub.WorkflowHubAPI._profile_filename('bad:name*?.json')
        self.assertIsNone(
            next((c for c in name if c in '<>:"/\\|?*'), None), name)

    def test_profile_path_blocks_traversal(self):
        self.assertIsNone(hub.WorkflowHubAPI._profile_path("..\\evil.json"))
        self.assertIsNone(hub.WorkflowHubAPI._profile_path("sub/dir/a.json"))
        self.assertIsNone(hub.WorkflowHubAPI._profile_path("a.txt"))
        got = hub.WorkflowHubAPI._profile_path("ok.json")
        self.assertIsNotNone(got)
        self.assertEqual(os.path.dirname(got),
                         os.path.abspath(hub._AUTOCLICKS_DIR))


class TestFindWorkflowJson(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="m2k_wf_")

    def _write(self, name):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}")
        return path

    def test_prefers_workflow_json(self):
        a = self._write("aaa.json")
        b = self._write("workflow.json")
        self.assertEqual(os.path.normcase(hub._find_workflow_json(self.dir)),
                         os.path.normcase(b))
        os.remove(a); os.remove(b)

    def test_then_folder_named_json(self):
        folder = os.path.join(tempfile.mkdtemp(prefix="m2k_proj_"), "MyGame")
        os.makedirs(folder)
        a = os.path.join(folder, "aaa.json")
        b = os.path.join(folder, "mygame.JSON")
        for p in (a, b):
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("{}")
        self.assertEqual(os.path.normcase(hub._find_workflow_json(folder)),
                         os.path.normcase(b))

    def test_empty_dir(self):
        self.assertIsNone(hub._find_workflow_json(self.dir))


class TestBlankFlow(unittest.TestCase):
    def test_shape_and_normalisation(self):
        flow = hub._blank_flow("Demo", controller="win32",
                               capture="adb", input_mode="weird")
        self.assertEqual(flow["controller"], "win32")
        self.assertEqual(flow["capture"], "adb")
        self.assertEqual(flow["win32"]["inputMode"], "background")
        self.assertEqual(flow["version"], 2)
        self.assertEqual(flow["activities"][0]["type"], "sequence")
        # Round-trips through JSON cleanly.
        json.loads(json.dumps(flow))


if __name__ == "__main__":
    unittest.main()
