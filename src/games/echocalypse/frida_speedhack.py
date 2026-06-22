"""
Runtime speedhack helper for Unity/IL2CPP (and Mono) games using Frida inject.

This manager pushes a JavaScript payload to the Android device and runs
``frida-inject`` against the target process. It avoids needing a persistent
``frida-server`` connection, which is fragile on some emulators (e.g.
LDPlayer). The injected script tries two strategies:

1. Call ``UnityEngine.Time.set_timeScale`` if the IL2CPP symbol is visible.
2. Hook ``clock_gettime`` / ``gettimeofday`` in ``libc.so`` to scale
   monotonic/real time for the whole process (works for Mono and stripped
   IL2CPP binaries).

Usage in a game class::

    from src.games.echocalypse.frida_speedhack import FridaSpeedhackManager

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
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from src.utils import log_error, log_info, log_success, log_warning


_INJECT_SCRIPT = """
var currentScale = 1.0;
var timeHookInstalled = false;
var baseReal = null;
var baseScaled = null;
var logFd = null;

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
    const candidateGetters = [
        '_ZN11UnityEngine4Time9timeScaleE',
        '_ZN11UnityEngine4Time12get_timeScaleE',
        'get_timeScale@UnityEngine.Time@@SAMXZ',
        '?get_timeScale@Time@UnityEngine@@SAMXZ',
        'UnityEngine.Time.get_timeScale',
        'UnityEngine_Time_get_timeScale',
        'get_timeScale',
    ];

    let setter = findExport(candidateSetters);
    let getter = findExport(candidateGetters);

    const m = findIl2CppModule();
    if (m) {
        const symbols = Module.enumerateExports(m.name);
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
        if (!getter) {
            for (let i = 0; i < symbols.length; i++) {
                const s = symbols[i];
                if (s.type !== 'function' || !s.name) continue;
                const lower = s.name.toLowerCase();
                if (lower.indexOf('get_timescale') !== -1 || lower.indexOf('get_time_scale') !== -1) {
                    getter = s.address; break;
                }
            }
        }
    }

    return { setter: setter, getter: getter };
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

function nowMs() {
    const tmp = Memory.alloc(16);
    const libc = Process.findModuleByName('libc.so');
    const fn = new NativeFunction(libc.getExportByName('clock_gettime'), 'int', ['int', 'pointer']);
    fn(1, tmp);
    return tmp.readLong() * 1000 + tmp.add(8).readLong() / 1000000;
}

function writeTimespec(tv, ms) {
    const sec = Math.floor(ms / 1000);
    const nsec = Math.floor((ms % 1000) * 1000000);
    tv.writeLong(sec);
    tv.add(8).writeLong(nsec);
}

function writeTimeval(tv, ms) {
    const sec = Math.floor(ms / 1000);
    const usec = Math.floor((ms % 1000) * 1000);
    tv.writeLong(sec);
    tv.add(8).writeLong(usec);
}

function installTimeHack(scale) {
    try {
        const libc = Process.findModuleByName('libc.so');
        if (!libc) {
            log('libc.so not found');
            return false;
        }
        const cgAddr = libc.getExportByName('clock_gettime');
        const gtAddr = libc.getExportByName('gettimeofday');

        if (cgAddr && !timeHookInstalled) {
            Interceptor.attach(cgAddr, {
                onEnter: function(args) { this.tv = args[1]; this.clock = args[0].toInt32(); },
                onLeave: function(retval) {
                    if (currentScale === 1.0) return;
                    if (!this.tv || this.tv.isNull()) return;
                    if (this.clock === 0) return;
                    if (baseReal === null) { baseReal = nowMs(); baseScaled = baseReal; }
                    const realMs = nowMs();
                    const delta = realMs - baseReal;
                    baseScaled += delta * currentScale;
                    baseReal = realMs;
                    writeTimespec(this.tv, baseScaled);
                }
            });
        }

        if (gtAddr && !timeHookInstalled) {
            Interceptor.attach(gtAddr, {
                onEnter: function(args) { this.tv = args[0]; },
                onLeave: function(retval) {
                    if (currentScale === 1.0) return;
                    if (!this.tv || this.tv.isNull()) return;
                    if (baseReal === null) { baseReal = nowMs(); baseScaled = baseReal; }
                    const realMs = nowMs();
                    const delta = realMs - baseReal;
                    baseScaled += delta * currentScale;
                    baseReal = realMs;
                    writeTimeval(this.tv, baseScaled);
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
    if (installTimeScaleHook(scale)) return;
    if (installTimeHack(scale)) return;
    log('error: no speedhack strategy available');
}

log('script loaded, target=' + TARGET_SCALE);
setScale(TARGET_SCALE);
log('script finished');
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
    ):
        self.package = package
        self._target_scale = float(time_scale)
        self._current_scale: float = 1.0
        self._frida_inject_path = frida_inject_path
        self._local_inject_binary = local_inject_binary

        self._device_script_path = "/data/local/tmp/speedhack.js"
        self._lock = threading.Lock()
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
    def _bundled_inject_path() -> Optional[Path]:
        root = Path(__file__).resolve().parents[3]
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
        root = Path(__file__).resolve().parents[3]
        bundled = root / "bin" / "adb.exe"
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

    def _run_adb(self, command: str) -> str:
        """Run an ADB shell command and return stdout+stderr; empty on failure."""
        adb = self._adb_path()
        try:
            result = subprocess.run(
                [adb, "shell", command],
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
        check = self._run_adb(f"test -f {self._frida_inject_path} && echo OK || echo MISSING")
        if "OK" in check:
            return True

        log_info("[speedhack] pushing frida-inject to device...")
        try:
            subprocess.run(
                [self._adb_path(), "push", str(local), self._frida_inject_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self._run_adb(f"chmod 755 {self._frida_inject_path}")
            return True
        except Exception as e:
            log_error(f"[speedhack] failed to push frida-inject: {e}")
            return False

    def _find_pid(self) -> Optional[int]:
        """Find the PID of the target package."""
        out = self._run_adb(f"pidof {self.package}")
        pid = out.strip().split()
        if pid and pid[0].isdigit():
            return int(pid[0])
        # Fallback: ps
        out = self._run_adb(f"ps -A | grep -F {self.package}")
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
                [self._adb_path(), "push", str(local_path), self._device_script_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return True
        except Exception as e:
            log_error(f"[speedhack] failed to push script: {e}")
            return False

    def set_scale(self, scale: float) -> bool:
        """Inject a script that sets the in-game/app time scale to ``scale``."""
        scale = float(scale)
        log_info(f"[speedhack] requesting time scale = {scale}")

        if not self.available:
            log_warning("[speedhack] frida-inject binary not available")
            return False

        with self._lock:
            if not self._push_inject_if_needed():
                return False

            pid = self._find_pid()
            if pid is None:
                log_error(f"[speedhack] cannot find pid for {self.package}")
                return False

            if not self._push_script(scale):
                return False

            log_info(f"[speedhack] injecting into {self.package} (pid {pid})...")
            try:
                proc = subprocess.Popen(
                    [
                        self._adb_path(),
                        "shell",
                        f"su -c '{self._frida_inject_path} -p {pid} -s {self._device_script_path}'",
                    ],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                self._inject_proc = proc

                # Stream logs in a background thread so we can see Frida send() messages.
                def _reader(pipe, label):
                    try:
                        for line in iter(pipe.readline, ""):
                            line = line.strip()
                            if not line:
                                continue
                            if label == "stdout":
                                log_info(f"[speedhack] {line}")
                            else:
                                log_warning(f"[speedhack] {line}")
                    except Exception:
                        pass

                import threading
                threading.Thread(target=_reader, args=(proc.stdout, "stdout"), daemon=True).start()
                threading.Thread(target=_reader, args=(proc.stderr, "stderr"), daemon=True).start()

                # Wait for injection. frida-inject may stay alive as an agent;
                # we don't want to block forever, but we do want to see initial output.
                try:
                    proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    pass

                # If we never saw an error, treat as success. The agent keeps running.
                self._current_scale = scale
                self._target_scale = scale
                log_success(f"[speedhack] time scale set to {scale}")
                return True
            except Exception as e:
                log_error(f"[speedhack] failed to inject: {e}")
                return False

    def get_scale(self) -> Optional[float]:
        """Return the last requested time scale."""
        return self._current_scale if self._current_scale != 1.0 else None

    def reset(self) -> bool:
        """Restore normal speed (time scale = 1.0)."""
        return self.set_scale(1.0)

    def detach(self) -> None:
        """Restore normal speed and clean up."""
        with self._lock:
            self.set_scale(1.0)
            try:
                if self._inject_proc is not None:
                    self._inject_proc.terminate()
                    self._inject_proc.wait(timeout=2)
            except Exception as e:
                log_warning(f"[speedhack] error stopping inject proc: {e}")
            finally:
                self._inject_proc = None
        log_info("[speedhack] detached")


def demo():
    """Small command-line demo to test injecting a running process."""
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m src.games.echocalypse.frida_speedhack <package> [scale]")
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
