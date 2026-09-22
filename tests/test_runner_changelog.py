"""Release-note metadata used by the Runner changelog."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
_spec = importlib.util.spec_from_file_location(
    "build_runner_under_test", _ROOT / "packaging" / "build_runner.py")
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)
from src import runner_update as ru


class ReleaseNotesTests(unittest.TestCase):
    def test_authored_notes_keep_the_auto_show_flag(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        path = os.path.join(folder, "notes.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("## Changes\n\n- Faster start\n")
        body = br.compose_release_notes("Game", "1.2.0", path, True)
        self.assertTrue(body.startswith("<!-- macro2k-runner: "))
        markdown, auto = ru.split_release_notes(body)
        self.assertTrue(auto)
        self.assertIn("Faster start", markdown)
        self.assertNotIn("macro2k-runner", markdown)

    def test_empty_notes_use_the_default_and_stay_quiet(self):
        body = br.compose_release_notes("Game", "1.0.22", "", True)
        markdown, auto = ru.split_release_notes(body)
        self.assertFalse(auto)
        self.assertEqual(markdown, "Standalone Runner for Game, version 1.0.22.")

    def test_bad_metadata_does_not_auto_show(self):
        markdown, auto = ru.split_release_notes('<!-- macro2k-runner: {"autoShow":"yes"} -->\n\nHello')
        self.assertFalse(auto)
        self.assertEqual(markdown, "Hello")

    def test_history_keeps_this_runners_releases_newest_first(self):
        rows = ru.normalize_releases([
            {"tag_name": "runner-Game-v1.0.0", "body": "old", "draft": False, "html_url": "https://github.com/o/r/releases/tag/a", "published_at": "2026-01-01"},
            {"tag_name": "runner-Other-v9.0.0", "body": "nope", "draft": False},
            {"tag_name": "runner-Game-v1.2.0", "draft": True, "body": "draft"},
            {"tag_name": "runner-Game-v1.1.0", "body": '<!-- macro2k-runner: {"autoShow":true} -->\n\nnewer', "draft": False, "html_url": "https://github.com/o/r/releases/tag/b", "published_at": "2026-02-01"},
        ], "runner-Game-v")
        self.assertEqual([row["version"] for row in rows], ["1.1.0", "1.0.0"])
        self.assertTrue(rows[0]["autoShow"])
        self.assertEqual(rows[0]["markdown"], "newer")
        self.assertEqual(json.loads(json.dumps(rows[0]))["page"].startswith("https://"), True)
