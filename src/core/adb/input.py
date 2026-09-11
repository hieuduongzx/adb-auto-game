"""Low-latency ADB input through a control-only scrcpy session.

The stock ``adb shell input`` path spawns a JVM on the device for every tap
(~100-300 ms each). This module speaks scrcpy-server's binary control protocol
directly instead, so a tap is a single small socket write. It reuses the
bundled ``vendor/scrcpy`` server (the same one the frame source pushes), started
with ``video=false audio=false control=true`` — no second video stream, no extra
window, and coordinates stay in native device pixels, exactly like ADB
``screencap`` templates expect.

The transport is chosen process-wide via ``set_input_backend`` (env
``ADB_AUTO_INPUT_BACKEND``): ``"adb"`` keeps the always-compatible
``adb shell input`` path, ``"scrcpy"`` uses this fast path with an automatic
fallback to the shell path whenever the session can't start.
"""
from __future__ import annotations

import os
import random
import socket
import struct
import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

from src.utils import CREATE_NO_WINDOW, log_debug, log_info, log_warning
from .constants import get_adb_path

# Message types (scrcpy 4.x control_msg.h) and Android motion actions.
_MSG_KEYCODE = 0
_MSG_TEXT = 1
_MSG_TOUCH = 2
_MSG_SCROLL = 3
_ACT_DOWN, _ACT_UP, _ACT_MOVE = 0, 1, 2

# A finger pointer id (well-known generic-finger value is -2; any non -1 value is
# treated as a touchscreen finger by the server).
_POINTER_FINGER = 0xFFFFFFFFFFFFFFFE

INPUT_BACKENDS = ("adb", "scrcpy")

_SESSIONS: Dict[str, "ScrcpyControlSession"] = {}
_SESSIONS_LOCK = threading.Lock()


def _input_backend() -> str:
    name = os.environ.get("ADB_AUTO_INPUT_BACKEND", "adb").strip().lower()
    return name if name in INPUT_BACKENDS else "adb"


def get_input_backend() -> str:
    """Current ADB input transport ("adb" | "scrcpy")."""
    return _input_backend()


def set_input_backend(name: str) -> str:
    """Set the process-wide ADB input transport; returns the normalized value."""
    normalized = (name or "").strip().lower()
    if normalized not in INPUT_BACKENDS:
        normalized = "adb"
    old = _input_backend()
    os.environ["ADB_AUTO_INPUT_BACKEND"] = normalized
    if old != normalized:
        stop_input_sessions()
        log_info(f"[input] backend → {normalized}")
    return normalized


def stop_input_sessions() -> None:
    """Tear down every control session (device lost / backend switch / exit)."""
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for s in sessions:
        s.close()


def control_session(controller) -> Optional["ScrcpyControlSession"]:
    """Return (creating if needed) the control session for *controller*'s device.

    Only meaningful for the ``scrcpy`` backend; returns ``None`` for the shell
    backend or when the device/compat pieces aren't available.
    """
    if _input_backend() != "scrcpy":
        return None
    serial = str(getattr(controller, "device_id", "") or
                 getattr(getattr(controller, "device", None), "serial", "") or "").strip()
    if not serial:
        return None
    with _SESSIONS_LOCK:
        sess = _SESSIONS.get(serial)
        if sess is None:
            sess = ScrcpyControlSession(serial)
            _SESSIONS[serial] = sess
    return sess


# ── wire encoding ─────────────────────────────────────────────────────────────

def _touch_msg(action: int, pointer_id: int, x: int, y: int, w: int, h: int,
               pressure: float, buttons: int = 0, action_button: int = 0) -> bytes:
    p = max(0.0, min(1.0, float(pressure)))
    uid = int(pointer_id) & 0xFFFFFFFFFFFFFFFF
    return struct.pack(">BBQiiHHHII", _MSG_TOUCH, int(action), uid,
                       int(x), int(y), int(w), int(h),
                       int(round(p * 0xFFFF)), int(action_button), int(buttons))


def _key_msg(action: int, keycode: int, repeat: int = 0, meta: int = 0) -> bytes:
    return struct.pack(">BBIII", _MSG_KEYCODE, int(action), int(keycode),
                       int(repeat), int(meta))


def _text_msg(text: str) -> bytes:
    data = (text or "").encode("utf-8")[:300]
    return struct.pack(">BI", _MSG_TEXT, len(data)) + data


def _scroll_msg(x: int, y: int, w: int, h: int,
                hscroll: float, vscroll: float, buttons: int = 0) -> bytes:
    hs = int(round(max(-1.0, min(1.0, hscroll)) * 0x7FFF))
    vs = int(round(max(-1.0, min(1.0, vscroll)) * 0x7FFF))
    return struct.pack(">BiiHHhhI", _MSG_SCROLL, int(x), int(y), int(w), int(h),
                       hs, vs, int(buttons))


class ScrcpyControlSession:
    """A control-only scrcpy-server session for one device serial."""

    JAR_REMOTE = "/data/local/tmp/scrcpy-server-aag.jar"

    def __init__(self, serial: str) -> None:
        self.serial = serial
        self._lock = threading.RLock()
        self._sock: Optional[socket.socket] = None
        self._proc: Optional[subprocess.Popen] = None
        self._port: Optional[int] = None
        self._dead = False
        self._last_error = ""
        self._size: Optional[Tuple[int, int]] = None

    @property
    def is_dead(self) -> bool:
        return self._dead

    def close(self) -> None:
        with self._lock:
            sock, self._sock = self._sock, None
            proc, self._proc = self._proc, None
            port, self._port = self._port, None
        for closer in (
            lambda: sock.close() if sock else None,
            lambda: proc.kill() if proc else None,
            lambda: self._adb("forward", "--remove", f"tcp:{port}") if port else None,
        ):
            try:
                closer()
            except Exception:
                pass

    # ── process / socket plumbing ─────────────────────────────────────────────

    def _adb(self, *args: str, timeout: float = 15.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            [get_adb_path(), "-s", self.serial, *args],
            capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW)

    def _server_paths(self):
        from .auto.scrcpy_capture import _scrcpy_server, _scrcpy_server_version
        return _scrcpy_server(), _scrcpy_server_version()

    def _ensure(self) -> bool:
        """Start the session if needed; True once the socket is usable."""
        with self._lock:
            if self._dead:
                return False
            if self._sock is not None:
                return True
            if not self._start():
                self._dead = True
                log_warning(f"[input] scrcpy control không khởi động được trên "
                            f"{self.serial} ({self._last_error}) → dùng ADB shell input")
                return False
            return True

    def _start(self) -> bool:
        try:
            server, version = self._server_paths()
            if not server or not os.path.isfile(server):
                self._last_error = "thiếu vendor/scrcpy/scrcpy-server"
                return False
            r = self._adb("push", server, self.JAR_REMOTE)
            if r.returncode != 0:
                self._last_error = f"adb push: {(r.stderr or r.stdout).strip()}"
                return False
            scid = f"{random.getrandbits(31):08x}"
            r = self._adb("forward", "tcp:0", f"localabstract:scrcpy_{scid}")
            if r.returncode != 0:
                self._last_error = f"adb forward: {(r.stderr or r.stdout).strip()}"
                return False
            port = int((r.stdout or "").strip())
            cmd = [
                get_adb_path(), "-s", self.serial, "shell",
                f"CLASSPATH={self.JAR_REMOTE}", "app_process", "/",
                "com.genymobile.scrcpy.Server", version,
                f"scid={scid}", "log_level=warn",
                "video=false", "audio=false", "control=true",
                "tunnel_forward=true", "raw_stream=true",
            ]
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=CREATE_NO_WINDOW)
            self._port = port
            self._proc = proc
            # The server needs a moment before its abstract socket answers. A
            # control connection has no initial bytes to wait on, so probe with
            # a short-lived connect: an upstream failure closes it immediately.
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    self._last_error = "scrcpy-server thoát sớm"
                    return False
                sock = self._probe_socket(port)
                if sock is not None:
                    self._sock = sock
                    log_info(f"[input] scrcpy control sẵn sàng ({self.serial})")
                    return True
                time.sleep(0.25)
            self._last_error = "scrcpy-server không mở control socket"
            return False
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def _probe_socket(self, port: int) -> Optional[socket.socket]:
        """Connect to the forwarded port and keep it if the server accepted."""
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1.5)
        except OSError:
            return None
        try:
            sock.settimeout(0.3)
            try:
                data = sock.recv(1, socket.MSG_PEEK)
                if data == b"":
                    sock.close()
                    return None
            except socket.timeout:
                pass  # connected, nothing sent yet — exactly what we expect
            except OSError:
                sock.close()
                return None
            sock.settimeout(2.0)
            return sock
        except Exception:
            try:
                sock.close()
            except OSError:
                pass
            return None

    def screen_size(self) -> Tuple[int, int]:
        """Device screen size as (w, h) in pixels; (0, 0) when unknown."""
        if self._size is None:
            try:
                out = self._adb("shell", "wm", "size").stdout or ""
                import re
                m = (re.search(r"Override size:\s*(\d+)x(\d+)", out)
                     or re.search(r"Physical size:\s*(\d+)x(\d+)", out))
                self._size = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
            except Exception:
                self._size = (0, 0)
        return self._size

    def _send(self, data: bytes) -> bool:
        if not self._ensure():
            return False
        try:
            with self._lock:
                self._sock.sendall(data)
            return True
        except Exception as exc:
            log_debug(f"[input] scrcpy control send lỗi ({self.serial}): {exc}")
            self._dead = True
            return False

    # ── high-level input ──────────────────────────────────────────────────────

    def tap(self, x: int, y: int, tap_count: int = 1, hold: float = 0.0,
            gap: float = 0.05) -> bool:
        """Tap *tap_count* times at (x, y).

        ``hold`` is how long the finger stays down (0 = instant, matching
        ``input tap``, which is the whole point of this backend — a held tap
        costs real wall-clock time and many UIs read it as a long-press).
        ``gap`` is the pause between taps of a multi-tap.
        """
        w, h = self.screen_size()
        if not (w and h):
            return False
        try:
            for i in range(max(1, int(tap_count))):
                if i:
                    time.sleep(max(0.0, float(gap)))
                if not self._send(_touch_msg(_ACT_DOWN, _POINTER_FINGER, x, y, w, h, 1.0)):
                    return False
                if hold > 0:
                    time.sleep(float(hold))
                if not self._send(_touch_msg(_ACT_UP, _POINTER_FINGER, x, y, w, h, 0.0)):
                    return False
            return True
        except Exception:
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        w, h = self.screen_size()
        if not (w and h):
            return False
        secs = max(1, int(duration)) / 1000.0
        steps = max(2, min(240, int(secs * 1000) // 15))
        try:
            if not self._send(_touch_msg(_ACT_DOWN, _POINTER_FINGER, x1, y1, w, h, 1.0)):
                return False
            # Schedule against a fixed start so send cost doesn't stretch the
            # gesture — a swipe that overruns its duration reads as a drag.
            start = time.monotonic()
            for i in range(1, steps + 1):
                target = start + secs * i / steps
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                cx = int(x1 + (x2 - x1) * i / steps)
                cy = int(y1 + (y2 - y1) * i / steps)
                if not self._send(_touch_msg(_ACT_MOVE, _POINTER_FINGER, cx, cy, w, h, 1.0)):
                    return False
            return self._send(_touch_msg(_ACT_UP, _POINTER_FINGER, x2, y2, w, h, 0.0))
        except Exception:
            return False

    def multi_tap(self, points: List[Tuple[int, int]], duration_ms: int = 80) -> bool:
        w, h = self.screen_size()
        if not (w and h) or len(points) < 2:
            return False
        pts = [(int(x), int(y)) for x, y in points][:10]
        try:
            for i, (x, y) in enumerate(pts):
                if not self._send(_touch_msg(_ACT_DOWN, i, x, y, w, h, 1.0)):
                    return False
            time.sleep(max(0.02, min(10.0, int(duration_ms) / 1000.0)))
            ok = True
            for i, (x, y) in enumerate(pts):
                if not self._send(_touch_msg(_ACT_UP, i, x, y, w, h, 0.0)):
                    ok = False
            return ok
        except Exception:
            return False

    def press_key(self, keycode: int) -> bool:
        try:
            if not self._send(_key_msg(_ACT_DOWN, int(keycode))):
                return False
            time.sleep(0.02)
            return self._send(_key_msg(_ACT_UP, int(keycode)))
        except Exception:
            return False

    def send_text(self, text: str) -> bool:
        if not text:
            return True
        return self._send(_text_msg(str(text)))

    def scroll(self, x: int, y: int, notches: int, horizontal: bool = False) -> bool:
        w, h = self.screen_size()
        if not (w and h):
            return False
        v = 0.0 if horizontal else (1.0 if notches > 0 else -1.0)
        hs = (1.0 if notches > 0 else -1.0) if horizontal else 0.0
        return self._send(_scroll_msg(x, y, w, h, hs, v))
