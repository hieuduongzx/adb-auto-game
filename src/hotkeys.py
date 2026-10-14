"""System-wide hotkeys: stop or pause a run without finding the Runner first.

A macro in Win32 *foreground* mode owns the real mouse, and a game in front
hides the Runner — the operator needs a key that works from anywhere.
``RegisterHotKey`` needs no keyboard hook or admin rights; a combination
another program already owns simply fails to register (reported, not fatal).
"""
from __future__ import annotations

import sys
import threading
from typing import Callable, Dict, List, Optional, Tuple

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

# (modifiers, virtual key, label) of the Runner's defaults.
STOP = (MOD_CONTROL | MOD_SHIFT, 0x7B, "Ctrl+Shift+F12")    # VK_F12
PAUSE = (MOD_CONTROL | MOD_SHIFT, 0x7A, "Ctrl+Shift+F11")   # VK_F11


class GlobalHotkeys:
    """Register hotkeys on a private thread with its own message loop."""

    def __init__(self, bindings: List[Tuple[int, int, str, Callable[[], None]]]):
        self._bindings = bindings
        self._thread: Optional[threading.Thread] = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.registered: List[str] = []
        self.failed: List[str] = []

    def start(self, timeout: float = 2.0) -> "GlobalHotkeys":
        if sys.platform != "win32" or self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._loop, name="global-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self

    def stop(self) -> None:
        """Unregister and end the loop. Safe from a binding itself (a Stop
        hotkey that stops the run lands here on the hotkey thread)."""
        thread = self._thread
        if thread is None or not self._thread_id:
            return
        self._thread = None
        import ctypes
        ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        handlers: Dict[int, Callable[[], None]] = {}
        for i, (mods, vk, label, fn) in enumerate(self._bindings, start=1):
            if user32.RegisterHotKey(None, i, mods | MOD_NOREPEAT, vk):
                handlers[i] = fn
                self.registered.append(label)
            else:
                self.failed.append(label)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    fn = handlers.get(int(msg.wParam))
                    if fn is not None:
                        try:
                            fn()
                        except Exception:
                            pass
        finally:
            for i in handlers:
                user32.UnregisterHotKey(None, i)
