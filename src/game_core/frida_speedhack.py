"""
Runtime speedhack helper for Android games using Frida inject.

This manager pushes a JavaScript payload to the Android device and runs
``frida-inject`` against the target process. It avoids needing a persistent
``frida-server`` connection, which is fragile on some emulators (e.g.
LDPlayer). The injected script scales game time by hooking ``clock_gettime``
in ``libc.so`` to stretch ``CLOCK_MONOTONIC`` process-wide:

1. A native CModule hook (opt-in via ``use_cmodule``) — every call stays in
   compiled C, so it is smooth even at high scales. NOTE: it compiles a fresh
   executable page with TinyCC, which some protected titles detect and crash
   on at inject time.
2. A plain-JS hook as the default / fallback. This funnels a hot-path syscall
   through Frida's JS lock, but survives on protected titles where the CModule
   path crashes.

This engine-agnostic approach (GameGuardian-style) works regardless of whether
the title is Unity, Mono, or native.

Once injected, the script stays alive and polls a system property for the
desired scale, so the host can change speed LIVE (just ``setprop``) without
re-injecting -- this keeps slider drags smooth and avoids resetting the
monotonic-time base on every change.

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
import hashlib
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from src.utils import log_error, log_info, log_success, log_warning


_INJECT_SCRIPT = """
// Speedhack agent. Applies a time scale and supports LIVE changes via a system
// property, so the host can adjust speed without re-injecting.

// Drop any interceptors left behind by a previous injection into this process.
try { Interceptor.detachAll(); } catch (e) {}

var currentScale = 1.0;
var hookMode = 'none';        // 'clock-cmodule' | 'clock-js'
var clockScaleBuf = null;     // Memory(8) holding the live scale for the CModule
var jsHookInstalled = false;
var baseByClock = {};         // state for the JS fallback hook
var lastScaledMs = 0;         // monotonic floor: scaled CLOCK_MONOTONIC never decreases

function log(msg) {
    send(msg);
    try { console.log(msg); } catch (e) {}
}

/* --------------- Native clock_gettime hook (CModule, no JS bridge) ----------
 * clock_gettime is on the hot path (millions of calls/sec). Running the scaling
 * logic in compiled C via Interceptor.attach(addr, cmodule) keeps every call
 * native -- no JS-bridge crossing, no per-call allocation -- so it stays smooth
 * even at high scales. g_scale is a shared double the host updates live.
 */
var CLOCK_HOOK_C = `
#include <gum/guminterceptor.h>
#include <stdint.h>

extern double g_scale;

typedef struct { int64_t tv_sec; int64_t tv_nsec; } timespec64;
typedef struct { int clock_id; void * tv; } HookState;

static double real_base[16];
static double scaled_base[16];
static int has_base[16];
/* Global floor: the scaled CLOCK_MONOTONIC we return must never decrease, even
 * across threads/cores. POSIX only guarantees per-core ordering, so two
 * back-to-back calls landing on different cores can see real time dip slightly;
 * without a floor that dip is multiplied by the scale and handed to callers as
 * time going backwards -- which hangs pthread_cond_timedwait / GC / netcode. */
static double last_out = 0.0;

void
onEnter (GumInvocationContext * ic)
{
  HookState * s = gum_invocation_context_get_listener_invocation_data (ic, sizeof (HookState));
  s->clock_id = (int) (size_t) gum_invocation_context_get_nth_argument (ic, 0);
  s->tv = gum_invocation_context_get_nth_argument (ic, 1);
}

void
onLeave (GumInvocationContext * ic)
{
  if ((size_t) gum_invocation_context_get_return_value (ic) != 0)
    return;

  HookState * s = gum_invocation_context_get_listener_invocation_data (ic, sizeof (HookState));
  int clk = s->clock_id;
  /* Scale ONLY CLOCK_MONOTONIC (1). Leaving CLOCK_BOOTTIME (7) real avoids the
   * classic SystemClock.elapsedRealtime() speedhack detection, and leaving the
   * CPU-time clocks (2,3) real avoids upsetting the ART GC / watchdog. */
  if (clk != 1)
    return;

  timespec64 * ts = (timespec64 *) s->tv;
  if (ts == 0)
    return;

  double scale = g_scale;
  double real_ms = (double) ts->tv_sec * 1000.0 + (double) ts->tv_nsec / 1000000.0;
  double scaled_ms;
  if (!has_base[clk]) {
    has_base[clk] = 1;
    real_base[clk] = real_ms;
    scaled_base[clk] = real_ms;
    scaled_ms = real_ms;
  } else {
    /* Clamp the per-call gap: a scene load stalls the caller for hundreds of
     * ms (real), and multiplying that whole gap by the scale injects a huge
     * time jump that detonates Unity's FixedUpdate accumulator (spiral of
     * death -> freeze). Scale only up to MAX_STEP_MS; let the overflow pass
     * through at 1x so big stalls don't get amplified and wall-clock stays
     * close to real. */
    double delta = real_ms - real_base[clk];
    /* Cross-core dips would otherwise be amplified into a backward jump. */
    if (delta < 0.0)
      delta = 0.0;
    double MAX_STEP_MS = 100.0;
    if (delta > MAX_STEP_MS)
      scaled_base[clk] += MAX_STEP_MS * scale + (delta - MAX_STEP_MS);
    else
      scaled_base[clk] += delta * scale;
    real_base[clk] = real_ms;
    scaled_ms = scaled_base[clk];
  }

  /* Never hand back a value below the last one we returned (monotonic floor). */
  if (scaled_ms < last_out)
    scaled_ms = last_out;
  last_out = scaled_ms;

  int64_t sec = (int64_t) (scaled_ms / 1000.0);
  int64_t nsec = (int64_t) ((scaled_ms - (double) sec * 1000.0) * 1000000.0);
  ts->tv_sec = sec;
  ts->tv_nsec = nsec;
}
`;

function installClockCModule(scale) {
    try {
        const libc = Process.findModuleByName('libc.so');
        if (!libc) { log('libc.so not found'); return false; }
        const cgAddr = libc.getExportByName('clock_gettime');
        if (!cgAddr) { log('clock_gettime not found'); return false; }
        clockScaleBuf = Memory.alloc(8);
        clockScaleBuf.writeDouble(scale);
        const cm = new CModule(CLOCK_HOOK_C, { g_scale: clockScaleBuf });
        Interceptor.attach(cgAddr, cm);
        currentScale = scale;
        hookMode = 'clock-cmodule';
        log('clock hook installed (CModule native): scale=' + scale);
        return true;
    } catch (e) {
        log('CModule clock hook unavailable: ' + e.message);
        return false;
    }
}

/* ----------------- JS fallback clock hook (no per-call alloc) ---------------- */
function scaledClockMs(clockId, realMs) {
    const key = String(clockId);
    let base = baseByClock[key];
    if (!base) {
        base = { real: realMs, scaled: realMs };
        baseByClock[key] = base;
        if (realMs > lastScaledMs) lastScaledMs = realMs;
        return realMs;
    }
    // Clamp the per-call gap so a scene-load stall (hundreds of ms real) is not
    // multiplied by the scale into a huge time jump that triggers Unity's
    // FixedUpdate spiral of death (freeze). Scale only up to MAX_STEP_MS; let
    // the overflow pass through at 1x.
    let delta = realMs - base.real;
    // CLOCK_MONOTONIC can dip a few us across cores; without this the dip is
    // multiplied by the scale and handed back as time going backwards.
    if (delta < 0) delta = 0;
    const MAX_STEP_MS = 100.0;
    if (delta > MAX_STEP_MS) {
        base.scaled += MAX_STEP_MS * currentScale + (delta - MAX_STEP_MS);
    } else {
        base.scaled += delta * currentScale;
    }
    base.real = realMs;
    // Monotonic floor: never return less than the last value we handed out.
    if (base.scaled < lastScaledMs) base.scaled = lastScaledMs;
    lastScaledMs = base.scaled;
    return base.scaled;
}

function writeTimespec(tv, ms) {
    const sec = Math.floor(ms / 1000);
    const nsec = Math.floor((ms % 1000) * 1000000);
    tv.writeLong(sec);
    tv.add(8).writeLong(nsec);
}

function installClockJs(scale) {
    try {
        const libc = Process.findModuleByName('libc.so');
        if (!libc) { log('libc.so not found'); return false; }
        const cgAddr = libc.getExportByName('clock_gettime');
        if (!cgAddr) { log('clock_gettime not found'); return false; }
        if (!jsHookInstalled) {
            // Read the real time straight from the output buffer the original
            // call just filled in -- no Memory.alloc, no second syscall.
            Interceptor.attach(cgAddr, {
                onEnter: function(args) { this.tv = args[1]; this.clock = args[0].toInt32(); },
                onLeave: function(retval) {
                    if (currentScale === 1.0) return;
                    if (retval.toInt32() !== 0) return;
                    if (!this.tv || this.tv.isNull()) return;
                    if (this.clock !== 1) return;  // only scale CLOCK_MONOTONIC
                    const realMs = this.tv.readLong().toNumber() * 1000 +
                                   this.tv.add(8).readLong().toNumber() / 1000000;
                    writeTimespec(this.tv, scaledClockMs(this.clock, realMs));
                }
            });
            jsHookInstalled = true;
        }
        currentScale = scale;
        hookMode = 'clock-js';
        log('clock hook installed (JS fallback): scale=' + scale);
        return true;
    } catch (e) {
        log('JS clock hook failed: ' + e.message);
        return false;
    }
}

/* ----------------------- strategy selection + live update ------------------- */
// Hook libc clock_gettime to scale CLOCK_MONOTONIC (universal / GameGuardian-
// style). Native CModule first when enabled, else the JS fallback.
function initHook(scale) {
    if (scale === 1.0) { currentScale = 1.0; return true; }
    if (USE_CMODULE && installClockCModule(scale)) return true;
    if (installClockJs(scale)) return true;
    log('error: clock hook unavailable');
    return false;
}

function applyScale(scale) {
    currentScale = scale;
    if (hookMode === 'clock-cmodule' && clockScaleBuf) {
        clockScaleBuf.writeDouble(scale);            // native hook reads it live
    } else if (hookMode === 'clock-js') {
        /* currentScale is read live inside the JS hook */
    } else {
        initHook(scale);                              // not set up yet -> install now
    }
}

/* ------------------- live scale channel: poll a system property ------------- */
var getPropFn = null;
(function() {
    const libc = Process.findModuleByName('libc.so');
    if (!libc) return;
    let addr = null;
    try { addr = libc.findExportByName('__system_property_get'); } catch (e) {}
    if (!addr) { try { addr = libc.getExportByName('__system_property_get'); } catch (e) {} }
    if (addr) getPropFn = new NativeFunction(addr, 'int', ['pointer', 'pointer']);
})();
var propName = Memory.allocUtf8String('SCALE_PROP_NAME');
var propBuf = Memory.alloc(96);

function readLiveScale() {
    if (!getPropFn) return null;
    try {
        const len = getPropFn(propName, propBuf);
        if (len <= 0) return null;
        const v = parseFloat(propBuf.readUtf8String());
        if (isNaN(v) || v <= 0) return null;
        return v;
    } catch (e) {
        return null;
    }
}

log('script loaded, target=' + TARGET_SCALE);
var speedhackOk = initHook(TARGET_SCALE);
log('script finished: ' + (speedhackOk ? 'success' : 'failed'));

// Live-scale channel poll (heavier: reads a system property). 250ms is plenty.
if (getPropFn) {
    setInterval(function() {
        const v = readLiveScale();
        if (v !== null && Math.abs(v - currentScale) > 1e-6) {
            log('live scale change: ' + currentScale + ' -> ' + v);
            applyScale(v);
        }
    }, 250);
    log('live scale poller active (SCALE_PROP_NAME)');
} else {
    log('live scale channel unavailable (__system_property_get missing)');
}
"""


class FridaSpeedhackManager:
    """
    Best-effort manager for a Frida-based clock_gettime time-scale speedhack.

    Args:
        package: Android package name of the target game.
        time_scale: Desired initial time scale (default 1.0 = normal speed).
        frida_inject_path: Base device path for ``frida-inject`` (an
            architecture suffix is appended automatically).
        local_inject_binary: Optional local path to a ``frida-inject`` binary
            that will be pushed to the device when not present.
    """

    # Map Android ``ro.product.cpu.abi`` values to Frida's binary arch suffix.
    _ABI_TO_FRIDA = {
        "x86_64": "x86_64",
        "x86": "x86",
        "arm64-v8a": "arm64",
        "armeabi-v7a": "arm",
        "armeabi": "arm",
    }

    def __init__(
        self,
        package: str,
        time_scale: float = 1.0,
        frida_inject_path: str = "/data/local/tmp/frida-inject",
        local_inject_binary: Optional[str] = None,
        device_id: Optional[str] = None,
        use_cmodule: bool = False,
    ):
        self.package = package
        # Default to the JS clock hook. The native CModule hook is faster (no
        # JS-bridge crossing) BUT it compiles a fresh executable page with
        # TinyCC, which protected titles (e.g. yoozoo's) detect and crash on at
        # inject time. The JS hook survives on those games; opt into CModule only
        # for titles proven to tolerate it.
        self._use_cmodule = use_cmodule
        self._target_scale = float(time_scale)
        self._current_scale: float = 1.0
        self._frida_inject_path = frida_inject_path
        self._local_inject_binary = local_inject_binary
        self._device_id = device_id

        self._device_script_path = "/data/local/tmp/speedhack.js"
        # Per-package system property used as the live-scale channel. Kept short
        # and under the ``debug.`` prefix so it is readable by the game process
        # (a different uid than the injector) without SELinux trouble.
        self._scale_prop = "debug.speedhack." + hashlib.md5(
            package.encode("utf-8")
        ).hexdigest()[:6]
        self._lock = threading.RLock()
        self._inject_proc: Optional[subprocess.Popen] = None
        # Once the property channel round-trips we trust it and skip the
        # read-back verification on subsequent live updates (snappier slider).
        self._live_verified = False

    @property
    def available(self) -> bool:
        """Whether any bundled ``frida-inject`` binary exists locally."""
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
    def _bundled_inject_path(arch: Optional[str] = None) -> Optional[Path]:
        """Locate a bundled ``frida-inject`` binary, preferring ``arch``.

        When ``arch`` is given we only return a binary matching that exact
        architecture (so an ``x86`` device never gets the ``x86_64`` binary).
        Without ``arch`` we return the first binary found -- enough for the
        cheap ``available`` check.
        """
        frida_dir = FridaSpeedhackManager._project_root() / "vendor" / "frida"
        if not frida_dir.is_dir():
            return None

        if arch:
            # Exact-arch match. The glob is anchored on the full filename, so
            # ``-android-x86`` does not match ``-android-x86_64``.
            for m in sorted(frida_dir.glob(f"frida-inject-*-android-{arch}")):
                if m.is_file():
                    return m
            exact = frida_dir / f"frida-inject-android-{arch}"
            return exact if exact.is_file() else None

        candidates = [
            frida_dir / "frida-inject-17.15.1-android-x86_64",
            frida_dir / "frida-inject",
        ]
        candidates += sorted(frida_dir.glob("frida-inject-*-android-*"))
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

    def _device_abi(self) -> str:
        """Return the device's primary ABI (e.g. ``arm64-v8a``)."""
        out = self._run_adb("getprop ro.product.cpu.abi").strip()
        return out.splitlines()[0].strip() if out else ""

    def _frida_arch(self) -> Optional[str]:
        """Map the device ABI to a Frida arch suffix (None if unknown)."""
        abi = self._device_abi()
        if not abi:
            return None
        arch = self._ABI_TO_FRIDA.get(abi)
        if not arch:
            log_warning(f"[speedhack] unknown device ABI '{abi}'")
        return arch

    def _push_inject_if_needed(self) -> bool:
        """Ensure an arch-matched ``frida-inject`` exists on the device.

        Picks the binary that matches the device's ABI and pushes it to an
        arch-specific device path, so switching between an x86_64 emulator and
        an arm64 device never reuses the wrong binary.
        """
        arch = self._frida_arch()

        if self._local_inject_binary:
            local = Path(self._local_inject_binary)
        elif arch:
            local = self._bundled_inject_path(arch)
            if not local:
                log_error(
                    f"[speedhack] no frida-inject for device arch '{arch}'. "
                    f"Download 'frida-inject-<version>-android-{arch}' and place "
                    f"it in vendor/frida/"
                )
                return False
        else:
            local = self._bundled_inject_path()

        if not local or not Path(local).is_file():
            log_error(
                "[speedhack] no local frida-inject binary. "
                "Download frida-inject for your device architecture and place it in vendor/frida/"
            )
            return False

        # Use an arch-specific device path so a stale binary from a different
        # device architecture is never reused.
        device_path = (
            f"/data/local/tmp/frida-inject-{arch}" if arch else self._frida_inject_path
        )
        inject_path = shlex.quote(device_path)

        # ``test -f`` exit code instead of parsing ``ls`` output: ``ls`` echoes
        # the path back in its own "No such file" error, so a naive substring
        # check always falsely reports the file as present.
        check = self._run_adb(f"test -f {inject_path} && echo OK || echo MISSING")
        if "OK" in check:
            self._frida_inject_path = device_path
            return True

        log_info(f"[speedhack] pushing frida-inject ({arch or 'default'}) to device...")
        try:
            subprocess.run(
                self._adb_prefix() + ["push", str(local), device_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self._run_adb(f"chmod 755 {inject_path}")
            self._frida_inject_path = device_path
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
        source = (
            _INJECT_SCRIPT
            .replace("TARGET_SCALE", f"{scale:.6f}")
            .replace("SCALE_PROP_NAME", self._scale_prop)
            .replace("USE_CMODULE", "true" if self._use_cmodule else "false")
        )
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

    def _set_device_scale_prop(self, scale: float) -> None:
        """Set the live-scale system property on the device."""
        cmd = f"setprop {self._scale_prop} {scale:.6f}"
        self._run_adb(f"su -c {shlex.quote(cmd)}")

    def _set_live_scale(self, scale: float) -> bool:
        """Update the running injection's scale via the system property.

        Returns True only when the property round-trips (read back matches),
        so a blocked ``setprop`` cleanly falls back to a full re-injection.
        """
        self._set_device_scale_prop(scale)
        if self._live_verified:
            return True
        check = self._run_adb(f"getprop {self._scale_prop}").strip()
        try:
            ok = abs(float(check.split()[0]) - scale) < 1e-3
        except Exception:
            ok = False
        if ok:
            self._live_verified = True
        return ok

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
        """Kill any frida-inject still running on the device.

        Each leftover frida-inject keeps its own ``clock_gettime`` interceptor
        alive. Two of them stack and time scales by ``scale^2``, which spirals
        the engine's frame delta and freezes the game -- so clear them out
        before every fresh injection (and on detach). Runs synchronously so the
        kill completes before we inject again.
        """
        self._run_adb("su -c 'pkill -f frida-inject' 2>/dev/null")

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

        # Seed the live-scale property so the script's poller agrees with the
        # value baked into TARGET_SCALE and does not immediately override it.
        self._set_device_scale_prop(scale)

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
        """Set the in-game/app time scale to ``scale``.

        If an injection is already alive, the change is pushed live via the
        system property (no re-injection -- smooth, no time-base reset).
        Otherwise a fresh injection is performed.
        """
        scale = float(scale)
        log_info(f"[speedhack] requesting time scale = {scale}")

        with self._lock:
            if not self.available:
                log_warning("[speedhack] frida-inject binary not available")
                if scale == 1.0:
                    self._current_scale = 1.0
                    self._target_scale = 1.0
                return scale == 1.0

            # Fast path: a live injection is running -> just update the shared
            # scale property. No process spawn, no monotonic-base reset.
            proc_alive = self._inject_proc is not None and self._inject_proc.poll() is None
            if proc_alive and self._set_live_scale(scale):
                self._current_scale = scale
                self._target_scale = scale
                log_success(f"[speedhack] time scale set to {scale} (live)")
                return True

            # Full (re)injection path.
            self._stop_inject_proc()
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
            self._set_device_scale_prop(1.0)
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
