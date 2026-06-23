"""
Runtime speedhack helper for Unity/IL2CPP (and Mono) games using Frida inject.

This manager pushes a JavaScript payload to the Android device and runs
``frida-inject`` against the target process. It avoids needing a persistent
``frida-server`` connection, which is fragile on some emulators (e.g.
LDPlayer). The injected script tries two strategies:

1. Call ``UnityEngine.Time.set_timeScale`` if the IL2CPP symbol is visible.
2. Hook ``clock_gettime`` in ``libc.so`` to scale monotonic time for
   the whole process (works for Mono and stripped IL2CPP binaries).

Usage in a game class::

    from src.game_core.frida_speedhack import FridaSpeedhackManager

    class Echocalypse(BaseGameAutomation):
        def __init__(self):
            super().__init__()
            self.speedhack = FridaSpeedhackManager(
                package="com.yoozoo.jgame.us",
            )

        def stop(self):
            self.speedhack.set_scale(1.0)
            super().stop()

NOTE: This is a best-effort helper. Actual hook success depends on the
device being rooted and supporting Frida. Anti-cheat/integrity checks may
detect the injection and lead to bans.
"""
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from src.utils import log_error, log_info, log_success, log_warning


_INJECT_SCRIPT = """
// Clean up any interceptors left by a previous injection into this process.
try { Interceptor.detachAll(); } catch(e) {}

var currentScale = 1.0;
var timeHookInstalled = false;
var clockGettimeOriginal = null;
var readingOriginalClock = false;
var baseByClock = {};

function log(msg) {
    send(msg);
    try { console.log(msg); } catch (e) {}
}

function findIl2CppModule() {
    const modules = Process.enumerateModules();
    const names = ['libil2cpp.so', 'libunity.so'];
    for (let i = 0; i < names.length; i++) {
        const m = modules.find(function(mod) { return mod.name === names[i]; });
        if (m) return m;
    }
    return modules.find(function(mod) {
        return mod.name.indexOf('libil2cpp') !== -1 ||
               mod.name.indexOf('libunity') !== -1;
    });
}

function findExport(symbols) {
    const modules = Process.enumerateModules();
    for (let i = 0; i < modules.length; i++) {
        const mod = modules[i];
        const name = mod.name || mod.path;
        if (!name) continue;
        let exports;
        try {
            exports = mod.enumerateExports();
        } catch (e) {
            continue;
        }
        for (let j = 0; j < exports.length; j++) {
            const exp = exports[j];
            if (exp.type !== 'function' || !exp.name) continue;
            for (let k = 0; k < symbols.length; k++) {
                if (exp.name === symbols[k] || exp.name.toLowerCase() === symbols[k].toLowerCase()) {
                    log('resolved ' + exp.name + ' in ' + name + ' at ' + exp.address);
                    return exp.address;
                }
            }
        }
    }
    return null;
}

function resolveTimeScale() {
    const candidateSetters = [
        '_ZN11UnityEngine4Time12set_timeScaleEf',
        'set_timeScale@UnityEngine.Time@@SAXM',
        '?set_timeScale@Time@UnityEngine@@SAXM@Z',
        'UnityEngine.Time.set_timeScale',
        'UnityEngine_Time_set_timeScale',
        'set_timeScale',
    ];

    let setter = findExport(candidateSetters);
    const m = findIl2CppModule();
    if (m) {
        let symbols;
        try {
            symbols = m.enumerateExports();
        } catch (e) {
            symbols = [];
            log('enumerate exports failed: ' + e.message);
        }
        if (!setter) {
            for (let i = 0; i < symbols.length; i++) {
                const s = symbols[i];
                if (s.type !== 'function' || !s.name) continue;
                const lower = s.name.toLowerCase();
                if (lower.indexOf('set_timescale') !== -1 || lower.indexOf('set_time_scale') !== -1) {
                    setter = s.address; break;
                }
            }
        }
    }

    return { setter: setter };
}

function installTimeScaleHook(scale) {
    const ts = resolveTimeScale();
    if (!ts || !ts.setter) return false;
    try {
        const setScale = new NativeFunction(ts.setter, 'void', ['float']);
        setScale(scale);
        currentScale = scale;
        log('Time.timeScale hook applied: ' + scale);
        return true;
    } catch (e) {
        log('Time.timeScale hook failed: ' + e.message);
        return false;
    }
}

function readClockMs(clockId) {
    if (!clockGettimeOriginal) return null;
    const tmp = Memory.alloc(16);
    readingOriginalClock = true;
    try {
        const ret = clockGettimeOriginal(clockId, tmp);
        if (ret !== 0) return null;
        return tmp.readLong() * 1000 + tmp.add(8).readLong() / 1000000;
    } finally {
        readingOriginalClock = false;
    }
}

function scaledClockMs(clockId, realMs) {
    const key = String(clockId);
    let base = baseByClock[key];
    if (!base) {
        base = { real: realMs, scaled: realMs };
        baseByClock[key] = base;
        return realMs;
    }
    const delta = realMs - base.real;
    base.scaled += delta * currentScale;
    base.real = realMs;
    return base.scaled;
}

function writeTimespec(tv, ms) {
    const sec = Math.floor(ms / 1000);
    const nsec = Math.floor((ms % 1000) * 1000000);
    tv.writeLong(sec);
    tv.add(8).writeLong(nsec);
}

function installTimeHack(scale) {
    try {
        const libc = Process.findModuleByName('libc.so');
        if (!libc) {
            log('libc.so not found');
            return false;
        }
        const cgAddr = libc.getExportByName('clock_gettime');
        if (!cgAddr) {
            log('clock_gettime not found');
            return false;
        }
        clockGettimeOriginal = new NativeFunction(cgAddr, 'int', ['int', 'pointer']);

        if (!timeHookInstalled) {
            Interceptor.attach(cgAddr, {
                onEnter: function(args) { this.tv = args[1]; this.clock = args[0].toInt32(); },
                onLeave: function(retval) {
                    if (readingOriginalClock) return;
                    if (currentScale === 1.0) return;
                    if (retval.toInt32() !== 0) return;
                    if (!this.tv || this.tv.isNull()) return;
                    if (this.clock === 0) return;
                    const realMs = readClockMs(this.clock);
                    if (realMs === null) return;
                    writeTimespec(this.tv, scaledClockMs(this.clock, realMs));
                }
            });
        }

        timeHookInstalled = true;
        currentScale = scale;
        log('Time-hack fallback installed: scale=' + scale);
        return true;
    } catch (e) {
        log('Time-hack fallback failed: ' + e.message);
        return false;
    }
}

function setScale(scale) {
    log('setScale called: ' + scale);
    currentScale = scale;
    if (installTimeScaleHook(scale)) {
        log('success: Time.timeScale applied');
        return true;
    }
    if (scale === 1.0) {
        log('success: normal scale requested');
        return true;
    }
    if (installTimeHack(scale)) {
        log('success: Time-hack fallback applied');
        return true;
    }
    log('error: no speedhack strategy available');
    return false;
}

log('script loaded, target=' + TARGET_SCALE);
const speedhackOk = setScale(TARGET_SCALE);
log('script finished: ' + (speedhackOk ? 'success' : 'failed'));
"""


class FridaSpeedhackManager:
    """
    Best-effort manager for a Frida-based Unity time-scale speedhack.

    Args:
        package: Android package name of the target game.
        time_scale: Desired initial time scale (default 1.0 = normal speed).
        frida_inject_path: Absolute device path to ``frida-inject``.
        local_inject_binary: Optional local path to a ``frida-inject`` binary
            that will be pushed to the device when not present.
    """

    def __init__(
        self,
        package: str,
        time_scale: float = 1.0,
        frida_inject_path: str = "/data/local/tmp/frida-inject",
        local_inject_binary: Optional[str] = None,
        device_id: Optional[str] = None,
    ):
        self.package = package
        self._target_scale = float(time_scale)
        self._current_scale: float = 1.0
        self._frida_inject_path = frida_inject_path
        self._local_inject_binary = local_inject_binary
        self._device_id = device_id

        self._device_script_path = "/data/local/tmp/speedhack.js"
        self._lock = threading.RLock()
        self._inject_proc: Optional[subprocess.Popen] = None

    @property
    def available(self) -> bool:
        """Whether the bundled ``frida-inject`` binary exists locally."""
        if self._local_inject_binary and Path(self._local_inject_binary).is_file():
            return True
        bundled = self._bundled_inject_path()
        return bundled is not None and bundled.is_file()

    @property
    def active(self) -> bool:
        """Whether the speedhack is currently running (scale != 1.0)."""
        return self._current_scale != 1.0

    @staticmethod
    def _project_root() -> Path:
        """Find the repository root from this shared module location."""
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "vendor").is_dir() or (parent / "bin").is_dir():
                return parent
        return current.parents[2]

    @staticmethod
    def _bundled_inject_path() -> Optional[Path]:
        root = FridaSpeedhackManager._project_root()
        candidates = [
            root / "vendor" / "frida" / "frida-inject-17.15.1-android-x86_64",
            root / "vendor" / "frida" / "frida-inject",
        ]
        for c in candidates:
            if c.is_file():
                return c
        return None

    @staticmethod
    def _adb_path() -> str:
        """Return a usable ADB binary path."""
        candidates = []
        root = FridaSpeedhackManager._project_root()
        bundled = root / "vendor" / "adb" / "adb.exe"
        if bundled.is_file():
            candidates.append(str(bundled))
        candidates.append("adb")
        for c in candidates:
            try:
                result = subprocess.run(
                    [c, "version"], shell=False, capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return c
            except Exception:
                continue
        return candidates[0]

    def _adb_prefix(self) -> list:
        """Return the ADB command prefix including -s device_id when known.

        ``device_id`` passed at construction wins, but if none was provided we
        also accept a late-bound ``self.adb_controller`` reference so callers
        can set the target device after construction.
        """
        adb = self._adb_path()
        device_id = self._device_id
        if not device_id:
            ctrl = getattr(self, "adb_controller", None)
            if ctrl is not None:
                device_id = getattr(ctrl, "device_id", None) or getattr(ctrl, "device", None)
        if device_id:
            return [adb, "-s", device_id]
        return [adb]

    def _run_adb(self, command: str) -> str:
        """Run an ADB shell command and return stdout+stderr; empty on failure."""
        try:
            result = subprocess.run(
                self._adb_prefix() + ["shell", command],
                shell=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
            return (result.stdout or "") + (result.stderr or "")
        except Exception as e:
            log_warning(f"[speedhack] adb command failed: {e}")
            return ""

    def _push_inject_if_needed(self) -> bool:
        """Ensure ``frida-inject`` exists on the device."""
        local = self._local_inject_binary or self._bundled_inject_path()
        if not local:
            log_error(
                "[speedhack] no local frida-inject binary. "
                "Download frida-inject for your device architecture and place it in vendor/frida/"
            )
            return False

        # Use ``test -f`` and check its exit code instead of parsing ``ls``
        # output: ``ls`` echoes the path back in its own "No such file" error,
        # so a naive substring check always falsely reports the file as present.
        inject_path = shlex.quote(self._frida_inject_path)
        check = self._run_adb(f"test -f {inject_path} && echo OK || echo MISSING")
        if "OK" in check:
            return True

        log_info("[speedhack] pushing frida-inject to device...")
        try:
            subprocess.run(
                self._adb_prefix() + ["push", str(local), self._frida_inject_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self._run_adb(f"chmod 755 {inject_path}")
            return True
        except Exception as e:
            log_error(f"[speedhack] failed to push frida-inject: {e}")
            return False

    def _find_pid(self) -> Optional[int]:
        """Find the PID of the target package."""
        package = shlex.quote(self.package)
        out = self._run_adb(f"pidof {package}")
        pid = out.strip().split()
        if pid and pid[0].isdigit():
            return int(pid[0])
        out = self._run_adb(f"ps -A | grep -F -- {package}")
        for line in out.splitlines():
            parts = line.split()
            if self.package in line and len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
        return None

    def _push_script(self, scale: float) -> bool:
        """Write the JS payload locally and push it to the device."""
        source = _INJECT_SCRIPT.replace("TARGET_SCALE", f"{scale:.6f}")
        local_path = Path(tempfile.gettempdir()) / f"speedhack_{scale:.2f}.js"
        try:
            local_path.write_text(source, encoding="utf-8")
            subprocess.run(
                self._adb_prefix() + ["push", str(local_path), self._device_script_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return True
        except Exception as e:
            log_error(f"[speedhack] failed to push script: {e}")
            return False
        finally:
            try:
                local_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _stop_inject_proc(self) -> None:
        proc = self._inject_proc
        self._inject_proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception as e:
                log_warning(f"[speedhack] error stopping inject proc: {e}")

    def _kill_device_frida(self) -> None:
        """Kill any running frida-inject processes on the device to avoid stacked hooks."""
        self._run_adb("su -c 'pkill -f frida-inject 2>/dev/null; sleep 0.3' &")

    def _inject_scale_locked(self, scale: float, keep_alive: bool) -> bool:
        self._kill_device_frida()
        if not self._push_inject_if_needed():
            return False

        pid = self._find_pid()
        if pid is None:
            log_error(f"[speedhack] cannot find pid for {self.package}")
            return False

        if not self._push_script(scale):
            return False

        log_info(f"[speedhack] injecting into {self.package} (pid {pid})...")
        proc = None
        try:
            proc = subprocess.Popen(
                self._adb_prefix()
                + [
                    "shell",
                    f"su -c {shlex.quote(f'{self._frida_inject_path} -p {pid} -s {self._device_script_path}')}",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if keep_alive:
                self._inject_proc = proc
            status = {"success": False, "error": False}

            def _reader(pipe, label):
                if pipe is None:
                    return
                try:
                    for line in iter(pipe.readline, ""):
                        line = line.strip()
                        if not line:
                            continue
                        lower = line.lower()
                        if "success:" in lower or "script finished: success" in lower:
                            status["success"] = True
                        if "error:" in lower or "script finished: failed" in lower:
                            status["error"] = True
                        if label == "stdout":
                            log_info(f"[speedhack] {line}")
                        else:
                            log_warning(f"[speedhack] {line}")
                except Exception:
                    pass

            threads = [
                threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True),
                threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True),
            ]
            for thread in threads:
                thread.start()

            deadline = time.monotonic() + 8
            while time.monotonic() < deadline and proc.poll() is None:
                if status["success"] or status["error"]:
                    break
                time.sleep(0.05)

            if proc.poll() is not None:
                for thread in threads:
                    thread.join(timeout=0.2)

            if status["error"] or (proc.poll() not in (None, 0) and not status["success"]):
                log_error("[speedhack] injection script reported failure")
                return False

            if not status["success"]:
                log_warning("[speedhack] injection result not confirmed")

            return True
        except Exception as e:
            log_error(f"[speedhack] failed to inject: {e}")
            return False
        finally:
            if not keep_alive and proc is not None:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=2)
                    except Exception:
                        pass

    def set_scale(self, scale: float) -> bool:
        """Inject a script that sets the in-game/app time scale to ``scale``."""
        scale = float(scale)
        log_info(f"[speedhack] requesting time scale = {scale}")

        with self._lock:
            self._stop_inject_proc()

            if not self.available:
                log_warning("[speedhack] frida-inject binary not available")
                if scale == 1.0:
                    self._current_scale = 1.0
                    self._target_scale = 1.0
                return scale == 1.0

            ok = self._inject_scale_locked(scale, keep_alive=scale != 1.0)
            if not ok:
                if scale != 1.0:
                    self._stop_inject_proc()
                return False

            self._current_scale = scale
            self._target_scale = scale
            if scale == 1.0:
                log_success("[speedhack] time scale reset to 1.0")
            else:
                log_success(f"[speedhack] time scale set to {scale}")
            return True

    def get_scale(self) -> Optional[float]:
        """Return the last requested time scale."""
        return self._current_scale if self._current_scale != 1.0 else None

    def reset(self) -> bool:
        """Restore normal speed (time scale = 1.0)."""
        return self.set_scale(1.0)

    def detach(self) -> None:
        """Restore normal speed and clean up."""
        with self._lock:
            self._stop_inject_proc()
            self._kill_device_frida()
            self._current_scale = 1.0
            self._target_scale = 1.0
            self._run_adb(f"rm -f {shlex.quote(self._device_script_path)}")
        log_info("[speedhack] detached")


def demo():
    """Small command-line demo to test injecting a running process."""
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m src.game_core.frida_speedhack <package> [scale]")
        sys.exit(1)

    pkg = sys.argv[1]
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    mgr = FridaSpeedhackManager(package=pkg)
    if not mgr.available:
        print("frida-inject binary not available")
        sys.exit(1)

    print(f"injecting into {pkg} and setting scale={scale}...")
    ok = mgr.set_scale(scale)
    print("set_scale:", "ok" if ok else "failed")
    if ok:
        time.sleep(2)
        print("reset:", mgr.reset())


if __name__ == "__main__":
    demo()
