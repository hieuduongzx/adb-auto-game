"""Shared screen capture helpers with optional scrcpy video frames.

The old path uses ``adb shell screencap`` for every screenshot. This module adds
an optional scrcpy-backed frame source so DevScope, workflow template matching
and OCR can all read from the same low-latency video stream. It is intentionally
best-effort: if scrcpy/PyAV cannot start, callers fall back to ADB screencap.
"""
from __future__ import annotations

import os
import subprocess
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


def _capture_backend() -> str:
    """Return requested capture backend: auto, scrcpy or adb."""
    return os.environ.get("ADB_AUTO_CAPTURE_BACKEND", "auto").strip().lower() or "auto"


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
    """Capture a BGR frame using configured backend, falling back to ADB.

    ``ADB_AUTO_CAPTURE_BACKEND``:
    - ``auto`` (default): try scrcpy, then ADB screencap
    - ``scrcpy``: try scrcpy first, still fallback to ADB on failure
    - ``adb``: force old screencap path
    """
    backend = _capture_backend()
    if backend != "adb":
        frame = capture_scrcpy_screen(controller, timeout=timeout)
        if frame is not None:
            return frame
        if backend == "scrcpy":
            log_warning("[capture] scrcpy chưa có frame, fallback ADB screencap")
    return capture_adb_screen(controller)


def capture_scrcpy_screen(controller, timeout: float = 1.5) -> Optional[np.ndarray]:
    """Return the latest scrcpy frame for a controller, or None if unavailable."""
    if not os.path.isfile(_SCRCPY_EXE):
        return None
    try:
        import av  # type: ignore  # optional dependency, imported lazily
    except Exception:
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
    """Background scrcpy process + PyAV decoder for one device serial."""

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest: Optional[np.ndarray] = None
        self._frame_id = 0
        self._last_error = ""
        self._last_start_attempt = 0.0
        self._started_once = False

    def get_frame(self, timeout: float = 1.5) -> Optional[np.ndarray]:
        self.start()
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
        if self._proc is not None and self._proc.poll() is None:
            return
        if not os.path.isfile(_SCRCPY_EXE):
            return
        now = time.monotonic()
        if now - self._last_start_attempt < 3.0:
            return
        self._last_start_attempt = now

        port_base = 30000 + (abs(hash(self.serial)) % 500)
        args = [
            _SCRCPY_EXE,
            "--no-window",
            "--no-audio",
            "--no-control",
            "--record=-",
            "--record-format=mkv",
            "--max-fps=30",
            f"--port={port_base}:{port_base + 20}",
            "-V",
            "warn",
        ]
        if self.serial and self.serial != "default":
            args.extend(["-s", self.serial])

        env = os.environ.copy()
        if os.path.isfile(_SCRCPY_SERVER):
            env["SCRCPY_SERVER_PATH"] = _SCRCPY_SERVER

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            self._proc = subprocess.Popen(
                args,
                cwd=_SCRCPY_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
            )
        except Exception as exc:
            self._last_error = str(exc)
            log_warning(f"[capture] không mở được scrcpy: {exc}")
            return

        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()
        self._stderr_thread = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_thread.start()
        if not self._started_once:
            log_info(f"[capture] scrcpy frame source started ({self.serial})")
            self._started_once = True

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _decode_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            import av  # type: ignore
            container = av.open(proc.stdout, format="matroska", mode="r")
            for frame in container.decode(video=0):
                arr = frame.to_ndarray(format="bgr24")
                with self._lock:
                    self._latest = arr
                    self._frame_id += 1
                self._frame_event.set()
                if proc.poll() is not None:
                    break
        except Exception as exc:
            self._last_error = str(exc)
            log_debug(f"[capture] scrcpy decode stopped: {exc}")
        finally:
            self.stop()

    def _stderr_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", errors="replace").strip()
                if line and ("ERROR" in line or "WARN" in line):
                    log_debug(f"[scrcpy] {line}")
                if proc.poll() is not None:
                    break
        except Exception:
            pass
