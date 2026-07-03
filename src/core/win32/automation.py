"""Win32 backend: window capture + input, mirroring the ADB automation API.

``Win32GameAutomation`` subclasses :class:`ADBGameAutomation` and swaps only the
device-touching parts — it keeps the exact same ``TemplateMatcher`` / ``OCRReader``
pipeline, so ``find_template`` / ``read_text`` / colour checks run identically
against a captured *window* frame. ``Win32Controller`` stands in for the ADB
controller (``self.auto.adb``) so the engine's ``self.auto.adb.*`` calls resolve.

Requires ``pywin32`` (imported lazily so ADB-only users are unaffected).
"""
from __future__ import annotations

import fnmatch
import os
import subprocess
import time
from typing import List, Optional, Tuple

import numpy as np

from src.utils import log_error, log_info, log_warning, log_debug
from src.core.adb.auto.automation import ADBGameAutomation
from src.core.adb.auto.config import Config
from src.core.adb.auto.template_matcher import TemplateMatcher
from src.core.adb.auto.visualizer import DebugVisualizer
from src.core.adb.auto.ocr import OCRReader

# ── Win32 message / flag constants ────────────────────────────────────────────
_WM_MOUSEMOVE     = 0x0200
_WM_LBUTTONDOWN   = 0x0201
_WM_LBUTTONUP     = 0x0202
_WM_LBUTTONDBLCLK = 0x0203
_WM_KEYDOWN       = 0x0100
_WM_KEYUP         = 0x0101
_WM_CHAR          = 0x0102
_WM_CLOSE         = 0x0010
_MK_LBUTTON       = 0x0001
_PW_CLIENTONLY        = 0x1
_PW_RENDERFULLCONTENT = 0x2  # capture DirectComposition/GPU content (Win 8.1+)
_VK_ESCAPE        = 0x1B
# mouse_event flags (foreground)
_ME_MOVE = 0x0001; _ME_ABSOLUTE = 0x8000
_ME_LDOWN = 0x0002; _ME_LUP = 0x0004
_KE_KEYUP = 0x0002


def _import_win32():
    """Lazy pywin32 import with a friendly error if it's missing."""
    try:
        import ctypes
        import win32gui, win32ui, win32con, win32api, win32process  # noqa: F401
        return ctypes, win32gui, win32ui, win32con, win32api, win32process
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Win32 backend cần gói 'pywin32' (pip install pywin32). Chi tiết: %s" % exc
        ) from exc


def _lparam(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


class Win32Controller:
    """ADBController stand-in that talks to a native window instead of a device.

    ``cfg`` keys: ``window`` (title/class to match), ``matchBy`` (``"title"`` |
    ``"class"``), ``inputMode`` (``"background"`` | ``"foreground"``).
    """

    def __init__(self, cfg: Optional[dict] = None):
        self._w = _import_win32()  # (ctypes, win32gui, win32ui, win32con, win32api, win32process)
        self.hwnd: Optional[int] = None
        self.cfg: dict = dict(cfg or {})
        # ADBController-compat attributes the engine reads.
        self.device_id = None

    # ── config ────────────────────────────────────────────────────────────────
    def configure(self, cfg: dict) -> None:
        self.cfg = dict(cfg or {})
        # A config change may point at a different window — force a re-attach.
        self.hwnd = None

    @property
    def _match(self) -> Tuple[str, str, str]:
        return (
            str(self.cfg.get("window", "")).strip(),
            str(self.cfg.get("matchBy", "title")).strip().lower() or "title",
            str(self.cfg.get("inputMode", "background")).strip().lower() or "background",
        )

    # ── engine/ADBController-compat surface ────────────────────────────────────
    @property
    def device(self):
        """Truthy once a window is attached (mirrors ADBController.device)."""
        return self.hwnd

    def clear_info_cache(self) -> None:
        pass

    def check_adb_connection(self) -> bool:
        """Attach to the target window (the Win32 analogue of 'connect')."""
        return self.attach()

    def attach(self) -> bool:
        pattern, by, _ = self._match
        if not pattern:
            log_error("[win32] Chưa đặt tên/lớp cửa sổ mục tiêu (Project settings)")
            return False
        hwnd = self._find_hwnd(pattern, by)
        if not hwnd:
            log_warning(f"[win32] Không tìm thấy cửa sổ khớp '{pattern}' ({by})")
            self.hwnd = None
            return False
        self.hwnd = hwnd
        _, win32gui = self._w[0], self._w[1]
        log_info(f"[win32] Gắn cửa sổ 0x{hwnd:X} — '{win32gui.GetWindowText(hwnd)}'")
        return True

    def _find_hwnd(self, pattern: str, by: str) -> Optional[int]:
        win32gui = self._w[1]
        low = pattern.lower()
        use_glob = any(ch in pattern for ch in "*?[")
        found: List[int] = []

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            if by == "class":
                name = win32gui.GetClassName(hwnd) or ""
                ok = (name == pattern) or (use_glob and fnmatch.fnmatch(name.lower(), low))
            else:
                title = win32gui.GetWindowText(hwnd) or ""
                if not title:
                    return
                ok = fnmatch.fnmatch(title.lower(), low) if use_glob else (low in title.lower())
            if ok:
                found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        return found[0] if found else None

    def get_screen_size(self) -> Tuple[int, int]:
        if not self.hwnd:
            return (0, 0)
        try:
            l, t, r, b = self._w[1].GetClientRect(self.hwnd)
            return (r - l, b - t)
        except Exception:
            return (0, 0)

    def get_current_app(self) -> Optional[str]:
        """Foreground window title — analogue of ADB's current package."""
        win32gui = self._w[1]
        try:
            return win32gui.GetWindowText(win32gui.GetForegroundWindow()) or ""
        except Exception:
            return ""

    # ── capture (PrintWindow → BGR ndarray) ────────────────────────────────────
    def capture_frame(self) -> Optional[np.ndarray]:
        if not self.hwnd:
            return None
        ctypes, win32gui, win32ui = self._w[0], self._w[1], self._w[2]
        try:
            l, t, r, b = win32gui.GetClientRect(self.hwnd)
            w, h = r - l, b - t
            if w <= 0 or h <= 0:
                return None
            hwnd_dc = win32gui.GetWindowDC(self.hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            # PW_CLIENTONLY | PW_RENDERFULLCONTENT captures the client area even
            # for GPU-composited windows without bringing them to the front.
            ok = ctypes.windll.user32.PrintWindow(
                self.hwnd, save_dc.GetSafeHdc(), _PW_CLIENTONLY | _PW_RENDERFULLCONTENT
            )
            info = bmp.GetInfo()
            bits = bmp.GetBitmapBits(True)
            img = np.frombuffer(bits, dtype=np.uint8).reshape(
                (info["bmHeight"], info["bmWidth"], 4)
            )
            frame = np.ascontiguousarray(img[:, :, :3])  # BGRA → BGR (drop alpha)
            # cleanup
            win32gui.DeleteObject(bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)
            if not ok:
                log_debug("[win32] PrintWindow trả về 0 (frame có thể đen)")
            return frame
        except Exception as exc:
            log_error(f"[win32] Lỗi chụp cửa sổ: {exc}")
            return None

    # ── window management ──────────────────────────────────────────────────────
    def activate(self) -> bool:
        if not self.hwnd:
            return False
        win32gui, win32con = self._w[1], self._w[3]
        try:
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(self.hwnd)
            return True
        except Exception as exc:
            log_warning(f"[win32] activate lỗi: {exc}")
            return False

    def close_window(self) -> bool:
        if not self.hwnd:
            return False
        try:
            self._w[1].PostMessage(self.hwnd, _WM_CLOSE, 0, 0)
            return True
        except Exception:
            return False

    def launch_app(self, target: str) -> bool:
        """Start a program by exe path (with optional args), or focus a window
        whose title contains ``target`` if it's already open."""
        target = (target or "").strip()
        if not target:
            return False
        # If it's a runnable path, start it; else treat as a window title to focus.
        exe = target.split('"')[1] if target.startswith('"') else target.split(" ")[0]
        if os.path.exists(exe):
            try:
                subprocess.Popen(target, shell=True)
                return True
            except Exception as exc:
                log_error(f"[win32] Không mở được '{target}': {exc}")
                return False
        hwnd = self._find_hwnd(target, "title")
        if hwnd:
            self.hwnd = hwnd
            return self.activate()
        log_warning(f"[win32] launch: '{target}' không phải file tồn tại và không có cửa sổ khớp")
        return False

    # ── input: coordinates are CLIENT-area pixels (same space as capture) ──────
    def _foreground(self) -> bool:
        return self._match[2] == "foreground"

    def tap(self, x: int, y: int, duration: float = 0.1, tap_count: int = 1) -> bool:
        if not self.hwnd:
            return False
        if self._foreground():
            return self._tap_fg(x, y, duration, tap_count)
        return self._tap_bg(x, y, duration, tap_count)

    def _tap_bg(self, x, y, duration, tap_count) -> bool:
        win32gui = self._w[1]
        lp = _lparam(x, y)
        try:
            win32gui.PostMessage(self.hwnd, _WM_MOUSEMOVE, 0, lp)
            for i in range(max(1, int(tap_count))):
                down = _WM_LBUTTONDBLCLK if (tap_count >= 2 and i > 0) else _WM_LBUTTONDOWN
                win32gui.PostMessage(self.hwnd, down, _MK_LBUTTON, lp)
                time.sleep(max(0.02, float(duration)))
                win32gui.PostMessage(self.hwnd, _WM_LBUTTONUP, 0, lp)
                if tap_count >= 2:
                    time.sleep(0.04)
            return True
        except Exception as exc:
            log_error(f"[win32] tap(bg) lỗi: {exc}")
            return False

    def _tap_fg(self, x, y, duration, tap_count) -> bool:
        win32gui, win32api = self._w[1], self._w[4]
        try:
            self.activate()
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
            win32api.SetCursorPos((sx, sy))
            for _ in range(max(1, int(tap_count))):
                win32api.mouse_event(_ME_LDOWN, 0, 0, 0, 0)
                time.sleep(max(0.02, float(duration)))
                win32api.mouse_event(_ME_LUP, 0, 0, 0, 0)
                time.sleep(0.03)
            return True
        except Exception as exc:
            log_error(f"[win32] tap(fg) lỗi: {exc}")
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        if not self.hwnd:
            return False
        steps = max(2, int(max(1, duration) / 15))
        try:
            if self._foreground():
                win32gui, win32api = self._w[1], self._w[4]
                self.activate()
                sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x1), int(y1)))
                win32api.SetCursorPos((sx, sy))
                win32api.mouse_event(_ME_LDOWN, 0, 0, 0, 0)
                for i in range(1, steps + 1):
                    cx = int(x1 + (x2 - x1) * i / steps)
                    cy = int(y1 + (y2 - y1) * i / steps)
                    px, py = win32gui.ClientToScreen(self.hwnd, (cx, cy))
                    win32api.SetCursorPos((px, py))
                    time.sleep(duration / 1000.0 / steps)
                win32api.mouse_event(_ME_LUP, 0, 0, 0, 0)
            else:
                win32gui = self._w[1]
                win32gui.PostMessage(self.hwnd, _WM_LBUTTONDOWN, _MK_LBUTTON, _lparam(x1, y1))
                for i in range(1, steps + 1):
                    cx = int(x1 + (x2 - x1) * i / steps)
                    cy = int(y1 + (y2 - y1) * i / steps)
                    win32gui.PostMessage(self.hwnd, _WM_MOUSEMOVE, _MK_LBUTTON, _lparam(cx, cy))
                    time.sleep(duration / 1000.0 / steps)
                win32gui.PostMessage(self.hwnd, _WM_LBUTTONUP, 0, _lparam(x2, y2))
            return True
        except Exception as exc:
            log_error(f"[win32] swipe lỗi: {exc}")
            return False

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        return self.swipe(x1, y1, x2, y2, duration)

    def hold_and_release(self, x: int, y: int, duration: int = 1000) -> bool:
        return self.tap(x, y, duration=duration / 1000.0)

    def send_text(self, text: str) -> bool:
        """Type text into the window via WM_CHAR (works background & focused)."""
        if not self.hwnd:
            return False
        win32gui = self._w[1]
        try:
            if self._foreground():
                self.activate()
            for ch in str(text):
                win32gui.PostMessage(self.hwnd, _WM_CHAR, ord(ch), 0)
                time.sleep(0.005)
            return True
        except Exception as exc:
            log_error(f"[win32] send_text lỗi: {exc}")
            return False

    def press_key(self, keycode: int) -> bool:
        """Press a **Windows virtual-key code** (VK_*). Note: for Win32 projects
        the 'Key' node's number is a VK code, not an Android keycode."""
        if not self.hwnd:
            return False
        try:
            vk = int(keycode)
        except (TypeError, ValueError):
            return False
        try:
            if self._foreground():
                win32api = self._w[4]
                self.activate()
                win32api.keybd_event(vk, 0, 0, 0)
                time.sleep(0.03)
                win32api.keybd_event(vk, 0, _KE_KEYUP, 0)
            else:
                win32gui = self._w[1]
                win32gui.PostMessage(self.hwnd, _WM_KEYDOWN, vk, 0)
                time.sleep(0.03)
                win32gui.PostMessage(self.hwnd, _WM_KEYUP, vk, 0)
            return True
        except Exception as exc:
            log_error(f"[win32] press_key lỗi: {exc}")
            return False

    def go_back(self) -> bool:
        return self.press_key(_VK_ESCAPE)

    def go_home(self) -> bool:
        # No desktop analogue; treat as a no-op success so flows don't error.
        return True


class Win32GameAutomation(ADBGameAutomation):
    """ADBGameAutomation with a Win32 window controller + PrintWindow capture.

    Reuses the parent's template matcher, OCR and all find/wait/read helpers —
    only ``__init__`` and the capture path are overridden (input already
    delegates to ``self.adb``, which here is a :class:`Win32Controller`)."""

    def __init__(self, cfg: Optional[dict] = None, config: Optional[Config] = None,
                 ocr_backend: Optional[str] = None):
        # Intentionally NOT calling super().__init__ — that builds an ADBController
        # and probes ADB. We set up the same shared pieces without any ADB.
        import logging
        import threading
        self.adb = Win32Controller(cfg)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.running = False
        self._stop_event = threading.Event()
        self.config_file = None
        self.config = config or Config()

        self.capture_interval = self.config.capture_interval
        self.latest_screen: Optional[np.ndarray] = None
        self.screen_lock = threading.Lock()
        self.capture_thread: Optional[threading.Thread] = None
        self.capture_running = False

        self.is_debug = self.config.debug_mode
        self.is_debug_fail = self.config.debug_fail_mode
        # Window templates are captured at native size — no orientation sweep.
        self.auto_orientation_detection = False

        self.matcher = TemplateMatcher(cache_size=self.config.template_cache_size)
        self.visualizer = DebugVisualizer()
        self.ocr = OCRReader(backend=ocr_backend)
        self.metrics = None

        self.monitor = {"top": 0, "left": 0, "width": 0, "height": 0}
        self.templates_dir = ""

    def configure(self, cfg: dict) -> None:
        """Point at a (possibly different) target window / input mode."""
        self.adb.configure(cfg)

    def _update_screen_size(self):
        if not getattr(self.adb, "device", None):
            return
        w, h = self.adb.get_screen_size()
        if w > 0 and h > 0:
            self.monitor["width"] = w
            self.monitor["height"] = h

    def capture_screen(self) -> Optional[np.ndarray]:
        try:
            return self.adb.capture_frame()
        except Exception as exc:
            log_error(f"[win32] capture_screen lỗi: {exc}")
            return None

    def _continuous_capture_worker(self):
        log_info("[win32] Bắt đầu luồng chụp cửa sổ liên tục")
        while self.capture_running:
            try:
                screen = self.capture_screen()
                if screen is not None:
                    with self.screen_lock:
                        self.latest_screen = screen
                time.sleep(self.capture_interval)
            except Exception as exc:
                log_error(f"[win32] Lỗi luồng chụp: {exc}")
                time.sleep(self.capture_interval)
        log_info("[win32] Dừng luồng chụp cửa sổ")

    def start_continuous_capture(self):
        import threading
        if not self.capture_running:
            self.capture_running = True
            self.capture_thread = threading.Thread(
                target=self._continuous_capture_worker, daemon=True
            )
            self.capture_thread.start()
        # Seed one frame so the first node doesn't run against an empty screen.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self.get_latest_screen() is not None:
                return
            screen = self.capture_screen()
            if screen is not None:
                with self.screen_lock:
                    self.latest_screen = screen
                return
            time.sleep(0.05)
        log_warning("[win32] Đã bật chụp nhưng chưa có frame đầu tiên")
