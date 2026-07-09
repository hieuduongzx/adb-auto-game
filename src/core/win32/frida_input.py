"""Frida-based input injection for Win32 games.

Provides ``FridaWin32Input`` which attaches to a game process and hooks
Windows input APIs (``GetCursorPos`` / ``GetMessagePos``) so the game reads
fake cursor coordinates without moving the real hardware cursor.

For Unity Mono/IL2CPP games an engine-level hook path is included as a
best-effort fallback (currently logs and falls back to the Win32 API hook).
"""
from __future__ import annotations

import threading
from typing import Optional

from src.utils import log_error, log_info, log_warning, log_debug

_FRIDA_SCRIPT_TEMPLATE = r"""
// Frida input hook script for Win32 games.
// Strategy: {{strategy}} ('api' or 'engine')

var strategy = "{{strategy}}";
var fakeX = -1, fakeY = -1;
var active = false;

function setFake(x, y) { fakeX = x; fakeY = y; active = (x !== -1); }
function clearFake() { fakeX = -1; fakeY = -1; active = false; }

/* ---------- Strategy 1: Win32 API hook (engine-agnostic) ---------- */
function hookApi() {
    var getCursorPos = Module.findExportByName('user32.dll', 'GetCursorPos');
    if (getCursorPos) {
        Interceptor.attach(getCursorPos, {
            onEnter: function(args) { this.pt = args[0]; },
            onLeave: function(retval) {
                if (!active) return;
                if (retval.toInt32() === 0) return;
                if (!this.pt || this.pt.isNull()) return;
                this.pt.writeS32(fakeX);
                this.pt.add(4).writeS32(fakeY);
            }
        });
        send({type:'hook', msg:'GetCursorPos hooked'});
    } else {
        send({type:'hook', msg:'GetCursorPos not found'});
    }

    var getMessagePos = Module.findExportByName('user32.dll', 'GetMessagePos');
    if (getMessagePos) {
        var orig = new NativeFunction(getMessagePos, 'uint', []);
        var replacement = new NativeCallback(function() {
            if (!active) return orig();
            return ((fakeY & 0xFFFF) << 16) | (fakeX & 0xFFFF);
        }, 'uint', []);
        Interceptor.replace(getMessagePos, replacement);
        send({type:'hook', msg:'GetMessagePos replaced'});
    } else {
        send({type:'hook', msg:'GetMessagePos not found'});
    }
}

/* ---------- Strategy 2: Unity engine hook (best-effort) ---------- */
function hookEngine() {
    var mono = Process.findModuleByName('mono.dll');
    if (!mono) mono = Process.findModuleByName('mono-2.0-bdwgc.dll');
    if (mono) {
        send({type:'hook', msg:'Mono runtime detected — engine hook not yet implemented (fallback to API)'});
        hookApi();
        return;
    }
    var unity = Process.findModuleByName('UnityPlayer.dll');
    var gameAsm = Process.findModuleByName('GameAssembly.dll');
    if (unity || gameAsm) {
        send({type:'hook', msg:'Unity/IL2CPP detected — engine hook not yet implemented (fallback to API)'});
        hookApi();
        return;
    }
    send({type:'hook', msg:'No recognised engine — falling back to Win32 API hook'});
    hookApi();
}

/* ---------- Init ---------- */
if (strategy === 'engine') {
    hookEngine();
} else {
    hookApi();
}

rpc.exports = {
    setTarget: function(x, y) { setFake(x, y); },
    clearTarget: function() { clearFake(); },
    isActive: function() { return active; }
};
"""


class FridaWin32Input:
    """Manages a Frida session that hooks cursor APIs inside the target process."""

    def __init__(self):
        self._session: Optional = None
        self._script: Optional = None
        self._pid: Optional[int] = None
        self._hwnd: Optional[int] = None
        self._strategy: str = "api"
        self._lock = threading.Lock()
        self._ready = False

    def _ensure_frida(self):
        try:
            import frida
            return frida
        except Exception as exc:
            raise RuntimeError(
                "Frida backend cần gói 'frida' (pip install frida). Chi tiết: %s" % exc
            ) from exc

    def attach(self, hwnd: int, strategy: str = "api") -> bool:
        frida = self._ensure_frida()
        # Resolve PID from hwnd
        try:
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception as exc:
            log_error(f"[frida-input] cannot get PID from hwnd: {exc}")
            return False

        if pid <= 0:
            log_error("[frida-input] invalid PID from hwnd")
            return False

        # Already attached to the same PID?
        if self._session and self._pid == pid:
            return True

        # Detach from old session first
        self.detach()

        self._hwnd = hwnd
        self._pid = pid
        self._strategy = strategy

        try:
            log_info(f"[frida-input] attaching to PID {pid} (strategy={strategy})...")
            self._session = frida.attach(pid)
            source = _FRIDA_SCRIPT_TEMPLATE.replace("{{strategy}}", strategy)
            self._script = self._session.create_script(source)

            def _on_message(msg, data):
                payload = msg.get("payload") if msg.get("type") == "send" else None
                if isinstance(payload, dict):
                    log_info(f"[frida-input] {payload.get('msg', '')}")
                elif msg.get("type") == "error":
                    log_error(f"[frida-input] script error: {msg.get('description', '')}")
                else:
                    log_debug(f"[frida-input] {msg}")

            self._script.on("message", _on_message)
            self._script.load()
            self._ready = True
            log_info("[frida-input] attached and script loaded")
            return True
        except Exception as exc:
            log_error(f"[frida-input] attach failed: {exc}")
            self.detach()
            return False

    def set_target(self, screen_x: int, screen_y: int) -> bool:
        with self._lock:
            if not self._ready or not self._script:
                return False
            try:
                self._script.exports.set_target(int(screen_x), int(screen_y))
                return True
            except Exception as exc:
                log_debug(f"[frida-input] set_target error: {exc}")
                return False

    def clear_target(self) -> bool:
        with self._lock:
            if not self._ready or not self._script:
                return False
            try:
                self._script.exports.clear_target()
                return True
            except Exception as exc:
                log_debug(f"[frida-input] clear_target error: {exc}")
                return False

    def detach(self) -> None:
        with self._lock:
            self._ready = False
            if self._script:
                try:
                    self._script.unload()
                except Exception:
                    pass
                self._script = None
            if self._session:
                try:
                    self._session.detach()
                except Exception:
                    pass
                self._session = None
            self._pid = None

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def pid(self) -> Optional[int]:
        return self._pid
