"""Direct tests for SettingsStore (Phase 4)."""
import json
import tempfile
import unittest
from pathlib import Path

from tests import _bootstrap  # noqa: F401
from src.game_core.settings_store import SettingsStore


class TestSettingsStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_returns_empty(self):
        store = SettingsStore("Game", settings_dir=self.dir)
        self.assertEqual(store.load(), ([], {}, None))

    def test_save_then_load_round_trip(self):
        store = SettingsStore("Game", settings_dir=self.dir)
        store.save(
            activities=[{"id": "a", "enabled": False, "poll_interval": 1.0}],
            ui_settings={"slider": 2.0},
            ocr_backend="tesseract",
        )
        activities, ui, backend = store.load()
        self.assertEqual(activities[0]["id"], "a")
        self.assertEqual(ui, {"slider": 2.0})
        self.assertEqual(backend, "tesseract")

    def test_legacy_bare_list_format(self):
        path = self.dir / "Game.json"
        path.write_text(json.dumps([{"id": "x", "enabled": True}]), encoding="utf-8")
        store = SettingsStore("Game", settings_dir=self.dir)
        activities, ui, backend = store.load()
        self.assertEqual(activities, [{"id": "x", "enabled": True}])
        self.assertEqual(ui, {})
        self.assertIsNone(backend)

    def test_corrupt_file_is_tolerated(self):
        path = self.dir / "Game.json"
        path.write_text("{not valid json", encoding="utf-8")
        store = SettingsStore("Game", settings_dir=self.dir)
        self.assertEqual(store.load(), ([], {}, None))


if __name__ == "__main__":
    unittest.main()
