"""Smoke tests: every module imports and every game instantiates.

Python attribute access is dynamic, so a renamed/missing attribute won't fail
at import — only when code runs. Instantiating each game exercises __init__
(template dicts, speedhack setup) without needing a device.
"""
import importlib
import unittest

from tests import _bootstrap  # noqa: F401

MODULES = [
    "src.utils",
    "src.core.adb.cache",
    "src.core.adb.constants",
    "src.core.adb.scanner",
    "src.core.adb.controller",
    "src.core.adb.auto.config",
    "src.core.adb.auto.template_matcher",
    "src.core.adb.auto.ocr",
    "src.core.adb.auto.automation",
    "src.core.adb.auto.visualizer",
    "src.core",
    "src.game_core.activity",
    "src.game_core.gui_base",
    "src.game_core.base_game",
    "src.game_core.speedhack",
    "src.game_core.frida_speedhack",
    "src.games.bd2.bd2",
    "src.games.cherrytale.cherrytale",
    "src.games.echocalypse.echocalypse",
    "src.games.girlwars.girlwars",
]


class TestImports(unittest.TestCase):
    def test_all_modules_import(self):
        for mod in MODULES:
            with self.subTest(module=mod):
                importlib.import_module(mod)


class TestGameDiscovery(unittest.TestCase):
    def test_scan_games_finds_four(self):
        from launcher import scan_games

        games = scan_games()
        self.assertEqual(
            set(games), {"bd2", "cherrytale", "echocalypse", "girlwars"}
        )

    def test_each_game_loads_and_instantiates(self):
        from launcher import scan_games, load_game_class

        for name, info in scan_games().items():
            with self.subTest(game=name):
                cls = load_game_class(info)
                self.assertIsNotNone(cls, f"could not load class for {name}")
                game = cls()
                activities = game.get_activities()
                self.assertTrue(activities, f"{name} has no activities")
                # get_status must produce a serializable snapshot.
                status = game.get_status()
                self.assertIn("activities", status)
                self.assertIn("running", status)


if __name__ == "__main__":
    unittest.main()
