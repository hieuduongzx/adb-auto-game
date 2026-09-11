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


class SyntheticTouch:
    """One synthetic touch device + contact injection helpers."""

    def __init__(self, max_contacts: int = 10) -> None:
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
            ctypes = api["ctypes"]
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
