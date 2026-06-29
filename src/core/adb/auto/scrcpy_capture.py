"""Shared screen capture helpers with optional scrcpy video frames.

The old path uses ``adb shell screencap`` for every screenshot. This module adds
an optional scrcpy-backed frame source so DevScope, workflow template matching
and OCR can all read from the same low-latency mirror frame.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, Optional

import cv2
import numpy as np

from src.utils import log_debug, log_info, log_warning


_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
_SCRCPY_DIR = os.path.join(_PROJECT_ROOT, "vendor", "scrcpy")
_SCRCPY_EXE = os.path.join(_SCRCPY_DIR, "scrcpy.exe" if os.name == "nt" else "scrcpy")
_SCRCPY_SERVER = os.path.join(_SCRCPY_DIR, "scrcpy-server")

_SOURCES: Dict[str, "ScrcpyFrameSource"] = {}
_SOURCES_LOCK = threading.Lock()
CAPTURE_BACKENDS = ("scrcpy", "adb")
_LAST_NO_FRAME_LOG = 0.0


def _capture_backend() -> str:
    """Return requested capture backend: scrcpy or adb."""
    backend = os.environ.get("ADB_AUTO_CAPTURE_BACKEND", "scrcpy").strip().lower()
    return backend if backend in CAPTURE_BACKENDS else "scrcpy"


def get_capture_backend() -> str:
    """Public backend value for UIs."""
    return _capture_backend()


def set_capture_backend(backend: str) -> str:
    """Set process-wide capture backend and return the normalized value."""
    normalized = (backend or "").strip().lower()
    if normalized not in CAPTURE_BACKENDS:
        normalized = "scrcpy"
    old = _capture_backend()
    os.environ["ADB_AUTO_CAPTURE_BACKEND"] = normalized
    if old != normalized:
        stop_scrcpy_sources()
        log_info(f"[capture] backend → {normalized}")
    return normalized


def _serial_of(controller) -> str:
    serial = getattr(controller, "device_id", None)
    if serial:
        return str(serial)
    device = getattr(controller, "device", None)
    serial = getattr(device, "serial", None)
    return str(serial or "default")


def decode_screencap(raw: Optional[bytes]) -> Optional[np.ndarray]:
    """Decode ADB screencap PNG bytes into BGR, or None."""
    if not raw:
        return None
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def capture_adb_screen(controller) -> Optional[np.ndarray]:
    """Capture one frame through ADB screencap."""
    try:
        return decode_screencap(controller.capture_screen_raw())
    except Exception as exc:
        log_warning(f"[capture] ADB screencap lỗi: {exc}")
        return None


def capture_screen(controller, timeout: float = 1.5) -> Optional[np.ndarray]:
    """Capture a BGR frame using configured backend.

    ``ADB_AUTO_CAPTURE_BACKEND``:
    - ``scrcpy`` (default): use headless scrcpy-client, return None on failure
    - ``adb``: force old screencap path
    """
    backend = _capture_backend()
    if backend == "adb":
        return capture_adb_screen(controller)
    frame = capture_scrcpy_screen(controller, timeout=timeout)
    if frame is None:
        global _LAST_NO_FRAME_LOG
        now = time.monotonic()
        if now - _LAST_NO_FRAME_LOG >= 1.0:
            _LAST_NO_FRAME_LOG = now
            log_warning("[capture] scrcpy chưa có frame (ADB fallback đang tắt)")
    return frame


def capture_scrcpy_screen(controller, timeout: float = 1.5) -> Optional[np.ndarray]:
    """Return the latest scrcpy frame for a controller, or None if unavailable."""
    if not os.path.isfile(_SCRCPY_EXE):
        log_warning(f"[capture] không tìm thấy scrcpy: {_SCRCPY_EXE}")
        return None

    serial = _serial_of(controller)
    with _SOURCES_LOCK:
        src = _SOURCES.get(serial)
        if src is None:
            src = ScrcpyFrameSource(serial=serial)
            _SOURCES[serial] = src
    return src.get_frame(timeout=timeout)


def stop_scrcpy_sources() -> None:
    """Stop all background scrcpy frame sources."""
    with _SOURCES_LOCK:
        sources = list(_SOURCES.values())
        _SOURCES.clear()
    for src in sources:
        src.stop()


class ScrcpyFrameSource:
    """Headless scrcpy-client frame source for one device serial."""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._client = None
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest: Optional[np.ndarray] = None
        self._frame_id = 0
        self._last_error = ""
        self._last_start_attempt = 0.0
        self._started_once = False

    def get_frame(self, timeout: float = 1.5) -> Optional[np.ndarray]:
        self.start()
        if self._client is None:
            return None
        start_id = self._frame_id
        deadline = time.monotonic() + max(0.05, timeout)
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest is not None and self._frame_id != start_id:
                    return self._latest.copy()
                if self._latest is not None and timeout <= 0:
                    return self._latest.copy()
            self._frame_event.wait(min(0.05, max(0.0, deadline - time.monotonic())))
            self._frame_event.clear()
        with self._lock:
            return self._latest.copy() if self._latest is not None else None

    def start(self) -> None:
        if self._client is not None:
            return
        if not os.path.isfile(_SCRCPY_EXE):
            return
        now = time.monotonic()
        if now - self._last_start_attempt < 3.0:
            return
        self._last_start_attempt = now

        try:
            # scrcpy-client uses adbutils internally and starts scrcpy-server
            # headlessly. Point it at the bundled adb/server assets where possible.
            os.environ.setdefault("SCRCPY_SERVER_PATH", _SCRCPY_SERVER)
            os.environ.setdefault("ADB", os.path.join(_SCRCPY_DIR, "adb.exe"))
            import scrcpy  # type: ignore

            client = scrcpy.Client(
                device=None if self.serial == "default" else self.serial,
                max_fps=30,
                block_frame=False,
            )
            client.add_listener(scrcpy.EVENT_FRAME, self._on_frame)
            client.start(threaded=True)
            self._client = client
        except Exception as exc:
            self._last_error = str(exc)
            self._client = None
            log_warning(f"[capture] không mở được scrcpy-client: {exc}")
            return

        if not self._started_once:
            log_info(f"[capture] scrcpy-client started headless ({self.serial})")
            self._started_once = True

    def stop(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            try:
                client.stop()
            except Exception:
                pass

    def _on_frame(self, frame) -> None:
        if frame is None:
            return
        try:
            arr = np.asarray(frame, dtype=np.uint8)
            # scrcpy-client 0.4.x already yields frames in OpenCV-friendly BGR
            # order on this stack. Do not RGB->BGR swap here, or template colors
            # diverge strongly from ADB screencap captures.
            if arr.ndim == 3 and arr.shape[2] >= 3:
                arr = arr[:, :, :3]
            with self._lock:
                self._latest = arr.copy()
                self._frame_id += 1
            self._frame_event.set()
        except Exception as exc:
            self._last_error = str(exc)
            log_debug(f"[capture] scrcpy frame callback lỗi: {exc}")
