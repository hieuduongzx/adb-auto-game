"""Tests for the Unity Bridge deployer (src/core/win32/unity_bridge).

Mono games get BepInEx 5 + the Mono plugin, IL2CPP games BepInEx 6 + the IL2CPP
plugin. The bundled packs are replaced by tiny fakes so the suite stays fast::

    python -m unittest discover -s tests -v
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.win32 import unity_bridge as ub  # noqa: E402


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class UnityBridgeDeployTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ub_test_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        # fake bundled packs
        self.pack5 = self.tmp / "pack5"
        for name in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version"):
            _touch(self.pack5 / name, b"d5")
        _touch(self.pack5 / "BepInEx" / "core" / "BepInEx.dll", b"core5")
        self.pack6 = self.tmp / "pack6"
        for name in ("winhttp.dll", "doorstop_config.ini", ".doorstop_version"):
            _touch(self.pack6 / name, b"d6")
        _touch(self.pack6 / "dotnet" / "coreclr.dll", b"clr")
        _touch(self.pack6 / "BepInEx" / "core" / "BepInEx.Core.dll", b"core6")
        _touch(self.pack6 / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll", b"il2cpp6")
        self.plugin5 = _touch(self.tmp / "plugin5" / "Macro2kBridge.dll", b"plugin-mono")
        self.plugin6 = _touch(self.tmp / "plugin6" / "Macro2kBridge.dll", b"plugin-il2cpp")

        for patcher in (
            mock.patch.object(ub, "BEPINEX_DIR", str(self.pack5)),
            mock.patch.object(ub, "BEPINEX6_DIR", str(self.pack6)),
            mock.patch.object(ub, "PLUGIN_DLL", str(self.plugin5)),
            mock.patch.object(ub, "PLUGIN_DLL_IL2CPP", str(self.plugin6)),
            mock.patch.object(ub, "vendored_bepinex_version", return_value="5.4.23.5"),
            mock.patch.object(ub, "_file_version", return_value="5.4.23.5"),
            mock.patch.object(ub, "_pe_arch", return_value="x64"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _game(self, *, il2cpp: bool) -> Path:
        game = self.tmp / ("il2cpp_game" if il2cpp else "mono_game")
        _touch(game / "Game.exe")
        _touch(game / "UnityPlayer.dll")
        _touch(game / "Game_Data" / "globalgamemanagers")
        if il2cpp:
            _touch(game / "GameAssembly.dll")
        else:
            (game / "Game_Data" / "Managed").mkdir(parents=True)
        return game

    def test_mono_game_gets_bepinex5_and_mono_plugin(self):
        game = self._game(il2cpp=False)
        res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(res["flavor"], "mono")
        self.assertEqual((game / ub.PLUGIN_REL).read_bytes(), b"plugin-mono")
        self.assertTrue((game / "BepInEx" / "core" / "BepInEx.dll").exists())
        self.assertFalse((game / "dotnet").exists())

    def test_il2cpp_game_gets_bepinex6_runtime_and_il2cpp_plugin(self):
        game = self._game(il2cpp=True)
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertEqual(info["backend"], "IL2CPP")
        self.assertEqual(info["problems"], [])
        self.assertEqual(info["vendorBepinexVersion"], ub.BEPINEX6_VERSION)

        res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual((game / ub.PLUGIN_REL).read_bytes(), b"plugin-il2cpp")
        self.assertTrue((game / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll").exists())
        self.assertTrue((game / "dotnet" / "coreclr.dll").exists())
        self.assertTrue((game / "winhttp.dll").exists())
        # second run is an update, not a reinstall
        again = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(again["pluginInstalled"] and again["pluginCurrent"])

    def test_il2cpp_game_with_bepinex5_is_rejected(self):
        game = self._game(il2cpp=True)
        _touch(game / "BepInEx" / "core" / "BepInEx.dll")
        _touch(game / "winhttp.dll")
        res = ub.deploy(str(game / "Game.exe"))
        self.assertFalse(res["ok"])
        self.assertIn("BepInEx 5", res["error"])

    def test_il2cpp_game_with_mono_bepinex6_is_rejected(self):
        game = self._game(il2cpp=True)
        _touch(game / "BepInEx" / "core" / "BepInEx.Core.dll")
        _touch(game / "winhttp.dll")
        res = ub.deploy(str(game / "Game.exe"))
        self.assertFalse(res["ok"])
        self.assertIn("BepInEx.Unity.IL2CPP.dll", res["error"])

    def test_il2cpp_bundled_bepinex6_missing_doorstop_gets_it_back(self):
        game = self._game(il2cpp=True)
        _touch(game / "BepInEx" / "core" / "BepInEx.Core.dll", b"core6")
        _touch(game / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll", b"il2cpp6")
        res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertTrue((game / "winhttp.dll").exists())
        self.assertTrue((game / "dotnet" / "coreclr.dll").exists())

    def test_il2cpp_other_bepinex6_build_missing_doorstop_is_not_touched(self):
        game = self._game(il2cpp=True)
        _touch(game / "BepInEx" / "core" / "BepInEx.Core.dll", b"core-other")
        _touch(game / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll", b"il2cpp-other-build")
        res = ub.deploy(str(game / "Game.exe"))
        self.assertFalse(res["ok"])
        self.assertIn("thiếu doorstop", res["error"])
        self.assertFalse((game / "winhttp.dll").exists())

    def test_il2cpp_existing_bepinex6_is_kept_when_doorstop_present(self):
        game = self._game(il2cpp=True)
        _touch(game / "BepInEx" / "core" / "BepInEx.Core.dll", b"core-other")
        _touch(game / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll", b"il2cpp-other-build")
        _touch(game / "winhttp.dll", b"their-doorstop")
        res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual((game / "winhttp.dll").read_bytes(), b"their-doorstop")
        self.assertEqual((game / "BepInEx" / "core" / "BepInEx.Unity.IL2CPP.dll").read_bytes(), b"il2cpp-other-build")
        self.assertEqual((game / ub.PLUGIN_REL).read_bytes(), b"plugin-il2cpp")

    def test_missing_il2cpp_plugin_build_blocks_deploy(self):
        game = self._game(il2cpp=True)
        self.plugin6.unlink()
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(any("plugin_il2cpp" in p for p in info["problems"]))


if __name__ == "__main__":
    unittest.main()
