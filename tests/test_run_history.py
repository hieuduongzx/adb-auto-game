"""Run history: one JSON line per finished run, newest first, bounded."""
import json
import os
import tempfile
import unittest
from unittest import mock

from src import run_history as RH


class RunHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "runner", "x", RH.HISTORY_FILE)

    def test_append_then_load_newest_first(self):
        for i in range(3):
            self.assertTrue(RH.append(self.path, {"end": i, "outcome": "completed"}))
        self.assertEqual([r["end"] for r in RH.load(self.path)], [2, 1, 0])
        self.assertEqual([r["end"] for r in RH.load(self.path, limit=2)], [2, 1])
        self.assertEqual(RH.last(self.path)["end"], 2)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(RH.load(self.path), [])
        self.assertIsNone(RH.last(self.path))
        self.assertTrue(RH.clear(self.path))

    def test_broken_lines_are_skipped(self):
        RH.append(self.path, {"end": 1})
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write('{"end": 2, "trunc\n')          # a crash mid-write
        self.assertEqual([r["end"] for r in RH.load(self.path)], [1])
        self.assertEqual(RH.last(self.path)["end"], 1)

    def test_file_is_trimmed_to_the_newest_records(self):
        with mock.patch.object(RH, "TRIM_AT", 12), mock.patch.object(RH, "MAX_RECORDS", 5):
            for i in range(13):
                RH.append(self.path, {"end": i})
        with open(self.path, encoding="utf-8") as fh:
            ends = [json.loads(line)["end"] for line in fh]
        self.assertEqual(ends, [8, 9, 10, 11, 12])

    def test_unserialisable_record_is_refused(self):
        self.assertFalse(RH.append(self.path, {"end": float("nan")}))
        self.assertEqual(RH.load(self.path), [])

    def test_runner_and_hub_share_one_folder_per_workflow(self):
        a = RH.history_path("Girl Wars", "x/GirlWars/GirlWars.json")
        b = RH.history_path("Girl Wars", "elsewhere/flow.json")
        self.assertEqual(a, b)
        unnamed = RH.history_path("", "x/GirlWars/GirlWars.json")
        self.assertIn("GirlWars_", unnamed)
        self.assertNotEqual(RH.history_path("A B", ""), RH.history_path("A_B", ""))


if __name__ == "__main__":
    unittest.main()
