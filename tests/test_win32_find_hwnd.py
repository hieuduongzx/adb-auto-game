"""Tests for ``Win32Controller._find_hwnd`` (src/core/win32/automation).

Why it matters: a game started as Administrator has an *unreadable* title —
Windows' UIPI blocks WM_GETTEXT, so ``GetWindowText`` returns "" and a
``matchBy="title"`` pattern can never match. The tool then reports "không tìm
thấy cửa sổ" while the game is plainly running. The exe match (which uses
``PROCESS_QUERY_LIMITED_INFORMATION``, never UIPI-blocked) must still find it,
and a *titled* window of the same exe must win over an untitled one.

The controller's pywin32 surface is faked, so this stays stdlib-only and runs
wherever the suite runs::

    python -m unittest discover -s tests -v
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.win32 import automation as win32auto  # noqa: E402

# (hwnd, title, class, pid)
_TITLED = (101, "BrownDust II", "UnityWndClass", 500)
_ELEVATED = (202, "", "UnityWndClass", 501)   # title unreadable under UIPI


class _FakeGui:
    def __init__(self, windows):
        self._windows = windows

    def IsWindowVisible(self, hwnd):
        return True

    def GetWindowText(self, hwnd):
        return next((t for h, t, _c, _p in self._windows if h == hwnd), "")

    def GetClassName(self, hwnd):
        return next((c for h, _t, c, _p in self._windows if h == hwnd), "")

    def EnumWindows(self, cb, param):
        for h, _t, _c, _p in self._windows:
            cb(h, param)
        return True


class _FakeProc:
    def __init__(self, windows):
        self._by_hwnd = {h: pid for h, _t, _c, pid in windows}

    def GetWindowThreadProcessId(self, hwnd):
        return (1, self._by_hwnd.get(hwnd, 0))


def _controller(windows, exe_by_pid):
    """A Win32Controller with its pywin32 tuple replaced by the fakes."""
    ctrl = win32auto.Win32Controller.__new__(win32auto.Win32Controller)
    ctrl._w = (None, _FakeGui(windows), None, None, None, _FakeProc(windows))
    return ctrl


_EXES = {500: "C:/games/BrownDust II.exe", 501: "C:/other/BrownDust II.exe"}


def _exe(pid):
    return _EXES.get(pid, "")


class _FindHwnd(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(win32auto, "process_exe_name", side_effect=_exe)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_title_match_finds_the_titled_window(self):
        ctrl = _controller([_TITLED, _ELEVATED], _exe)
        self.assertEqual(ctrl._find_hwnd("BrownDust II", "title"), _TITLED[0])

    def test_exe_match_finds_an_elevated_untitled_window(self):
        # The reported failure: title unreadable, game clearly running.
        ctrl = _controller([_ELEVATED], _exe)
        self.assertEqual(ctrl._find_hwnd("BrownDust II.exe", "exe"), _ELEVATED[0])

    def test_titled_window_wins_over_untitled_for_the_same_exe(self):
        # Untitled listed first: the return value must not depend on order.
        ctrl = _controller([_ELEVATED, _TITLED], _exe)
        self.assertEqual(ctrl._find_hwnd("BrownDust II.exe", "exe"), _TITLED[0])

    def test_exe_match_still_ignores_other_programs(self):
        other = (303, "", "Notepad", 777)
        ctrl = _controller([other], _exe)
        self.assertIsNone(ctrl._find_hwnd("BrownDust II.exe", "exe"))


class _AttachFallback(unittest.TestCase):
    """``attach()`` must fall back from a title match to the game's exe."""

    def _ctrl(self, path, found):
        ctrl = win32auto.Win32Controller.__new__(win32auto.Win32Controller)
        ctrl.cfg = {"window": "BrownDust II", "matchBy": "title", "path": path}
        ctrl.hwnd = None
        ctrl._window_list_at = 0.0
        ctrl._warned = []
        ctrl._warn_if_uipi_blocked = lambda: ctrl._warned.append(True)
        ctrl._w = (None, _FakeGui([]), None, None, None, _FakeProc([]))
        ctrl.calls = []

        def fake_find(pattern, by):
            ctrl.calls.append((pattern, by))
            return found if by == "exe" else None

        ctrl._find_hwnd = fake_find
        return ctrl

    def test_attach_uses_exe_when_title_cannot_match(self):
        ctrl = self._ctrl("D:/other/BrownDust II.exe", found=_ELEVATED[0])
        self.assertTrue(ctrl.attach())
        self.assertEqual(ctrl.hwnd, _ELEVATED[0])
        self.assertIn(("BrownDust II.exe", "exe"), ctrl.calls)

    def test_attach_does_not_use_exe_when_no_path_is_configured(self):
        ctrl = self._ctrl("", found=_ELEVATED[0])
        ctrl._log_window_list = lambda: None
        self.assertFalse(ctrl.attach())
        self.assertNotIn("exe", [by for _pattern, by in ctrl.calls])


class _BridgeProbe(unittest.TestCase):
    """``_check_bridge`` must say loudly whether the in-game plugin answers."""

    def _ctrl(self):
        ctrl = win32auto.Win32Controller.__new__(win32auto.Win32Controller)
        ctrl.cfg = {"inputMode": "unity_bridge", "bridgePort": 17820}
        ctrl._bridge_warned = False
        return ctrl

    def test_bridge_online_is_reported_and_marks_warned(self):
        ctrl = self._ctrl()
        with mock.patch.object(win32auto, "log_info") as info, \
                mock.patch.object(win32auto, "log_error") as err, \
                mock.patch("src.core.win32.unity_bridge.ping",
                           return_value="ok Macro2kBridge 1.0.0 1920 1080"):
            ctrl._check_bridge()
        self.assertTrue(info.called)
        self.assertFalse(err.called)
        self.assertTrue(ctrl._bridge_warned)

    def test_bridge_offline_is_an_error_with_the_fix(self):
        ctrl = self._ctrl()
        with mock.patch.object(win32auto, "log_error") as err, \
                mock.patch("src.core.win32.unity_bridge.ping", return_value=None):
            ctrl._check_bridge()
        self.assertTrue(err.called)
        message = err.call_args[0][0]
        self.assertIn("COULD NOT connect", message)
        self.assertIn("127.0.0.1:17820", message)


if __name__ == "__main__":
    unittest.main()
