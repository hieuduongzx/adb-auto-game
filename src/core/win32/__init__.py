"""Win32 desktop controller — a second automation backend alongside ADB.

Lets a workflow drive a **native Windows program/game window** (by title or
class) instead of an Android device over ADB. It exposes the *same* surface the
workflow engine already uses on ``ADBGameAutomation`` (``capture_screen``,
``tap``/``swipe``/``send_text``/``press_key``, template matching, OCR), so every
image / colour / text / coordinate node works unchanged — only the capture and
input transport differ.

Two control modes (chosen per workflow):

* ``background`` — capture via ``PrintWindow`` and click via ``PostMessage`` to
  the target ``hwnd``. Works while the window is covered / minimised and does
  not steal the real mouse, but some DirectX / anti-cheat games ignore it.
* ``foreground`` — bring the window to the front and drive the *real* cursor
  and keyboard (``SendInput``/``mouse_event``). Reliable with most games but
  takes over the machine while running.
"""
from .automation import Win32GameAutomation, Win32Controller
from .injector import (
    detect_unity_backend,
    inject_unity_cheat,
    launch_and_inject,
    module_loaded,
    pid_from_hwnd,
)

__all__ = [
    "Win32GameAutomation",
    "Win32Controller",
    "inject_unity_cheat",
    "launch_and_inject",
    "detect_unity_backend",
    "module_loaded",
    "pid_from_hwnd",
]
