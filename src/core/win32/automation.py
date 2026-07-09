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
import threading
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
_WM_ACTIVATE      = 0x0006
_WA_ACTIVE        = 1
_MK_LBUTTON       = 0x0001
_SMTO_ABORTIFHUNG = 0x0002
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

    ``cfg`` keys: ``window`` (title/class/PID to match), ``matchBy`` (``"title"``
    | ``"class"`` | ``"pid"``), ``inputMode``:
      - ``"background"``        — pure PostMessage; never touches the mouse. Many
        GDI apps accept it, but engines that poll the REAL cursor (Unity/Unreal
        games such as NIKKE) ignore the message coordinates.
      - ``"background_cursor"`` — MaaFramework-style ``SendMessageWithCursorPos``:
        pretend-activate via WM_ACTIVATE, briefly move the hardware cursor to
        the target, send the messages synchronously, restore the cursor. Works
        for cursor-polling games while the window stays behind others.
      - ``"background_frida_api"``   — Frida-injected hook of ``GetCursorPos`` /
        ``GetMessagePos`` inside the game process. The real cursor never moves
        and the window is never activated, but cursor-polling games read the
        faked coordinates. Requires ``pip install frida``.
      - ``"background_frida_engine"`` — Frida hook at the engine level
        (Unity Mono / IL2CPP) when available, otherwise falls back to the API
        hook. Same "no real cursor move" guarantee.
      - ``"foreground"``        — bring the window forward and use real mouse input.
    """

    def __init__(self, cfg: Optional[dict] = None):
        self._w = _import_win32()  # (ctypes, win32gui, win32ui, win32con, win32api, win32process)
        self.hwnd: Optional[int] = None
        self.cfg: dict = dict(cfg or {})
        # Capture method that last produced a usable frame ("print" | "wgc" |
        # "blt" | "screen") — probed on first capture, then reused. See
        # capture_frame.
        self._cap_method: Optional[str] = None
        # Windows Graphics Capture session state (lazily started by _cap_wgc).
        self._wgc: Optional[dict] = None
        # Frida-based input session (background_frida_* modes).
        self._frida: Optional["FridaWin32Input"] = None
        # ADBController-compat attributes the engine reads.
        self.device_id = None

    # ── config ────────────────────────────────────────────────────────────────
    def configure(self, cfg: dict) -> None:
        self.cfg = dict(cfg or {})
        # A config change may point at a different window — force a re-attach
        # and re-probe of the capture method.
        self.hwnd = None
        self._cap_method = None
        self._wgc_stop()
        # Drop any Frida session when leaving a frida-based input mode.
        new_mode = str(self.cfg.get("inputMode", "background")).strip().lower()
        if not new_mode.startswith("background_frida") and self._frida is not None:
            self._frida.detach()
            self._frida = None

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
        self._warn_if_uipi_blocked()
        return True

    # ── UIPI (integrity level) check ───────────────────────────────────────────
    # Windows blocks PostMessage/SendInput from a lower-integrity process to a
    # higher one ("Access is denied", winerror 5). Typical case: the game runs
    # as Administrator while this tool doesn't — capture still works, input not.

    @staticmethod
    def _integrity_level(process_handle) -> int:
        import win32security
        tok = win32security.OpenProcessToken(process_handle, 0x0008)  # TOKEN_QUERY
        sid, _ = win32security.GetTokenInformation(tok, win32security.TokenIntegrityLevel)
        # Integrity SID is S-1-16-<level>: 0x2000 medium, 0x3000 high/admin.
        return int(win32security.ConvertSidToStringSid(sid).rsplit("-", 1)[1])

    def _warn_if_uipi_blocked(self) -> None:
        try:
            win32api, win32process = self._w[4], self._w[5]
            pid = win32process.GetWindowThreadProcessId(self.hwnd)[1]
            ph = win32api.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if self._integrity_level(ph) > self._integrity_level(win32api.GetCurrentProcess()):
                log_error(
                    "[win32] ⚠ Cửa sổ mục tiêu chạy quyền CAO HƠN tool (Run as "
                    "Administrator) — Windows (UIPI) sẽ chặn mọi thao tác "
                    "chuột/phím (Access is denied), chỉ xem/capture được. "
                    "→ Đóng tool và mở lại bằng 'Run as Administrator'."
                )
        except Exception:
            pass  # best-effort — never block attach on the diagnostics

    def _input_error(self, api: str, exc: Exception) -> None:
        """Log an input failure; error 5 gets the actionable UIPI explanation."""
        code = getattr(exc, "winerror", None)
        if code is None and getattr(exc, "args", None):
            code = exc.args[0] if isinstance(exc.args[0], int) else None
        if code == 5:
            log_error(
                f"[win32] {api} bị chặn (Access is denied) — game đang chạy quyền "
                "Admin cao hơn tool. Mở lại tool bằng 'Run as Administrator'."
            )
        else:
            log_error(f"[win32] {api} lỗi: {exc}")

    def _find_hwnd(self, pattern: str, by: str) -> Optional[int]:
        win32gui, win32process = self._w[1], self._w[5]
        low = pattern.lower()
        use_glob = any(ch in pattern for ch in "*?[")
        want_pid: Optional[int] = None
        if by == "pid":
            try:
                want_pid = int(pattern)
            except (TypeError, ValueError):
                log_error(f"[win32] PID không hợp lệ: '{pattern}'")
                return None
        found: List[int] = []

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            if by == "pid":
                try:
                    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                except Exception:
                    return
                # Only top-level windows with a title, so an invisible helper
                # window of the same process doesn't win over the real one.
                ok = (pid == want_pid) and bool(win32gui.GetWindowText(hwnd))
            elif by == "class":
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

    # ── capture (PrintWindow / WGC / BitBlt / screen crop → BGR ndarray) ───────
    # GPU-composited windows (DirectX/OpenGL games, emulators) often hand one
    # API a black frame while another works fine:
    #   print  — PrintWindow(PW_CLIENTONLY|PW_RENDERFULLCONTENT): captures most
    #            composited windows even when covered; some GPU swapchains → black.
    #   wgc    — Windows Graphics Capture: reads the DWM composition surface, so
    #            it captures GPU games (Unity/DirectX) even when covered by other
    #            windows. Needs the ``windows-capture`` package (Win10 1903+).
    #            A returned frame is authoritative — a black WGC frame means the
    #            window really is black, so no fall-through to blt/screen (those
    #            can "succeed" with the WRONG pixels: whatever covers the window).
    #   blt    — BitBlt from the window's client DC: classic GDI windows.
    #   screen — crop the desktop at the window's client rect: always has pixels,
    #            but the window must be on-screen and not covered by others.
    # capture_frame probes them in order, caches the first that yields a usable
    # frame and keeps using it (re-probing if it goes black again).
    def capture_frame(self) -> Optional[np.ndarray]:
        if not self.hwnd:
            return None
        win32gui, win32con = self._w[1], self._w[3]
        try:
            if not win32gui.IsWindow(self.hwnd):
                log_warning("[win32] Cửa sổ mục tiêu đã đóng")
                self.hwnd = None
                self._wgc_stop()
                return None
            if win32gui.IsIconic(self.hwnd):
                # A minimized window has no client pixels to copy — restore it
                # (the one capture case that must touch the window's state).
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                time.sleep(0.2)
            l, t, r, b = win32gui.GetClientRect(self.hwnd)
            w, h = r - l, b - t
            if w <= 0 or h <= 0:
                return None
        except Exception as exc:
            log_error(f"[win32] Lỗi chụp cửa sổ: {exc}")
            return None
        methods = ["print", "wgc", "blt", "screen"]
        if self._cap_method in methods:
            methods.remove(self._cap_method)
            methods.insert(0, self._cap_method)
        dark = None
        for name in methods:
            try:
                img = getattr(self, "_cap_" + name)(w, h)
            except Exception as exc:
                log_debug(f"[win32] capture '{name}' lỗi: {exc}")
                img = None
            if img is None:
                continue
            # WGC frames are trusted even when black (see note above); the GDI
            # methods fall through on a black frame to try the next API.
            if name != "wgc" and int(img.max()) < 8:
                if dark is None:
                    dark = img
                continue
            if name != self._cap_method:
                self._cap_method = name
                extra = " — cửa sổ phải hiện trên màn hình, không bị che" if name == "screen" else ""
                log_info(f"[win32] Capture dùng phương pháp '{name}'{extra}")
            return img
        # Every method came back black — likely the screen really is black.
        return dark

    # ── Windows Graphics Capture session (windows-capture package) ─────────────
    def _wgc_stop(self) -> None:
        s, self._wgc = self._wgc, None
        if s and s.get("control") is not None:
            try:
                s["control"].stop()
            except Exception:
                pass

    def _cap_wgc(self, w, h) -> Optional[np.ndarray]:
        s = self._wgc
        if s is not None and s.get("hwnd") != self.hwnd:
            self._wgc_stop()
            s = None
        if s is not None and s.get("dead"):
            return None
        if s is None:
            try:
                from windows_capture import WindowsCapture
            except ImportError:
                log_debug("[win32] gói 'windows-capture' chưa cài (pip install windows-capture)")
                return None
            s = {"hwnd": self.hwnd, "lock": threading.Lock(), "frame": None,
                 "event": threading.Event(), "control": None, "dead": False}
            # NOTE: draw_border is left untouched — toggling it off needs Win11;
            # on Win10 the OS draws a yellow border around the captured window.
            cap = WindowsCapture(cursor_capture=False, window_hwnd=self.hwnd)

            @cap.event
            def on_frame_arrived(frame, control):  # noqa: ANN001
                buf = frame.frame_buffer  # BGRA
                with s["lock"]:
                    s["frame"] = np.ascontiguousarray(buf[:, :, :3])
                s["event"].set()

            @cap.event
            def on_closed():
                s["dead"] = True
                s["event"].set()

            try:
                s["control"] = cap.start_free_threaded()
            except Exception as exc:
                log_debug(f"[win32] WGC không khởi động được: {exc}")
                return None
            self._wgc = s
        if not s["event"].wait(timeout=2.0) or s.get("dead"):
            return None
        with s["lock"]:
            frame = s["frame"]
        if frame is None:
            return None
        # WGC frames cover the whole window (title bar + borders included) and
        # their size varies between the full GetWindowRect bounds and the
        # visible window, so window-rect offsets can't be trusted. Anchor on
        # window geometry instead: side/bottom borders are equal, the rest of
        # the top is the title bar → client sits centred at the bottom.
        fh, fw = frame.shape[:2]
        if fw >= w and fh >= h and (fw != w or fh != h):
            bx = (fw - w) // 2               # left border = right border
            cy = max(0, fh - h - bx)          # bottom border = side border
            frame = frame[cy:cy + h, bx:bx + w]
        return np.ascontiguousarray(frame)

    def _dib(self, src_dc, w, h, blit) -> Optional[np.ndarray]:
        """Copy ``w×h`` pixels into a DIB via ``blit(save_dc, src_mfc_dc)`` and
        return them as a BGR ndarray. The caller owns ``src_dc``."""
        win32gui, win32ui = self._w[1], self._w[2]
        mfc_dc = win32ui.CreateDCFromHandle(src_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        try:
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)
            if not blit(save_dc, mfc_dc):
                return None
            info = bmp.GetInfo()
            bits = bmp.GetBitmapBits(True)
            img = np.frombuffer(bits, dtype=np.uint8).reshape(
                (info["bmHeight"], info["bmWidth"], 4)
            )
            return np.ascontiguousarray(img[:, :, :3])  # BGRA → BGR (drop alpha)
        finally:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()

    def _cap_print(self, w, h) -> Optional[np.ndarray]:
        ctypes, win32gui = self._w[0], self._w[1]
        hwnd_dc = win32gui.GetWindowDC(self.hwnd)

        def blit(save_dc, _mfc):
            ok = ctypes.windll.user32.PrintWindow(
                self.hwnd, save_dc.GetSafeHdc(), _PW_CLIENTONLY | _PW_RENDERFULLCONTENT)
            if not ok:
                log_debug("[win32] PrintWindow trả về 0 (frame có thể đen)")
            return True  # some windows paint fine despite returning 0

        try:
            return self._dib(hwnd_dc, w, h, blit)
        finally:
            win32gui.ReleaseDC(self.hwnd, hwnd_dc)

    def _cap_blt(self, w, h) -> Optional[np.ndarray]:
        win32gui, win32con = self._w[1], self._w[3]
        hdc = win32gui.GetDC(self.hwnd)  # client-area DC
        try:
            return self._dib(hdc, w, h, lambda save_dc, mfc_dc: (
                save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY), True)[1])
        finally:
            win32gui.ReleaseDC(self.hwnd, hdc)

    def _cap_screen(self, w, h) -> Optional[np.ndarray]:
        win32gui, win32con = self._w[1], self._w[3]
        sx, sy = win32gui.ClientToScreen(self.hwnd, (0, 0))
        desk_dc = win32gui.GetDC(0)
        try:
            return self._dib(desk_dc, w, h, lambda save_dc, mfc_dc: (
                save_dc.BitBlt((0, 0), (w, h), mfc_dc, (sx, sy), win32con.SRCCOPY), True)[1])
        finally:
            win32gui.ReleaseDC(0, desk_dc)

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

    def _get_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        """Return (left, top, right, bottom) in screen coordinates, or None."""
        if not self.hwnd:
            return None
        try:
            return self._w[1].GetWindowRect(self.hwnd)
        except Exception:
            return None

    def _is_borderless(self) -> bool:
        """Detect borderless / popup window (no caption bar = engine-managed)."""
        if not self.hwnd:
            return False
        try:
            win32con, win32api = self._w[3], self._w[4]
            style = win32api.GetWindowLong(self.hwnd, win32con.GWL_STYLE)
            # Borderless games usually use WS_POPUP without WS_CAPTION / WS_THICKFRAME.
            has_caption = bool(style & win32con.WS_CAPTION)
            has_thickframe = bool(style & win32con.WS_THICKFRAME)
            return not has_caption and not has_thickframe
        except Exception:
            return False

    def resize_window(self, width: int, height: int) -> bool:
        if not self.hwnd:
            return False
        win32gui, win32con = self._w[1], self._w[3]
        try:
            rect = self._get_window_rect()
            if rect is None:
                return False
            l, t, r, b = rect

            # If maximized, restore first so resize can take effect.
            placement = win32gui.GetWindowPlacement(self.hwnd)
            if placement[1] == win32con.SW_SHOWMAXIMIZED:
                log_info("[win32] window is maximized → restoring before resize")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                time.sleep(0.05)

            borderless = self._is_borderless()
            if borderless:
                log_warning(
                    "[win32] ⚠ Cửa sổ đang borderless (WS_POPUP, không viền). "
                    "Game engine (Unity/DirectX) tự quản lý swapchain và thường ignore WM_SIZE. "
                    "Resize qua Win32 API CÓ THỂ không có hiệu lực. "
                    "→ Gợi ý: chuyển game sang Windowed mode (có viền) trong Settings game, "
                    "hoặc dùng node 'Win style' để ép windowed (experimental)."
                )

            # Use MoveWindow (sends WM_SIZE). For borderless outer rect = client rect.
            win32gui.MoveWindow(self.hwnd, l, t, int(width), int(height), True)
            log_info(f"[win32] resize_window {l},{t} → {width}×{height}  (borderless={borderless})")
            return True
        except Exception as exc:
            log_warning(f"[win32] resize_window lỗi: {exc}")
            return False

    def move_window(self, x: int, y: int) -> bool:
        if not self.hwnd:
            return False
        win32gui = self._w[1]
        try:
            rect = self._get_window_rect()
            if rect is None:
                return False
            _, _, r, b = rect
            w, h = r - rect[0], b - rect[1]
            win32gui.MoveWindow(self.hwnd, int(x), int(y), w, h, True)
            log_info(f"[win32] move_window → ({x}, {y})  size {w}×{h}")
            return True
        except Exception as exc:
            log_warning(f"[win32] move_window lỗi: {exc}")
            return False

    def minimize_window(self) -> bool:
        if not self.hwnd:
            return False
        win32con = self._w[3]
        try:
            self._w[1].ShowWindow(self.hwnd, win32con.SW_MINIMIZE)
            return True
        except Exception as exc:
            log_warning(f"[win32] minimize_window lỗi: {exc}")
            return False

    def maximize_window(self) -> bool:
        if not self.hwnd:
            return False
        win32con = self._w[3]
        try:
            self._w[1].ShowWindow(self.hwnd, win32con.SW_MAXIMIZE)
            return True
        except Exception as exc:
            log_warning(f"[win32] maximize_window lỗi: {exc}")
            return False

    def restore_window(self) -> bool:
        if not self.hwnd:
            return False
        win32con = self._w[3]
        try:
            self._w[1].ShowWindow(self.hwnd, win32con.SW_RESTORE)
            return True
        except Exception as exc:
            log_warning(f"[win32] restore_window lỗi: {exc}")
            return False

    def set_always_on_top(self, on_top: bool = True) -> bool:
        if not self.hwnd:
            return False
        win32gui, win32con = self._w[1], self._w[3]
        try:
            z = win32con.HWND_TOPMOST if on_top else win32con.HWND_NOTOPMOST
            win32gui.SetWindowPos(self.hwnd, z, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW)
            return True
        except Exception as exc:
            log_warning(f"[win32] set_always_on_top lỗi: {exc}")
            return False

    def set_window_title(self, title: str) -> bool:
        if not self.hwnd:
            return False
        try:
            self._w[1].SetWindowText(self.hwnd, str(title))
            return True
        except Exception as exc:
            log_warning(f"[win32] set_window_title lỗi: {exc}")
            return False

    def set_window_style(self, style_name: str = "windowed") -> bool:
        """Experimental: change window style between windowed/borderless/popup.
        
        WARNING: Game engines may crash or fail to recreate swapchain when style
        changes mid-flight. Use only when the game tolerates it."""
        if not self.hwnd:
            return False
        win32gui, win32con, win32api = self._w[1], self._w[3], self._w[4]
        try:
            style = win32api.GetWindowLong(self.hwnd, win32con.GWL_STYLE)
            exstyle = win32api.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
            s = str(style_name).strip().lower()
            if s == "windowed":
                # Standard overlapped window with caption, border, thick frame
                new_style = (win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE) & ~win32con.WS_POPUP
                new_exstyle = exstyle & ~win32con.WS_EX_TOPMOST
            elif s == "borderless":
                # Borderless popup: no caption, no thick frame
                new_style = (win32con.WS_POPUP | win32con.WS_VISIBLE | win32con.WS_CLIPCHILDREN) & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME & ~win32con.WS_SYSMENU & ~win32con.WS_MINIMIZEBOX & ~win32con.WS_MAXIMIZEBOX
                new_exstyle = exstyle & ~win32con.WS_EX_TOPMOST
            elif s == "popup":
                # Simple popup (may also be used by some engines)
                new_style = win32con.WS_POPUP | win32con.WS_VISIBLE | win32con.WS_CLIPCHILDREN
                new_exstyle = exstyle
            else:
                log_warning(f"[win32] unknown style '{style_name}' — use windowed/borderless/popup")
                return False

            win32api.SetWindowLong(self.hwnd, win32con.GWL_STYLE, new_style)
            win32api.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, new_exstyle)
            win32gui.SetWindowPos(
                self.hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED | win32con.SWP_NOACTIVATE
            )
            log_info(f"[win32] set_window_style → {s} (experimental)")
            return True
        except Exception as exc:
            log_warning(f"[win32] set_window_style lỗi: {exc}")
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

    def _cursor_mode(self) -> bool:
        return self._match[2] == "background_cursor"

    def _frida_mode(self) -> bool:
        m = self._match[2]
        return m in ("background_frida_api", "background_frida_engine")

    def _send(self, msg: int, wparam: int, lparam: int) -> None:
        """SendMessage with an abort-if-hung timeout so a frozen game can't
        stall the whole engine thread."""
        self._w[1].SendMessageTimeout(self.hwnd, msg, wparam, lparam, _SMTO_ABORTIFHUNG, 1000)

    def tap(self, x: int, y: int, duration: float = 0.1, tap_count: int = 1) -> bool:
        if not self.hwnd:
            return False
        if self._foreground():
            return self._tap_fg(x, y, duration, tap_count)
        if self._cursor_mode():
            return self._tap_bg_cursor(x, y, duration, tap_count)
        if self._frida_mode():
            return self._tap_bg_frida(x, y, duration, tap_count)
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
            self._input_error("tap(bg)", exc)
            return False

    def _tap_bg_cursor(self, x, y, duration, tap_count) -> bool:
        """MaaFramework-style ``SendMessageWithCursorPos`` click.

        Games that poll the REAL cursor (Unity/Unreal — NIKKE etc.) take the
        click position from GetCursorPos, not the message's lParam. Sequence:
        WM_ACTIVATE (window believes it's active, foreground unchanged) →
        SetCursorPos to target → WM_MOUSEMOVE → WM_LBUTTONDOWN/UP, all sent
        synchronously — then restore the cursor. The cursor leaves the user's
        position for only ~30 ms per click; the window may stay covered."""
        win32gui, win32api = self._w[1], self._w[4]
        lp = _lparam(x, y)
        saved = None
        try:
            saved = win32api.GetCursorPos()
        except Exception:
            pass
        try:
            self._send(_WM_ACTIVATE, _WA_ACTIVE, 0)
            time.sleep(0.01)
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
            for i in range(max(1, int(tap_count))):
                win32api.SetCursorPos((sx, sy))
                time.sleep(0.001)
                self._send(_WM_MOUSEMOVE, 0, lp)
                time.sleep(0.01)
                self._send(_WM_LBUTTONDOWN, _MK_LBUTTON, lp)
                time.sleep(max(0.02, float(duration)))
                self._send(_WM_LBUTTONUP, 0, lp)
                if tap_count >= 2:
                    time.sleep(0.04)
            return True
        except Exception as exc:
            self._input_error("tap(bg+cursor)", exc)
            return False
        finally:
            if saved is not None:
                try:
                    win32api.SetCursorPos(saved)
                except Exception:
                    pass

    def _swipe_bg_cursor(self, x1, y1, x2, y2, duration) -> bool:
        """Cursor-pos variant of a background swipe: the hardware cursor traces
        the gesture (so cursor-polling games see it) while the button messages
        go to the window — the window itself may stay in the background."""
        win32gui, win32api = self._w[1], self._w[4]
        steps = max(2, int(max(1, duration) / 15))
        saved = None
        try:
            saved = win32api.GetCursorPos()
        except Exception:
            pass
        try:
            self._send(_WM_ACTIVATE, _WA_ACTIVE, 0)
            time.sleep(0.01)
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x1), int(y1)))
            win32api.SetCursorPos((sx, sy))
            time.sleep(0.001)
            self._send(_WM_MOUSEMOVE, 0, _lparam(x1, y1))
            time.sleep(0.01)
            self._send(_WM_LBUTTONDOWN, _MK_LBUTTON, _lparam(x1, y1))
            for i in range(1, steps + 1):
                cx = int(x1 + (x2 - x1) * i / steps)
                cy = int(y1 + (y2 - y1) * i / steps)
                px, py = win32gui.ClientToScreen(self.hwnd, (cx, cy))
                win32api.SetCursorPos((px, py))
                self._send(_WM_MOUSEMOVE, _MK_LBUTTON, _lparam(cx, cy))
                time.sleep(duration / 1000.0 / steps)
            self._send(_WM_LBUTTONUP, 0, _lparam(x2, y2))
            return True
        except Exception as exc:
            self._input_error("swipe(bg+cursor)", exc)
            return False
        finally:
            if saved is not None:
                try:
                    win32api.SetCursorPos(saved)
                except Exception:
                    pass

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
            self._input_error("tap(fg)", exc)
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        if not self.hwnd:
            return False
        if self._cursor_mode():
            return self._swipe_bg_cursor(x1, y1, x2, y2, duration)
        if self._frida_mode():
            return self._swipe_bg_frida(x1, y1, x2, y2, duration)
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
            self._input_error("swipe", exc)
            return False

    def _ensure_frida(self) -> bool:
        """Lazy-attach Frida to the current window's PID when needed."""
        if self._frida is None:
            from .frida_input import FridaWin32Input
            self._frida = FridaWin32Input()
        if not self.hwnd:
            return False
        win32process = self._w[5]
        _, pid = win32process.GetWindowThreadProcessId(self.hwnd)
        if not self._frida.ready or self._frida.pid != pid:
            strategy = "engine" if self._match[2] == "background_frida_engine" else "api"
            return self._frida.attach(self.hwnd, strategy=strategy)
        return True

    def _tap_bg_frida(self, x, y, duration, tap_count) -> bool:
        """Frida-based tap: hooks GetCursorPos/GetMessagePos inside the game
        so the game reads fake coordinates while the real cursor never moves."""
        win32gui = self._w[1]
        lp = _lparam(x, y)
        try:
            if not self._ensure_frida():
                return False
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
            self._frida.set_target(sx, sy)
            win32gui.PostMessage(self.hwnd, _WM_MOUSEMOVE, 0, lp)
            for i in range(max(1, int(tap_count))):
                down = _WM_LBUTTONDBLCLK if (tap_count >= 2 and i > 0) else _WM_LBUTTONDOWN
                win32gui.PostMessage(self.hwnd, down, _MK_LBUTTON, lp)
                time.sleep(max(0.02, float(duration)))
                win32gui.PostMessage(self.hwnd, _WM_LBUTTONUP, 0, lp)
                if tap_count >= 2:
                    time.sleep(0.04)
            self._frida.clear_target()
            return True
        except Exception as exc:
            self._input_error("tap(frida)", exc)
            return False

    def _swipe_bg_frida(self, x1, y1, x2, y2, duration) -> bool:
        """Frida-based swipe: updates the hooked cursor position each step."""
        win32gui = self._w[1]
        steps = max(2, int(max(1, duration) / 15))
        try:
            if not self._ensure_frida():
                return False
            win32gui.PostMessage(self.hwnd, _WM_LBUTTONDOWN, _MK_LBUTTON, _lparam(x1, y1))
            for i in range(1, steps + 1):
                cx = int(x1 + (x2 - x1) * i / steps)
                cy = int(y1 + (y2 - y1) * i / steps)
                sx, sy = win32gui.ClientToScreen(self.hwnd, (cx, cy))
                self._frida.set_target(sx, sy)
                win32gui.PostMessage(self.hwnd, _WM_MOUSEMOVE, _MK_LBUTTON, _lparam(cx, cy))
                time.sleep(duration / 1000.0 / steps)
            self._frida.clear_target()
            win32gui.PostMessage(self.hwnd, _WM_LBUTTONUP, 0, _lparam(x2, y2))
            return True
        except Exception as exc:
            self._input_error("swipe(frida)", exc)
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
            self._input_error("send_text", exc)
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
            self._input_error("press_key", exc)
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
