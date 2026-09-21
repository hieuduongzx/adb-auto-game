"""Tests for the Unity Bridge deployer (src/core/win32/unity_bridge).

No BepInEx: the bridge DLL is injected into the running game's process, nothing is
ever copied into the game folder. Mono games get a managed DLL (Macro2kInjector's
"inject" mode, the game's own Mono embedding API); IL2CPP games get a native DLL
(Macro2kInjector's "loadlibrary" mode, CreateRemoteThread + LoadLibraryW). The
injector executable is replaced by a tiny fake so the suite stays fast and needs
no real game process::

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

        self.injector = _touch(self.tmp / "injector" / "Macro2kInjector.exe", b"injector")
        self.plugin_mono = _touch(self.tmp / "inject" / "Macro2kBridge.Inject.dll", b"plugin-mono")
        self.plugin_il2cpp = _touch(self.tmp / "il2cpp" / "Macro2kBridge.Il2Cpp.dll", b"plugin-il2cpp")

        for patcher in (
            mock.patch.object(ub, "INJECTOR_EXE", str(self.injector)),
            mock.patch.object(ub, "PLUGIN_DLL_MONO", str(self.plugin_mono)),
            mock.patch.object(ub, "PLUGIN_DLL_IL2CPP", str(self.plugin_il2cpp)),
            mock.patch.object(ub, "INJECT_PORT_FILE", str(self.tmp / "bridge.port")),
            mock.patch.object(ub, "INJECT_LOG", str(self.tmp / "Macro2kBridge.log")),
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

    # ── inspect_game ────────────────────────────────────────────────────────────────

    def test_mono_game_is_detected(self):
        game = self._game(il2cpp=False)
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertEqual(info["backend"], "Mono")
        self.assertEqual(info["flavor"], "mono")
        self.assertEqual(info["arch"], "x64")
        self.assertEqual(info["problems"], [])
        self.assertFalse(info["legacyBepinex"])

    def test_il2cpp_game_is_detected(self):
        game = self._game(il2cpp=True)
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertEqual(info["backend"], "IL2CPP")
        self.assertEqual(info["flavor"], "il2cpp")
        self.assertEqual(info["problems"], [])

    def test_unity_game_with_custom_data_folder_is_detected(self):
        game = self.tmp / "custom_data_game"
        _touch(game / "Game.exe")
        _touch(game / "UnityPlayer.dll")
        _touch(game / "Data" / "globalgamemanagers")
        (game / "Data" / "Managed").mkdir(parents=True)

        info = ub.inspect_game(str(game / "Game.exe"))

        self.assertTrue(info["unity"])
        self.assertEqual(info["backend"], "Mono")
        self.assertEqual(info["dataDir"], str(game / "Data"))
        self.assertEqual(info["problems"], [])

    def test_non_unity_executable_is_rejected(self):
        game = self.tmp / "not_unity"
        _touch(game / "Game.exe")
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertFalse(info["unity"])
        self.assertTrue(info["problems"])

    def test_missing_executable_is_rejected(self):
        info = ub.inspect_game(str(self.tmp / "missing" / "Game.exe"))
        self.assertIn("was not found", info["problems"][0])

    def test_wrong_arch_is_rejected(self):
        game = self._game(il2cpp=False)
        with mock.patch.object(ub, "_pe_arch", return_value="x86"):
            info = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(any("x86" in p for p in info["problems"]))

    def test_missing_mono_plugin_blocks_deploy(self):
        game = self._game(il2cpp=False)
        self.plugin_mono.unlink()
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(any("plugin_inject" in p for p in info["problems"]))

    def test_missing_il2cpp_plugin_blocks_deploy(self):
        game = self._game(il2cpp=True)
        self.plugin_il2cpp.unlink()
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(any("plugin_il2cpp" in p for p in info["problems"]))

    def test_missing_injector_blocks_deploy(self):
        game = self._game(il2cpp=False)
        self.injector.unlink()
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(any("Macro2kInjector.exe" in p for p in info["problems"]))

    def test_legacy_bepinex_files_are_detected(self):
        game = self._game(il2cpp=False)
        _touch(game / "winhttp.dll", b"old doorstop")
        info = ub.inspect_game(str(game / "Game.exe"))
        self.assertTrue(info["legacyBepinex"])

    # ── deploy (injection) ──────────────────────────────────────────────────────────

    def _fake_injector(self, *, ok: bool, reply: str = "ok Macro2kBridge 1.1.0 1920 1080"):
        """A subprocess.run stand-in for Macro2kInjector.exe: records the argv and pretends to
        succeed or fail without touching any real process."""
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            out = "ok\n" if ok else "err simulated failure\n"
            return mock.Mock(returncode=0 if ok else 1, stdout=out, stderr="")

        # ensure_injected() pings once before injecting (must be down) and again after (must answer
        # once the injector "succeeded"); itertools.repeat keeps later pings from raising StopIteration.
        import itertools
        pings = itertools.chain([None], itertools.repeat(reply))
        return calls, mock.patch.object(ub.subprocess, "run", side_effect=run), \
            mock.patch.object(ub, "ping", side_effect=lambda *a, **k: next(pings))

    def test_deploy_injects_mono_game(self):
        game = self._game(il2cpp=False)
        calls, run_patch, ping_patch = self._fake_injector(ok=True)
        with run_patch, ping_patch, mock.patch.object(ub, "find_game_pids", return_value=[4321]):
            res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertTrue(res["injected"])
        self.assertEqual(calls[-1][:3], [str(self.injector), "inject", "4321"])
        self.assertEqual(calls[-1][3], str(self.plugin_mono))
        self.assertEqual(tuple(calls[-1][4:]), ub.INJECT_ENTRY)
        self.assertEqual((self.tmp / "bridge.port").read_text(), str(ub.DEFAULT_PORT))
        self.assertFalse((game / "BepInEx").exists())

    def test_deploy_injects_il2cpp_game_with_loadlibrary(self):
        game = self._game(il2cpp=True)
        calls, run_patch, ping_patch = self._fake_injector(ok=True)
        with run_patch, ping_patch, mock.patch.object(ub, "find_game_pids", return_value=[5555]):
            res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertTrue(res["injected"])
        self.assertEqual(calls[-1], [str(self.injector), "loadlibrary", "5555", str(self.plugin_il2cpp)])

    def test_deploy_reports_injection_failure_without_copying_anything(self):
        game = self._game(il2cpp=False)
        calls, run_patch, ping_patch = self._fake_injector(ok=False)
        with run_patch, ping_patch, mock.patch.object(ub, "find_game_pids", return_value=[1]):
            res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"])  # deploy() itself succeeds; the injection outcome is in the actions
        self.assertFalse(res["injected"])
        self.assertTrue(any("Not injected yet" in a for a in res["actions"]))
        self.assertFalse((game / "BepInEx").exists())

    def test_deploy_skips_injection_when_bridge_already_running(self):
        game = self._game(il2cpp=False)
        with mock.patch.object(ub, "ping", return_value="ok Macro2kBridge 1.1.0 1920 1080"), \
                mock.patch.object(ub.subprocess, "run") as run:
            res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"])
        self.assertTrue(res["injected"])
        run.assert_not_called()

    def test_deploy_removes_legacy_bepinex_files(self):
        game = self._game(il2cpp=False)
        _touch(game / "BepInEx" / "plugins" / "Macro2kBridge" / "Macro2kBridge.dll", b"old plugin")
        _touch(game / "winhttp.dll", b"old doorstop")
        _touch(game / "doorstop_config.ini", b"old config")
        with mock.patch.object(ub, "ping", return_value="ok Macro2kBridge 1.1.0 1920 1080"):
            res = ub.deploy(str(game / "Game.exe"))
        self.assertTrue(res["ok"])
        self.assertFalse((game / "BepInEx").exists())
        self.assertFalse((game / "winhttp.dll").exists())
        self.assertFalse((game / "doorstop_config.ini").exists())
        self.assertTrue(any("Removed the old BepInEx file" in a for a in res["actions"]))

    def test_deploy_blocked_by_problems_does_not_run_the_injector(self):
        game = self._game(il2cpp=False)
        self.plugin_mono.unlink()
        with mock.patch.object(ub.subprocess, "run") as run:
            res = ub.deploy(str(game / "Game.exe"))
        self.assertFalse(res["ok"])
        self.assertIn("plugin_inject", res["error"])
        run.assert_not_called()

    # ── ensure_injected / inject ────────────────────────────────────────────────────

    def test_ensure_injected_returns_already_when_bridge_answers(self):
        game = self._game(il2cpp=False)
        with mock.patch.object(ub, "ping", return_value="ok Macro2kBridge 1.1.0 1920 1080"):
            res = ub.ensure_injected(str(game / "Game.exe"))
        self.assertTrue(res["ok"])
        self.assertTrue(res["already"])

    def test_ensure_injected_fails_when_game_not_running(self):
        game = self._game(il2cpp=False)
        with mock.patch.object(ub, "ping", return_value=None), \
                mock.patch.object(ub, "find_game_pids", return_value=[]):
            res = ub.ensure_injected(str(game / "Game.exe"))
        self.assertFalse(res["ok"])
        self.assertIn("not running", res["error"])

    def test_inject_reports_injector_failure(self):
        failed = mock.Mock(returncode=1, stdout="err OpenProcess failed\n", stderr="")
        with mock.patch.object(ub.subprocess, "run", return_value=failed):
            res = ub.inject(4242, il2cpp=False)
        self.assertFalse(res["ok"])
        self.assertIn("OpenProcess failed", res["error"])

    def test_inject_reports_timeout_when_dll_loads_but_bridge_silent(self):
        ok = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch.object(ub.subprocess, "run", return_value=ok), \
                mock.patch.object(ub, "ping", return_value=None):
            res = ub.inject(4242, il2cpp=True, wait=0.01)
        self.assertFalse(res["ok"])
        self.assertIn("did not answer", res["error"])

    def test_inject_timeout_includes_only_errors_from_the_current_attempt(self):
        Path(ub.INJECT_LOG).write_text(
            "12:00:00.000 [Error] stale failure\n", encoding="utf-8"
        )
        ok = mock.Mock(returncode=0, stdout="ok\n", stderr="")

        def run(*args, **kwargs):
            with open(ub.INJECT_LOG, "a", encoding="utf-8") as fh:
                fh.write("12:00:01.000 [Info] Macro2kBridge loading\n")
                fh.write("12:00:01.100 [Error] IL2CPP API is unavailable\n")
            return ok

        with mock.patch.object(ub.subprocess, "run", side_effect=run), \
                mock.patch.object(ub, "ping", return_value=None):
            res = ub.inject(4242, il2cpp=True, wait=0.01)

        self.assertFalse(res["ok"])
        self.assertIn("IL2CPP API is unavailable", res["error"])
        self.assertNotIn("stale failure", res["error"])

    def test_inject_writes_the_port_file(self):
        ok = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        with mock.patch.object(ub.subprocess, "run", return_value=ok), \
                mock.patch.object(ub, "ping", return_value="ok Macro2kBridge 1.1.0 1920 1080"):
            res = ub.inject(1, il2cpp=False, port=17821)
        self.assertTrue(res["ok"])
        self.assertEqual((self.tmp / "bridge.port").read_text(), "17821")

    def test_launch_injected_returns_the_created_process_id(self):
        game = self._game(il2cpp=True)
        completed = mock.Mock(returncode=0, stdout="ok 2468\n", stderr="")
        with mock.patch.object(ub.subprocess, "run", return_value=completed) as run:
            res = ub.launch_injected(str(game / "Game.exe"), "--server test", port=17822)

        self.assertEqual(res, {"ok": True, "pid": 2468})
        self.assertEqual(
            run.call_args.args[0],
            [str(self.injector), "launchlibrary", str(game / "Game.exe"),
             str(self.plugin_il2cpp), "--server test"],
        )
        self.assertEqual((self.tmp / "bridge.port").read_text(), "17822")

    def test_launch_injected_reports_injector_failure(self):
        game = self._game(il2cpp=True)
        completed = mock.Mock(returncode=1, stdout="err CreateProcess failed: denied\n", stderr="")
        with mock.patch.object(ub.subprocess, "run", return_value=completed):
            res = ub.launch_injected(str(game / "Game.exe"))

        self.assertFalse(res["ok"])
        self.assertIn("CreateProcess failed: denied", res["error"])


if __name__ == "__main__":
    unittest.main()
