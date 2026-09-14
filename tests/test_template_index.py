"""Tests for the Template Library's usage index (apps/workflow_designer.py).

The scan is pure — it pairs a flow dict with a list of files — so it can be
tested against a fixture rather than a real workflow folder. The numbers are
cross-checked against the GirlWars project separately; what matters here is
that every reference shape the editor can produce is recognised.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.workflow_designer import (  # noqa: E402
    _norm_tpl,
    build_template_index,
    iter_template_refs,
)


def _flow():
    """One activity and one function, covering all four reference shapes."""
    return {
        "activities": [{
            "id": "a1", "name": "Đánh boss",
            "graph": {"nodes": [
                {"id": "n1", "type": "tap_image", "params": {"template": "templates/btn.png"}},
                {"id": "n2", "type": "find_any",
                 "params": {"templates": ["templates/a.png", "templates/b.png"]}},
                {"id": "n3", "type": "tap", "params": {"x": 1, "y": 2}},
            ]},
        }],
        "functions": [{
            "id": "f1", "name": "wait_loading",
            "graph": {"nodes": [
                {"id": "n4", "type": "tap_image", "params": {"template": "templates/btn.png"}},
            ]},
        }],
    }


def _files(*names):
    return [{"name": n, "path": "workflows/X/templates/" + n, "size": 10,
             "w": 4, "h": 4} for n in names]


class TestNormTpl(unittest.TestCase):
    def test_collapses_to_basename(self):
        for raw in ("templates/btn.png", "templates\\btn.png",
                    "C:/proj/out/btn.png", "btn.png"):
            self.assertEqual(_norm_tpl(raw), "btn.png", raw)

    def test_case_insensitive(self):
        self.assertEqual(_norm_tpl("Templates/BTN.PNG"), "btn.png")

    def test_empty(self):
        self.assertEqual(_norm_tpl(None), "")
        self.assertEqual(_norm_tpl(""), "")


class TestIterTemplateRefs(unittest.TestCase):
    def test_finds_every_shape(self):
        refs = list(iter_template_refs(_flow()))
        # btn.png ×2 (activity + function), a.png, b.png
        self.assertEqual(len(refs), 4)

    def test_scalar_and_list_positions(self):
        scalars = [r for r in iter_template_refs(_flow()) if r[4] is None]
        listed = [r for r in iter_template_refs(_flow()) if r[4] is not None]
        self.assertEqual(len(scalars), 2)
        self.assertEqual(sorted(r[4] for r in listed), [0, 1])

    def test_list_index_points_at_the_right_value(self):
        for node, _k, _o, pk, idx, raw in iter_template_refs(_flow()):
            if idx is not None:
                self.assertEqual(node["params"][pk][idx], raw)

    def test_skips_empty_and_none(self):
        flow = {"activities": [{"id": "a", "graph": {"nodes": [
            {"id": "n", "type": "tap_image", "params": {"template": ""}},
            {"id": "m", "type": "find_any", "params": {"templates": [None, ""]}},
        ]}}]}
        self.assertEqual(list(iter_template_refs(flow)), [])

    def test_tolerates_broken_shapes(self):
        for flow in ({}, {"activities": None}, {"activities": [{}]},
                     {"activities": [{"graph": None}]},
                     {"activities": [{"graph": {"nodes": None}}]},
                     {"activities": [{"graph": {"nodes": [{"params": "nope"}]}}]}):
            self.assertEqual(list(iter_template_refs(flow)), [])


class TestBuildTemplateIndex(unittest.TestCase):
    def test_counts(self):
        idx = build_template_index(_flow(), _files("btn.png", "a.png", "b.png", "dead.png"))
        self.assertEqual(idx["counts"]["total"], 4)
        self.assertEqual(idx["counts"]["used"], 3)
        self.assertEqual(idx["counts"]["orphan"], 1)
        self.assertEqual(idx["counts"]["refs"], 4)
        self.assertEqual(idx["counts"]["missing"], 0)

    def test_usage_names_the_owning_activity_and_node(self):
        idx = build_template_index(_flow(), _files("btn.png"))
        btn = idx["templates"][0]
        self.assertEqual(btn["usedCount"], 2)
        owners = {(u["ownerKind"], u["activity"]) for u in btn["used"]}
        self.assertEqual(owners, {("activity", "Đánh boss"), ("function", "wait_loading")})
        self.assertEqual({u["nodeId"] for u in btn["used"]}, {"n1", "n4"})
        self.assertEqual({u["nodeLabel"] for u in btn["used"]}, {"Chạm ảnh"})

    def test_missing_reference_is_reported_not_counted_as_orphan(self):
        # btn.png is referenced but absent from the folder: that node will fail
        # at run time, so it must surface as `missing`, never silently vanish.
        idx = build_template_index(_flow(), _files("a.png", "b.png"))
        self.assertEqual(idx["counts"]["missing"], 2)
        self.assertEqual({m["nodeId"] for m in idx["missing"]}, {"n1", "n4"})
        self.assertTrue(all(m["name"] == "btn.png" for m in idx["missing"]))
        self.assertEqual(idx["counts"]["orphan"], 0)

    def test_subfolder_paths_still_match(self):
        # Assets can sit in a per-package subfolder; the basename is the key.
        idx = build_template_index(_flow(), _files("pkg/btn.png"))
        self.assertEqual(idx["templates"][0]["usedCount"], 2)

    def test_empty_folder_lists_every_reference_as_missing(self):
        idx = build_template_index(_flow(), [])
        self.assertEqual(idx["counts"]["total"], 0)
        self.assertEqual(idx["counts"]["missing"], 4)

    def test_no_references_means_everything_is_an_orphan(self):
        idx = build_template_index({"activities": []}, _files("x.png", "y.png"))
        self.assertEqual(idx["counts"]["orphan"], 2)
        self.assertEqual(idx["counts"]["used"], 0)


if __name__ == "__main__":
    unittest.main()
