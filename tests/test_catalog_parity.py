"""The engine catalog and the Designer's node catalog describe the same blocks.

Engine labels reach the user through crash markers and log lines ("Failed — at
Tap image"), so they must read exactly like the block names in the Designer.
"""
import re
import unittest
from pathlib import Path

from src.workflow.catalog import NODE_TYPES

ROOT = Path(__file__).resolve().parents[1]


def designer_nodes():
    js = (ROOT / "apps/web/wf/js/workflow.js").read_text(encoding="utf-8")
    body = js[js.index("const WF_NODES = {"):]
    rows = re.findall(r'^\s{2}"?(\w+)"?\s*:\s*\{label:"([^"]+)",.*?kind:"(\w+)"', body, re.M)
    return {key: (label, kind) for key, label, kind in rows}


class CatalogParityTests(unittest.TestCase):
    def test_same_node_types(self):
        self.assertEqual(sorted(designer_nodes()), sorted(NODE_TYPES))

    def test_labels_match_designer(self):
        for key, (label, _kind) in designer_nodes().items():
            with self.subTest(node=key):
                self.assertEqual(NODE_TYPES[key]["label"], label)

    def test_kinds_match_designer(self):
        for key, (_label, kind) in designer_nodes().items():
            with self.subTest(node=key):
                self.assertEqual(NODE_TYPES[key]["kind"], kind)


if __name__ == "__main__":
    unittest.main()
