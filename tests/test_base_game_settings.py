"""Characterization test for BaseGameAutomation settings load/merge/save.

This is the riskiest logic moved during the refactor (Phase 4/SettingsStore),
so we pin its observable behavior end-to-end: defaults seed custom_values,
toggles persist across re-instantiation, and the JSON payload keeps its shape.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import List

from tests import _bootstrap  # noqa: F401
from src.game_core.base_game import BaseGameAutomation
from src.game_core.activity import Activity


class _FakeGame(BaseGameAutomation):
    """Minimal concrete game: no device, two sequential activities."""

    def define_activities(self) -> List[Activity]:
        return [
            Activity(id="alpha", name="Alpha", enabled=True),
            Activity(
                id="beta", name="Beta", enabled=True,
                custom_settings=[{"key": "scale", "default": 2.0}],
            ),
        ]

    def handle_activity_alpha(self):
        return True

    def handle_activity_beta(self):
        return True


class TestBaseGameSettings(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cwd = os.getcwd()
        os.chdir(self._tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _settings_path(self) -> Path:
        return Path("data") / "settings" / "_FakeGame.json"

    def test_custom_values_seeded_from_defaults(self):
        game = _FakeGame()
        beta = game.get_activity("beta")
        self.assertEqual(beta.custom_values.get("scale"), 2.0)

    def test_toggle_persists_across_reinstantiation(self):
        game = _FakeGame()
        game.set_activity_enabled("alpha", False)
        self.assertTrue(self._settings_path().exists())

        # Fresh instance must read back the persisted disabled state.
        game2 = _FakeGame()
        self.assertFalse(game2.get_activity("alpha").enabled)
        self.assertTrue(game2.get_activity("beta").enabled)

    def test_saved_payload_shape(self):
        game = _FakeGame()
        game.set_custom_setting("beta", "scale", 3.5)
        with self._settings_path().open(encoding="utf-8") as f:
            payload = json.load(f)
        self.assertIn("activities", payload)
        self.assertIn("ui_settings", payload)
        self.assertIn("ocr_backend", payload)
        beta = next(a for a in payload["activities"] if a["id"] == "beta")
        self.assertEqual(beta["custom"]["scale"], 3.5)

    def test_ui_setting_round_trip(self):
        game = _FakeGame()
        game.set_ui_setting("speed_slider", 2.0)
        game2 = _FakeGame()
        self.assertEqual(game2.get_ui_setting("speed_slider"), 2.0)


if __name__ == "__main__":
    unittest.main()
