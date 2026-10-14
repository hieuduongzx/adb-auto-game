"""Global hotkeys: registered on a private thread; WM_HOTKEY runs the binding."""
import sys
import threading
import unittest

from src import hotkeys as H

VK_F24 = 0x87   # a key no keyboard has: registering it disturbs nothing


@unittest.skipUnless(sys.platform == "win32", "Win32 RegisterHotKey")
class GlobalHotkeyTests(unittest.TestCase):
    def test_a_hotkey_message_runs_its_binding_and_stop_unregisters(self):
        import ctypes
        hit = threading.Event()
        mods = H.MOD_CONTROL | H.MOD_ALT | H.MOD_SHIFT
        hk = H.GlobalHotkeys([(mods, VK_F24, "Ctrl+Alt+Shift+F24", hit.set)]).start()
        try:
            self.assertEqual(hk.registered, ["Ctrl+Alt+Shift+F24"])
            ctypes.windll.user32.PostThreadMessageW(hk._thread_id, H.WM_HOTKEY, 1, 0)
            self.assertTrue(hit.wait(2))
        finally:
            hk.stop()
        # Unregistered on stop: a second owner can take the same combination.
        again = H.GlobalHotkeys([(mods, VK_F24, "again", lambda: None)]).start()
        try:
            self.assertEqual(again.registered, ["again"])
        finally:
            again.stop()

    def test_a_taken_combination_is_reported_not_fatal(self):
        mods = H.MOD_CONTROL | H.MOD_ALT | H.MOD_SHIFT
        first = H.GlobalHotkeys([(mods, VK_F24, "first", lambda: None)]).start()
        try:
            second = H.GlobalHotkeys([(mods, VK_F24, "second", lambda: None)]).start()
            try:
                self.assertEqual((second.registered, second.failed), ([], ["second"]))
            finally:
                second.stop()
        finally:
            first.stop()


if __name__ == "__main__":
    unittest.main()
