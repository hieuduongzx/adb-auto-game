"""Synthetic-pointer (``WM_POINTER``) injection for the Win32 backend.

Implements the *anchored touch* input mode: touch contacts are injected with
``InjectSyntheticPointerInput`` so the target window receives ``WM_POINTER``
messages while the hardware cursor never moves and the foreground window never
changes. This is the same technique MaaFramework calls ``AnchoredTouch``.

Requires Windows 10 1809 (build 17763) or newer. :func:`available` reports
whether the API is present on this machine; callers fall back to another input
mode when it isn't.
"""
from __future__ import annotations

from typing import Optional

# POINTER_INPUT_TYPE / POINTER_FLAGS / TOUCH_MASK constants from winuser.h.
_PT_TOUCH = 0x00000002
_POINTER_FEEDBACK_DEFAULT = 0x0001
_FLAG_INRANGE = 0x00000002
_FLAG_INCONTACT = 0x00000004
_FLAG_PRIMARY = 0x00002000
_FLAG_CONFIDENCE = 0x00004000
_FLAG_DOWN = 0x00010000
_FLAG_UPDATE = 0x00020000
_FLAG_UP = 0x00040000
_MASK_CONTACTAREA = 0x00000001
_MASK_PRESSURE = 0x00000004

_CONTACT_DOWN = _FLAG_INRANGE | _FLAG_INCONTACT | _FLAG_PRIMARY | _FLAG_CONFIDENCE | _FLAG_DOWN
_CONTACT_UPDATE = _FLAG_INRANGE | _FLAG_INCONTACT | _FLAG_PRIMARY | _FLAG_CONFIDENCE | _FLAG_UPDATE
_CONTACT_UP = _FLAG_INRANGE | _FLAG_PRIMARY | _FLAG_CONFIDENCE | _FLAG_UP

# Anchored-touch frame flags, mirroring MaaFramework's AnchoredTouchInput:
# the *first* contact (held on a tiny topmost anchor window at a screen corner)
# becomes the system PRIMARY pointer, so every operation contact rides along as
# non-primary and the real mouse cursor is never grabbed. POINTER_FLAG_PRIMARY
# is deliberately not set — the system assigns it to the first contact.
_TOUCH_DOWN = _FLAG_INRANGE | _FLAG_INCONTACT | _FLAG_CONFIDENCE | _FLAG_DOWN
_TOUCH_UPDATE = _FLAG_INRANGE | _FLAG_INCONTACT | _FLAG_CONFIDENCE | _FLAG_UPDATE
_TOUCH_UP = _FLAG_UP

# Anchor window: smallest visible alpha (0 would make hit-testing fall through)
# and no touch feedback ripples.
_ANCHOR_ALPHA = 1
_ANCHOR_SIZE = 4
_POINTER_FEEDBACK_NONE = 0x00000003

_API = None  # None = not probed yet, False = unavailable, dict = ready


def _api() -> Optional[dict]:
    """Build (once) the ctypes structs + user32 prototypes.

    Returns ``None`` when the synthetic-pointer API is missing (pre-1809
    Windows) or anything failed to resolve.
    """
    global _API
    if _API is not None:
        return _API or None
    try:
        import ctypes
        from ctypes import wintypes

        class POINTER_INFO(ctypes.Structure):
            _fields_ = [
                ("pointerType", wintypes.DWORD),
                ("pointerId", wintypes.UINT),
                ("frameId", wintypes.UINT),
                ("pointerFlags", wintypes.UINT),
                ("sourceDevice", wintypes.HANDLE),
                ("hwndTarget", wintypes.HWND),
                ("ptPixelLocation", wintypes.POINT),
                ("ptHimetricLocation", wintypes.POINT),
                ("ptPixelLocationRaw", wintypes.POINT),
                ("ptHimetricLocationRaw", wintypes.POINT),
                ("dwTime", wintypes.DWORD),
                ("historyCount", wintypes.UINT),
                ("InputData", ctypes.c_int32),
                ("dwKeyStates", wintypes.DWORD),
                ("PerformanceCount", ctypes.c_uint64),
                ("ButtonChangeType", ctypes.c_int32),
            ]

        class POINTER_TOUCH_INFO(ctypes.Structure):
            _fields_ = [
                ("pointerInfo", POINTER_INFO),
                ("touchFlags", wintypes.UINT),
                ("touchMask", wintypes.UINT),
                ("rcContact", wintypes.RECT),
                ("rcContactRaw", wintypes.RECT),
                ("orientation", wintypes.UINT),
                ("pressure", wintypes.UINT),
            ]

        class POINTER_PEN_INFO(ctypes.Structure):
            _fields_ = [
                ("pointerInfo", POINTER_INFO),
                ("penFlags", wintypes.UINT),
                ("penMask", wintypes.UINT),
                ("pressure", wintypes.UINT),
                ("rotation", wintypes.UINT),
                ("tiltX", ctypes.c_int32),
                ("tiltY", ctypes.c_int32),
            ]

        class _PTI_UNION(ctypes.Union):
            _fields_ = [("touchInfo", POINTER_TOUCH_INFO),
                        ("penInfo", POINTER_PEN_INFO)]

        class POINTER_TYPE_INFO(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", _PTI_UNION)]

        user32 = ctypes.windll.user32
        if not hasattr(user32, "CreateSyntheticPointerDevice"):
            _API = False
            return None
        user32.CreateSyntheticPointerDevice.restype = wintypes.HANDLE
        user32.CreateSyntheticPointerDevice.argtypes = [
            wintypes.DWORD, ctypes.c_ulong, wintypes.DWORD]
        user32.InjectSyntheticPointerInput.restype = wintypes.BOOL
        user32.InjectSyntheticPointerInput.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(POINTER_TYPE_INFO), wintypes.UINT]
        user32.DestroySyntheticPointerDevice.argtypes = [wintypes.HANDLE]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]

        _API = {
            "ctypes": ctypes, "wintypes": wintypes, "user32": user32,
            "POINTER_TYPE_INFO": POINTER_TYPE_INFO,
        }
    except Exception:
        _API = False
    return _API or None


def available() -> bool:
    """True when synthetic touch injection can run on this machine."""
    return _api() is not None


def _virtual_origin(api) -> tuple:
    """Top-left of the virtual screen (SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN).

    Synthetic touch coordinates are measured from this origin, not from the
    primary monitor: with a monitor left of / above the primary one, raw screen
    coordinates land that many pixels off (on the other monitor)."""
    try:
        user32 = api["user32"]
        return user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    except Exception:
        return 0, 0


class SyntheticTouch:
    """One synthetic touch device + contact injection helpers."""

    def __init__(self, max_contacts: int = 11) -> None:
        self._api = _api()
        self._dev = None
        if self._api is None:
            return
        try:
            self._dev = self._api["user32"].CreateSyntheticPointerDevice(
                _PT_TOUCH, int(max_contacts), _POINTER_FEEDBACK_DEFAULT)
        except Exception:
            self._dev = None

    @property
    def ready(self) -> bool:
        return bool(self._dev)

    def close(self) -> None:
        if self._dev:
            try:
                self._api["user32"].DestroySyntheticPointerDevice(self._dev)
            except Exception:
                pass
            self._dev = None

    # ── injection ─────────────────────────────────────────────────────────────

    def _inject(self, flags: int, x: int, y: int, contact: int,
                pressure: int = 512, radius: int = 6) -> bool:
        api = self._api
        if api is None or not self._dev:
            return False
        try:
            vx, vy = _virtual_origin(api)
            x, y = int(x) - vx, int(y) - vy
            info = api["POINTER_TYPE_INFO"]()
            info.type = _PT_TOUCH
            ti = info.touchInfo
            pi = ti.pointerInfo
            pi.pointerType = _PT_TOUCH
            pi.pointerId = int(contact)
            pi.pointerFlags = int(flags)
            pi.ptPixelLocation.x = int(x)
            pi.ptPixelLocation.y = int(y)
            pi.ptPixelLocationRaw.x = int(x)
            pi.ptPixelLocationRaw.y = int(y)
            ti.touchFlags = 0
            ti.touchMask = _MASK_CONTACTAREA | _MASK_PRESSURE
            ti.rcContact.left = int(x) - radius
            ti.rcContact.top = int(y) - radius
            ti.rcContact.right = int(x) + radius
            ti.rcContact.bottom = int(y) + radius
            ti.rcContactRaw = ti.rcContact
            ti.pressure = int(pressure)
            arr = (api["POINTER_TYPE_INFO"] * 1)(info)
            return bool(api["user32"].InjectSyntheticPointerInput(self._dev, arr, 1))
        except Exception:
            return False

    def down(self, x: int, y: int, contact: int = 0) -> bool:
        return self._inject(_CONTACT_DOWN, x, y, contact)

    def update(self, x: int, y: int, contact: int = 0) -> bool:
        return self._inject(_CONTACT_UPDATE, x, y, contact)

    def up(self, x: int, y: int, contact: int = 0) -> bool:
        return self._inject(_CONTACT_UP, x, y, contact)

    def inject(self, contacts) -> bool:
        """Submit one multi-contact frame.

        ``contacts`` is an iterable of ``(pointer_id, flags, x, y)`` in screen
        pixels. All contacts share one frame, which is what lets the anchor
        primary and the operation contact(s) travel together.
        """
        api = self._api
        if api is None or not self._dev:
            return False
        try:
            items = [tuple(c) for c in contacts]
            if not items:
                return False
            info_t = api["POINTER_TYPE_INFO"]
            arr = (info_t * len(items))()
            vx, vy = _virtual_origin(api)
            for k, (pid, flags, x, y) in enumerate(items):
                x, y = int(x) - vx, int(y) - vy
                info = info_t()
                info.type = _PT_TOUCH
                ti = info.touchInfo
                pi = ti.pointerInfo
                pi.pointerType = _PT_TOUCH
                pi.pointerId = int(pid)
                pi.pointerFlags = int(flags)
                pi.ptPixelLocation.x = int(x)
                pi.ptPixelLocation.y = int(y)
                pi.ptPixelLocationRaw.x = int(x)
                pi.ptPixelLocationRaw.y = int(y)
                ti.touchFlags = 0
                ti.touchMask = _MASK_CONTACTAREA | _MASK_PRESSURE
                ti.rcContact.left = int(x) - 2
                ti.rcContact.top = int(y) - 2
                ti.rcContact.right = int(x) + 2
                ti.rcContact.bottom = int(y) + 2
                ti.rcContactRaw = ti.rcContact
                ti.pressure = 512
                arr[k] = info
            return bool(api["user32"].InjectSyntheticPointerInput(self._dev, arr, len(items)))
        except Exception:
            return False

    # ── Z-order rescue ────────────────────────────────────────────────────────
    def window_under_point(self, x: int, y: int) -> int:
        """Top-level window at screen (x, y), or 0. Used to detect occlusion."""
        api = self._api
        if api is None:
            return 0
        try:
            wintypes = api["wintypes"]
            user32 = api["user32"]
            pt = wintypes.POINT(int(x), int(y))
            hw = user32.WindowFromPoint(pt)
            if not hw:
                return 0
            root = hw
            for _ in range(16):
                parent = user32.GetAncestor(root, 1)  # GA_PARENT
                if not parent:
                    break
                root = parent
            return int(root)
        except Exception:
            return 0


# ── anchor window ─────────────────────────────────────────────────────────────
# A tiny, invisible, topmost, never-activated tool window parked at a screen
# corner. The synthetic device's PRIMARY contact is held here; operation
# contacts are then injected as non-primary. Without the anchor the primary
# contact lands on the operation point, Windows promotes it to the real mouse
# (cursor is grabbed) and touch-aware games never see a proper WM_POINTER.
_ANCHOR_CLASS_NAME = "Macro2kAnchorTouch"
_anchor_class_ready = False
_anchor_proc_ref = None

_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_TOPMOST = 0x00000008
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_WS_POPUP = 0x80000000
_LWA_ALPHA = 0x00000002
_HWND_TOPMOST = -1
_SWP_NOACTIVATE = 0x0010
_SW_SHOWNOACTIVATE = 4
_WM_NCHITTEST = 0x0084
_WM_MOUSEACTIVATE = 0x0021
_WM_POINTERACTIVATE = 0x024B
_HTCLIENT = 1
_MA_NOACTIVATE = 3
_PA_NOACTIVATE = 3


def _ensure_anchor_class(api) -> bool:
    """Register (once) the anchor window class and keep its WNDPROC alive."""
    global _anchor_class_ready, _anchor_proc_ref
    if _anchor_class_ready:
        return True
    try:
        ctypes = api["ctypes"]
        wintypes = api["wintypes"]
        user32 = api["user32"]
        kernel32 = ctypes.windll.kernel32

        wndproc_t = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                       wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", wndproc_t),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        def _wndproc(hwnd, msg, wparam, lparam):
            # Never activate and always claim the client area; swallow every
            # pointer message so the system does not promote the primary
            # contact into a real mouse event.
            if msg == _WM_NCHITTEST:
                return _HTCLIENT
            if msg == _WM_MOUSEACTIVATE:
                return _MA_NOACTIVATE
            if msg == _WM_POINTERACTIVATE:
                return _PA_NOACTIVATE
            if 0x0241 <= msg <= 0x024F:  # WM_NCPOINTER*/WM_POINTER*/WM_TOUCHHITTESTING
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM]
        user32.RegisterClassW.restype = ctypes.c_ushort
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

        proc = wndproc_t(_wndproc)
        wc = WNDCLASS()
        wc.lpfnWndProc = proc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = _ANCHOR_CLASS_NAME
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom and kernel32.GetLastError() not in (0, 1410):
            return False
        _anchor_proc_ref = proc
        _anchor_class_ready = True
        return True
    except Exception:
        return False


class AnchorWindow:
    """Invisible topmost window that holds the primary synthetic pointer.

    A window belongs to the thread that created it: Windows destroys it when
    that thread exits and only that thread can pump its messages. Callers must
    keep one anchor per input thread and check :attr:`alive` before use."""

    def __init__(self, size: int = _ANCHOR_SIZE) -> None:
        self._api = _api()
        self._hwnd = 0
        self._thread = 0
        self.size = int(size)
        if self._api is None or not _ensure_anchor_class(self._api):
            return
        try:
            ctypes = self._api["ctypes"]
            wintypes = self._api["wintypes"]
            user32 = self._api["user32"]
            kernel32 = ctypes.windll.kernel32

            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, wintypes.UINT]
            user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
            user32.SetLayeredWindowAttributes.argtypes = [
                wintypes.HWND, wintypes.DWORD, ctypes.c_byte, wintypes.DWORD]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.ShowWindow.restype = wintypes.BOOL
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

            ex = _WS_EX_LAYERED | _WS_EX_TOOLWINDOW | _WS_EX_TOPMOST | _WS_EX_NOACTIVATE
            hwnd = user32.CreateWindowExW(
                ex, _ANCHOR_CLASS_NAME, "", _WS_POPUP,
                -32000, -32000, self.size, self.size, None, None,
                kernel32.GetModuleHandleW(None), None)
            if not hwnd:
                return
            user32.SetLayeredWindowAttributes(hwnd, 0, _ANCHOR_ALPHA, _LWA_ALPHA)
            user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            self._hwnd = int(hwnd)
            self._thread = int(kernel32.GetCurrentThreadId())
        except Exception:
            self._hwnd = 0

    @property
    def ready(self) -> bool:
        return bool(self._hwnd)

    @property
    def thread_id(self) -> int:
        return self._thread

    @property
    def alive(self) -> bool:
        """True while the window still exists and is owned by its creator
        thread (a recycled handle from a dead thread fails the owner check)."""
        if not self._hwnd:
            return False
        try:
            user32 = self._api["user32"]
            if not user32.IsWindow(self._hwnd):
                return False
            return int(user32.GetWindowThreadProcessId(self._hwnd, None)) == self._thread
        except Exception:
            return False

    @property
    def hwnd(self) -> int:
        return self._hwnd

    def move(self, x: int, y: int) -> bool:
        """Park the anchor so its centre sits at screen (x, y)."""
        if not self._hwnd:
            return False
        try:
            wintypes = self._api["wintypes"]
            user32 = self._api["user32"]
            return bool(user32.SetWindowPos(
                self._hwnd, wintypes.HWND(_HWND_TOPMOST),
                int(x) - self.size // 2, int(y) - self.size // 2,
                self.size, self.size, _SWP_NOACTIVATE))
        except Exception:
            return False

    def close(self) -> None:
        if self._hwnd:
            try:
                if self.alive:
                    ctypes = self._api["ctypes"]
                    if int(ctypes.windll.kernel32.GetCurrentThreadId()) == self._thread:
                        self._api["user32"].DestroyWindow(self._hwnd)
                    else:
                        # DestroyWindow fails cross-thread; the owner destroys
                        # it on its next pump (or when the thread exits).
                        self._api["user32"].PostMessageW(self._hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception:
                pass
            self._hwnd = 0
