"""Emulator nodes: boot, find, resize, restart and kill emulator instances on the PC."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.workflow.logs import log_error, log_info, log_success, log_warning


# ── Emulator launch specs ─────────────────────────────────────────────────────
#
# Per-family console executable + argv template for booting one instance, plus
# the default install dirs to auto-discover the console when the user leaves the
# path blank. ``{index}`` = instance number, ``{instance}`` = BlueStacks instance
# name. A ``custom`` command (with ``{index}``/``{path}`` placeholders) always
# overrides these — the escape hatch for non-standard installs. The per-family
# first-instance ADB port + step mirror src/core/adb/constants.py so a launch can
# poll the right ``127.0.0.1:PORT`` until the emulator's ADB comes up.
EMULATOR_CONSOLES: Dict[str, Dict[str, Any]] = {
    "ldplayer": {
        "exes": ["ldconsole.exe", "dnconsole.exe"],
        "args": ["launch", "--index", "{index}"],
        "quit_args": ["quit", "--index", "{index}"],
        "restart_args": ["reboot", "--index", "{index}"],
        "dirs": [r"C:\LDPlayer\LDPlayer9", r"C:\LDPlayer\LDPlayer64",
                 r"C:\ChangZhi\LDPlayer9", r"D:\LDPlayer\LDPlayer9"],
        "port0": 5555, "step": 2,
    },
    "mumu": {
        "exes": ["MuMuManager.exe"],
        "args": ["control", "-v", "{index}", "launch"],
        "quit_args": ["control", "-v", "{index}", "shutdown"],
        "restart_args": ["control", "-v", "{index}", "restart"],
        # ``info`` reports the instance's REAL adb_port — MuMu Global's ports do
        # not always follow 16384+32*index (index 2 answers on 16449, not
        # 16448), so asking beats deriving whenever the console is reachable.
        "info_args": ["info", "-v", "{index}"],
        # MuMu's console also drives the *device* resolution (settings keys),
        # which plain Win32 window sizing can't reach.
        "res_keys": {"width": "resolution_width.custom",
                     "height": "resolution_height.custom",
                     "dpi": "resolution_dpi.custom",
                     "mode": "resolution_mode"},
        # MuMu 12 keeps the console in <install>\shell; the newer 5.x/6.x
        # (incl. Global) builds moved it to <install>\nx_main — "subdirs" lets
        # a bare install dir resolve either layout.
        "subdirs": ["shell", "nx_main"],
        "dirs": [r"C:\Program Files\Netease\MuMuPlayer-12.0",
                 r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0",
                 r"C:\Program Files\Netease\MuMuPlayer",
                 r"C:\Program Files\Netease\MuMuPlayerGlobal"],
        "port0": 16384, "step": 32,
    },
    "nox": {
        "exes": ["NoxConsole.exe"],
        "args": ["launch", "-index:{index}"],
        "quit_args": ["quit", "-index:{index}"],
        "restart_args": ["reboot", "-index:{index}"],
        "dirs": [r"C:\Program Files (x86)\Nox\bin", r"C:\Program Files\Nox\bin"],
        "port0": 62001, "step": 1,
    },
    "memu": {
        "exes": ["memuc.exe"],
        "args": ["start", "-i", "{index}"],
        "quit_args": ["stop", "-i", "{index}"],
        "restart_args": ["reboot", "-i", "{index}"],
        "dirs": [r"C:\Program Files\Microvirt\MEmu", r"C:\Program Files (x86)\Microvirt\MEmu"],
        "port0": 21503, "step": 1,
    },
    "bluestacks": {
        # HD-Player has no shutdown/restart verb — kill/restart fall back to
        # taskkill + relaunch of the player window's process tree.
        "exes": ["HD-Player.exe"],
        "args": ["--instance", "{instance}"],
        "dirs": [r"C:\Program Files\BlueStacks_nxt", r"C:\Program Files\BlueStacks"],
        "port0": 5555, "step": 10,
    },
}

# Last successful launch_emulator payload ({emulator, index, port, serial, …}).
# if_emulator's "last" option reads this back so a flow can check "is the
# emulator I used before still the one running?" across runs. Resolved via
# data_root() so frozen builds write to the writable user-data folder (next to
# the app, or %LOCALAPPDATA% for a read-only install), never inside _MEIPASS.
def _emulator_state_path() -> str:
    from src.utils import data_root
    return os.path.join(data_root(), "data", "emulator_state.json")

# Lowercased exe-basename prefixes of each family's *player* UI process — the
# console exes in EMULATOR_CONSOLES (ldconsole / MuMuManager / …) run headless,
# so resizing the window means finding the player process instead. Matched via
# basename prefix: MuMuPlayer.exe → "mumuplayer", HD-Player.exe → "hd-player".
EMU_PLAYER_EXES: Dict[str, List[str]] = {
    "ldplayer": ["dnplayer", "ldplayer"],
    "mumu": ["mumuplayer", "nemuplayer", "mumunxdevice"],
    "nox": ["nox"],
    "memu": ["memu"],
    "bluestacks": ["hd-player", "bluestacks"],
}

# Node param value meaning "whatever device the toolbar has selected" — the
# device the user is looking at, rather than one this flow launched itself.
EMU_SELECTED = "selected"

# Instances per family, mirroring the 32-entry port ranges in
# src/core/adb/constants.py. Guards _emulator_port_candidates against an
# unrelated port landing on a formula by accident.
EMU_INDEX_MAX = 32


def _split_emulator_serial(serial: str) -> Tuple[str, Optional[int]]:
    """``(host, adb_port)`` for a toolbar serial; ``(host, None)`` with no port.

    Covers the three shapes the device list can hand us: ``host:port`` (what an
    emulator publishes, loopback or LAN), adb's ``emulator-N`` console form —
    whose ADB port is N+1, the classic 5554/5555 pairing LDPlayer answers on —
    and a USB serial (``R58M…``), which no emulator node can act on.
    """
    s = str(serial or "").strip()
    if not s:
        return "", None
    if s.lower().startswith("emulator-"):
        try:
            return "", int(s.split("-", 1)[1]) + 1
        except (TypeError, ValueError):
            return "", None
    if ":" in s:
        host, _, tail = s.rpartition(":")
        try:
            port = int(tail)
        except (TypeError, ValueError):
            return s, None
        return host.strip(), (port if port > 0 else None)
    return s, None


def _emulator_port_candidates(port: int) -> List[Tuple[str, int]]:
    """Every ``(family, index)`` whose ADB port is *port*.

    Inverts each family's ``port0``/``step``. More than one family can answer
    the same port — LDPlayer's ``5555 + 2n`` meets BlueStacks' ``5555 + 10n`` on
    seven of them — so a single candidate is a certain answer, while several
    need the running-process evidence :meth:`_resolve_selected_emulator` adds.
    """
    if not port or port <= 0:
        return []
    out: List[Tuple[str, int]] = []
    for kind, spec in EMULATOR_CONSOLES.items():
        port0 = int(spec.get("port0") or 0)
        step = int(spec.get("step") or 0)
        if port0 <= 0 or step <= 0:
            continue
        delta = int(port) - port0
        if delta < 0 or delta % step:
            continue
        index = delta // step
        if 0 <= index < EMU_INDEX_MAX:
            out.append((kind, index))
    return out


def _emulator_family_from_exe(path: str) -> Optional[str]:
    """Family whose *player* exe *path* names, or None (a bare ``adb.exe``)."""
    name = os.path.basename(str(path or "")).lower()
    if not name:
        return None
    for kind, prefixes in EMU_PLAYER_EXES.items():
        if any(name.startswith(pre) for pre in prefixes):
            return kind
    return None


def _process_image_path(pid: int) -> str:
    """Full exe path of *pid* ("" for elevated/protected or non-Windows)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buf))
            if not kernel32.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buf, ctypes.byref(size)):
                return ""
            return buf.value
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        return ""


def _emulator_render_child(hwnd: int) -> Optional[tuple]:
    """Largest child window of an emulator player = its Android render surface.

    MuMu (and the other Qt-based players) put a toolbar strip inside the same
    client area — MuMu's is 40px tall — so the client rect is NOT the device
    view: a client of 1920×1080 leaves the render child at 1920×1040, which is
    no longer 16:9, and the player letterboxes the device inside it → black
    bars down both sides. Returns ``(hwnd, width, height)`` of that child, or
    None when the player draws straight into its own client area.
    """
    try:
        import win32gui
    except ImportError:
        return None
    kids: List[int] = []
    try:
        win32gui.EnumChildWindows(hwnd, lambda c, _: kids.append(c), None)
    except Exception:
        return None
    best: Optional[tuple] = None
    for c in kids:
        try:
            l, t, r, b = win32gui.GetWindowRect(c)
        except Exception:
            continue
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            continue
        if best is None or w * h > best[1] * best[2]:
            best = (c, w, h)
    return best


def _enum_player_windows() -> Dict[str, List[Dict[str, Any]]]:
    """Every visible top-level emulator player window, grouped by family.

    One ``EnumWindows`` pass answers both questions the emulator nodes ask:
    *which families are running at all* (needed to tell two families apart when
    they share an ADB port) and *which window is this instance's* — see
    :func:`_pick_player_window`.

    A window qualifies when its process exe basename starts with one of the
    family's :data:`EMU_PLAYER_EXES` prefixes. When the exe can't be read
    (elevated), the window title is trusted instead — it usually carries the
    brand — and the window is listed under every family its title matches.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    try:
        import win32gui
        import win32process
    except ImportError:
        return out

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return  # skip invisible-named helper windows
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            return
        exe_path = _process_image_path(pid)
        name = os.path.basename(exe_path or "").lower()
        low_title = title.lower()
        for kind, prefixes in EMU_PLAYER_EXES.items():
            if name:
                if not any(name.startswith(pre) for pre in prefixes):
                    continue
            elif not any(pre in low_title for pre in prefixes + [kind]):
                continue
            out.setdefault(kind, []).append({
                "hwnd": hwnd, "pid": int(pid), "title": title,
                "exe_path": exe_path, "area": abs(w * h),
            })

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return out
    return out


def _pick_player_window(records: Dict[str, List[Dict[str, Any]]], kind: str,
                        install_dir: str = "", *,
                        pid_hints: Optional[List[int]] = None,
                        strict: bool = False) -> Tuple[Optional[int], str]:
    """Pick one instance's player window for *kind*; returns ``(hwnd, how)``.

    ``how`` names the rung that decided it, because the caller has to know
    whether the answer is certain:

      ``pid``        — the window's process holds the instance's ADB port, so
                       this IS that instance (exact)
      ``single``     — only one window of the family is open (exact)
      ``largest``    — several windows, nothing identified the right one: the
                       historical rule, kept for the explicit family+index nodes
      ``ambiguous``  — several windows and the caller asked for one specific
                       instance (``strict``) → refuse instead of resizing a sibling
      ``none``       — no window of the family at all

    ``install_dir`` (node param / saved launch_emulator state) orders windows
    whose process lives under it first — several emulator versions installed
    side by side all match the same family prefixes.
    """
    recs = records.get(kind) or []
    if not recs:
        return None, "none"
    base = os.path.normcase(os.path.normpath(install_dir)) if install_dir else ""

    def _key(rec: Dict[str, Any]) -> tuple:
        under = False
        exe_path = rec.get("exe_path") or ""
        if base and exe_path:
            exe_dir = os.path.normcase(os.path.normpath(os.path.dirname(exe_path)))
            under = exe_dir.startswith(base) or exe_dir.startswith(
                os.path.normcase(os.path.normpath(os.path.dirname(base)))
            )
        return (under, rec.get("area") or 0, rec.get("hwnd") or 0)

    hints = {int(p) for p in (pid_hints or [])}
    if hints:
        hit = [r for r in recs if int(r.get("pid") or 0) in hints]
        if hit:
            return max(hit, key=_key)["hwnd"], "pid"
    if len(recs) == 1:
        return recs[0]["hwnd"], "single"
    if strict:
        return None, "ambiguous"
    return max(recs, key=_key)["hwnd"], "largest"


def _find_emulator_window(kind: str, install_dir: str = "") -> Optional[int]:
    """Locate an emulator family's visible main window; largest one wins.

    Thin wrapper over :func:`_enum_player_windows` + :func:`_pick_player_window`
    that keeps the original "largest window of the family" contract for callers
    with no way to identify the instance — see ``_pick_player_window`` for the
    ``how`` values that make the choice exact instead.
    """
    return _pick_player_window(_enum_player_windows(), kind, install_dir)[0]


def _tcp_listener_pids(port: int) -> List[int]:
    """PIDs holding a LISTENING TCP socket on *port* (``[]`` when unknown).

    This is what makes "the device I selected" exact: the instance whose ADB
    port the toolbar serial names is the one whose window must be resized, and
    that association is the only signal that survives several instances of the
    same family being open at once. ``netstat`` rather than a ctypes
    ``GetExtendedTcpTable`` because the table's struct layout is a minefield
    that can't be exercised without the emulator installed.
    """
    import subprocess
    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    except Exception:
        return []
    pids: List[int] = []
    for line in (r.stdout or "").splitlines():
        #   TCP    127.0.0.1:16384    0.0.0.0:0    LISTENING    1234
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        if ":" not in local:
            continue
        try:
            if int(local.rsplit(":", 1)[1]) != int(port):
                continue
            pid = int(parts[4])
        except (TypeError, ValueError):
            continue
        if pid > 0 and pid not in pids:
            pids.append(pid)
    return pids


class EmulatorNodes:
    """launch/kill/restart/resize emulator nodes and their ADB attach."""

    # ── Emulator launch ───────────────────────────────────────────────────────

    def _a_launch_emulator(self, node, p) -> bool:
        """Boot the emulator *process* on the PC (LDPlayer/MuMu/Nox/MEmu/
        BlueStacks). Optional ``at`` (HH:MM) waits until that clock time first;
        optional ``wait`` seconds then polls the instance's ADB port until it is
        connectable (so the very next node can drive the freshly-booted device).
        """
        at = str(p.get("at", "")).strip()
        if at and not self._wait_until_clock(at, bool(p.get("nextDay", True))):
            return False  # malformed schedule time

        kind = self._emulator_kind(p, "ldplayer")
        # Shared project install folder (pathSrc="project") — folded into p so
        # the argv builder and saved emulator state both see the resolved path.
        p = {**(p or {}), "path": self._emulator_path(p)}
        index = self._emulator_index(p)

        argv = self._emulator_launch_argv(p, kind, index)
        if not argv:
            log_error(
                f"▶ Could not build the launch command for '{kind}' — set 'Path' "
                f"to the install folder or console .exe, or use 'Custom command'"
            )
            return False

        import subprocess
        try:
            log_info(f"▶ Launching emulator: {' '.join(argv)}")
            subprocess.Popen(
                argv,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        except Exception as exc:
            log_error(f"▶ Failed to launch emulator: {exc}")
            return False

        wait = float(p.get("wait", 0) or 0)
        port = self._emulator_adb_port(p, kind, index)
        host: Optional[str] = None
        if wait > 0:
            # The console only publishes the real port once the instance is up,
            # so keep re-asking it while polling instead of trusting the
            # pre-boot guess.
            host = self._wait_emulator_adb(
                port, wait,
                resolver=lambda: self._emulator_adb_port(p, kind, index))
            if host:
                try:
                    port = int(host.rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    pass
        # Remember which instance this flow booted so if_emulator's "last used"
        # option can re-check the same one on future runs.
        self._save_emulator_state({
            "emulator": kind,
            "index": index,
            "instance": str(p.get("instance", "") or ""),
            "path": str(p.get("path", "") or ""),
            "port": port,
            "serial": host or (f"127.0.0.1:{port}" if port else None),
            "launched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        # Flows started with no device (deferred readiness in _ensure_ready)
        # attach to the freshly booted emulator here so the next node can run.
        if getattr(self, "_controller", "adb") != "win32" and not self.auto.adb.device:
            self._attach_adb_after_boot(host)
        return True

    @staticmethod
    def _save_emulator_state(state: Dict[str, Any]) -> None:
        path = _emulator_state_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            log_warning(f"Couldn't save the emulator state: {exc}")

    @staticmethod
    def _load_emulator_state() -> Optional[Dict[str, Any]]:
        try:
            with open(_emulator_state_path(), "r", encoding="utf-8") as fh:
                return json.load(fh) or None
        except Exception:
            return None

    def _resolve_emulator_target(self, p: Dict) -> Optional[tuple]:
        """Resolve ``(kind, index, host)`` for if_emulator / wait_emulator.

        ``emulator`` = "last" re-checks the instance the last successful
        launch_emulator saved. The port comes from the explicit override, then
        the family console's own report, then the state file, then the
        port0+index*step formula — the console is asked before the saved value
        because MuMu Global's real port can differ from the derived one, and a
        stale saved port would make a healthy emulator look unready. Returns
        None when the target can't be resolved.
        """
        kind = str(p.get("emulator", "last")).strip().lower() or "last"
        try:
            index = int(float(p.get("index", 0) or 0))
        except (TypeError, ValueError):
            index = 0
        # Blank/0 port = "auto" (the designer serializes an empty num field as 0).
        port: Optional[int] = None
        override = str(p.get("port", "") or "").strip()
        if override:
            try:
                val = int(float(override))
                port = val if val > 0 else None
            except (TypeError, ValueError):
                port = None
        saved_port: Optional[int] = None
        path = self._emulator_path(p)
        if kind == "last":
            saved = self._load_emulator_state()
            if not saved:
                log_warning("🖥 No saved emulator yet — run a Launch emulator node once first")
                return None
            kind = str(saved.get("emulator") or "?").lower()
            try:
                index = int(saved.get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            if not path:
                path = str(saved.get("path") or "").strip()
            try:
                val = int(saved.get("port") or 0)
                saved_port = val if val > 0 else None
            except (TypeError, ValueError):
                saved_port = None
        if port is None:
            port = self._emulator_adb_port({"path": path}, kind, index)
        if port is None:
            port = saved_port
        if port is None:
            log_warning(f"🖥 Can't derive the ADB port for '{kind}' — set 'ADB port override'")
            return None
        return kind, index, f"127.0.0.1:{port}"

    def _maybe_attach_emulator(self, p: Dict, host: str) -> None:
        """Attach ADB to ``host`` when ``attach`` is on and no device is bound yet."""
        if (bool(p.get("attach", True))
                and getattr(self, "_controller", "adb") != "win32"
                and not self.auto.adb.device):
            self._attach_adb_after_boot(host)

    def set_selected_device(self, serial: Optional[str]) -> None:
        """Report the device the host app's picker currently has selected.

        The Designer/Runner call this whenever ``select_device`` runs, so an
        emulator node targeting ``EMU_SELECTED`` acts on what the user is
        actually looking at instead of on whatever this flow launched last.
        """
        self.selected_serial = str(serial or "").strip()

    def _current_selected_serial(self) -> str:
        """The selected-device serial: what the host pushed, else the bound ADB
        device — the same "current device" ``_a_install_apk`` and
        ``_a_device_info`` read off the controller."""
        return (self.selected_serial
                or str(getattr(self.auto.adb, "device_id", "") or "").strip())

    def _resolve_selected_emulator(self, p: Dict, verb: str) -> Optional[tuple]:
        """``(kind, index, install_dir, instance)`` for the toolbar's device.

        The toolbar holds an ADB serial, the PC-side nodes need family+index, so
        this walks: serial → port → candidate families. A port one family owns
        is a certain answer; a shared port (LDPlayer and BlueStacks both answer
        5555) is settled by which of those families actually has a player window
        open. When that evidence is missing too we refuse and say so, rather
        than resizing whichever sibling happens to be largest.
        """
        serial = self._current_selected_serial()
        if not serial:
            log_warning(f"🖥 {verb}: no toolbar device selected — select a device, "
                        f"or set 'Emulator' to 'Last used (saved)' or a specific vendor")
            return None
        _, port = _split_emulator_serial(serial)
        cands = _emulator_port_candidates(port) if port else []
        if not cands:
            log_warning(f"🖥 {verb}: selected device '{serial}' does not match any emulator "
                        f"ADB port — select a specific emulator vendor in the node")
            return None
        running = _enum_player_windows()
        if len(cands) == 1:
            kind, index = cands[0]
            note = ""
        else:
            live = [c for c in cands if running.get(c[0])]
            if len(live) != 1:
                names = " and ".join(f"'{k}'" for k, _ in cands)
                log_warning(f"🖥 {verb}: port {port} is shared by {names}, but no matching "
                            f"process is running — select a specific emulator vendor in the node")
                return None
            kind, index = live[0]
            note = " (based on running process)"
        # The running instance's own exe path beats the project setting: several
        # copies of one emulator installed side by side answer the same family.
        path = ""
        for rec in running.get(kind) or []:
            if rec.get("exe_path"):
                path = os.path.dirname(rec["exe_path"])
                break
        log_info(f"🖥 {verb}: selected device {serial} → {kind} #{index}{note}")
        return kind, index, path or self._emulator_path(p), ""

    def _emulator_pc_target(self, p: Dict, verb: str) -> Optional[tuple]:
        """Resolve ``(kind, index, install_dir, instance)`` for the PC-side
        emulator nodes (resize / kill / restart / device resolution).

        ``emulator`` = "last" reuses the instance the last successful
        launch_emulator saved (family + index + install path + BlueStacks
        instance name); ``EMU_SELECTED`` resolves the toolbar's device instead.
        Returns None when the family can't be determined; the reason is logged
        here.
        """
        kind = str(p.get("emulator", "last")).strip().lower() or "last"
        if kind == EMU_SELECTED:
            return self._resolve_selected_emulator(p, verb)
        try:
            index = int(float(p.get("index", 0) or 0))
        except (TypeError, ValueError):
            index = 0
        path = self._emulator_path(p)
        instance = str(p.get("instance", "") or "").strip()
        if kind == "last":
            saved = self._load_emulator_state()
            if not saved:
                log_warning(f"🖥 {verb}: no saved emulator — "
                            f"run a 'Launch emulator' node first or select a specific vendor")
                return None
            kind = str(saved.get("emulator") or "").lower()
            try:
                index = int(saved.get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            if not path:
                path = str(saved.get("path") or "").strip()
            if not instance:
                instance = str(saved.get("instance") or "").strip()
        if kind not in EMU_PLAYER_EXES:
            log_warning(f"🖥 {verb}: unrecognized emulator vendor '{kind}' — select a specific vendor in the node")
            return None
        return kind, index, path, instance

    def _run_emulator_console(self, kind: str, path: str, args_key: str,
                              index: int, extra: Optional[Dict[str, Any]] = None,
                              timeout: float = 30.0) -> Optional[str]:
        """Run one console verb (``args_key`` in EMULATOR_CONSOLES) for *index*.

        Returns the command's stdout on success; None when the family has no
        such verb, the console exe can't be found, or the call raised — the
        caller then decides whether a Win32 fallback applies.
        """
        import subprocess
        spec = EMULATOR_CONSOLES.get(kind) or {}
        template = spec.get(args_key)
        if not template:
            return None
        exe = self._resolve_console_exe(
            path, spec.get("exes", []), spec.get("dirs", []), spec.get("subdirs"))
        if not exe:
            return None
        subs = {"index": str(index), **{k: str(v) for k, v in (extra or {}).items()}}
        argv = [exe]
        for a in template:
            for k, v in subs.items():
                a = a.replace("{" + k + "}", v)
            argv.append(a)
        try:
            log_info(f"🖥 {' '.join(argv)}")
            r = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            return r.stdout or ""
        except Exception as exc:
            log_warning(f"🖥 Console '{args_key}' error: {exc}")
            return None

    def _taskkill_emulator_window(self, kind: str, path: str, *,
                                  pid_hints: Optional[List[int]] = None,
                                  strict: bool = False) -> Optional[bool]:
        """Force-kill the process tree owning the family's player window.

        True = killed, None = no window found (already closed), False = error.
        ``pid_hints``/``strict`` narrow the choice to one instance — see
        :func:`_pick_player_window`.
        """
        import subprocess
        hwnd = _pick_player_window(_enum_player_windows(), kind, path,
                                   pid_hints=pid_hints, strict=strict)[0]
        if not hwnd:
            return None
        try:
            import win32process
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            return True
        except Exception as exc:
            log_warning(f"🖥 Failed to terminate emulator: {exc}")
            return False

    def _selected_instance_hints(self, p: Dict
                                 ) -> Tuple[Optional[int], Optional[List[int]], bool]:
        """``(adb_port, listener_pids, strict)`` for a node naming one instance.

        A node targeting the toolbar's device means *that* instance, so the
        caller passes ``strict`` and refuses rather than resizing a sibling when
        the window can't be pinned down. ``listener_pids`` is the set of PIDs
        holding the device's ADB port — the only signal that survives several
        instances of one family being open, and ``None`` on the explicit
        family+index paths, which keep the historical largest-window rule.

        The port comes from the serial itself rather than the family formula, so
        a drifted MuMu port or a LAN-bound LDPlayer still resolves.
        """
        if str(p.get("emulator", "")).strip().lower() != EMU_SELECTED:
            return None, None, False
        port = _split_emulator_serial(self._current_selected_serial())[1]
        return port, (_tcp_listener_pids(port) if port else []), True

    def _a_resize_emulator(self, node, p) -> bool:
        """Resize the emulator's PC window so the ANDROID RENDER AREA becomes
        width×height — the thing that decides whether the device is letterboxed.

        Two layers of chrome sit between the outer frame and the device view:
        the title bar/borders, and (on MuMu) a ~40px toolbar strip inside the
        client area. Sizing either the frame or the client to 1920×1080 leaves
        the render surface short of 16:9, so the player pillarboxes the device →
        black bars down both sides. Both deltas are therefore measured live
        (GetWindowRect vs the largest child window) and added on top. Unlike
        ``win_resize`` — which resizes the flow's Win32 target window — this
        needs no controller, so it works in ADB flows; the player window is
        found via the family's process names ("last" = the instance the last
        successful launch_emulator saved, "selected" = the toolbar's device).
        Keeps the restore-if-maximized + WM_SIZE nudge, because the Qt/DX player
        windows otherwise ignore plain SetWindowPos.
        """
        target = self._emulator_pc_target(p, "Resize")
        if not target:
            return False
        kind, index, install_dir, _ = target
        try:
            w = max(200, int(float(p.get("width", 1920) or 1920)))
            h = max(200, int(float(p.get("height", 1080) or 1080)))
        except (TypeError, ValueError):
            w, h = 1920, 1080
        _, hints, strict = self._selected_instance_hints(p)
        hwnd, how = _pick_player_window(_enum_player_windows(), kind, install_dir,
                                        pid_hints=hints, strict=strict)
        if how == "ambiguous":
            log_warning(f"🖥 Resize: '{kind}' has multiple windows and the window for "
                        f"{self._current_selected_serial()} could not be identified — close extra instances "
                        f"or select a specific vendor and index in the node")
            return False
        if not hwnd:
            log_warning(f"🖥 Emulator window '{kind}' #{index} not found — is it running?")
            return False
        if how == "largest":
            log_warning(f"🖥 Resize: '{kind}' has multiple windows — targeting the largest, "
                        f"which may be the wrong instance")
        try:
            import win32api
            import win32con
            import win32gui
            placement = win32gui.GetWindowPlacement(hwnd)
            if placement[1] == win32con.SW_SHOWMAXIMIZED:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.05)
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            # Chrome = outer frame minus the render surface. Fall back to the
            # client rect for players that draw into their own client area.
            child = _emulator_render_child(hwnd)
            if child:
                _, rw, rh = child
            else:
                cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
                rw, rh = cr - cl, cb - ct
            dx = max(0, (r - l) - rw)
            dy = max(0, (b - t) - rh)
            # Optional reposition — blank X/Y keeps the window where it is, so a
            # flow can also park several instances side by side.
            for key in ("x", "y"):
                val = str(p.get(key, "")).strip()
                if val in ("", "None"):
                    continue
                try:
                    if key == "x":
                        l = int(float(val))
                    else:
                        t = int(float(val))
                except (TypeError, ValueError):
                    pass
            SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0004, 0x0010, 0x0020
            win32gui.SetWindowPos(hwnd, 0, l, t, w + dx, h + dy,
                                  SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            # WM_SIZE carries the new *client* size (render + toolbar strip).
            win32api.SendMessage(hwnd, 0x0005, 0, ((h + dy - 4) << 16) | ((w + dx) & 0xFFFF))
            time.sleep(0.3)  # Qt relayouts the render child asynchronously
            after = _emulator_render_child(hwnd)
            got = (after[1], after[2]) if after else None
            if got and got != (w, h):
                log_warning(f"🖥 Display area after resize is {got[0]}×{got[1]} "
                            f"(requested {w}×{h}) — the window may enforce a minimum size")
            # Name the window: with two instances of one family open, this is
            # how the user sees which one the node actually acted on.
            title = (win32gui.GetWindowText(hwnd) or "").strip()
            log_success(f"🖥 Resized emulator {kind} #{index}"
                        f"{f' — window {title!r}' if title else ''}"
                        f" → display {w}×{h} at ({l}, {t})")
            return True
        except Exception as exc:
            log_warning(f"🖥 Emulator resize failed: {exc}")
            return False

    def _a_kill_emulator(self, node, p) -> bool:
        """Kill the emulator instance — closing the app inside ≠ closing the
        emulator; the instance keeps running and holds its RAM/CPU + ADB port.

        Preferred path is the family's console shutdown (LDPlayer/MuMu/Nox/
        MEmu; BlueStacks has none). When the console can't be resolved — or the
        family has no console shutdown — fall back to taskkilling the process
        tree that owns the player window (the same window resize_emulator
        finds). Returns True when the kill command was issued or there was
        nothing to kill; False only when the target couldn't even be resolved.
        """
        target = self._emulator_pc_target(p, "Stop emulator")
        if not target:
            return False
        kind, index, path, _ = target
        _, hints, strict = self._selected_instance_hints(p)

        # 1) console shutdown — leaves no zombie VM process behind.
        if self._run_emulator_console(kind, path, "quit_args", index) is not None:
            log_success(f"🖥 Stopped emulator {kind} #{index}")
            return True
        # 2) fallback: taskkill the player window's process tree (BlueStacks has
        #    no console verb; or the console exe couldn't be resolved).
        killed = self._taskkill_emulator_window(kind, path, pid_hints=hints, strict=strict)
        if killed is None:
            log_info(f"🖥 Emulator window '{kind}' #{index} not found (already stopped? — skipping)")
            return True
        if not killed:
            return False
        log_success(f"🖥 Stopped emulator {kind} #{index}")
        return True

    def _a_restart_emulator(self, node, p) -> bool:
        """Reboot the emulator instance — the fix for a wedged Android session
        (frozen UI, ADB gone, app stuck) that ``app_stop`` can't clear.

        Console ``reboot``/``restart`` when the family has one, else kill the
        player and relaunch it via the same argv launch_emulator builds. With
        ``wait`` > 0 the node then polls the instance's ADB until Android
        reports ``sys.boot_completed`` so the next node can drive the device.
        """
        target = self._emulator_pc_target(p, "Restart emulator")
        if not target:
            return False
        kind, index, path, instance = target
        sel_port, hints, strict = self._selected_instance_hints(p)
        try:
            wait = max(0.0, float(p.get("wait", 120) or 0))
        except (TypeError, ValueError):
            wait = 120.0
        # Relaunching BlueStacks means `HD-Player --instance <name>`, and an
        # instance name can't be read off an ADB serial — so say so instead of
        # relaunching whatever instance the console would default to.
        if strict and kind == "bluestacks" and not instance:
            log_warning("🖥 Restart emulator: BlueStacks requires an instance name — set 'Instance "
                        "name' in the node (it cannot be derived from the selected device)")
            return False

        if self._run_emulator_console(kind, path, "restart_args", index) is None:
            # No console restart verb (BlueStacks) → kill, then relaunch.
            log_info(f"🖥 '{kind}' has no restart command — stopping and relaunching")
            killed = self._taskkill_emulator_window(kind, path, pid_hints=hints, strict=strict)
            if killed is False:
                return False
            if killed:
                time.sleep(3.0)  # let the VM processes actually exit
            argv = self._emulator_launch_argv(
                {**p, "path": path, "instance": instance, "command": ""}, kind, index)
            if not argv:
                log_error(f"🖥 Could not build relaunch command for '{kind}' — set 'Path' to the install folder")
                return False
            import subprocess
            try:
                log_info(f"🖥 Relaunching emulator: {' '.join(argv)}")
                subprocess.Popen(argv, creationflags=getattr(
                    subprocess, "CREATE_NO_WINDOW", 0x08000000))
            except Exception as exc:
                log_error(f"🖥 Failed to relaunch emulator: {exc}")
                return False

        if wait <= 0:
            log_success(f"🖥 Sent restart command to emulator {kind} #{index}")
            return True
        # An instance that is still shutting down would answer the *old* ADB
        # session; give it a moment before polling for the fresh boot.
        time.sleep(3.0)
        # Use the resolved install path for console-reported ports. A restart
        # node using `emulator: "last"` often leaves `path` blank.
        port_params = {**p, "path": path}
        # Targeting the toolbar's device, the port is already known from its
        # serial — and it beats the formula, which can drift across a reboot
        # (MuMu Global) or name the other emulator on a shared port.
        port = sel_port or self._emulator_adb_port(port_params, kind, index)
        host = f"127.0.0.1:{port}" if port else None
        if not host:
            log_warning(f"🖥 Could not determine ADB port for '{kind}' #{index} — skipping wait")
            return True
        end = time.time() + wait
        while not self._stop.is_set():
            self._pause.wait()
            if self._emulator_adb_ready(host):
                log_success(f"🖥 Emulator {kind} #{index} restarted and finished booting ({host})")
                self._maybe_attach_emulator(p, host)
                return True
            if time.time() >= end:
                break
            time.sleep(1.0)
        log_warning(f"🖥 Emulator {kind} #{index} did not finish booting after {wait:.0f}s")
        return False

    def _a_emulator_resolution(self, node, p) -> bool:
        """Set the emulator's *device* resolution (Android screen px + DPI).

        This is the setting that actually decides what the templates were
        cropped against — ``resize_emulator`` only changes the PC window, so a
        window at 1920×1080 over a 1600×900 device still letterboxes. Only MuMu
        exposes it on the console (``setting --key resolution_*``); the change
        needs a restart of the instance to take effect, which ``restart`` does
        here when asked.
        """
        target = self._emulator_pc_target(p, "Change resolution")
        if not target:
            return False
        kind, index, path, _ = target
        spec = EMULATOR_CONSOLES.get(kind) or {}
        keys = spec.get("res_keys")
        if not keys:
            log_warning(f"🖥 '{kind}' does not support console resolution changes — "
                        f"change it in the emulator settings (only MuMu is supported)")
            return False
        try:
            w = max(200, int(float(p.get("width", 1920) or 1920)))
            h = max(200, int(float(p.get("height", 1080) or 1080)))
            dpi = max(80, int(float(p.get("dpi", 280) or 280)))
        except (TypeError, ValueError):
            w, h, dpi = 1920, 1080, 280
        exe = self._resolve_console_exe(
            path, spec.get("exes", []), spec.get("dirs", []), spec.get("subdirs"))
        if not exe:
            log_warning(f"🖥 Console for '{kind}' not found — set 'Path' to the install folder")
            return False
        # A custom w/h/dpi only applies when the mode is switched off the presets.
        argv = [exe, "setting", "-v", str(index),
                "-k", keys["mode"], "-val", "custom",
                "-k", keys["width"], "-val", str(w),
                "-k", keys["height"], "-val", str(h),
                "-k", keys["dpi"], "-val", str(dpi)]
        import subprocess
        try:
            log_info(f"🖥 {' '.join(argv)}")
            r = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            out = (r.stdout or "") + (r.stderr or "")
        except Exception as exc:
            log_warning(f"🖥 Resolution change failed: {exc}")
            return False
        if "errcode" in out.lower() and '"errcode": 0' not in out:
            log_warning(f"🖥 Console rejected the resolution change: {out.strip()[:200]}")
            return False
        log_success(f"🖥 Emulator resolution {kind} #{index} → {w}×{h} @ {dpi}dpi")
        if bool(p.get("restart", True)):
            # The instance reads resolution at boot, so it must cycle to apply.
            return self._a_restart_emulator(node, {**p, "wait": p.get("wait", 120)})
        log_info("🖥 Restart the emulator to apply the new resolution")
        return True

    def _c_if_emulator(self, p: Dict) -> bool:
        """True when the target emulator instance is booted and its ADB answers
        (``adb connect`` + ``sys.boot_completed`` == 1).

        ``emulator`` = "last" (default) re-checks the instance the last
        successful launch_emulator saved — "is the one I set still running?".
        With ``attach`` on (default), a flow that started with no device binds
        to the ready instance so the following nodes can drive it.
        """
        target = self._resolve_emulator_target(p)
        if not target:
            return False
        kind, index, host = target
        ready = self._emulator_adb_ready(host)
        log_info(f"🖥 Emulator {kind} #{index} ({host}) → {'ready' if ready else 'not ready'}")
        if ready:
            self._maybe_attach_emulator(p, host)
        return ready

    def _c_wait_emulator(self, p: Dict) -> bool:
        """Poll until the target emulator finishes booting (ADB +
        ``sys.boot_completed``) or ``timeout`` seconds elapse.

        true  → ready (and optionally attached as the active device)
        false → timeout / unresolvable target / stopped mid-wait
        """
        target = self._resolve_emulator_target(p)
        if not target:
            return False
        kind, index, host = target
        try:
            timeout = float(p.get("timeout", 120) or 120)
        except (TypeError, ValueError):
            timeout = 120.0
        timeout = max(0.0, timeout)
        log_info(
            f"⏳ Waiting for emulator {kind} #{index} ({host}) "
            f"up to {timeout:.0f}s…"
        )
        end = time.time() + timeout
        # Immediate probe first so an already-booted instance returns instantly.
        while not self._stop.is_set():
            self._pause.wait()
            if self._emulator_adb_ready(host):
                log_success(
                    f"⏳ Emulator {kind} #{index} ({host}) ready"
                )
                self._maybe_attach_emulator(p, host)
                return True
            if time.time() >= end:
                break
            # Short sleep so stop/pause stay responsive; boot often takes tens of s.
            time.sleep(1.0)
        if self._stop.is_set():
            log_warning(f"⏳ Wait emulator cancelled ({host})")
        else:
            log_warning(
                f"⏳ Emulator {kind} #{index} ({host}) not ready "
                f"after {timeout:.0f}s"
            )
        return False

    @staticmethod
    def _emulator_adb_ready(host: str) -> bool:
        """One-shot readiness probe: ``adb connect`` succeeds AND the instance
        reports ``sys.boot_completed`` == 1 (Android finished booting)."""
        from src.core.adb.constants import get_adb_path
        import subprocess
        adb = get_adb_path()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            r = subprocess.run(
                [adb, "connect", host],
                capture_output=True, text=True, timeout=5, creationflags=flags,
            )
            if "connected" not in (r.stdout or "").lower():
                return False
            r = subprocess.run(
                [adb, "-s", host, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, timeout=5, creationflags=flags,
            )
            return (r.stdout or "").strip() == "1"
        except Exception:
            return False

    def _attach_adb_after_boot(self, serial: Optional[str]) -> None:
        """Bind the engine to the emulator that launch_emulator just booted:
        select its ADB serial (if known), then start capture — the steps
        _ensure_ready() skipped when the flow started with no device."""
        try:
            adb = self.auto.adb
            if serial:
                adb.device_id = serial
            adb.check_adb_connection()
            if not adb.device:
                log_warning(
                    "No ADB device after the emulator launch — "
                    "set 'Wait' on the Launch emulator node so it can finish booting"
                )
                return
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
        except Exception as exc:
            log_warning(f"Couldn't attach to the booted emulator: {exc}")

    def _emulator_launch_argv(self, p: Dict, kind: str, index: int) -> Optional[List[str]]:
        """Build the console argv for booting one instance, or None if it can't be
        resolved. A custom command always wins; otherwise the per-family console
        exe is discovered under the given path or the default install dirs."""
        path = str(self._resolve_value(p.get("path", ""))).strip()
        custom = str(p.get("command", "")).strip()
        if kind == "custom" or custom:
            if not custom:
                return None
            cmd = custom.replace("{index}", str(index)).replace("{path}", path)
            try:
                import shlex
                return shlex.split(cmd, posix=False)
            except Exception:
                return [cmd]

        spec = EMULATOR_CONSOLES.get(kind)
        if not spec:
            return None
        exe = self._resolve_console_exe(path, spec["exes"], spec["dirs"], spec.get("subdirs"))
        if not exe:
            return None
        instance = str(p.get("instance", "") or index)
        args = [a.replace("{index}", str(index)).replace("{instance}", instance)
                for a in spec["args"]]
        return [exe] + args

    @staticmethod
    def _resolve_console_exe(path: str, exes: List[str], dirs: List[str],
                             subdirs: Optional[List[str]] = None) -> Optional[str]:
        """Find the console .exe: an explicit file, else inside an explicit dir,
        else inside each known default install dir. ``subdirs`` are well-known
        per-family subfolders also searched under each dir (e.g. MuMu's
        ``shell``/``nx_main``)."""
        def find_in(d: str) -> Optional[str]:
            for sub in [""] + list(subdirs or []):
                for name in exes:
                    cand = os.path.join(d, sub, name)
                    if os.path.exists(cand):
                        return cand
            return None

        if path:
            if os.path.isfile(path):
                return path
            if os.path.isdir(path):
                hit = find_in(path)
                if hit:
                    return hit
        for d in dirs:
            hit = find_in(d)
            if hit:
                return hit
        return None

    def _emulator_adb_port(self, p: Dict, kind: str, index: int) -> Optional[int]:
        """The instance's ADB port: an explicit ``port`` override, else what the
        family's console reports for that instance, else derived from the
        family's first-instance port + index*step (mirrors constants.py).

        Asking the console matters because MuMu Global does not always follow
        16384+32*index (instance 2 answers on 16449), so a derived port would
        make the boot-wait time out on a perfectly healthy emulator.
        """
        # The designer serializes a blank num field as 0 — treat <= 0 as "auto".
        override = str(p.get("port", "")).strip()
        if override:
            try:
                val = int(float(override))
                if val > 0:
                    return val
            except ValueError:
                pass
        spec = EMULATOR_CONSOLES.get(kind)
        if not spec:
            return None
        if spec.get("info_args"):
            out = self._run_emulator_console(
                kind, str(self._resolve_value(p.get("path", "")) or "").strip(),
                "info_args", index, timeout=15.0)
            if out:
                m = re.search(r'"adb_port"\s*:\s*(\d+)', out)
                if m:
                    port = int(m.group(1))
                    if port > 0:
                        return port
        if "port0" not in spec:
            return None
        return spec["port0"] + index * spec["step"]

    def _wait_emulator_adb(self, port: Optional[int], wait: float,
                           resolver: Optional[Callable[[], Optional[int]]] = None
                           ) -> Optional[str]:
        """Poll until an instance's ADB is connectable *and* Android reports
        ``sys.boot_completed`` == 1, or ``wait`` s elapse.

        ``resolver`` is re-asked while polling: a family whose console only
        publishes the real ADB port once the instance is up (MuMu Global —
        instance 2 lands on 16449, not the derived 16448) cannot be resolved
        before the boot, so every candidate port found along the way is probed.
        Returns the connected ``host:port`` serial, or None. With no port at all
        it degrades to sleeping ``wait`` s to let the emulator boot.
        """
        hosts: List[str] = [f"127.0.0.1:{port}"] if port else []
        if not hosts and resolver is None:
            log_info(f"▶ Waiting {wait:.0f}s for emulator startup (ADB port unknown)")
            self._sleep(wait)
            return None
        end = time.time() + wait
        next_resolve = 0.0
        while time.time() < end and not self._stop.is_set():
            self._pause.wait()
            if resolver is not None and time.time() >= next_resolve:
                next_resolve = time.time() + 5.0
                try:
                    fresh = resolver()
                except Exception:
                    fresh = None
                if fresh:
                    host = f"127.0.0.1:{fresh}"
                    if host not in hosts:
                        hosts.append(host)
            for host in hosts:
                if self._emulator_adb_ready(host):
                    log_success(f"▶ Emulator ready — ADB {host}")
                    return host
            time.sleep(1.0)
        label = ", ".join(hosts) or "?"
        log_warning(f"▶ ADB {label} not found after {wait:.0f}s")
        return None

    def set_emulator_config(self, kind: str, path: str, index: Optional[int] = None) -> None:
        """Point the shared emulator setting (``emulator``) somewhere else — the
        Runner's Settings override. Read by emulator nodes on ``project``.
        ``index`` is the shared instance index; ``None`` keeps the current one."""
        kind = str(kind or "").strip().lower()
        path = str(path or "").strip()
        try:
            idx = max(0, int(float(index))) if index is not None else None
        except (TypeError, ValueError):
            idx = None
        self._emu_cfg["kind"] = kind
        self._emu_cfg["path"] = path
        if idx is not None:
            self._emu_cfg["index"] = idx
        if isinstance(self.flow, dict):
            emu = self.flow.get("emulator")
            if not isinstance(emu, dict):
                emu = self.flow["emulator"] = {}
            emu["kind"] = kind
            emu["path"] = path
            if idx is not None:
                emu["index"] = idx

    def _emulator_path(self, params: Dict[str, Any]) -> str:
        """Resolve the emulator install folder for an emulator node.

        ``pathSrc``:
          - ``project`` — the shared emulator setting (Project / Runner Settings)
          - ``custom``  — the node's own ``path`` field
          - missing     — legacy: shared setting first, else the node's path
        """
        p = params or {}
        src = str(p.get("pathSrc") or "").strip().lower()
        project = str((self._emu_cfg or {}).get("path") or "").strip()
        custom = str(self._resolve_value(p.get("path", "")) or "").strip()
        if src == "custom":
            return custom
        # "project" and legacy (no src) both prefer the shared setting; an empty
        # shared path falls back to the node's own path so old files still run.
        return project or custom

    def _emulator_kind(self, params: Dict[str, Any], default: str = "ldplayer") -> str:
        """Resolve the emulator family for a launch node (see ``_emulator_path``)."""
        p = params or {}
        src = str(p.get("pathSrc") or "").strip().lower()
        custom = str(p.get("emulator") or "").strip().lower()
        project = str((self._emu_cfg or {}).get("kind") or "").strip().lower()
        if src == "custom":
            return custom or default
        return project or custom or default

    def _emulator_index(self, params: Dict[str, Any]) -> int:
        """Resolve the instance index for an emulator node (see ``_emulator_path``).

        ``pathSrc`` == ``custom`` reads the node's own ``index``; ``project``
        (and legacy flows with no source) read the shared emulator setting's
        ``index``, falling back to the node's field so a file saved before the
        project index existed still boots the instance it was built for."""
        p = params or {}
        src = str(p.get("pathSrc") or "").strip().lower()
        project = (self._emu_cfg or {}).get("index")
        raw = p.get("index") if (src == "custom" or project in (None, "")) else project
        try:
            return max(0, int(float(raw if raw not in (None, "") else 0)))
        except (TypeError, ValueError):
            return 0
