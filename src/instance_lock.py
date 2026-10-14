"""One Runner per workflow: a second launch brings the first one forward.

Two Runners on one workflow would drive the same device or game window at
once. The Runner that opens a workflow writes its PID to
``data/runner/<slug>/runner.pid``; a later launch of the same workflow finds
that process alive, raises its window and exits instead of opening a twin.
A PID left behind by a crash is simply taken over (the process is gone).
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

from src.run_history import runner_dir

LOCK_FILE = "runner.pid"
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def lock_path(flow_name: str, flow_path: str = "") -> str:
    return os.path.join(runner_dir(flow_name, flow_path), LOCK_FILE)


def pid_alive(pid: int) -> bool:
    """True while process *pid* is running (Windows; elsewhere best effort)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied still means it exists; anything else means it is gone.
        return ctypes.GetLastError() == 5
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def holder(path: str) -> Optional[int]:
    """PID of a live Runner holding *path*, other than this process; else None."""
    try:
        with open(path, encoding="utf-8") as fh:
            pid = int((json.load(fh) or {}).get("pid") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if pid == os.getpid() or not pid_alive(pid):
        return None
    return pid


def acquire(path: str) -> Optional[int]:
    """Take the lock for this process. Returns the PID that already holds it
    (and leaves the lock alone), or None once this process holds it."""
    other = holder(path)
    if other:
        return other
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "started": time.time()}, fh)
        os.replace(tmp, path)
    except OSError:
        pass                     # no lock is better than no Runner
    return None


def release(path: str) -> None:
    """Drop the lock if this process holds it."""
    try:
        with open(path, encoding="utf-8") as fh:
            pid = int((json.load(fh) or {}).get("pid") or 0)
        if pid == os.getpid():
            os.remove(path)
    except (OSError, ValueError, TypeError, AttributeError):
        pass


def focus_process_window(pid: int) -> bool:
    """Restore and raise the main window of process *pid*. Windows only."""
    if sys.platform != "win32":
        return False
    try:
        import win32con
        import win32gui
        import win32process
    except ImportError:
        return False
    found = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd):
            return True
        try:
            if win32process.GetWindowThreadProcessId(hwnd)[1] == int(pid):
                found.append(hwnd)
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return False
    for hwnd in found:
        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            continue
    return False
