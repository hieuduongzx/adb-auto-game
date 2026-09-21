"""Win32 / ADB parity nodes: Kill process, Wait for app, colour region scans,
ADB-only nodes failing in Win32 projects, and the notify escaping fix."""
import subprocess
import unittest
from unittest import mock

import numpy as np

from src.core.win32.automation import Win32Controller
from src.workflow import engine as E


def make_engine(controller="adb"):
    with mock.patch.object(E, "ADBGameAutomation"):
        eng = E.WorkflowEngine()
    eng._controller = controller
    eng._ensure_ready = mock.Mock(return_value=True)
    eng._sleep = mock.Mock()
    return eng


class TestAdbOnlyNodesInWin32Project(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine("win32")

    def test_adb_only_actions_fail_instead_of_faking_success(self):
        for handler, params in (
            (self.engine._a_app_stop, {"pkgSrc": "custom", "package": "a.b"}),
            (self.engine._a_app_uninstall, {"pkgSrc": "custom", "package": "a.b"}),
            (self.engine._a_app_install, {"apk": "x.apk"}),
            (self.engine._a_adb_shell, {"command": "id"}),
            (self.engine._a_screen_power, {"action": "on"}),
        ):
            with self.subTest(handler=handler.__name__):
                self.assertFalse(handler({}, params))

    def test_adb_only_conditions_take_the_false_branch(self):
        self.assertFalse(self.engine._eval_condition("if_screen_on", {}))
        # negate must not turn "unavailable" into a pass
        self.assertFalse(self.engine._eval_condition("if_screen_on", {"negate": True}))
        self.assertFalse(self.engine._eval_condition("if_device_size", {}))

    def test_same_nodes_still_run_in_adb_projects(self):
        eng = make_engine("adb")
        eng.auto.adb.device.shell.return_value = "out"
        self.assertTrue(eng._a_adb_shell({}, {"command": "id"}))


class TestWaitApp(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine("adb")
        self.engine._pause = mock.Mock()

    def _current(self, *apps):
        self.engine.auto.adb.get_current_app.side_effect = list(apps)

    def test_returns_true_once_the_app_is_in_front(self):
        self._current("home", "com.game/.Main")
        params = {"pkgSrc": "custom", "package": "com.game", "timeout": 5}
        with mock.patch.object(E.time, "sleep"):
            self.assertTrue(self.engine._eval_condition("wait_app", params))

    def test_negate_waits_for_the_app_to_go_away(self):
        self._current("com.game/.Main", "com.android.launcher")
        params = {"pkgSrc": "custom", "package": "com.game", "timeout": 5, "negate": True}
        with mock.patch.object(E.time, "sleep"):
            self.assertTrue(self.engine._eval_condition("wait_app", params))

    def test_times_out_to_the_false_branch(self):
        self.engine.auto.adb.get_current_app.return_value = "home"
        params = {"pkgSrc": "custom", "package": "com.game", "timeout": 0}
        self.assertFalse(self.engine._eval_condition("wait_app", params))

    def test_if_app_still_honours_negate(self):
        self.engine.auto.adb.get_current_app.return_value = "com.game/.Main"
        params = {"pkgSrc": "custom", "package": "com.game"}
        self.assertTrue(self.engine._eval_condition("if_app", params))
        self.assertFalse(self.engine._eval_condition("if_app", {**params, "negate": True}))

    def test_win32_checks_the_target_window_title(self):
        eng = make_engine("win32")
        eng._pause = mock.Mock()
        eng.auto.adb.target_title.return_value = "My Game - v1"
        params = {"pkgSrc": "custom", "package": "my game", "timeout": 1}
        self.assertTrue(eng._eval_condition("wait_app", params))


class TestColourRegionScan(unittest.TestCase):
    RED = "#ff0000"

    def setUp(self):
        self.engine = make_engine("adb")
        self.engine._pause = mock.Mock()
        self.frame = np.zeros((100, 200, 3), dtype=np.uint8)
        self.frame[40:44, 150:154] = (0, 0, 255)          # BGR red patch
        self.engine.auto.capture_screen.return_value = self.frame

    def test_if_color_point_mode_is_unchanged(self):
        self.assertTrue(self.engine._eval_condition(
            "if_color", {"color": self.RED, "x": 151, "y": 41}))
        self.assertFalse(self.engine._eval_condition(
            "if_color", {"color": self.RED, "x": 5, "y": 5}))

    def test_if_color_anywhere_finds_the_patch_and_remembers_it(self):
        params = {"color": self.RED, "where": "anywhere"}
        self.assertTrue(self.engine._eval_condition("if_color", params))
        self.assertEqual(self.engine._last_pos, (150, 40))

    def test_if_color_anywhere_respects_the_search_region(self):
        params = {"color": self.RED, "where": "anywhere",
                  "regionX": 0, "regionY": 0, "regionW": 100, "regionH": 100}
        self.assertFalse(self.engine._eval_condition("if_color", params))

    def test_if_color_anywhere_supports_negate(self):
        params = {"color": self.RED, "where": "anywhere", "negate": True}
        self.assertFalse(self.engine._eval_condition("if_color", params))

    def test_wait_color_anywhere(self):
        params = {"color": self.RED, "where": "anywhere", "timeout": 1}
        self.assertTrue(self.engine._eval_condition("wait_color", params))

    def test_wait_color_anywhere_times_out(self):
        self.frame[:] = 0
        params = {"color": self.RED, "where": "anywhere", "timeout": 0}
        self.assertFalse(self.engine._eval_condition("wait_color", params))

    def test_wait_color_negate_waits_for_the_colour_to_vanish(self):
        self.frame[:] = 0
        params = {"color": self.RED, "where": "anywhere", "timeout": 1, "negate": True}
        self.assertTrue(self.engine._eval_condition("wait_color", params))


class TestLongPress(unittest.TestCase):
    def test_uses_a_real_hold_not_a_zero_length_swipe(self):
        eng = make_engine("adb")
        eng._a_long_press({}, {"target": "pos", "x": 10, "y": 20, "duration": 900})
        eng.auto.adb.hold_and_release.assert_called_once_with(10, 20, 900)
        eng.auto.adb.swipe.assert_not_called()


class TestWinKill(unittest.TestCase):
    def _controller(self, pid=4321):
        ctrl = Win32Controller.__new__(Win32Controller)
        ctrl.hwnd = 77
        ctrl._held_keys = {13}
        ctrl.window_exists = mock.Mock(return_value=True)
        ctrl._w = (None, None, None, None, None, mock.Mock())
        ctrl._w[5].GetWindowThreadProcessId.return_value = (1, pid)
        return ctrl

    def test_kills_the_process_tree_and_drops_the_window(self):
        ctrl = self._controller()
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("src.core.win32.automation.subprocess.run", return_value=ok) as run:
            self.assertTrue(ctrl.kill_process())
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "4321", "/F", "/T"])
        self.assertIsNone(ctrl.hwnd)
        self.assertEqual(ctrl._held_keys, set())

    def test_tree_off_omits_the_child_switch(self):
        ctrl = self._controller()
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch("src.core.win32.automation.subprocess.run", return_value=ok) as run:
            ctrl.kill_process(tree=False)
        self.assertNotIn("/T", run.call_args.args[0])

    def test_missing_window_is_not_an_error(self):
        ctrl = self._controller()
        ctrl.window_exists.return_value = False
        self.assertIsNone(ctrl.kill_process())

    def test_never_kills_this_app_or_system_pids(self):
        import os
        for pid in (0, 4, os.getpid()):
            with self.subTest(pid=pid):
                ctrl = self._controller(pid)
                with mock.patch("src.core.win32.automation.subprocess.run") as run:
                    self.assertFalse(ctrl.kill_process())
                run.assert_not_called()

    def test_taskkill_failure_is_reported(self):
        ctrl = self._controller()
        bad = subprocess.CompletedProcess([], 1, "", "Access is denied")
        with mock.patch("src.core.win32.automation.subprocess.run", return_value=bad):
            self.assertFalse(ctrl.kill_process())
        self.assertEqual(ctrl.hwnd, 77)

    def test_engine_node_treats_no_window_as_success(self):
        eng = make_engine("win32")
        eng.auto.adb.kill_process.return_value = None
        self.assertTrue(eng._a_win_kill({}, {}))

    def test_engine_node_fails_when_the_kill_fails(self):
        eng = make_engine("win32")
        eng.auto.adb.kill_process.return_value = False
        self.assertFalse(eng._a_win_kill({}, {}))

    def test_node_is_rejected_outside_win32_projects(self):
        self.assertFalse(make_engine("adb")._a_win_kill({}, {}))


class TestNotifyEscaping(unittest.TestCase):
    def test_text_travels_in_the_environment_not_the_script(self):
        eng = make_engine("adb")
        nasty = 'say "hi" $(calc) `x`'
        with mock.patch("subprocess.Popen") as popen:
            eng._a_notify({}, {"title": "T", "message": nasty, "sound": False})
        args, kwargs = popen.call_args
        script = args[0][-1]
        self.assertNotIn("calc", script)
        self.assertNotIn(nasty, script)
        self.assertEqual(kwargs["env"]["M2K_NOTIFY_MSG"], nasty)
        self.assertEqual(kwargs["env"]["M2K_NOTIFY_TITLE"], "T")


class TestRegistry(unittest.TestCase):
    def test_new_nodes_are_registered_and_dispatchable(self):
        for name in ("wait_app", "win_kill"):
            self.assertIn(name, E.NODE_TYPES)
        self.assertEqual(E.NODE_TYPES["wait_app"]["kind"], "condition")
        eng = make_engine()
        self.assertIn("win_kill", eng._actions)


if __name__ == "__main__":
    unittest.main()
