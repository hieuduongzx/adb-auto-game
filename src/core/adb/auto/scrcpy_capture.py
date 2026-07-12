"""Shared screen capture helpers with optional scrcpy video frames.

The old path uses ``adb shell screencap`` for every screenshot. This module adds
an optional scrcpy-backed frame source so DevScope, workflow template matching
and OCR can all read from the same low-latency mirror frame.

The frame source speaks the scrcpy 2.x+ protocol directly against the bundled
``vendor/scrcpy/scrcpy-server`` (4.x): push jar → ``app_process`` with
``raw_stream=true`` (video only) → decode the H.264 stream with PyAV. The pip
package ``scrcpy-client`` is no longer used — its bundled v1.20 server dies on
Android 13+ (MuMu Android-15 images), and it ignored our server path anyway.
"""
from __future__ import annotations

import os
import random
import re
import socket
import subprocess
import threading
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

try:
    from av.codec import CodecContext  # PyAV — H.264 decode
except ImportError:  # pragma: no cover
    CodecContext = None

from src.utils import CREATE_NO_WINDOW, app_dir, log_debug, log_info, log_warning
from ..constants import get_adb_path


def _scrcpy_dir() -> str:
    """``vendor/scrcpy`` next to the project root (source) or the .exe (frozen)."""
    return os.path.join(app_dir(), "vendor", "scrcpy")


def _scrcpy_exe() -> str:
    return os.path.join(_scrcpy_dir(), "scrcpy.exe" if os.name == "nt" else "scrcpy")


def _scrcpy_server() -> str:
    return os.path.join(_scrcpy_dir(), "scrcpy-server")


_SOURCES: Dict[str, "ScrcpyFrameSource"] = {}
_SOURCES_LOCK = threading.Lock()
CAPTURE_BACKENDS = ("scrcpy", "adb")
_LAST_NO_FRAME_LOG = 0.0
_UNAVAILABLE_LOGGED = False

_SERVER_VERSION: Optional[str] = None


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


def _scrcpy_available() -> bool:
    return (CodecContext is not None
            and os.path.isfile(_scrcpy_server()))


def _adb_run(serial: str, *args: str, timeout: float = 15.0) -> subprocess.CompletedProcess:
    """Run a vendor-adb command against one device."""
    return subprocess.run(
        [get_adb_path(), "-s", serial, *args],
        capture_output=True, text=True, timeout=timeout,
        creationflags=CREATE_NO_WINDOW,
    )


def _scrcpy_server_version() -> str:
    """Version string the server jar expects as its first argument.

    Read once from ``scrcpy.exe --version`` (exe and jar ship together in
    vendor/). The server refuses to start when this doesn't match exactly.
    """
    global _SERVER_VERSION
    if _SERVER_VERSION:
        return _SERVER_VERSION
    try:
        out = subprocess.run(
            [_scrcpy_exe(), "--version"], capture_output=True, text=True,
            timeout=10, creationflags=CREATE_NO_WINDOW,
        ).stdout
        m = re.search(r"scrcpy\s+(\d[\w.]*)", out or "")
        if m:
            _SERVER_VERSION = m.group(1)
    except Exception as exc:
        log_debug(f"[capture] scrcpy --version failed: {exc}")
    return _SERVER_VERSION or "4.0"


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
    - ``scrcpy`` (default): headless scrcpy stream; auto-falls back to ADB
      screencap per device when scrcpy can't stream there
    - ``adb``: force old screencap path
    """
    backend = _capture_backend()
    if backend == "adb":
        return capture_adb_screen(controller)
    if not _scrcpy_available():
        global _UNAVAILABLE_LOGGED
        if not _UNAVAILABLE_LOGGED:
            _UNAVAILABLE_LOGGED = True
            log_warning("[capture] scrcpy không khả dụng (thiếu PyAV hoặc "
                        "vendor/scrcpy/scrcpy-server) → dùng ADB screencap")
        return capture_adb_screen(controller)
    frame = capture_scrcpy_screen(controller, timeout=timeout)
    if frame is None:
        serial = _serial_of(controller)
        with _SOURCES_LOCK:
            src = _SOURCES.get(serial)
        if src is not None and src.is_dead:
            # scrcpy-server không chạy nổi trên máy này → ADB screencap thay.
            return capture_adb_screen(controller)
        global _LAST_NO_FRAME_LOG
        now = time.monotonic()
        if now - _LAST_NO_FRAME_LOG >= 1.0:
            _LAST_NO_FRAME_LOG = now
            log_warning("[capture] scrcpy chưa có frame")
    return frame


def capture_scrcpy_screen(controller, timeout: float = 1.5) -> Optional[np.ndarray]:
    """Return the latest scrcpy frame for a controller, or None if unavailable."""
    if not _scrcpy_available():
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


def warm_scrcpy_source(controller_or_serial) -> bool:
    """Pre-start the headless scrcpy stream for a device.

    The stream needs ~1-2s after start before its first frame arrives; calling
    this as soon as a device connects means a later workflow run (or DevScope
    capture) reads a frame instantly instead of paying that warm-up on Play.
    Idempotent and cheap: an already-running source is left untouched.
    """
    if _capture_backend() != "scrcpy" or not _scrcpy_available():
        return False
    serial = (controller_or_serial if isinstance(controller_or_serial, str)
              else _serial_of(controller_or_serial))
    if not serial:
        return False
    with _SOURCES_LOCK:
        src = _SOURCES.get(serial)
        if src is None:
            src = ScrcpyFrameSource(serial=serial)
            _SOURCES[serial] = src
    src.start()
    return not src.is_dead


class ScrcpyFrameSource:
    """Headless scrcpy 4.x frame source for one device serial.

    Lifecycle per session (all in one background thread):
    push jar → ``adb forward`` → launch server via ``app_process`` →
    connect the forwarded socket → decode raw H.264 with PyAV → publish
    the latest BGR frame. Frames are resized to the device's ``wm size``
    when the encoder caps the stream below native resolution (MuMu
    Android-15 emits 1820×1024 for a 1920×1080 display), so template
    coordinates stay consistent with ADB screencap captures.
    """

    JAR_REMOTE = "/data/local/tmp/scrcpy-server-aag.jar"

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._lock = threading.Lock()
        self._frame_event = threading.Event()
        self._latest: Optional[np.ndarray] = None
        self._frame_id = 0
        self._last_error = ""
        self._last_start_attempt = 0.0
        self._started_once = False
        self._dead = False
        self._failed_starts = 0
        self._stopping = False
        self._streaming = False
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._port: Optional[int] = None
        # Device size as (long side, short side); frames get fitted to it.
        self._native: Optional[Tuple[int, int]] = None

    @property
    def is_dead(self) -> bool:
        """True when scrcpy can't stream this device (callers should use ADB)."""
        return self._dead

    # ── Public API ───────────────────────────────────────────────────────────

    def get_frame(self, timeout: float = 1.5) -> Optional[np.ndarray]:
        if self._dead:
            return None
        self.start()
        deadline = time.monotonic() + max(0.05, timeout)
        while time.monotonic() < deadline:
            with self._lock:
                # A live stream means the latest frame IS the current screen:
                # the encoder only emits when the display changes, so a static
                # screen produces no new frames — don't wait out the timeout.
                if self._latest is not None and (self._streaming or timeout <= 0):
                    return self._latest.copy()
            self._frame_event.wait(min(0.05, max(0.0, deadline - time.monotonic())))
            self._frame_event.clear()
        with self._lock:
            return self._latest.copy() if self._latest is not None else None

    def start(self) -> None:
        """Ensure the background stream session is running (non-blocking)."""
        if self._dead:
            return
        t = self._thread
        if t is not None and t.is_alive():
            return
        now = time.monotonic()
        if now - self._last_start_attempt < 3.0:
            return
        self._last_start_attempt = now
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"scrcpy-src-{self.serial}")
        self._thread.start()

    def stop(self) -> None:
        self._stopping = True
        self._cleanup()

    # ── Stream session (background thread) ───────────────────────────────────

    def _run(self) -> None:
        got_frame = False
        try:
            first_chunk = self._launch_and_connect()
            got_frame = self._stream_loop(first_chunk)
        except Exception as exc:
            self._last_error = str(exc)
            if not self._stopping:
                log_debug(f"[capture] scrcpy source {self.serial}: {exc}")
        finally:
            self._cleanup()
            if not self._stopping:
                self._register_outcome(got_frame)

    def _register_outcome(self, got_frame: bool) -> None:
        if got_frame:
            # Streamed fine and then dropped (device reboot, adb hiccup…):
            # transient — a later get_frame()/start() relaunches the session.
            self._failed_starts = 0
            return
        self._failed_starts += 1
        if self._failed_starts >= 2:
            self._dead = True
            log_warning(
                f"[capture] scrcpy không stream được trên {self.serial} "
                f"({self._last_error or 'không có frame'}) "
                "→ tự chuyển sang ADB screencap cho máy này")
        else:
            log_debug(f"[capture] scrcpy chưa stream được trên {self.serial}, "
                      f"sẽ thử lại ({self._last_error or 'không có frame'})")

    def _launch_and_connect(self) -> bytes:
        """Push server, forward a port, start it, return the first bytes."""
        r = _adb_run(self.serial, "push", _scrcpy_server(), self.JAR_REMOTE)
        if r.returncode != 0:
            raise RuntimeError(f"adb push thất bại: {(r.stderr or r.stdout).strip()}")

        # MuMu wipes /data/local/tmp periodically, so the jar is re-pushed on
        # every session start; a running server keeps its (unlinked) dex alive.
        scid = f"{random.getrandbits(31):08x}"
        r = _adb_run(self.serial, "forward", "tcp:0", f"localabstract:scrcpy_{scid}")
        if r.returncode != 0:
            raise RuntimeError(f"adb forward thất bại: {(r.stderr or r.stdout).strip()}")
        self._port = int(r.stdout.strip())

        cmd = [
            get_adb_path(), "-s", self.serial, "shell",
            f"CLASSPATH={self.JAR_REMOTE}", "app_process", "/",
            "com.genymobile.scrcpy.Server", _scrcpy_server_version(),
            f"scid={scid}", "log_level=info",
            "video=true", "audio=false", "control=false",
            "tunnel_forward=true", "raw_stream=true",
            "max_fps=30", "max_size=0",
        ]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, creationflags=CREATE_NO_WINDOW)
        threading.Thread(target=self._pump_server_log, args=(self._proc,),
                         daemon=True).start()

        self._native = self._query_native_size()

        # The server needs a moment before its abstract socket listens; with
        # raw_stream there is no dummy byte, so probe until real data arrives.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not self._stopping:
            if self._proc.poll() is not None:
                raise RuntimeError("scrcpy-server thoát sớm")
            try:
                sock = socket.create_connection(("127.0.0.1", self._port), timeout=2.0)
            except OSError:
                time.sleep(0.2)
                continue
            sock.settimeout(2.0)
            try:
                first = sock.recv(0x10000)
            except (socket.timeout, OSError):
                first = b""
            if first:
                self._sock = sock
                return first
            try:
                sock.close()
            except OSError:
                pass
            time.sleep(0.2)
        raise RuntimeError("scrcpy-server không gửi dữ liệu")

    def _stream_loop(self, chunk: bytes) -> bool:
        codec = CodecContext.create("h264", "r")
        sock = self._sock
        sock.settimeout(1.0)
        got_frame = False
        while not self._stopping:
            if chunk:
                for packet in codec.parse(chunk):
                    for frame in codec.decode(packet):
                        arr = frame.to_ndarray(format="bgr24")
                        arr = self._fit(arr)
                        with self._lock:
                            self._latest = arr
                            self._frame_id += 1
                        self._frame_event.set()
                        got_frame = True
                        self._streaming = True
                        if not self._started_once:
                            self._started_once = True
                            h, w = arr.shape[:2]
                            log_info(f"[capture] scrcpy stream {w}x{h} "
                                     f"({self.serial})")
            try:
                chunk = sock.recv(0x20000)
            except socket.timeout:
                chunk = b""
                if self._proc is None or self._proc.poll() is not None:
                    break
                continue
            except OSError:
                break
            if not chunk:
                break
        return got_frame

    def _pump_server_log(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:
                line = line.strip()
                if line:
                    log_debug(f"[scrcpy-server {self.serial}] {line}")
        except Exception:
            pass

    def _cleanup(self) -> None:
        self._streaming = False
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        port, self._port = self._port, None
        if port is not None:
            try:
                _adb_run(self.serial, "forward", "--remove", f"tcp:{port}",
                         timeout=5.0)
            except Exception:
                pass

    # ── Frame fitting ────────────────────────────────────────────────────────

    def _query_native_size(self) -> Optional[Tuple[int, int]]:
        """Device screen size from ``wm size`` as (long, short), or None."""
        try:
            out = _adb_run(self.serial, "shell", "wm", "size").stdout or ""
            # Prefer "Override size" (user-changed) over "Physical size".
            m = (re.search(r"Override size:\s*(\d+)x(\d+)", out)
                 or re.search(r"Physical size:\s*(\d+)x(\d+)", out))
            if not m:
                return None
            a, b = int(m.group(1)), int(m.group(2))
            return (max(a, b), min(a, b))
        except Exception as exc:
            log_debug(f"[capture] wm size failed for {self.serial}: {exc}")
            return None

    def _fit(self, arr: np.ndarray) -> np.ndarray:
        """Resize a decoded frame to the device resolution when the encoder
        capped the stream (keeps template-matching coordinates correct)."""
        if self._native is None:
            return arr
        h, w = arr.shape[:2]
        long_side, short_side = self._native
        tw, th = (long_side, short_side) if w >= h else (short_side, long_side)
        if (w, h) != (tw, th):
            arr = cv2.resize(arr, (tw, th), interpolation=cv2.INTER_LINEAR)
        return arr
