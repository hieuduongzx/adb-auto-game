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
import socket
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.utils import log_error, log_info, log_warning, log_debug, LOG_KIND_ACTIVITY
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
_WM_RBUTTONDOWN   = 0x0204
_WM_RBUTTONUP     = 0x0205
_WM_RBUTTONDBLCLK = 0x0206
_WM_MBUTTONDOWN   = 0x0207
_WM_MBUTTONUP     = 0x0208
_WM_MBUTTONDBLCLK = 0x0209
_WM_MOUSEWHEEL    = 0x020A
_WM_MOUSEHWHEEL   = 0x020E
_WM_KEYDOWN       = 0x0100
_WM_KEYUP         = 0x0101
_WM_CHAR          = 0x0102
_WM_SYSKEYDOWN    = 0x0104
_WM_SYSKEYUP      = 0x0105
_WM_CLOSE         = 0x0010
_WM_ACTIVATE      = 0x0006
_WA_ACTIVE        = 1
_MK_LBUTTON       = 0x0001
_MK_RBUTTON       = 0x0002
_MK_MBUTTON       = 0x0010
# SetWindowPos flags used by the window-pos input mode.
_SWP_NOSIZE = 0x0001; _SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004; _SWP_NOACTIVATE = 0x0010
# Synthetic-pointer (WM_POINTER) injection — see _tap_anchored.
_PT_TOUCH = 0x00000002
_POINTER_FLAG_INRANGE    = 0x00000002
_POINTER_FLAG_INCONTACT  = 0x00000004
_POINTER_FLAG_PRIMARY    = 0x00002000
_POINTER_FLAG_CONFIDENCE = 0x00004000
_POINTER_FLAG_DOWN       = 0x00010000
_POINTER_FLAG_UPDATE     = 0x00020000
_POINTER_FLAG_UP         = 0x00040000
_TOUCH_MASK_CONTACTAREA  = 0x00000001
_TOUCH_MASK_PRESSURE     = 0x00000004
_WS_EX_LAYERED    = 0x00080000
_LWA_ALPHA        = 0x00000002
_HWND_TOPMOST     = -1
_HWND_NOTOPMOST   = -2
_SMTO_ABORTIFHUNG = 0x0002
_PW_CLIENTONLY        = 0x1
_PW_RENDERFULLCONTENT = 0x2  # capture DirectComposition/GPU content (Win 8.1+)
_VK_ESCAPE        = 0x1B
_VK_SHIFT = 0x10; _VK_CONTROL = 0x11; _VK_MENU = 0x12; _VK_LWIN = 0x5B
_WHEEL_DELTA      = 120
# mouse_event flags (foreground)
_ME_MOVE = 0x0001; _ME_ABSOLUTE = 0x8000
_ME_LDOWN = 0x0002; _ME_LUP = 0x0004
_ME_RDOWN = 0x0008; _ME_RUP = 0x0010
_ME_MDOWN = 0x0020; _ME_MUP = 0x0040
_ME_WHEEL = 0x0800; _ME_HWHEEL = 0x1000
_KE_KEYUP = 0x0002
_KE_EXTENDEDKEY = 0x0001
# Keys whose scan code carries the "extended" flag (bit 24 of a key message's
# lParam, KEYEVENTF_EXTENDEDKEY for keybd_event): navigation cluster, arrows,
# right-hand Ctrl/Alt, Windows keys, numpad divide, Num Lock.
_EXTENDED_VKS = frozenset((0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E,
                           0x5B, 0x5C, 0x6F, 0x90, 0xA3, 0xA5))

# Per-button message triples used by the generalised click path:
#   button -> (WM_*BUTTONDOWN, WM_*BUTTONUP, WM_*BUTTONDBLCLK, MK_* flag,
#              mouse_event down flag, mouse_event up flag)
_MOUSE_BUTTONS = {
    "left":   (_WM_LBUTTONDOWN, _WM_LBUTTONUP, _WM_LBUTTONDBLCLK, _MK_LBUTTON, _ME_LDOWN, _ME_LUP),
    "right":  (_WM_RBUTTONDOWN, _WM_RBUTTONUP, _WM_RBUTTONDBLCLK, _MK_RBUTTON, _ME_RDOWN, _ME_RUP),
    "middle": (_WM_MBUTTONDOWN, _WM_MBUTTONUP, _WM_MBUTTONDBLCLK, _MK_MBUTTON, _ME_MDOWN, _ME_MUP),
}

# Modifier name -> virtual-key, for the hotkey (combo) path.
_MODIFIER_VKS = {"ctrl": _VK_CONTROL, "shift": _VK_SHIFT, "alt": _VK_MENU, "win": _VK_LWIN}

# Every input transport the Win32 controller understands. The first four route
# through window messages; the last two use native cursor / pointer injection.
_INPUT_MODES = ("background", "background_sync", "background_cursor",
                "background_window", "anchored_touch", "unity_bridge", "foreground")
# unity_bridge: TCP line protocol served by an in-game plugin (BD2MOD InputBridge).
_BRIDGE_DEFAULT_PORT = 17820


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


def process_exe_name(pid: int) -> str:
    """Return a process executable basename using limited query rights."""
    path = process_exe_path(pid)
    return os.path.basename(path) if path else ""


def process_exe_path(pid: int) -> str:
    """Return a process's full executable path using limited query rights."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buf))
            if not kernel32.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buf, ctypes.byref(size)):
                return ""
            return buf.value
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        return ""


class Win32Controller:
    """ADBController stand-in that talks to a native window instead of a device.

    ``cfg`` keys: ``window`` (title/class/PID/executable to match), ``matchBy``
    (``"title"`` | ``"class"`` | ``"pid"`` | ``"exe"``), ``inputMode``:
      - ``"background"``        — asynchronous PostMessage; never touches the mouse.
      - ``"background_sync"``   — synchronous SendMessageTimeout; useful for apps
        that drop or defer queued PostMessage input.
      - ``"background_cursor"`` — MaaFramework-style ``SendMessageWithCursorPos``:
        pretend-activate via WM_ACTIVATE, briefly move the hardware cursor to
        the target, send the messages synchronously, restore the cursor. Works
        for cursor-polling games while the window stays behind others.
      - ``"background_window"`` — ``SendMessageWithWindowPos``: briefly slide the
        WINDOW so the target point sits under the (unmoved) cursor, send the
        messages, restore. Either the cursor or the window moves — this mode
        never touches the cursor, so it is safe while the user works elsewhere.
        The window flickers for a frame per click.
      - ``"anchored_touch"``    — inject a synthetic touch contact
        (``InjectSyntheticPointerInput``): the window gets ``WM_POINTER`` events
        with no cursor movement and no foreground change. Best for touch-aware
        games (Unity), unavailable before Windows 10 1809.
      - ``"unity_bridge"``      — send tap/swipe to an in-game plugin over
        127.0.0.1 (``bridgePort``, default 17820) which fires them through
        Unity's EventSystem: no cursor, no focus, window may be covered. Falls
        back to anchored_touch when the plugin is unreachable or hits no UI.
      - ``"foreground"``        — bring the window forward and use real mouse input.
    """

    def __init__(self, cfg: Optional[dict] = None):
        self._w = _import_win32()  # (ctypes, win32gui, win32ui, win32con, win32api, win32process)
        self._held_keys: set = set()   # VKs left down by press_key(action="down")
        self._bridge_key_warned = False
        self.hwnd: Optional[int] = None
        self.cfg: dict = dict(cfg or {})
        # Capture method that last produced a usable frame ("print" | "wgc" |
        # "blt" | "screen") — probed on first capture, then reused. See
        # capture_frame.
        self._cap_method: Optional[str] = None
        # Windows Graphics Capture session state (lazily started by _cap_wgc).
        self._wgc: Optional[dict] = None
        # ADBController-compat attributes the engine reads.
        self.device_id = None
        # PID of the most recently started program. Used by an initial
        # win_launch node to attach its window without preconfigured title.
        self.last_launch_pid: Optional[int] = None
        # anchored_touch state: the synthetic touch device + primary-pointer
        # anchor window (built lazily) and a one-shot flag so the "not
        # supported" warning isn't logged per click.
        self._touch_dev = None
        self._anchors: Dict[int, object] = {}  # input thread id -> AnchorWindow
        self._anchored_warned = False
        self._bridge_warned = False
        self._bridge_miss_warned = False
        # When attach fails we dump the open windows to help diagnose a bad
        # target; throttled because an unattached preview retries repeatedly.
        self._window_list_at = 0.0

    # ── config ────────────────────────────────────────────────────────────────
    def configure(self, cfg: dict) -> None:
        self.cfg = dict(cfg or {})
        # A config change may point at a different window — force a re-attach
        # and re-probe of the capture method.
        self.hwnd = None
        self._cap_method = None
        self._wgc_stop()
        self._touch_stop()
        self._bridge_warned = False
        self._bridge_miss_warned = False

    def _touch_stop(self) -> None:
        """Release the synthetic touch device + anchor window (if any)."""
        dev, self._touch_dev = self._touch_dev, None
        anchors, self._anchors = self._anchors, {}
        self._anchored_warned = False
        for anchor in anchors.values():
            try:
                anchor.close()
            except Exception:
                pass
        if dev:
            try:
                dev.close()
            except Exception:
                pass

    @property
    def _match(self) -> Tuple[str, str, str]:
        mode = str(self.cfg.get("inputMode", "background")).strip().lower()
        if mode not in _INPUT_MODES:
            mode = "background"
        return (
            str(self.cfg.get("window", "")).strip(),
            str(self.cfg.get("matchBy", "title")).strip().lower() or "title",
            mode,
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
        if not hwnd and by == "title":
            # A game started as Administrator has an unreadable title (UIPI
            # blocks WM_GETTEXT, so GetWindowText returns ""), and a localised
            # client's title may simply differ — in both cases no title ever
            # matches. Fall back to the configured program's exe name, which
            # needs only PROCESS_QUERY_LIMITED_INFORMATION (never UIPI-blocked).
            exe = self._exe_pattern()
            if exe:
                hwnd = self._find_hwnd(exe, "exe")
                if hwnd:
                    log_info(f"[win32] Không khớp tiêu đề '{pattern}' — "
                             f"gắn theo chương trình '{exe}' thay thế")
        if not hwnd:
            log_warning(f"[win32] Không tìm thấy cửa sổ khớp '{pattern}' ({by})")
            self._log_window_list()
            self.hwnd = None
            return False
        self.hwnd = hwnd
        _, win32gui = self._w[0], self._w[1]
        title = win32gui.GetWindowText(hwnd) or "(tiêu đề không đọc được)"
        log_info(f"[win32] Gắn cửa sổ 0x{hwnd:X} — '{title}'")
        self._warn_if_uipi_blocked()
        if self._bridge_mode():
            self._check_bridge()
        return True

    def _bridge_port(self) -> int:
        try:
            return int(self.cfg.get("bridgePort") or _BRIDGE_DEFAULT_PORT)
        except (TypeError, ValueError):
            return _BRIDGE_DEFAULT_PORT

    def _check_bridge(self) -> None:
        """Announce whether the in-game Unity Bridge answers, right after attach.

        A ``unity_bridge`` workflow is chosen precisely because message-based
        input is ignored by the game, yet when the plugin is missing the code
        silently falls back to ``anchored_touch``, which many Unity games also
        ignore — so the operator sees "the window is there but nothing happens"
        with no clue. This probes 127.0.0.1 and says exactly what to fix."""
        try:
            from src.core.win32 import unity_bridge
        except Exception:
            return
        port = self._bridge_port()
        reply = unity_bridge.ping(port)
        if reply and reply.startswith("ok"):
            log_info(f"[win32] unity_bridge đã kết nối plugin 127.0.0.1:{port} — {reply}")
        else:
            log_error(
                f"[win32] unity_bridge KHÔNG kết nối được plugin tại 127.0.0.1:{port} "
                "(game chưa nạp BepInEx/Macro2kBridge, hoặc plugin lỗi). "
                "Sau khi copy file game (Settings → Game files) PHẢI khởi động lại game; "
                "kiểm tra BepInEx\\LogOutput.log trong thư mục game. "
                "Trong lúc đó tool tạm dùng anchored_touch nên có thể không điều khiển được."
            )
        # Either way one message is enough — stop _bridge_call repeating it.
        self._bridge_warned = True

    def _exe_pattern(self) -> str:
        """Basename of the configured game program (``cfg['path']``)."""
        path = str(self.cfg.get("path", "")).strip()
        return os.path.basename(path) if path else ""

    def _log_window_list(self, limit: int = 20, min_interval: float = 30.0) -> None:
        """Log the visible top-level windows when the target can't be matched, so
        the user (and whoever supports them) can see what Windows actually
        reports — a localised title, a missing window, or blank titles on an
        elevated game. Throttled: an unattached preview retries every couple of
        seconds and must not flood the log."""
        now = time.time()
        if now - self._window_list_at < min_interval:
            return
        self._window_list_at = now
        win32gui, win32process = self._w[1], self._w[5]
        rows: List[tuple] = []

        def _cb(hwnd, _):
            try:
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd) or ""
                cls = win32gui.GetClassName(hwnd) or ""
                if not title and not cls:
                    return
                pid = int(win32process.GetWindowThreadProcessId(hwnd)[1])
                rows.append((title, cls, pid))
            except Exception:
                return

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            return
        if not rows:
            return
        log_warning(f"[win32] {len(rows)} cửa sổ đang mở (tiêu đề | lớp | exe):")
        for title, cls, pid in rows[:limit]:
            log_warning(f"[win32]   '{title}' | {cls} | "
                        f"{process_exe_name(pid) or f'pid {pid}'}")

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
        # Windows whose exe matched but whose title is unreadable. A game started
        # as Administrator has an unreadable title (UIPI blocks WM_GETTEXT, so
        # GetWindowText returns ""), so it can never match a title pattern — yet
        # it is a perfectly valid target. Kept apart from ``found`` so a titled
        # window of the same exe always wins.
        untitled: List[int] = []
        exe_by_pid: dict[int, str] = {}

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return
            if by in ("pid", "exe"):
                try:
                    pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                except Exception:
                    return
                # Only top-level windows with a title, so an invisible helper
                # window of the same process doesn't win over the real one.
                if by == "pid":
                    ok = (pid == want_pid) and bool(win32gui.GetWindowText(hwnd))
                else:
                    if pid not in exe_by_pid:
                        exe_by_pid[pid] = process_exe_name(pid).lower()
                    exe = exe_by_pid[pid]
                    base = os.path.basename(exe)
                    base_stem = os.path.splitext(base)[0]
                    if use_glob:
                        ok = fnmatch.fnmatch(base, low) or fnmatch.fnmatch(exe, low)
                    else:
                        # Match by file name ("BrownDust II.exe") as well as by the
                        # full path it was configured with: the same game often
                        # lives in a different folder on every PC, and the exe
                        # name is what identifies it.
                        ok = (low in (base, base_stem, exe, os.path.splitext(exe)[0])
                              or low in base)
            elif by == "class":
                name = win32gui.GetClassName(hwnd) or ""
                ok = (name == pattern) or (use_glob and fnmatch.fnmatch(name.lower(), low))
            else:
                title = win32gui.GetWindowText(hwnd) or ""
                if not title:
                    return
                ok = fnmatch.fnmatch(title.lower(), low) if use_glob else (low in title.lower())
            if ok:
                if by == "exe" and not win32gui.GetWindowText(hwnd):
                    untitled.append(hwnd)
                else:
                    found.append(hwnd)

        win32gui.EnumWindows(_cb, None)
        if found:
            return found[0]
        return untitled[0] if untitled else None

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
        """Reliably make the target the real foreground window before input.

        Windows normally rejects ``SetForegroundWindow`` from a background
        automation thread. Temporarily joining its input queue to the current
        foreground/target threads, plus the standard Alt-key unlock, makes the
        focus transfer explicit instead of moving the cursor over an inactive
        game window.
        """
        if not self.hwnd:
            return False
        ctypes, win32gui, _, win32con, win32api, win32process = self._w
        target = self.hwnd
        try:
            try:
                target = win32gui.GetAncestor(self.hwnd, 2) or self.hwnd  # GA_ROOT
            except Exception:
                pass
            self.hwnd = target
            win32gui.ShowWindow(target, win32con.SW_RESTORE)
            user32 = ctypes.windll.user32
            current_tid = int(win32api.GetCurrentThreadId())
            target_tid = int(win32process.GetWindowThreadProcessId(target)[0])
            foreground = win32gui.GetForegroundWindow()
            foreground_tid = (int(win32process.GetWindowThreadProcessId(foreground)[0])
                              if foreground else 0)
            attached = []
            for tid in (foreground_tid, target_tid):
                if tid and tid != current_tid and tid not in attached:
                    if user32.AttachThreadInput(current_tid, tid, True):
                        attached.append(tid)
            try:
                # Press/release Alt to legally unlock foreground activation for
                # this input sequence under Windows' foreground-lock policy.
                win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
                try:
                    win32gui.BringWindowToTop(target)
                    win32gui.SetForegroundWindow(target)
                    try:
                        win32gui.SetActiveWindow(target)
                        win32gui.SetFocus(target)
                    except Exception:
                        pass
                finally:
                    win32api.keybd_event(win32con.VK_MENU, 0, _KE_KEYUP, 0)
            finally:
                for tid in reversed(attached):
                    try:
                        user32.AttachThreadInput(current_tid, tid, False)
                    except Exception:
                        pass
            # Do not report success until Windows confirms the target is active.
            for _ in range(8):
                fg = win32gui.GetForegroundWindow()
                try:
                    fg = win32gui.GetAncestor(fg, 2) or fg
                except Exception:
                    pass
                if fg == target:
                    return True
                time.sleep(0.025)
            log_warning("[win32] Không thể đưa cửa sổ mục tiêu lên foreground")
            return False
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

    def _frame_size(self) -> Tuple[int, int]:
        """Width/height the frame (borders, caption, menu bar) adds around the
        client area — ``GetWindowRect`` minus ``GetClientRect``."""
        rect = self._get_window_rect()
        cw, ch = self.get_screen_size()
        if rect is None or not (cw and ch):
            return (0, 0)
        return (max(0, (rect[2] - rect[0]) - cw), max(0, (rect[3] - rect[1]) - ch))

    def _centered_origin(self, width: int, height: int) -> Tuple[int, int]:
        """Top-left that centres a ``width``×``height`` window on the work area
        (screen minus taskbar) of the monitor the window is on. A window larger
        than the work area is pinned to its top-left rather than pushed off-screen."""
        win32api = self._w[4]
        try:
            monitor = win32api.MonitorFromWindow(self.hwnd, 2)   # MONITOR_DEFAULTTONEAREST
            left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
        except Exception:
            left, top = 0, 0
            right, bottom = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
        return (left + max(0, (right - left - int(width)) // 2),
                top + max(0, (bottom - top - int(height)) // 2))

    def resize_window(self, width: int, height: int, center: bool = False,
                      client: bool = False) -> bool:
        """Resize the target window.

        ``client``: ``width``×``height`` is the client area — the space captures,
        taps and templates use — and the frame is added on top. Off (legacy): the
        whole window including borders and caption.
        ``center``: centre it on the monitor's work area. Off (legacy): the
        top-left corner stays where it was.
        """
        if not self.hwnd:
            return False
        win32gui, win32con = self._w[1], self._w[3]
        try:
            placement = win32gui.GetWindowPlacement(self.hwnd)
            if placement[1] in (win32con.SW_SHOWMAXIMIZED, win32con.SW_SHOWMINIMIZED):
                log_info("[win32] window is maximized/minimized → restoring before resize")
                win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
                time.sleep(0.05)

            rect = self._get_window_rect()
            if rect is None:
                return False
            l, t = rect[0], rect[1]

            borderless = self._is_borderless()
            if borderless:
                log_warning(
                    "[win32] ⚠ Cửa sổ đang borderless (WS_POPUP, không viền). "
                    "Game engine (Unity/DirectX) tự quản lý swapchain và thường ignore WM_SIZE. "
                    "Resize qua Win32 API CÓ THỂ không có hiệu lực. "
                    "→ Gợi ý: chuyển game sang Windowed mode (có viền) trong Settings game, "
                    "hoặc dùng node 'Win style' để ép windowed (experimental)."
                )

            w, h = int(width), int(height)
            if client:
                fw, fh = self._frame_size()
                w, h = w + fw, h + fh
            if center:
                l, t = self._centered_origin(w, h)
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            win32gui.SetWindowPos(self.hwnd, 0, l, t, w, h, flags)
            if client:
                # One correction pass from the real client size: a menu bar that
                # re-wraps or a DPI-scaled frame can make the first guess miss.
                cw, ch = self.get_screen_size()
                dx, dy = int(width) - cw, int(height) - ch
                if cw and ch and (dx or dy):
                    w, h = w + dx, h + dy
                    if center:
                        l, t = self._centered_origin(w, h)
                    win32gui.SetWindowPos(self.hwnd, 0, l, t, w, h, flags)
            cw, ch = self.get_screen_size()
            WM_SIZE = 0x0005
            SIZE_RESTORED = 0
            import win32api
            # WM_SIZE carries the CLIENT size (it used to be sent the outer size).
            win32api.SendMessage(self.hwnd, WM_SIZE, SIZE_RESTORED,
                                 ((ch or h) << 16) | ((cw or w) & 0xFFFF))
            log_info(f"[win32] resize_window → ({l},{t}) window {w}×{h}, client {cw}×{ch}"
                     f"{' · centered' if center else ''}  (borderless={borderless})")
            # Some engines take the resize and then put their own resolution back
            # a few hundred ms later. Unity does it for a client size it won't
            # render at — Brown Dust II reverts a 1920×1080 *outer* window (client
            # 1904×1041, not 16:9) to its previous size within 0.5s. Check once it
            # has had the chance, so the block fails with the reason instead of
            # reporting a resize that didn't stick.
            time.sleep(0.5)
            want = (int(width), int(height))
            if client:
                got = self.get_screen_size()
            else:
                after = self._get_window_rect() or (0, 0, 0, 0)
                got = (after[2] - after[0], after[3] - after[1])
            if abs(got[0] - want[0]) > 2 or abs(got[1] - want[1]) > 2:
                hint = ("→ Bật 'Size = game area (client)' để vùng game đúng tỉ lệ game hỗ trợ (vd 16:9)."
                        if not client else
                        "→ Game không chấp nhận kích thước này (tỉ lệ / độ phân giải không hỗ trợ, hoặc lớn hơn màn hình).")
                log_warning(f"[win32] ⚠ Game đã tự đổi lại kích thước: muốn "
                            f"{want[0]}×{want[1]} {'client' if client else '(cả khung)'}, "
                            f"hiện {got[0]}×{got[1]}. {hint}")
                return False
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

    def find_window_by_pid(self, pid: Optional[int]) -> Optional[int]:
        """Return a visible top-level window owned by *pid*, if one exists."""
        if not pid:
            return None
        win32gui, win32process = self._w[1], self._w[5]
        found: list = []

        def _cb(hwnd, _):
            try:
                if (win32gui.IsWindowVisible(hwnd)
                        and win32process.GetWindowThreadProcessId(hwnd)[1] == int(pid)):
                    found.append(hwnd)
            except Exception:
                pass

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception:
            return None
        return found[0] if found else None

    def launch_app(self, target: str) -> bool:
        """Start a program by exe path (with optional args), or focus a window
        whose title contains ``target`` if it's already open."""
        target = (target or "").strip()
        if not target:
            return False
        # A bare path may contain spaces. Check the complete string before
        # parsing a quoted command with arguments.
        if os.path.exists(target):
            exe = target
        elif target.startswith('"') and '"' in target[1:]:
            exe = target.split('"', 2)[1]
        else:
            exe = target.split(" ", 1)[0]
        if os.path.exists(exe):
            try:
                use_shell = os.path.splitext(exe)[1].lower() in (".bat", ".cmd")
                command = target if use_shell or target != exe else [exe]
                proc = subprocess.Popen(command, shell=use_shell)
                self.last_launch_pid = int(proc.pid)
                return True
            except Exception as exc:
                log_error(f"[win32] Không mở được '{target}': {exc}")
                return False
        hwnd = self._find_hwnd(target, "title")
        if hwnd:
            self.hwnd = hwnd
            self.last_launch_pid = None
            return self.activate()
        log_warning(f"[win32] launch: '{target}' không phải file tồn tại và không có cửa sổ khớp")
        return False

    # ── input: coordinates are CLIENT-area pixels (same space as capture) ──────
    def _foreground(self) -> bool:
        return self._match[2] == "foreground"

    def _cursor_mode(self) -> bool:
        return self._match[2] == "background_cursor"

    def _sync_mode(self) -> bool:
        return self._match[2] == "background_sync"

    def _window_mode(self) -> bool:
        return self._match[2] == "background_window"

    def _anchored_mode(self) -> bool:
        return self._match[2] == "anchored_touch"

    def _bridge_mode(self) -> bool:
        return self._match[2] == "unity_bridge"

    # ── unity_bridge input (in-game plugin over 127.0.0.1) ────────────────────
    def _bridge_call(self, line: str, op_ms: float = 0.0) -> Optional[str]:
        """Send one command line to the in-game bridge and return its reply.

        Returns None when the plugin is unreachable; the caller falls back to
        anchored_touch. One connection per command keeps this thread-safe."""
        port = self._bridge_port()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
                sock.settimeout(max(0.0, float(op_ms)) / 1000.0 + 6.0)
                sock.sendall((line + "\n").encode("utf-8"))
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
            reply = buf.decode("utf-8", "replace").strip()
            log_debug(f"[win32] bridge '{line}' -> '{reply}'")
            return reply
        except OSError as exc:
            if not self._bridge_warned:
                self._bridge_warned = True
                log_warning(f"[win32] unity_bridge: không kết nối được plugin 127.0.0.1:{port} "
                            f"({exc}) — game đã load BD2MOD chưa? Tạm dùng anchored_touch.",
                            kind=LOG_KIND_ACTIVITY)
            return None

    def _bridge_result(self, reply: Optional[str], what: str) -> Optional[bool]:
        """True = delivered, None = fall back (unreachable / no UI hit), False = error."""
        if reply is None:
            return None
        if reply.startswith("ok"):
            return True
        if reply == "miss":
            if not self._bridge_miss_warned:
                self._bridge_miss_warned = True
                log_warning(
                    f"[win32] unity_bridge: plugin phản hồi nhưng {what} không trúng UI "
                    "(EventSystem) — tool chuyển sang anchored_touch. Kiểm tra toạ độ "
                    "theo độ phân giải cửa sổ.", kind=LOG_KIND_ACTIVITY)
            log_debug(f"[win32] unity_bridge: {what} không trúng UI — thử anchored_touch")
            return None
        log_warning(f"[win32] unity_bridge {what}: {reply}")
        return False

    def _tap_bridge(self, x, y, duration, tap_count) -> bool:
        w, h = self.get_screen_size()
        hold_ms = max(20, int(float(duration) * 1000))
        for i in range(max(1, int(tap_count))):
            res = self._bridge_result(
                self._bridge_call(f"tap {int(x)} {int(y)} {hold_ms} {w} {h}", hold_ms), "tap")
            if res is None:
                return self._tap_anchored(x, y, duration, tap_count - i)
            if not res:
                return False
            if tap_count >= 2:
                time.sleep(0.04)
        return True

    def _swipe_bridge(self, x1, y1, x2, y2, duration) -> bool:
        w, h = self.get_screen_size()
        ms = max(1, int(duration))
        res = self._bridge_result(
            self._bridge_call(f"swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {ms} {w} {h}", ms), "swipe")
        if res is None:
            return self._swipe_anchored(x1, y1, x2, y2, duration)
        return res

    # ── window-pos input (SendMessageWithWindowPos equivalent) ────────────────
    def _is_maximized(self) -> bool:
        """True when the window is maximized (so it can't be slid around).

        ``win32gui.IsZoomed`` is missing from some pywin32 builds, so this reads
        ``GetWindowPlacement``'s show-command instead, which is always present.
        """
        try:
            win32gui, win32con = self._w[1], self._w[3]
            return win32gui.GetWindowPlacement(self.hwnd)[1] == win32con.SW_SHOWMAXIMIZED
        except Exception:
            return False

    def _send_window_pos(self, x: int, y: int, fn) -> bool:
        """Send click messages with the WINDOW slid under the unmoved cursor.

        ``fn(dispatch)`` runs while the window is offset so the client point
        (x, y) sits exactly under the current hardware cursor; the cursor never
        moves. Some games take the click position from ``GetCursorPos``, so the
        window — not the pointer — is what has to travel. The window is restored
        in a ``finally`` even when a send raises.
        """
        win32gui, win32api = self._w[1], self._w[4]
        try:
            if self._is_maximized():
                # A maximized window cannot be slid; fall back to messages (the
                # cursor-polling case simply won't see this click).
                fn(self._dispatch)
                return True
            cx, cy = win32api.GetCursorPos()
            l, t, _, _ = win32gui.GetWindowRect(self.hwnd)
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
            dx, dy = int(cx) - sx, int(cy) - sy
            moved = (dx != 0 or dy != 0)
            if moved:
                win32gui.SetWindowPos(self.hwnd, 0, l + dx, t + dy, 0, 0,
                                      _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE)
                time.sleep(0.02)
            try:
                fn(self._send)
            finally:
                if moved:
                    win32gui.SetWindowPos(self.hwnd, 0, l, t, 0, 0,
                                          _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE)
            return True
        except Exception as exc:
            self._input_error("send_window_pos", exc)
            return False

    def _tap_bg_window(self, x, y, duration, tap_count) -> bool:
        lp = _lparam(x, y)
        def run(send):
            send(_WM_MOUSEMOVE, 0, lp)
            for i in range(max(1, int(tap_count))):
                down = _WM_LBUTTONDBLCLK if (tap_count >= 2 and i > 0) else _WM_LBUTTONDOWN
                send(down, _MK_LBUTTON, lp)
                time.sleep(max(0.02, float(duration)))
                send(_WM_LBUTTONUP, 0, lp)
                if tap_count >= 2:
                    time.sleep(0.04)
        return self._send_window_pos(x, y, run)

    def _click_bg_window(self, x, y, btn, duration, count) -> bool:
        down, up, dbl, mk, _, _ = _MOUSE_BUTTONS[btn]
        lp = _lparam(x, y)
        def run(send):
            send(_WM_MOUSEMOVE, 0, lp)
            for i in range(max(1, int(count))):
                msg = dbl if (count >= 2 and i > 0) else down
                send(msg, mk, lp)
                time.sleep(max(0.02, float(duration)))
                send(up, 0, lp)
                if count >= 2:
                    time.sleep(0.04)
        return self._send_window_pos(x, y, run)

    # ── anchored-touch input (InjectSyntheticPointerInput) ────────────────────
    def _touch_device(self):
        """Lazily build the synthetic touch device (None when unsupported)."""
        if self._touch_dev is None:
            try:
                from .pointer import SyntheticTouch
                self._touch_dev = SyntheticTouch()
            except Exception as exc:
                log_warning(f"[win32] anchored_touch không khả dụng: {exc}")
                self._touch_dev = False
        return self._touch_dev or None

    def _thread_anchor(self):
        """Anchor window owned by the CALLING thread, created on demand.

        Each workflow run (and each background action) uses its own thread; a
        window dies with the thread that created it and only that thread pumps
        its messages, so anchors cannot be shared across threads."""
        tid = threading.get_native_id()
        for key, anchor in list(self._anchors.items()):
            if key != tid and not anchor.alive:
                self._anchors.pop(key, None)
        anchor = self._anchors.get(tid)
        if anchor is not None and anchor.alive:
            return anchor
        try:
            from .pointer import AnchorWindow
            anchor = AnchorWindow()
        except Exception as exc:
            log_warning(f"[win32] anchored_touch: lỗi tạo anchor window: {exc}")
            return None
        if not anchor.ready:
            return None
        self._anchors[tid] = anchor
        return anchor

    def _anchored_screen_xy(self, x: int, y: int):
        try:
            return self._w[1].ClientToScreen(self.hwnd, (int(x), int(y)))
        except Exception:
            return None

    def _pump(self, seconds: float = 0.0) -> None:
        """Process this thread's messages so the anchor window consumes the
        synthetic WM_POINTER frames promptly. If it lags, Windows promotes the
        primary contact to a real mouse event and steals the cursor."""
        win32gui, win32api = self._w[1], self._w[4]
        try:
            saved = win32api.GetCursorPos()
        except Exception:
            saved = None
        end = time.monotonic() + max(0.0, float(seconds))
        while True:
            try:
                win32gui.PumpWaitingMessages()
            except Exception:
                pass
            if time.monotonic() >= end:
                break
            time.sleep(0.002)
        # On systems where synthetic touch is promoted to the mouse the cursor
        # hops to the anchor; put it straight back so the user never notices.
        if saved is not None:
            try:
                win32api.SetCursorPos(saved)
            except Exception:
                pass

    def _restore_cursor(self) -> None:
        saved = getattr(self, "_anchored_cursor", None)
        if saved is None:
            return
        try:
            self._w[4].SetCursorPos(saved)
        except Exception:
            pass

    def _anchor_screen_pos(self):
        """Centre of a 4x4 anchor window at a MONITOR corner that does not
        intersect the target window (mirrors MaaFramework's anchor).

        Corners of the virtual-screen bounding box are not used: with monitors
        of different heights/offsets they can fall where no display exists, and
        a contact there hits no window."""
        win32api = self._w[4]
        size, margin = 4, 8
        try:
            monitors = [tuple(win32api.GetMonitorInfo(h)["Monitor"])
                        for h, _, _ in win32api.EnumDisplayMonitors()]
        except Exception:
            monitors = []
        if not monitors:
            w = win32api.GetSystemMetrics(0)   # SM_CXSCREEN
            h = win32api.GetSystemMetrics(1)   # SM_CYSCREEN
            monitors = [(0, 0, w, h)]
        try:
            wl, wt, wr, wb = self._w[1].GetWindowRect(self.hwnd)
        except Exception:
            wl = wt = wr = wb = 0
        candidates = []
        for ml, mt, mr, mb in monitors:
            candidates += [
                (ml + margin, mt + margin),
                (mr - size - margin, mt + margin),
                (ml + margin, mb - size - margin),
                (mr - size - margin, mb - size - margin),
            ]
        for cx, cy in candidates:
            if not (cx < wr and cx + size > wl and cy < wb and cy + size > wt):
                return (cx + size // 2, cy + size // 2)
        return (candidates[0][0] + size // 2, candidates[0][1] + size // 2)

    def _anchored_occluded(self, sx: int, sy: int) -> bool:
        """True when another window sits over the contact point.

        The point must hit the target (or a child of it); otherwise the touch
        would land on the covering window instead. Never activates anything."""
        win32gui = self._w[1]
        try:
            hit = win32gui.WindowFromPoint((int(sx), int(sy)))
            if not hit:
                return True
            root = win32gui.GetAncestor(hit, 2) or hit
            target_root = win32gui.GetAncestor(self.hwnd, 2) or self.hwnd
            if root == target_root:
                return False
            try:
                return not win32gui.IsChild(target_root, hit)
            except Exception:
                return True
        except Exception:
            return False

    def _anchored_setup(self, *screen_points):
        """Anchor + device + occlusion check for an anchored operation.

        Returns ``(dev, anchor, ax, ay)`` or ``None`` when the mode cannot run;
        the caller then falls back to a background message op. Never raises or
        activates the target window."""
        dev = self._touch_device()
        if dev is None or not dev.ready:
            if not self._anchored_warned:
                self._anchored_warned = True
                log_warning("[win32] anchored_touch cần Windows 10 1809+ — "
                            "tạm dùng PostMessage. Đổi Input mode trong Project settings.")
            return None
        anchor = self._thread_anchor()
        if anchor is None:
            if not self._anchored_warned:
                self._anchored_warned = True
                log_warning("[win32] anchored_touch: không tạo được anchor window — "
                            "tạm dùng PostMessage.")
            return None
        origin = self._anchor_screen_pos()
        if origin is None:
            return None
        ax, ay = origin
        anchor.move(ax, ay)
        for sx, sy in screen_points:
            if self._anchored_occluded(sx, sy):
                if not self._anchored_warned:
                    self._anchored_warned = True
                    log_warning("[win32] anchored_touch: điểm chạm đang bị cửa sổ khác che. "
                                "Hãy để cửa sổ game lộ ra, hoặc dùng input mode khác.")
                return None
        # Unity's EventSystem (StandaloneInputModule / InputSystemUIInputModule)
        # drops UI input while the app is unfocused: touches still reach
        # scripts that poll Input directly (tap effects) but buttons ignore
        # them. A sent WM_ACTIVATE makes the player believe it has focus
        # without changing the real foreground window (as background_cursor).
        try:
            self._send(_WM_ACTIVATE, _WA_ACTIVE, 0)
        except Exception:
            pass
        self._pump(0.03)
        try:
            self._anchored_cursor = self._w[4].GetCursorPos()
        except Exception:
            self._anchored_cursor = None
        return dev, anchor, ax, ay

    def _tap_anchored(self, x, y, duration, tap_count) -> bool:
        pt = self._anchored_screen_xy(x, y)
        if pt is None:
            return False
        sx, sy = pt
        prep = self._anchored_setup((sx, sy))
        if prep is None:
            return self._tap_bg(x, y, duration, tap_count)
        dev, _anchor, ax, ay = prep
        from .pointer import _TOUCH_DOWN, _TOUCH_UPDATE, _TOUCH_UP
        aid, cid = 1, 2  # anchor gets the primary pointer, op contact rides along
        try:
            for _ in range(max(1, int(tap_count))):
                # 1) establish the primary pointer on the anchor (own frame)
                if not dev.inject([(aid, _TOUCH_DOWN, ax, ay)]):
                    return False
                self._pump(0.02)
                # 2) operation contact delivered as NON-primary -> no cursor grab
                if not dev.inject([(aid, _TOUCH_UPDATE, ax, ay),
                                   (cid, _TOUCH_DOWN, sx, sy)]):
                    return False
                self._pump(max(0.03, float(duration)))
                if not dev.inject([(aid, _TOUCH_UPDATE, ax, ay),
                                   (cid, _TOUCH_UP, sx, sy)]):
                    return False
                self._pump(0.03)
                if int(tap_count) >= 2:
                    self._pump(0.04)
            return True
        finally:
            try:
                dev.inject([(aid, _TOUCH_UP, ax, ay)])
            except Exception:
                pass
            self._pump(0.02)
            self._restore_cursor()

    def _swipe_anchored(self, x1, y1, x2, y2, duration) -> bool:
        p1 = self._anchored_screen_xy(x1, y1)
        p2 = self._anchored_screen_xy(x2, y2)
        if p1 is None or p2 is None:
            return False
        sx1, sy1 = p1
        sx2, sy2 = p2
        prep = self._anchored_setup((sx1, sy1), (sx2, sy2))
        if prep is None:
            return self._swipe_bg(x1, y1, x2, y2, duration)
        dev, _anchor, ax, ay = prep
        from .pointer import _TOUCH_DOWN, _TOUCH_UPDATE, _TOUCH_UP
        aid, cid = 1, 2
        steps = max(2, int(max(1, duration) / 15))
        try:
            if not dev.inject([(aid, _TOUCH_DOWN, ax, ay)]):
                return False
            self._pump(0.02)
            if not dev.inject([(aid, _TOUCH_UPDATE, ax, ay),
                               (cid, _TOUCH_DOWN, sx1, sy1)]):
                return False
            for i in range(1, steps + 1):
                cx = int(sx1 + (sx2 - sx1) * i / steps)
                cy = int(sy1 + (sy2 - sy1) * i / steps)
                if not dev.inject([(aid, _TOUCH_UPDATE, ax, ay),
                                   (cid, _TOUCH_UPDATE, cx, cy)]):
                    return False
                self._pump(max(0.004, duration / 1000.0 / steps))
            if not dev.inject([(aid, _TOUCH_UPDATE, ax, ay),
                               (cid, _TOUCH_UP, sx2, sy2)]):
                return False
            self._pump(0.02)
            return True
        finally:
            try:
                dev.inject([(aid, _TOUCH_UP, ax, ay)])
            except Exception:
                pass
            self._pump(0.02)
            self._restore_cursor()

    def _multi_tap_anchored(self, points, duration_ms) -> bool:
        spots = []
        for x, y in points:
            pt = self._anchored_screen_xy(x, y)
            if pt is None:
                return False
            spots.append(pt)
        prep = self._anchored_setup(*spots)
        if prep is None:
            return all(self._tap_bg(x, y, duration=0.02) for x, y in points)
        dev, _anchor, ax, ay = prep
        from .pointer import _TOUCH_DOWN, _TOUCH_UPDATE, _TOUCH_UP
        aid = 1
        try:
            if not dev.inject([(aid, _TOUCH_DOWN, ax, ay)]):
                return False
            self._pump(0.02)
            frame = [(aid, _TOUCH_UPDATE, ax, ay)]
            frame += [(2 + i, _TOUCH_DOWN, sx, sy) for i, (sx, sy) in enumerate(spots)]
            if not dev.inject(frame):
                return False
            self._pump(max(0.02, min(10.0, int(duration_ms) / 1000.0)))
            frame_up = [(aid, _TOUCH_UPDATE, ax, ay)]
            frame_up += [(2 + i, _TOUCH_UP, sx, sy) for i, (sx, sy) in enumerate(spots)]
            if not dev.inject(frame_up):
                return False
            self._pump(0.02)
            return True
        finally:
            try:
                dev.inject([(aid, _TOUCH_UP, ax, ay)])
            except Exception:
                pass
            self._pump(0.02)
            self._restore_cursor()

    def _send(self, msg: int, wparam: int, lparam: int) -> None:
        """SendMessage with an abort-if-hung timeout so a frozen game can't
        stall the whole engine thread."""
        self._w[1].SendMessageTimeout(self.hwnd, msg, wparam, lparam, _SMTO_ABORTIFHUNG, 1000)

    def _dispatch(self, msg: int, wparam: int, lparam: int) -> None:
        """Use synchronous SendMessage only in background_sync mode."""
        if self._sync_mode():
            self._send(msg, wparam, lparam)
        else:
            self._w[1].PostMessage(self.hwnd, msg, wparam, lparam)

    def tap(self, x: int, y: int, duration: float = 0.1, tap_count: int = 1) -> bool:
        if not self.hwnd:
            return False
        if self._foreground():
            return self._tap_fg(x, y, duration, tap_count)
        if self._bridge_mode():
            return self._tap_bridge(x, y, duration, tap_count)
        if self._anchored_mode():
            return self._tap_anchored(x, y, duration, tap_count)
        if self._window_mode():
            return self._tap_bg_window(x, y, duration, tap_count)
        if self._cursor_mode():
            return self._tap_bg_cursor(x, y, duration, tap_count)
        return self._tap_bg(x, y, duration, tap_count)

    def multi_tap(self, points: List[Tuple[int, int]], duration_ms: int = 80) -> bool:
        """Deliver overlapping button-down/up messages to several client points.

        Native foreground/cursor input has only one hardware pointer, so those
        modes fall back to a tight sequence. Background message mode can hold all
        requested points down before releasing them.
        """
        clean = [(int(x), int(y)) for x, y in points][:10]
        if not self.hwnd or not clean:
            return False
        if self._bridge_mode():
            # EventSystem pointers are independent, but the bridge runs one
            # command per round-trip; a tight sequence is equivalent for UI.
            return all(self.tap(x, y, duration=0.02, tap_count=1) for x, y in clean)
        if self._anchored_mode():
            return self._multi_tap_anchored(clean, duration_ms)
        if self._foreground() or self._cursor_mode() or self._window_mode():
            log_warning("[win32] multi-point tap: current input mode has one cursor; using rapid sequence")
            return all(self.tap(x, y, duration=0.02, tap_count=1) for x, y in clean)
        try:
            for x, y in clean:
                lp = _lparam(x, y)
                self._dispatch(_WM_MOUSEMOVE, 0, lp)
                self._dispatch(_WM_LBUTTONDOWN, _MK_LBUTTON, lp)
            time.sleep(max(0.02, min(10.0, int(duration_ms) / 1000.0)))
            for x, y in clean:
                self._dispatch(_WM_LBUTTONUP, 0, _lparam(x, y))
            return True
        except Exception as exc:
            self._input_error("multi_tap(bg)", exc)
            return False

    def _tap_bg(self, x, y, duration, tap_count) -> bool:
        lp = _lparam(x, y)
        try:
            self._dispatch(_WM_MOUSEMOVE, 0, lp)
            for i in range(max(1, int(tap_count))):
                down = _WM_LBUTTONDBLCLK if (tap_count >= 2 and i > 0) else _WM_LBUTTONDOWN
                self._dispatch(down, _MK_LBUTTON, lp)
                time.sleep(max(0.02, float(duration)))
                self._dispatch(_WM_LBUTTONUP, 0, lp)
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
            if not self.activate():
                return False
            time.sleep(0.03)
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

    def _swipe_bg(self, x1, y1, x2, y2, duration) -> bool:
        """Background message swipe (PostMessage / SendMessage per mode)."""
        steps = max(2, int(max(1, duration) / 15))
        try:
            self._dispatch(_WM_LBUTTONDOWN, _MK_LBUTTON, _lparam(x1, y1))
            for i in range(1, steps + 1):
                cx = int(x1 + (x2 - x1) * i / steps)
                cy = int(y1 + (y2 - y1) * i / steps)
                self._dispatch(_WM_MOUSEMOVE, _MK_LBUTTON, _lparam(cx, cy))
                time.sleep(duration / 1000.0 / steps)
            self._dispatch(_WM_LBUTTONUP, 0, _lparam(x2, y2))
            return True
        except Exception as exc:
            self._input_error("swipe(bg)", exc)
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        if not self.hwnd:
            return False
        if self._bridge_mode():
            return self._swipe_bridge(x1, y1, x2, y2, duration)
        if self._anchored_mode():
            return self._swipe_anchored(x1, y1, x2, y2, duration)
        if self._cursor_mode():
            return self._swipe_bg_cursor(x1, y1, x2, y2, duration)
        if self._window_mode():
            # Window-pos cannot trace a cursor path without moving the window on
            # every step (it would jitter the whole frame); a message swipe is
            # the pragmatic choice, matching how most flows use swipes.
            return self._swipe_bg(x1, y1, x2, y2, duration)
        if self._foreground():
            steps = max(2, int(max(1, duration) / 15))
            win32gui, win32api = self._w[1], self._w[4]
            try:
                if not self.activate():
                    return False
                time.sleep(0.03)
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
                return True
            except Exception as exc:
                self._input_error("swipe(fg)", exc)
                return False
        return self._swipe_bg(x1, y1, x2, y2, duration)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        return self.swipe(x1, y1, x2, y2, duration)

    def hold_and_release(self, x: int, y: int, duration: int = 1000) -> bool:
        return self.tap(x, y, duration=duration / 1000.0)

    def send_text(self, text: str) -> bool:
        """Type text into the window via WM_CHAR (works background & focused)."""
        if not self.hwnd:
            return False
        try:
            if self._foreground() and not self.activate():
                return False
            for ch in str(text):
                self._dispatch(_WM_CHAR, ord(ch), 0)
                time.sleep(0.005)
            return True
        except Exception as exc:
            self._input_error("send_text", exc)
            return False

    def _key_scan(self, vk: int) -> int:
        """Hardware scan code of a virtual key (MAPVK_VK_TO_VSC), 0 if unknown."""
        try:
            return int(self._w[4].MapVirtualKey(int(vk), 0)) & 0xFF
        except Exception:
            return 0

    def _key_lparam(self, vk: int, up: bool, alt: bool = False) -> int:
        """lParam of WM_(SYS)KEYDOWN/UP: repeat count 1, scan code, extended bit,
        the Alt context bit, and previous-state + transition bits for a key-up.

        It used to be 0, which Unity's Input System reads as "no key" — it
        identifies keys by scan code, not by virtual-key."""
        lp = 1 | (self._key_scan(vk) << 16)
        if vk in _EXTENDED_VKS:
            lp |= 1 << 24
        if alt:
            lp |= 1 << 29
        if up:
            lp |= (1 << 30) | (1 << 31)
        return lp - (1 << 32) if lp >= (1 << 31) else lp   # LPARAM is signed

    def _key_event(self, vk: int, up: bool) -> None:
        """One key transition on the target, by the current input mode."""
        if self._foreground():
            if not up and not self.activate():
                raise RuntimeError("could not bring the target window to the foreground")
            flags = (_KE_KEYUP if up else 0) | (_KE_EXTENDEDKEY if vk in _EXTENDED_VKS else 0)
            self._w[4].keybd_event(vk, self._key_scan(vk), flags, 0)
        else:
            self._dispatch(_WM_KEYUP if up else _WM_KEYDOWN, vk, self._key_lparam(vk, up))

    def _key_bridge(self, vk: int, hold: float, action: str) -> Optional[bool]:
        """Keys through the in-game bridge (``key`` / ``keydown`` / ``keyup``).

        ``None`` → fall back to window messages: the plugin is unreachable, or
        it predates key commands."""
        hold_ms = int(hold * 1000)
        line = {"press": f"key {vk} {hold_ms}", "down": f"keydown {vk}", "up": f"keyup {vk}"}[action]
        reply = self._bridge_call(line, hold_ms if action == "press" else 0)
        if reply is None:
            return None
        if reply.startswith("err unknown command"):
            if not self._bridge_key_warned:
                self._bridge_key_warned = True
                log_warning("[win32] unity_bridge: plugin trong game chưa hỗ trợ phím (lệnh key) — "
                            "build lại plugin rồi mở lại game; tạm gửi phím qua window message",
                            kind=LOG_KIND_ACTIVITY)
            return None
        if reply.startswith("ok"):
            return True
        log_warning(f"[win32] unity_bridge key: {reply}", kind=LOG_KIND_ACTIVITY)
        return False

    def press_key(self, keycode: int, hold_ms: float = 0, action: str = "press") -> bool:
        """Press a **Windows virtual-key code** (VK_*). Note: for Win32 projects
        the 'Key' node's number is a VK code, not an Android keycode.

        ``action``: ``press`` — down, hold ``hold_ms`` (at least 30 ms), up;
        ``down`` — keep it held (walking) until a later ``up``; ``up`` — release.
        A game polls input once per frame, so a character only moves for as long
        as the key stays down."""
        if not self.hwnd:
            return False
        try:
            vk = int(keycode)
        except (TypeError, ValueError):
            return False
        action = str(action or "press").strip().lower()
        if action not in ("press", "down", "up"):
            action = "press"
        hold = max(0.03, float(hold_ms or 0) / 1000.0)
        try:
            delivered = self._key_bridge(vk, hold, action) if self._bridge_mode() else None
            if delivered is None:
                if action in ("press", "down"):
                    self._key_event(vk, up=False)
                if action == "press":
                    time.sleep(hold)
                if action in ("press", "up"):
                    self._key_event(vk, up=True)
                delivered = True
            if delivered:
                if action == "down":
                    self._held_keys.add(vk)
                else:
                    self._held_keys.discard(vk)
            return bool(delivered)
        except Exception as exc:
            self._input_error("press_key", exc)
            return False

    def release_all_keys(self) -> None:
        """Release every key a flow left down — a stopped run must not leave the
        character walking."""
        for vk in list(self._held_keys):
            try:
                self.press_key(vk, action="up")
            except Exception:
                pass
        self._held_keys.clear()

    def go_back(self) -> bool:
        return self.press_key(_VK_ESCAPE)

    def go_home(self) -> bool:
        # No desktop analogue; treat as a no-op success so flows don't error.
        return True

    # ── extended mouse input: right / middle button, wheel, bare move ──────────
    def click(self, x: int, y: int, button: str = "left",
              duration: float = 0.1, click_count: int = 1) -> bool:
        """Click any mouse button at a CLIENT-area point.

        ``left`` routes through :meth:`tap` so the existing per-mode paths
        (foreground / background_cursor / background message) stay the single
        implementation. Right/middle reuse the same three modes with that
        button's message triple.
        """
        btn = str(button or "left").strip().lower()
        if btn in ("", "left", "l"):
            return self.tap(x, y, duration=duration, tap_count=click_count)
        if btn not in _MOUSE_BUTTONS:
            log_warning(f"[win32] click: nút '{button}' không hợp lệ (left/right/middle)")
            return False
        if not self.hwnd:
            return False
        if self._anchored_mode() or self._bridge_mode():
            # Touch contacts / bridge taps have no right/middle button; fall
            # back to window-pos for those so no cursor is moved.
            if btn == "left":
                return self.tap(x, y, duration=duration, tap_count=click_count)
            return self._click_bg_window(x, y, btn, duration, click_count)
        if self._foreground():
            return self._click_fg(x, y, btn, duration, click_count)
        if self._cursor_mode():
            return self._click_bg_cursor(x, y, btn, duration, click_count)
        if self._window_mode():
            return self._click_bg_window(x, y, btn, duration, click_count)
        return self._click_bg(x, y, btn, duration, click_count)

    def _click_bg(self, x, y, btn, duration, count) -> bool:
        down, up, dbl, mk, _, _ = _MOUSE_BUTTONS[btn]
        lp = _lparam(x, y)
        try:
            self._dispatch(_WM_MOUSEMOVE, 0, lp)
            for i in range(max(1, int(count))):
                msg = dbl if (count >= 2 and i > 0) else down
                self._dispatch(msg, mk, lp)
                time.sleep(max(0.02, float(duration)))
                self._dispatch(up, 0, lp)
                if count >= 2:
                    time.sleep(0.04)
            return True
        except Exception as exc:
            self._input_error(f"click({btn},bg)", exc)
            return False

    def _click_bg_cursor(self, x, y, btn, duration, count) -> bool:
        """Cursor-pos variant (see :meth:`_tap_bg_cursor`) for any button."""
        down, up, _, mk, _, _ = _MOUSE_BUTTONS[btn]
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
            for _ in range(max(1, int(count))):
                win32api.SetCursorPos((sx, sy))
                time.sleep(0.001)
                self._send(_WM_MOUSEMOVE, 0, lp)
                time.sleep(0.01)
                self._send(down, mk, lp)
                time.sleep(max(0.02, float(duration)))
                self._send(up, 0, lp)
                if count >= 2:
                    time.sleep(0.04)
            return True
        except Exception as exc:
            self._input_error(f"click({btn},bg+cursor)", exc)
            return False
        finally:
            if saved is not None:
                try:
                    win32api.SetCursorPos(saved)
                except Exception:
                    pass

    def _click_fg(self, x, y, btn, duration, count) -> bool:
        _, _, _, _, me_down, me_up = _MOUSE_BUTTONS[btn]
        win32gui, win32api = self._w[1], self._w[4]
        try:
            if not self.activate():
                return False
            time.sleep(0.03)
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
            win32api.SetCursorPos((sx, sy))
            for _ in range(max(1, int(count))):
                win32api.mouse_event(me_down, 0, 0, 0, 0)
                time.sleep(max(0.02, float(duration)))
                win32api.mouse_event(me_up, 0, 0, 0, 0)
                time.sleep(0.03)
            return True
        except Exception as exc:
            self._input_error(f"click({btn},fg)", exc)
            return False

    def scroll(self, x: int, y: int, notches: int = -3, horizontal: bool = False) -> bool:
        """Mouse wheel at a CLIENT point. ``notches`` > 0 = up/right, < 0 = down/left.

        WM_MOUSEWHEEL's lParam is in SCREEN coordinates (unlike the button
        messages), so the client point is converted before dispatch.
        """
        if not self.hwnd:
            return False
        try:
            n = int(notches)
        except (TypeError, ValueError):
            return False
        if n == 0:
            return True
        win32gui, win32api = self._w[1], self._w[4]
        try:
            sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
        except Exception as exc:
            self._input_error("scroll(client_to_screen)", exc)
            return False
        try:
            if self._foreground():
                if not self.activate():
                    return False
                win32api.SetCursorPos((sx, sy))
                flag = _ME_HWHEEL if horizontal else _ME_WHEEL
                for _ in range(abs(n)):
                    win32api.mouse_event(flag, 0, 0, (_WHEEL_DELTA if n > 0 else -_WHEEL_DELTA), 0)
                    time.sleep(0.02)
                return True
            msg = _WM_MOUSEHWHEEL if horizontal else _WM_MOUSEWHEEL
            lp = _lparam(sx, sy)
            if self._window_mode():
                def run(send):
                    for _ in range(abs(n)):
                        delta = _WHEEL_DELTA if n > 0 else -_WHEEL_DELTA
                        wparam = (delta & 0xFFFF) << 16
                        send(msg, wparam, lp)
                        time.sleep(0.02)
                return self._send_window_pos(x, y, run)
            saved = None
            if self._cursor_mode():
                try:
                    saved = win32api.GetCursorPos()
                except Exception:
                    pass
                self._send(_WM_ACTIVATE, _WA_ACTIVE, 0)
                win32api.SetCursorPos((sx, sy))
                time.sleep(0.01)
            try:
                for _ in range(abs(n)):
                    delta = _WHEEL_DELTA if n > 0 else -_WHEEL_DELTA
                    # wParam high word = signed wheel delta; low word = key flags.
                    wparam = (delta & 0xFFFF) << 16
                    self._dispatch(msg, wparam, lp)
                    time.sleep(0.02)
                return True
            finally:
                if saved is not None:
                    try:
                        win32api.SetCursorPos(saved)
                    except Exception:
                        pass
        except Exception as exc:
            self._input_error("scroll", exc)
            return False

    def move_mouse(self, x: int, y: int) -> bool:
        """Move the pointer to a CLIENT point without clicking (hover menus).

        Background message mode only posts WM_MOUSEMOVE; cursor/foreground modes
        also move the real cursor (and, unlike a click, leave it there — hover is
        only meaningful while the pointer stays put).
        """
        if not self.hwnd:
            return False
        lp = _lparam(x, y)
        if self._window_mode():
            # Slide the window once so the hover point is under the pointer,
            # post the move, then restore (hover is inherently transient here).
            return self._send_window_pos(x, y, lambda send: send(_WM_MOUSEMOVE, 0, lp))
        try:
            if self._foreground() or self._cursor_mode():
                win32gui, win32api = self._w[1], self._w[4]
                if self._foreground() and not self.activate():
                    return False
                sx, sy = win32gui.ClientToScreen(self.hwnd, (int(x), int(y)))
                win32api.SetCursorPos((sx, sy))
                if self._cursor_mode():
                    self._send(_WM_ACTIVATE, _WA_ACTIVE, 0)
            self._dispatch(_WM_MOUSEMOVE, 0, lp)
            return True
        except Exception as exc:
            self._input_error("move_mouse", exc)
            return False

    # ── extended keyboard input: modifier combos ────────────────────────────────
    def press_hotkey(self, keycode: int, ctrl: bool = False, shift: bool = False,
                     alt: bool = False, win: bool = False) -> bool:
        """Press ``keycode`` while holding the requested modifiers.

        Foreground mode uses real ``keybd_event`` presses. Background modes hold
        the modifiers with WM_KEYDOWN and mark the Alt case with WM_SYSKEYDOWN /
        WM_SYSKEYUP, which is what apps expect for Alt combos.
        """
        if not self.hwnd:
            return False
        try:
            vk = int(keycode)
        except (TypeError, ValueError):
            return False
        mods = [_MODIFIER_VKS[n] for n, on in
                (("ctrl", ctrl), ("shift", shift), ("alt", alt), ("win", win)) if on]
        if not mods:
            return self.press_key(vk)
        try:
            if self._foreground():
                if not self.activate():
                    return False
                for m in mods:
                    self._key_event(m, up=False)
                    time.sleep(0.01)
                self._key_event(vk, up=False)
                time.sleep(0.03)
                self._key_event(vk, up=True)
                for m in reversed(mods):
                    self._key_event(m, up=True)
                    time.sleep(0.01)
                return True
            down = _WM_SYSKEYDOWN if alt else _WM_KEYDOWN
            up = _WM_SYSKEYUP if alt else _WM_KEYUP
            for m in mods:
                self._dispatch(_WM_KEYDOWN, m, self._key_lparam(m, False))
                time.sleep(0.01)
            self._dispatch(down, vk, self._key_lparam(vk, False, alt=alt))
            time.sleep(0.03)
            self._dispatch(up, vk, self._key_lparam(vk, True, alt=alt))
            for m in reversed(mods):
                self._dispatch(_WM_KEYUP, m, self._key_lparam(m, True))
                time.sleep(0.01)
            return True
        except Exception as exc:
            self._input_error("press_hotkey", exc)
            return False

    # ── target-window state (the Win32 analogue of "is the app running?") ──────
    def window_exists(self) -> bool:
        """True when the configured target window can be found right now.

        Unlike :meth:`get_current_app` (which reports the FOREGROUND window's
        title), this answers "is my target still alive?" — the check a flow needs
        to detect a crashed game while running in a background input mode.
        """
        win32gui = self._w[1]
        if self.hwnd:
            try:
                if win32gui.IsWindow(self.hwnd):
                    return True
            except Exception:
                pass
            self.hwnd = None
        pattern, by, _ = self._match
        if not pattern:
            return False
        hwnd = self._find_hwnd(pattern, by)
        if hwnd:
            self.hwnd = hwnd
            return True
        return False

    def target_title(self) -> str:
        """The target window's own title ('' when not attached/alive)."""
        if not self.window_exists():
            return ""
        try:
            return self._w[1].GetWindowText(self.hwnd) or ""
        except Exception:
            return ""

    def is_foreground(self) -> bool:
        """True when the target window is the active/foreground window."""
        if not self.hwnd:
            return False
        win32gui = self._w[1]
        try:
            fg = win32gui.GetForegroundWindow()
            try:
                fg = win32gui.GetAncestor(fg, 2) or fg  # GA_ROOT
            except Exception:
                pass
            return fg == self.hwnd
        except Exception:
            return False

    def is_minimized(self) -> bool:
        if not self.hwnd:
            return False
        try:
            return bool(self._w[1].IsIconic(self.hwnd))
        except Exception:
            return False

    def window_info(self) -> dict:
        """Target-window facts for the ``win_info`` node.

        Keys: ``title``, ``class``, ``pid``, ``exe``, ``x``/``y`` (window
        top-left, screen coords), ``width``/``height`` (CLIENT size — the same
        space taps and captures use), ``hwnd``, ``foreground``, ``minimized``.
        """
        out = {"title": "", "class": "", "pid": 0, "exe": "", "x": 0, "y": 0,
               "width": 0, "height": 0, "hwnd": 0,
               "foreground": False, "minimized": False}
        if not self.window_exists():
            return out
        win32gui, win32process = self._w[1], self._w[5]
        out["hwnd"] = int(self.hwnd)
        try:
            out["title"] = win32gui.GetWindowText(self.hwnd) or ""
        except Exception:
            pass
        try:
            out["class"] = win32gui.GetClassName(self.hwnd) or ""
        except Exception:
            pass
        try:
            pid = int(win32process.GetWindowThreadProcessId(self.hwnd)[1])
            out["pid"] = pid
            out["exe"] = process_exe_name(pid)
        except Exception:
            pass
        rect = self._get_window_rect()
        if rect:
            out["x"], out["y"] = int(rect[0]), int(rect[1])
        w, h = self.get_screen_size()
        out["width"], out["height"] = int(w), int(h)
        out["foreground"] = self.is_foreground()
        out["minimized"] = self.is_minimized()
        return out


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
