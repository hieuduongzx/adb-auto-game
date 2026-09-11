"""Win32 desktop controller — a second automation backend alongside ADB.

Lets a workflow drive a **native Windows program/game window** (by title or
class) instead of an Android device over ADB. It exposes the *same* surface the
workflow engine already uses on ``ADBGameAutomation`` (``capture_screen``,
``tap``/``swipe``/``send_text``/``press_key``, template matching, OCR), so every
image / colour / text / coordinate node works unchanged — only the capture and
input transport differ.

Six input modes (chosen per workflow), in rough order of "least intrusive"
to "most compatible":

* ``background`` — ``PostMessage`` to the target ``hwnd``. Fire-and-forget, works
  while the window is covered / minimised and never touches the real mouse, but
  some DirectX / anti-cheat games ignore it.
* ``background_sync`` — same messages via ``SendMessage``; blocks until the app
  has processed each one, which fixes engines that drop queued input.
* ``background_cursor`` — ``background`` plus ``WM_SETCURSOR``/``WM_NCHITTEST``
  bookkeeping so Unity / Unreal titles that poll the cursor still react.
* ``background_window`` — moves the *window* under a fixed screen point and posts
  input there, so hit-testing lines up without moving the user's cursor.
* ``anchored_touch`` — injects real ``WM_POINTER`` touch events through a
  synthetic pointer device anchored over the window. Indistinguishable from a
  touchscreen, so it passes most input validation, but the window must be
  visible (it is raised / made transparent briefly when covered).
* ``foreground`` — bring the window to the front and drive the *real* cursor
  and keyboard (``SendInput``/``mouse_event``). Reliable with most games but
  takes over the machine while running.

Capture is independent of the input mode: ``PrintWindow`` by default, so most
modes keep working with the window covered or minimised.
"""
from .automation import Win32GameAutomation, Win32Controller

__all__ = [
    "Win32GameAutomation",
    "Win32Controller",
]
