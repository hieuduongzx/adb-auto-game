"""
Runtime speedhack helper for Android games using Frida inject.

This manager pushes a JavaScript payload to the Android device and runs
``frida-inject`` against the target process. It avoids needing a persistent
``frida-server`` connection, which is fragile on some emulators (e.g.
LDPlayer). The injected script scales game time by hooking ``clock_gettime``
in ``libc.so`` to stretch ``CLOCK_MONOTONIC`` process-wide.

This engine-agnostic approach (GameGuardian-style) works regardless of whether
the title is Unity, Mono, or native.

Two hook flavours for the ``clock_gettime`` hot path:

1. A native CModule hook (opt-in via ``use_cmodule``) — every call stays in
   compiled C, so it is smooth even at high scales. NOTE: it compiles a fresh
   executable page with TinyCC, which some protected titles detect and crash
   on at inject time.
2. A plain-JS hook as the default / fallback. This funnels a hot-path syscall
   through Frida's JS lock, but survives on protected titles where the CModule
   path crashes.

Why a plain clock hook is not enough (the "crashes after a while" bug)
---------------------------------------------------------------------
Faking the *output* of ``clock_gettime`` makes the process' idea of monotonic
time run ahead of the kernel's by ``drift = (scale - 1) * elapsed``, which grows
without bound. Any code that turns that fake reading into an **absolute
deadline** and hands it to the kernel loses::

    clock_gettime(CLOCK_MONOTONIC, &ts);   /* faked: ahead of real time */
    ts.tv_sec += 5;                        /* wants to wait 5s          */
    pthread_cond_timedwait(&c, &m, &ts);   /* kernel compares vs REAL   */

The wait then lasts ``drift + 5s``. At 3x speed, ten real minutes of play means
a 20-minute drift, so every timed wait effectively hangs: ART's thread-suspend
timeout aborts the runtime (SIGABRT), watchdogs fire, netcode stalls. That is
why the hack feels fine at first and dies the longer it runs.

So the agent also hooks every libc entry point that takes an **absolute**
deadline on a scaled clock and converts that deadline back to real time
(``clock_nanosleep(TIMER_ABSTIME)``, the ``pthread_cond_*``/``pthread_mutex_*``/
``pthread_rwlock_*``/``sem_*`` clockwait+monotonic variants). Relative timeouts
(``poll``, ``epoll_wait``, ``nanosleep``, ``select``) are deliberately left
alone: their error is a bounded factor rather than an unbounded offset, and
dividing them would multiply the process' real frame rate — and CPU load — by
the scale for no gain in game speed.

The whole scaled clock family shares one drift, so ``CLOCK_MONOTONIC``,
``CLOCK_MONOTONIC_RAW`` and (by default) ``CLOCK_BOOTTIME`` can never diverge
from each other — keeping the ``BOOTTIME >= MONOTONIC`` invariant the framework
relies on. ``CLOCK_REALTIME`` stays real (scaling wall clock desyncs server
time) and CPU-time clocks stay real (ART GC / watchdog accounting).

Once injected, the script stays alive and polls a system property for the
desired scale, so the host can change speed LIVE (just ``setprop``) without
re-injecting -- this keeps slider drags smooth and avoids resetting the
monotonic-time base on every change. Going back to 1.0 *parks* the agent: the
accumulated drift is kept as a constant offset and time simply resumes at the
real rate. It is never snapped backwards, because a backwards jump in
CLOCK_MONOTONIC is itself a crash. For the same reason ``reset()`` leaves the
agent resident instead of unloading it.

Usage (workflow engine / designer)::

    from src.core.frida_speedhack import FridaSpeedhackManager

    mgr = FridaSpeedhackManager(package="com.example.game")
    mgr.set_scale(2.0)
    ...
    mgr.ensure_alive()      # re-injects if the game restarted

NOTE: This is a best-effort helper. Actual hook success depends on the
device being rooted and supporting Frida. Anti-cheat/integrity checks may
detect the injection and lead to bans.
"""
import hashlib
import re
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from src.utils import CREATE_NO_WINDOW, log_error, log_info, log_success, log_warning


_INJECT_SCRIPT = """
// ============================== speedhack agent ==============================
// Scales the monotonic clock family, and converts absolute wait deadlines back
// to real time so timed waits keep their intended duration (see the Python
// module docstring for why that second half is what stops the long-run crash).
//
// Time model -- one shared drift for the whole scaled family:
//     scaled(clk) = real + drift + (real - anchor[clk]) * (scale - 1)
//     real(clk)   = (scaled - drift + anchor[clk] * (scale - 1)) / scale
// `drift` is frozen and carried over on every rate change, so the scaled
// timeline is continuous (no jump, ever) and -- unlike a per-call accumulator --
// cannot drift away from a pure function of real time.

// Drop any interceptors left behind by a previous injection into this process.
try { Interceptor.detachAll(); } catch (e) {}

// timespec is { time_t tv_sec; long tv_nsec; } -> both fields are pointer-sized.
// Hardcoding 8 corrupts the caller's stack on 32-bit processes (x86 / armeabi-v7a).
var PSIZE = Process.pointerSize;
var NSEC_OFF = PSIZE;
var SCALE_BT = SCALE_BOOTTIME;      // also scale CLOCK_BOOTTIME (keeps BOOTTIME >= MONOTONIC)
var TIMER_ABSTIME = 1;
// An absolute deadline of >= 1e9 seconds (year 2001+) can only be CLOCK_REALTIME;
// a monotonic uptime that large would be 31 years. Used where the clock of an
// abstime is not an argument (a cond var configured via pthread_condattr_setclock).
var REALTIME_SEC_MIN = 1000000000;

var hookMode = 'none';              // 'clock-cmodule' | 'clock-js'
var waitersHooked = 0;

function log(msg) {
    send(msg);
    try { console.log(msg); } catch (e) {}
}

function isScaledClock(clk) {
    return clk === 1 || clk === 4 || (SCALE_BT && clk === 7);
}

/* ------------------------- timespec read / write ----------------------------
 * Reading the low 32 bits is enough (monotonic uptime and any realistic
 * CLOCK_REALTIME value fit, tv_nsec < 1e9) and keeps the hot path free of JS
 * allocations: readLong() would box an Int64 object on every single call, which
 * is millions of objects per second of GC pressure inside Frida's runtime. */
function tsReadMs(p, q) {
    return p.readU32() * 1000.0 + q.readU32() / 1000000.0;
}

function tsWriteMs(p, q, ms) {
    var sec = Math.floor(ms / 1000);
    var nsec = Math.floor((ms - sec * 1000) * 1000000);
    if (nsec < 0) nsec = 0;
    if (nsec > 999999999) nsec = 999999999;
    p.writeU32(sec);
    q.writeU32(nsec);
    if (PSIZE === 8) { p.add(4).writeU32(0); q.add(4).writeU32(0); }
}

/* ------------------------------ shared state -------------------------------
 * The CModule keeps its state in a host-allocated struct so the JS waiter hooks
 * can read the very same anchors/drift regardless of which clock hook is live.
 * Layout (must match `State` in CLOCK_HOOK_C):
 *   0 double scale | 8 double drift | 16 double cur_scale | 24 double elapsed
 *   32 int epoch   | 36 int cur_epoch
 *   40 double a_real[16] | 168 double last_out[16] | 296 int a_init[16]  => 360 */
var ST_SCALE = 0, ST_DRIFT = 8, ST_CURSCALE = 16, ST_ELAPSED = 24,
    ST_EPOCH = 32, ST_CUREPOCH = 36,
    ST_AREAL = 40, ST_LASTOUT = 168, ST_AINIT = 296, ST_SIZE = 360;
var ST = null;                      // Memory(ST_SIZE), allocated for the CModule path
var cmKeep = null;                  // CModule ref: dropping it would free the code page

// JS-path state: plain vars/arrays -- the hot path never touches native memory.
var jsScale = 1.0, jsDrift = 0.0, jsCurScale = 1.0, jsElapsed = 0.0;
var jsEpoch = 0, jsCurEpoch = -1;
var jsAReal = new Array(16).fill(0.0);
var jsAInit = new Array(16).fill(0);
var jsLastOut = new Array(16).fill(0.0);

// State accessors used by the waiter hooks; bound once the clock hook is chosen.
var stScale = function() { return jsScale; };
var stDrift = function() { return jsDrift; };
var stAnchor = function(clk) { return jsAReal[clk]; };
var stAnchored = function(clk) { return jsAInit[clk] !== 0; };

/* --------------- Native clock_gettime hook (CModule, no JS bridge) ----------
 * clock_gettime is on the hot path (millions of calls/sec). Running the scaling
 * logic in compiled C via Interceptor.attach(addr, cmodule) keeps every call
 * native -- no JS-bridge crossing, no per-call allocation -- so it stays smooth
 * even at high scales. */
var CLOCK_HOOK_C = `
#include <gum/guminterceptor.h>

#define SCALE_BT ${SCALE_BT ? 1 : 0}

/* time_t / long: sized by the target ABI, so this is correct on 32-bit too. */
typedef struct { long tv_sec; long tv_nsec; } ts_t;

typedef struct {
  double scale;
  double drift;
  double cur_scale;
  double elapsed;        /* real ms since the current anchor, shared by the family */
  int epoch;
  int cur_epoch;
  double a_real[16];
  double last_out[16];
  int a_init[16];
} State;

extern State g_state;

typedef struct { int clock_id; ts_t * tv; } ClockCall;

void
onEnter (GumInvocationContext * ic)
{
  ClockCall * s = gum_invocation_context_get_listener_invocation_data (ic, sizeof (ClockCall));
  s->clock_id = (int) (size_t) gum_invocation_context_get_nth_argument (ic, 0);
  s->tv = (ts_t *) gum_invocation_context_get_nth_argument (ic, 1);
}

void
onLeave (GumInvocationContext * ic)
{
  ClockCall * s;
  ts_t * ts;
  int clk, i;
  double real_ms, out, scale;
  long sec, nsec;

  if ((size_t) gum_invocation_context_get_return_value (ic) != 0)
    return;

  s = gum_invocation_context_get_listener_invocation_data (ic, sizeof (ClockCall));
  clk = s->clock_id;
  /* Only the monotonic family is scaled; bail before touching the buffer --
   * cheapest path for most calls. CLOCK_REALTIME (0) would desync server time
   * and the CPU-time clocks (2, 3) drive ART GC / watchdog accounting. */
  if (clk != 1 && clk != 4 && !(SCALE_BT && clk == 7))
    return;

  ts = s->tv;
  if (ts == 0)
    return;

  real_ms = (double) ts->tv_sec * 1000.0 + (double) ts->tv_nsec / 1000000.0;

  /* Rate change: freeze the drift accumulated at the OLD rate, then make every
   * clock re-anchor on its next call. The scaled timeline stays continuous. */
  if (g_state.cur_epoch != g_state.epoch) {
    g_state.drift += g_state.elapsed * (g_state.cur_scale - 1.0);
    g_state.elapsed = 0.0;
    g_state.cur_scale = g_state.scale;
    g_state.cur_epoch = g_state.epoch;
    for (i = 0; i < 16; i++)
      g_state.a_init[i] = 0;
  }
  /* Anchor a clock seen for the first time as if it had been anchored with the
   * rest of the family: every clock here ticks with real time, so backdating by
   * the shared elapsed keeps their mutual offsets intact. Anchoring it at "now"
   * instead would leave it (scale-1) * (how late it joined) behind the others --
   * that is how CLOCK_BOOTTIME ends up below CLOCK_MONOTONIC. */
  if (!g_state.a_init[clk]) {
    g_state.a_real[clk] = real_ms - g_state.elapsed;
    g_state.a_init[clk] = 1;
  }
  g_state.elapsed = real_ms - g_state.a_real[clk];
  /* Threads share this state with no locking (the point of the native path is
   * that it never takes one). Aligned 64-bit loads are single-copy atomic on
   * arm64/x86_64, but clamp anyway so a torn read on a 32-bit build can only
   * cost one dull reading instead of hurling the clock into next week. */
  if (g_state.elapsed < 0.0 || g_state.elapsed > 1e10)
    g_state.elapsed = 0.0;

  scale = g_state.scale;
  /* Parked at normal speed with nothing accumulated -> pure passthrough. Note
   * that a non-zero drift must KEEP being applied at scale 1.0: dropping it
   * would jump CLOCK_MONOTONIC backwards, which hangs every pending wait. */
  if (scale == 1.0 && g_state.drift == 0.0)
    return;

  out = real_ms + g_state.drift + g_state.elapsed * (scale - 1.0);

  /* Never hand back a value below the last one we returned (monotonic floor).
   * POSIX only guarantees per-core ordering, so back-to-back calls on different
   * cores can see real time dip; the scale would amplify that dip into time
   * going backwards, which hangs pthread_cond_timedwait / GC / netcode. */
  if (out < g_state.last_out[clk])
    out = g_state.last_out[clk];
  g_state.last_out[clk] = out;

  sec = (long) (out / 1000.0);
  nsec = (long) ((out - (double) sec * 1000.0) * 1000000.0);
  if (nsec < 0) nsec = 0;
  if (nsec > 999999999) nsec = 999999999;
  ts->tv_sec = sec;
  ts->tv_nsec = nsec;
}
`;

function stateAlloc(scale) {
    const st = Memory.alloc(ST_SIZE);            // zero-filled: drift/anchors start clean
    st.writeDouble(scale);
    st.add(ST_CURSCALE).writeDouble(1.0);
    st.add(ST_EPOCH).writeInt(1);                // != cur_epoch -> anchor on first call
    st.add(ST_CUREPOCH).writeInt(0);
    return st;
}

// Point the waiter hooks at the CModule's state. Only called once the native
// hook is actually live, so a failed CModule leaves the JS accessors in place.
function bindStateC(st) {
    ST = st;
    stScale = function() { return ST.readDouble(); };
    stDrift = function() { return ST.add(ST_DRIFT).readDouble(); };
    stAnchor = function(clk) { return ST.add(ST_AREAL + clk * 8).readDouble(); };
    stAnchored = function(clk) { return ST.add(ST_AINIT + clk * 4).readInt() !== 0; };
}

function installClockCModule(scale) {
    try {
        const libc = Process.findModuleByName('libc.so');
        if (!libc) { log('libc.so not found'); return false; }
        const cgAddr = libc.getExportByName('clock_gettime');
        if (!cgAddr) { log('clock_gettime not found'); return false; }
        const st = stateAlloc(scale);
        const cm = new CModule(CLOCK_HOOK_C, { g_state: st });
        Interceptor.attach(cgAddr, cm);
        cmKeep = cm;                             // keep the module (and its page) alive
        bindStateC(st);
        hookMode = 'clock-cmodule';
        log('clock hook installed (CModule native): scale=' + scale);
        return true;
    } catch (e) {
        log('CModule clock hook unavailable: ' + e.message);
        return false;
    }
}

/* ----------------- JS clock hook (linear anchor, allocation-light) ----------
 * Same time model as the CModule, on per-clock scalars -- no String() key, no
 * dict lookup, no Int64 boxing -- so the hot path makes almost no GC garbage. */
function jsScaleClock(clk, tv) {
    const nsp = tv.add(NSEC_OFF);
    const realMs = tsReadMs(tv, nsp);

    if (jsCurEpoch !== jsEpoch) {           // rate change: freeze drift, re-anchor all
        jsDrift += jsElapsed * (jsCurScale - 1.0);
        jsElapsed = 0.0;
        jsCurScale = jsScale;
        jsCurEpoch = jsEpoch;
        for (let i = 0; i < 16; i++) jsAInit[i] = 0;
    }
    // Backdate a first-seen clock by the shared elapsed so it lines up with the
    // rest of the family (see the CModule comment): anchoring it at "now" would
    // park it (scale-1) * (how late it joined) behind the others.
    if (!jsAInit[clk]) { jsAReal[clk] = realMs - jsElapsed; jsAInit[clk] = 1; }
    jsElapsed = realMs - jsAReal[clk];

    // Parked at normal speed with nothing accumulated -> leave the real value.
    if (jsScale === 1.0 && jsDrift === 0.0) return;

    let out = realMs + jsDrift + jsElapsed * (jsScale - 1.0);
    if (out < jsLastOut[clk]) out = jsLastOut[clk];   // per-clock monotonic floor
    jsLastOut[clk] = out;
    tsWriteMs(tv, nsp, out);
}

var jsHookInstalled = false;
var origClockGettime = null;  // NativeFunction -> original, via replaceFast trampoline
var jsClockCb = null;         // NativeCallback (kept referenced so it is never GC'd)

// Legacy attach hook (onEnter + onLeave => two JS-bridge crossings per call).
// Used only when Interceptor.replaceFast is unavailable on the runtime.
function installClockJsAttach(cgAddr) {
    Interceptor.attach(cgAddr, {
        onEnter: function(args) { this.tv = args[1]; this.clock = args[0].toInt32(); },
        onLeave: function(retval) {
            if (retval.toInt32() !== 0) return;
            if (!isScaledClock(this.clock)) return;
            if (!this.tv || this.tv.isNull()) return;
            jsScaleClock(this.clock, this.tv);
        }
    });
}

function installClockJs(scale) {
    try {
        const libc = Process.findModuleByName('libc.so');
        if (!libc) { log('libc.so not found'); return false; }
        const cgAddr = libc.getExportByName('clock_gettime');
        if (!cgAddr) { log('clock_gettime not found'); return false; }

        if (!jsHookInstalled) {
            // Prefer replaceFast: one native->JS crossing per call (the callback)
            // instead of attach's two (onEnter + onLeave), and a lighter
            // trampoline. The callback can only run its JS body once we yield the
            // JS lock -- which is after origClockGettime is assigned below -- so
            // there is no window where it could fire with a null original.
            if (typeof Interceptor.replaceFast === 'function') {
                try { Interceptor.revert(cgAddr); } catch (e) {}
                jsClockCb = new NativeCallback(function(clk, tv) {
                    const ret = origClockGettime(clk, tv);
                    // Fast bails (the common case): error or unscaled clock.
                    if (ret !== 0 || !isScaledClock(clk)) return ret;
                    if (!tv.isNull()) jsScaleClock(clk, tv);
                    return ret;
                }, 'int', ['int', 'pointer']);
                const orig = Interceptor.replaceFast(cgAddr, jsClockCb);
                origClockGettime = new NativeFunction(orig, 'int', ['int', 'pointer']);
                log('clock hook installed (JS replaceFast)');
            } else {
                installClockJsAttach(cgAddr);
                log('clock hook installed (JS attach fallback)');
            }
            jsHookInstalled = true;
        }
        jsScale = scale;
        jsEpoch++;
        hookMode = 'clock-js';
        log('clock hook ready (JS): scale=' + scale);
        return true;
    } catch (e) {
        log('JS clock hook failed: ' + e.message);
        // If replaceFast blew up before installing, fall back to attach.
        if (!jsHookInstalled) {
            try {
                const libc = Process.findModuleByName('libc.so');
                const cgAddr = libc && libc.getExportByName('clock_gettime');
                if (cgAddr) {
                    installClockJsAttach(cgAddr);
                    jsHookInstalled = true;
                    jsScale = scale;
                    jsEpoch++;
                    hookMode = 'clock-js';
                    log('clock hook installed (JS attach fallback after error)');
                    return true;
                }
            } catch (e2) {
                log('JS attach fallback also failed: ' + e2.message);
            }
        }
        return false;
    }
}

/* ------------------- absolute-deadline (waiter) hooks -----------------------
 * THE fix for "works at first, dies after a while". Each of these takes an
 * absolute deadline that the caller computed off our faked clock; the kernel
 * compares it against the real one. Without translating it back, every timed
 * wait lasts `drift + timeout`, and drift grows for as long as the hack runs.
 *
 * Relative timeouts (poll / epoll_wait / nanosleep / select) are intentionally
 * NOT hooked: their error is a bounded factor, and shortening them would raise
 * the process' real frame rate by `scale` -- the same game speed for `scale`x
 * the CPU, which on an emulator is its own source of stalls.
 *
 * spec = [name, tsArg, clkArg, fixedClk, flagsArg]
 *   clkArg   >= 0  argument index holding a clockid_t
 *   fixedClk       clock id when clkArg < 0; -2 = unknown (decide by magnitude)
 *   flagsArg >= 0  argument index holding flags; convert only if TIMER_ABSTIME
 * Every one of these is a public libc symbol that funnels into an internal
 * static (bionic never calls one public entry point from another), so no call
 * can be translated twice. */
var WAITERS = [
    ['clock_nanosleep',                      2,  0, -1,  1],
    ['pthread_cond_timedwait',               2, -1, -2, -1],
    ['pthread_cond_timedwait_monotonic_np',  2, -1,  1, -1],
    ['pthread_cond_clockwait',               3,  2, -1, -1],
    ['pthread_mutex_timedlock',              1, -1, -2, -1],
    ['pthread_mutex_timedlock_monotonic_np', 1, -1,  1, -1],
    ['pthread_mutex_clocklock',              2,  1, -1, -1],
    ['pthread_rwlock_timedrdlock',           1, -1, -2, -1],
    ['pthread_rwlock_timedwrlock',           1, -1, -2, -1],
    ['pthread_rwlock_clockrdlock',           2,  1, -1, -1],
    ['pthread_rwlock_clockwrlock',           2,  1, -1, -1],
    ['sem_timedwait',                        1, -1, -2, -1],
    ['sem_timedwait_monotonic_np',           1, -1,  1, -1],
    ['sem_clockwait',                        2,  1, -1, -1],
];

/* Per-thread scratch timespec: the converted deadline is handed to the callee
 * in our own buffer, so the caller's struct is never mutated (it may be reused
 * across retries, or shared). A thread can only sit in one timed wait at a
 * time, so one slot per thread is enough. Slabbed a page at a time and never
 * freed -- releasing one while a blocked thread's kernel wait still points at
 * it would be a use-after-free. */
var slabKeep = [], slabPage = null, slabOff = 0;
var scratchByTid = {};
function scratchFor() {
    const tid = Process.getCurrentThreadId();
    let b = scratchByTid[tid];
    if (b === undefined) {
        if (slabPage === null || slabOff + 16 > Process.pageSize) {
            slabPage = Memory.alloc(Process.pageSize);
            slabKeep.push(slabPage);
            slabOff = 0;
        }
        b = slabPage.add(slabOff);
        slabOff += 16;
        scratchByTid[tid] = b;
    }
    return b;
}

function installWaiter(libc, spec) {
    const name = spec[0], tsArg = spec[1], clkArg = spec[2],
          fixedClk = spec[3], flagsArg = spec[4];
    let addr = null;
    try { addr = libc.findExportByName(name); } catch (e) {}
    if (!addr) { try { addr = libc.getExportByName(name); } catch (e) {} }
    if (!addr) return false;
    Interceptor.attach(addr, {
        onEnter: function(args) {
            // A bad deadline pointer is the caller's bug to hit, not ours to
            // die on: leave the arguments untouched and let the call proceed.
            try {
                const scale = stScale();
                const drift = stDrift();
                if (scale === 1.0 && drift === 0.0) return;   // nothing faked yet
                if (flagsArg >= 0 && (args[flagsArg].toInt32() & TIMER_ABSTIME) === 0)
                    return;                                    // relative -> leave alone
                const p = args[tsArg];
                if (p === undefined || p === null || p.isNull()) return;
                const sec = p.readU32();
                let clk = clkArg >= 0 ? args[clkArg].toInt32() : fixedClk;
                if (clk === -2) {
                    // Clock came from a cond/sem attribute we cannot read: only a
                    // CLOCK_REALTIME deadline can be this far from zero.
                    if (sec >= REALTIME_SEC_MIN) return;
                    clk = 1;
                }
                if (!isScaledClock(clk)) return;
                // Without an anchor for this clock there is nothing to invert
                // against; in practice the caller read the clock to build this
                // deadline, so it is always anchored by the time we get here.
                if (!stAnchored(clk)) return;
                const nsp = p.add(NSEC_OFF);
                const scaledMs = sec * 1000.0 + nsp.readU32() / 1000000.0;
                let realMs = (scaledMs - drift + stAnchor(clk) * (scale - 1.0)) / scale;
                if (realMs < 0) realMs = 0;                    // already expired
                const buf = scratchFor();
                tsWriteMs(buf, buf.add(NSEC_OFF), realMs);
                args[tsArg] = buf;
            } catch (e) {}
        }
    });
    return true;
}

function installWaiters() {
    const libc = Process.findModuleByName('libc.so');
    if (!libc) return 0;
    let n = 0;
    const missing = [];
    for (const spec of WAITERS) {
        try {
            if (installWaiter(libc, spec)) n++;
            else missing.push(spec[0]);
        } catch (e) {
            log('waiter hook failed for ' + spec[0] + ': ' + e.message);
        }
    }
    log('deadline hooks: ' + n + '/' + WAITERS.length +
        (missing.length ? ' (absent: ' + missing.join(',') + ')' : ''));
    return n;
}

/* ----------------------- strategy selection + live update ------------------- */
// Hook libc clock_gettime to scale the monotonic clock family (universal /
// GameGuardian-style). Native CModule first when enabled, else the JS fallback.
function initHook(scale) {
    if (USE_CMODULE && installClockCModule(scale)) {
        // fall through to the waiters
    } else if (!installClockJs(scale)) {
        log('error: clock hook unavailable');
        return false;
    }
    waitersHooked = installWaiters();
    return true;
}

function applyScale(scale) {
    if (hookMode === 'clock-cmodule') {
        ST.writeDouble(scale);                                  // read live by the native hook
        ST.add(ST_EPOCH).writeInt((ST.add(ST_EPOCH).readInt() + 1) | 0);
    } else if (hookMode === 'clock-js') {
        jsScale = scale;
        // Bump the epoch so each clock re-anchors at its current scaled value ->
        // the timeline stays continuous across the rate change (no time jump,
        // which would otherwise spike FixedUpdate / time deltas).
        jsEpoch++;
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

log('script loaded, target=' + TARGET_SCALE + ' ptr=' + PSIZE);
var speedhackOk = initHook(TARGET_SCALE);
log('script finished: ' + (speedhackOk ? 'success' : 'failed'));

// Live-scale channel poll (heavier: reads a system property). 250ms is plenty.
if (getPropFn) {
    setInterval(function() {
        const v = readLiveScale();
        if (v !== null && Math.abs(v - stScale()) > 1e-6) {
            log('live scale change: ' + stScale() + ' -> ' + v);
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
        use_cmodule: Run the clock hook as compiled C instead of JS (faster,
            but detected by some protected titles -- see the module docstring).
        scale_boottime: Also scale CLOCK_BOOTTIME, keeping the framework's
            ``BOOTTIME >= MONOTONIC`` invariant. Turn off only for titles that
            check ``SystemClock.elapsedRealtime()`` against a server clock.
    """

    # Map Android ``ro.product.cpu.abi`` values to Frida's binary arch suffix.
    _ABI_TO_FRIDA = {
        "x86_64": "x86_64",
        "x86": "x86",
        "arm64-v8a": "arm64",
        "armeabi-v7a": "arm",
        "armeabi": "arm",
    }
    # 64-bit arch -> its 32-bit sibling, for apps running 32-bit on a 64-bit device.
    _ARCH_32 = {"x86_64": "x86", "arm64": "arm"}
    # ELF e_machine -> Frida arch suffix. The process image is the only honest
    # source here: an emulator that translates ARM in-process (MuMu, LDPlayer)
    # advertises the app as arm64-v8a while the process -- and the libc.so we
    # hook -- is x86_64. Trusting the app's ABI asks for the wrong injector.
    _EM_TO_FRIDA = {0x03: "x86", 0x28: "arm", 0x3E: "x86_64", 0xB7: "arm64"}

    def __init__(
        self,
        package: str,
        time_scale: float = 1.0,
        frida_inject_path: str = "/data/local/tmp/frida-inject",
        local_inject_binary: Optional[str] = None,
        device_id: Optional[str] = None,
        use_cmodule: bool = False,
        scale_boottime: bool = True,
    ):
        self.package = package
        # Default to the JS clock hook. The native CModule hook is faster (no
        # JS-bridge crossing) BUT it compiles a fresh executable page with
        # TinyCC, which protected titles (e.g. yoozoo's) detect and crash on at
        # inject time. The JS hook survives on those games; opt into CModule only
        # for titles proven to tolerate it.
        self._use_cmodule = use_cmodule
        self._scale_boottime = scale_boottime
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
        # PID we injected into. A game restart gives the package a new PID and
        # leaves the old hook behind with it, so this is what tells us the
        # injection is stale even though our local adb pipe is still open.
        self._injected_pid: Optional[int] = None
        # Keeps "game not running yet" out of the log on every watchdog poll.
        self._pid_missing_logged = False
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
        """Find the repository root (or the folder next to a frozen .exe)."""
        try:
            from src.utils import app_dir
            return Path(app_dir())
        except Exception:
            pass
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
                    [c, "version"], shell=False, capture_output=True, text=True, timeout=5,
                    creationflags=CREATE_NO_WINDOW,
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
                creationflags=CREATE_NO_WINDOW,
            )
            return (result.stdout or "") + (result.stderr or "")
        except Exception as e:
            log_warning(f"[speedhack] adb command failed: {e}")
            return ""

    def _device_abi(self) -> str:
        """Return the device's primary ABI (e.g. ``arm64-v8a``)."""
        out = self._run_adb("getprop ro.product.cpu.abi").strip()
        return out.splitlines()[0].strip() if out else ""

    def _frida_arch(self, pid: Optional[int] = None) -> Optional[str]:
        """Frida arch suffix for the *target process*, not just the device.

        The process' own ELF header decides, because neither of the obvious
        properties is trustworthy: ``ro.product.cpu.abi`` misses a 32-bit game
        on a 64-bit device (wrong ``timespec`` layout in the agent), while the
        app's ``primaryCpuAbi`` reads ``arm64-v8a`` on an ARM-translating
        emulator whose processes are really x86_64. Falls back to the device ABI
        plus a bitness probe when the header cannot be read.
        """
        if pid is not None:
            arch = self._process_arch(pid)
            if arch:
                return arch

        abi = self._device_abi()
        device_arch = self._ABI_TO_FRIDA.get(abi)
        if not device_arch:
            if abi:
                log_warning(f"[speedhack] unknown device ABI '{abi}'")
            return None
        if pid is not None and self._is_32bit_process(pid):
            arch32 = self._ARCH_32.get(device_arch, device_arch)
            log_info(f"[speedhack] {self.package} runs 32-bit -> using {arch32}")
            return arch32
        return device_arch

    def _process_arch(self, pid: int) -> Optional[str]:
        """Frida arch suffix read from the target's own ELF header (None if unreadable)."""
        inner = f"dd if=/proc/{pid}/exe bs=1 count=20 2>/dev/null"
        out = self._run_adb(f"su -c {shlex.quote(inner)} | od -An -tx1")
        octets = re.findall(r"\b[0-9a-f]{2}\b", out or "")
        if len(octets) < 20:
            return None
        head = [int(h, 16) for h in octets[:20]]
        if head[:4] != [0x7F, 0x45, 0x4C, 0x46]:      # not an ELF -> unreadable
            return None
        machine = head[18] | (head[19] << 8)          # e_machine, little-endian
        arch = self._EM_TO_FRIDA.get(machine)
        if not arch:
            log_warning(f"[speedhack] unknown ELF machine 0x{machine:x} for pid {pid}")
            return None
        log_info(f"[speedhack] target pid {pid} is {arch}")
        return arch

    def _is_32bit_process(self, pid: int) -> bool:
        """Whether ``pid`` is a 32-bit process (zygote32 -> app_process32)."""
        out = self._run_adb(f"su -c {shlex.quote(f'readlink /proc/{pid}/exe')}")
        return "app_process32" in (out or "")

    def _push_inject_if_needed(self, arch: Optional[str]) -> bool:
        """Ensure an arch-matched ``frida-inject`` exists on the device.

        Pushes the binary for ``arch`` (the *target process'* architecture) to an
        arch-specific device path, so switching between an x86_64 emulator and
        an arm64 device never reuses the wrong binary.
        """
        if self._local_inject_binary:
            local = Path(self._local_inject_binary)
        elif arch:
            local = self._bundled_inject_path(arch)
            if not local:
                log_error(
                    f"[speedhack] no frida-inject for target arch '{arch}'. "
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
                creationflags=CREATE_NO_WINDOW,
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
            .replace("SCALE_BOOTTIME", "true" if self._scale_boottime else "false")
        )
        local_path = Path(tempfile.gettempdir()) / "speedhack_agent.js"
        try:
            local_path.write_text(source, encoding="utf-8")
            subprocess.run(
                self._adb_prefix() + ["push", str(local_path), self._device_script_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=CREATE_NO_WINDOW,
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

    def _ps_snapshot(self) -> List[Tuple[int, str]]:
        """``[(pid, cmdline)]`` for every process on the device.

        Needs the full command line (not the 15-char ``comm``) to tell which
        process a ``frida-inject`` is aimed at. ``ps -ef`` is the fallback for
        toybox builds that reject ``-o``; the header rows drop out on their own
        because their first column is not a number.
        """
        rows: List[Tuple[int, str]] = []
        for cmd, pid_col, args_col in (("ps -A -o PID,ARGS", 0, 1), ("ps -ef", 1, 7)):
            for line in (self._run_adb(cmd) or "").splitlines():
                parts = line.strip().split(None, args_col)
                if len(parts) <= args_col or not parts[pid_col].isdigit():
                    continue
                rows.append((int(parts[pid_col]), parts[args_col]))
            if rows:
                break
        return rows

    def _kill_device_frida(self, target_pid: Optional[int] = None) -> None:
        """Kill stale ``frida-inject`` processes on the device.

        Each leftover frida-inject keeps its own ``clock_gettime`` interceptor
        alive. Two of them stack and time scales by ``scale^2``, which spirals
        the engine's frame delta and freezes the game -- so clear them out
        before every fresh injection.

        Only injectors aimed at ``target_pid`` (or at a process that no longer
        exists) are killed, so a second workflow speeding up a different game
        keeps running. ``ps`` is parsed on the host rather than shelling out to
        ``pkill -f frida-inject``: that pattern also matched the wrapper shell
        running it, so pkill signalled its own parent and the kill was
        unreliable -- exactly the case that leaves two hooks stacked.
        """
        rows = self._ps_snapshot()
        if not rows:
            return
        live = {pid for pid, _ in rows}
        doomed = []
        for pid, args in rows:
            if "frida-inject" not in args:
                continue
            m = re.search(r"-p\s+(\d+)", args)
            victim = int(m.group(1)) if m else None
            if victim is None:
                continue
            if victim == target_pid or victim == self._injected_pid or victim not in live:
                doomed.append(pid)
        if not doomed:
            return
        log_info(f"[speedhack] clearing {len(doomed)} stale frida-inject process(es)")
        kill = "kill -9 " + " ".join(str(p) for p in doomed)
        self._run_adb(f"su -c {shlex.quote(kill)}")

    def _inject_scale_locked(self, scale: float, pid: Optional[int] = None,
                             keep_alive: bool = True) -> bool:
        if pid is None:
            pid = self._find_pid()
        if pid is None:
            # The watchdog retries every few seconds until the game is up, so
            # say this once instead of once per poll.
            if not self._pid_missing_logged:
                log_info(f"[speedhack] {self.package} is not running yet — waiting for it")
                self._pid_missing_logged = True
            return False
        self._pid_missing_logged = False

        self._kill_device_frida(target_pid=pid)

        if not self._push_inject_if_needed(self._frida_arch(pid)):
            return False

        if not self._push_script(scale):
            return False

        # Seed the live-scale property so the script's poller agrees with the
        # value baked into TARGET_SCALE and does not immediately override it.
        self._set_device_scale_prop(scale)
        self._live_verified = False

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
                creationflags=CREATE_NO_WINDOW,
            )
            if keep_alive:
                self._inject_proc = proc
                self._injected_pid = pid
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
                finally:
                    # Never leave the pipe unread: frida-inject blocks writing to
                    # a full pipe, and it blocks while holding the agent's JS
                    # lock -- which would freeze every thread in the game.
                    try:
                        for _ in iter(pipe.readline, ""):
                            pass
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
                self._injected_pid = None
                return False

            if not status["success"]:
                log_warning("[speedhack] injection result not confirmed")

            return True
        except Exception as e:
            log_error(f"[speedhack] failed to inject: {e}")
            self._injected_pid = None
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

    def _agent_alive(self, pid: Optional[int] = None) -> bool:
        """Whether our agent is still resident in the *current* target process.

        Checking the local adb pipe alone is not enough: when the game restarts,
        that pipe can stay open while the hook died with the old process, and
        every later ``setprop`` would silently do nothing.
        """
        if self._inject_proc is None or self._inject_proc.poll() is not None:
            return False
        if self._injected_pid is None:
            return False
        if pid is None:
            pid = self._find_pid()
        return pid == self._injected_pid

    def set_scale(self, scale: float) -> bool:
        """Set the in-game/app time scale to ``scale``.

        If an injection is already alive, the change is pushed live via the
        system property (no re-injection -- smooth, no time-base reset).
        Otherwise a fresh injection is performed.
        """
        scale = float(scale)
        log_info(f"[speedhack] requesting time scale = {scale}")

        with self._lock:
            self._target_scale = scale
            if not self.available:
                log_warning("[speedhack] frida-inject binary not available")
                if scale == 1.0:
                    self._current_scale = 1.0
                return scale == 1.0

            # Fast path: our agent is alive in the current process -> just update
            # the shared scale property. No process spawn, no time-base reset.
            pid = self._find_pid()
            if self._agent_alive(pid) and self._set_live_scale(scale):
                self._current_scale = scale
                log_success(f"[speedhack] time scale set to {scale} (live)")
                return True

            if scale == 1.0:
                # Nothing resident to slow down, and injecting purely to ask for
                # normal speed would be a pointless hook on a healthy game.
                self._current_scale = 1.0
                return True

            # Full (re)injection path.
            self._stop_inject_proc()
            if not self._inject_scale_locked(scale, pid=pid):
                self._stop_inject_proc()
                return False

            self._current_scale = scale
            log_success(f"[speedhack] time scale set to {scale}")
            return True

    def ensure_alive(self) -> bool:
        """Re-inject when the agent is gone (game restarted, injector died).

        Cheap enough for a few-second poll. Returns True when a live injection
        is in place for the requested scale, False when there is nothing to
        inject into (game not running) or the injection failed.
        """
        with self._lock:
            if self._target_scale == 1.0:
                return True
            pid = self._find_pid()
            if self._agent_alive(pid):
                return True
            if pid is None:
                return False                     # game not up (yet)
            if self._injected_pid is not None:
                log_warning("[speedhack] agent lost (game restarted?) — re-injecting")
            self._stop_inject_proc()
            self._injected_pid = None
            if not self._inject_scale_locked(self._target_scale, pid=pid):
                return False
            self._current_scale = self._target_scale
            log_success(f"[speedhack] re-armed x{self._target_scale}")
            return True

    def reset(self) -> bool:
        """Park the agent at normal speed, leaving it resident.

        The agent is deliberately NOT unloaded: ripping a hook out of a function
        that every thread calls millions of times a second races with the
        threads inside its trampoline, and dropping the accumulated drift would
        jump CLOCK_MONOTONIC backwards. Parked at 1.0 the agent is a no-op that
        keeps time advancing at the real rate.
        """
        with self._lock:
            self._target_scale = 1.0
            self._current_scale = 1.0
            if self._inject_proc is not None and self._inject_proc.poll() is None:
                self._set_device_scale_prop(1.0)
                log_info("[speedhack] parked at 1.0 (agent stays resident)")
            return True

    def detach(self) -> None:
        """Restore normal speed and tear the injection down."""
        with self._lock:
            resident = self._inject_proc is not None and self._inject_proc.poll() is None
            if resident:
                # Park first so the game is already running at the real rate,
                # and give the agent's 250ms poller time to see it, before the
                # hook disappears from under its threads.
                self._set_device_scale_prop(1.0)
                time.sleep(0.8)
            self._stop_inject_proc()
            self._kill_device_frida()
            self._set_device_scale_prop(1.0)
            self._injected_pid = None
            self._current_scale = 1.0
            self._target_scale = 1.0
            self._live_verified = False
            self._run_adb(f"rm -f {shlex.quote(self._device_script_path)}")
        log_info("[speedhack] detached")


def demo():
    """Small command-line demo to test injecting a running process."""
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m src.core.frida_speedhack <package> [scale]")
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
        mgr.detach()


if __name__ == "__main__":
    demo()
