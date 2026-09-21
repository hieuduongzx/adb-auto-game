"""Deploy and probe the Macro2k Unity Bridge for Unity games.

The bridge runs inside a Unity game and performs taps/swipes through Unity's
EventSystem on commands sent over 127.0.0.1 (see ``Win32Controller``'s
``unity_bridge`` input mode; protocol in ``vendor/unity_bridge/README.md``).
No BepInEx: Macro2kInjector loads a DLL straight into the running process and
nothing is copied into the game folder. Mono games get a managed DLL loaded
through the game's own Mono embedding API; IL2CPP games (no managed runtime to
load an assembly into) get a native DLL loaded the classic
CreateRemoteThread(LoadLibraryW) way, and it talks to the game through the
il2cpp_* C API that GameAssembly.dll exports. This module inspects a game
folder, injects the matching build into the running process and pings a
running bridge.
"""
from __future__ import annotations

import csv
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from typing import List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _vendor_dir() -> str:
    """Where the injector + plugin DLLs live: private (bundled into PyInstaller's
    ``_internal``/``_macro2k``) when a packaged Runner ships them there — see
    ``packaging/build_runner.py``'s ``_copy_vendor`` — else the app's external
    ``vendor/`` (a full Designer/Hub build, or running from source; both keep
    every other vendor tool — adb, scrcpy — external, so this is the fallback
    rather than the first choice)."""
    try:
        from src.utils import app_dir, bundle_dir
    except Exception:
        return os.path.join(_PROJECT_ROOT, "vendor", "unity_bridge")
    private = os.path.join(bundle_dir(), "vendor", "unity_bridge")
    if os.path.isdir(private):
        return private
    return os.path.join(app_dir(), "vendor", "unity_bridge")


VENDOR_DIR = _vendor_dir()
INJECTOR_EXE = os.path.join(VENDOR_DIR, "injector", "Macro2kInjector.exe")
# Mono games: a managed DLL, loaded through the Mono embedding API (mono_thread_attach,
# mono_assembly_load_from_full, ...) and started by calling Loader.Load().
PLUGIN_DLL_MONO = os.path.join(VENDOR_DIR, "plugin_inject", "Macro2kBridge.Inject.dll")
INJECT_ENTRY = ("Macro2k.UnityBridge.Inject", "Loader", "Load")
# IL2CPP games: a native DLL, loaded with LoadLibraryW; its DllMain does the rest.
PLUGIN_DLL_IL2CPP = os.path.join(VENDOR_DIR, "plugin_il2cpp", "Macro2kBridge.Il2Cpp.dll")
INJECT_LOG = os.path.join(tempfile.gettempdir(), "Macro2kBridge.log")
INJECT_PORT_FILE = os.path.join(tempfile.gettempdir(), "Macro2kBridge.port")
DEFAULT_PORT = 17820

_PE_MACHINE = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}


def _pe_arch(path: str) -> str:
    """Machine type from a PE header ("x64" / "x86" / "arm64" / "")."""
    try:
        with open(path, "rb") as fh:
            if fh.read(2) != b"MZ":
                return ""
            fh.seek(0x3C)
            (pe_offset,) = struct.unpack("<I", fh.read(4))
            fh.seek(pe_offset)
            if fh.read(4) != b"PE\0\0":
                return ""
            (machine,) = struct.unpack("<H", fh.read(2))
            return _PE_MACHINE.get(machine, hex(machine))
    except OSError:
        return ""


def _unity_data_dir(game_dir: str, exe_path: str) -> str:
    """Return the Unity data folder, including games that rename it to Data."""
    standard = os.path.join(
        game_dir, os.path.splitext(os.path.basename(exe_path))[0] + "_Data"
    )
    candidates = (standard, os.path.join(game_dir, "Data"))
    for path in candidates:
        if (os.path.isfile(os.path.join(path, "globalgamemanagers"))
                and (os.path.isdir(os.path.join(path, "Managed"))
                     or os.path.isdir(os.path.join(path, "il2cpp_data")))):
            return path
    return standard


# Files older Macro2k versions put into a game when it still used BepInEx.
def _legacy_bepinex_paths(game_dir: str) -> List[str]:
    candidates = (
        os.path.join(game_dir, "BepInEx"),
        os.path.join(game_dir, "winhttp.dll"),
        os.path.join(game_dir, "doorstop_config.ini"),
        os.path.join(game_dir, ".doorstop_version"),
        os.path.join(game_dir, "dotnet"),
    )
    return [path for path in candidates if os.path.exists(path)]


def inspect_game(exe_path: str) -> dict:
    """Describe a game install as seen by the deployer.

    ``problems`` lists everything that blocks a deploy; it is empty when
    :func:`deploy` can proceed."""
    info = {
        "exe": exe_path or "", "gameDir": "", "dataDir": "", "unity": False,
        "backend": "", "flavor": "", "arch": "", "legacyBepinex": False,
        "problems": [],
    }
    problems: List[str] = info["problems"]
    if not exe_path or not os.path.isfile(exe_path):
        problems.append("The game executable was not found.")
        return info

    game_dir = os.path.dirname(os.path.abspath(exe_path))
    info["gameDir"] = game_dir
    data_dir = _unity_data_dir(game_dir, exe_path)
    info["dataDir"] = data_dir
    player = os.path.join(game_dir, "UnityPlayer.dll")

    info["unity"] = os.path.isdir(data_dir) and (
        os.path.isfile(player)
        or os.path.isdir(os.path.join(data_dir, "Managed"))
        or os.path.isdir(os.path.join(data_dir, "il2cpp_data")))
    if not info["unity"]:
        problems.append("This is not a Unity game (the <executable name>_Data folder is missing). "
                        "Select the game executable, not its launcher.")
        return info

    il2cpp = (os.path.isfile(os.path.join(game_dir, "GameAssembly.dll"))
              or os.path.isdir(os.path.join(data_dir, "il2cpp_data")))
    info["backend"] = "IL2CPP" if il2cpp else "Mono"
    info["flavor"] = "il2cpp" if il2cpp else "mono"
    info["arch"] = _pe_arch(player if os.path.isfile(player) else exe_path)
    if info["arch"] and info["arch"] != "x64":
        problems.append(f"The game is {info['arch']}; the bridge supports x64 only.")

    info["legacyBepinex"] = bool(_legacy_bepinex_paths(game_dir))
    plugin_dll = PLUGIN_DLL_IL2CPP if il2cpp else PLUGIN_DLL_MONO
    plugin_rel = "plugin_il2cpp/Macro2kBridge.Il2Cpp.dll" if il2cpp else "plugin_inject/Macro2kBridge.Inject.dll"
    if not os.path.isfile(plugin_dll):
        problems.append(f"vendor/unity_bridge/{plugin_rel} is missing. Build the plugin first.")
    if not os.path.isfile(INJECTOR_EXE):
        problems.append("vendor/unity_bridge/injector/Macro2kInjector.exe is missing. Build the injector first.")
    return info


def find_game_pids(exe_path: str) -> List[int]:
    """PIDs of running processes with the game executable's file name."""
    name = os.path.basename(exe_path or "")
    if not name:
        return []
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:
        return []
    return [int(row[1]) for row in csv.reader(out.splitlines())
            if len(row) > 1 and row[0].lower() == name.lower() and row[1].isdigit()]


def _run_injector(args: List[str]) -> dict:
    try:
        proc = subprocess.run([INJECTOR_EXE, *args], capture_output=True, text=True, timeout=60,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"Cannot run the injector: {exc}"}
    line = (proc.stdout or "").strip().splitlines()[-1:] or [""]
    if proc.returncode != 0 or not line[0].startswith("ok"):
        detail = line[0][4:] if line[0].startswith("err ") else (proc.stderr or line[0] or "unknown error").strip()
        return {"ok": False, "error": f"Injection failed: {detail}. See {INJECT_LOG}."}
    return {"ok": True}


def inject(pid: int, il2cpp: bool, port: int = DEFAULT_PORT, wait: float = 10.0) -> dict:
    """Load the bridge DLL into a running game and wait until it answers ping.

    Returns {"ok": True, "reply": ...} or {"ok": False, "error": ...}."""
    plugin_dll = PLUGIN_DLL_IL2CPP if il2cpp else PLUGIN_DLL_MONO
    for path, what in ((INJECTOR_EXE, "injector"), (plugin_dll, "plugin")):
        if not os.path.isfile(path):
            return {"ok": False, "error": f"The Unity Bridge {what} is missing ({path})."}
    try:
        with open(INJECT_PORT_FILE, "w", encoding="ascii") as fh:  # read by the bridge inside the game
            fh.write(str(int(port)))
    except OSError:
        pass
    if il2cpp:
        res = _run_injector(["loadlibrary", str(int(pid)), plugin_dll])
    else:
        ns, cls, method = INJECT_ENTRY
        res = _run_injector(["inject", str(int(pid)), plugin_dll, ns, cls, method])
    if not res["ok"]:
        return res
    deadline = time.time() + wait
    while time.time() < deadline:  # the bridge starts on the game's next frame(s)
        reply = ping(port)
        if reply and reply.startswith("ok"):
            return {"ok": True, "reply": reply}
        time.sleep(0.25)
    return {"ok": False, "error": f"The DLL was loaded but the bridge did not answer on port {port}. See {INJECT_LOG}."}


def ensure_injected(exe_path: str, port: int = DEFAULT_PORT, pid: Optional[int] = None) -> dict:
    """Make sure the bridge runs inside the game (see :func:`inject`)."""
    reply = ping(port)
    if reply and reply.startswith("ok"):
        return {"ok": True, "already": True, "reply": reply}
    info = inspect_game(exe_path)
    if info["problems"]:
        return {"ok": False, "error": " ".join(info["problems"])}
    pids = [pid] if pid else find_game_pids(exe_path)
    if not pids:
        return {"ok": False, "error": "The game is not running."}
    return inject(pids[0], info["flavor"] == "il2cpp", port)


def deploy(exe_path: str) -> dict:
    """Inject the bridge into a running game; nothing is ever copied into the game folder.

    Leftover BepInEx files from older Macro2k versions are removed first (they can
    make BepInEx games detect a "modded" install even though Macro2k no longer uses it;
    they are never touched if removal fails, e.g. the game is holding them open)."""
    info = inspect_game(exe_path)
    if info["problems"]:
        return {"ok": False, "error": " ".join(info["problems"]), **info}

    actions = ["Unity Bridge is injected into the running game; nothing is copied to the game folder"]
    for path in _legacy_bepinex_paths(info["gameDir"]):
        try:
            shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            actions.append(f"Removed the old BepInEx file {os.path.relpath(path, info['gameDir'])}")
        except OSError as exc:
            actions.append(f"Could not remove {path}: {exc}")

    res = ensure_injected(exe_path)
    if res.get("ok"):
        actions.append("Already running in the game" if res.get("already") else "Injected into the running game")
    else:
        actions.append(f"Not injected yet: {res.get('error')} Macro2k injects it when a workflow attaches to the game.")
    return {"ok": True, "actions": actions, "injected": bool(res.get("ok")), **inspect_game(exe_path)}


def ping(port: int = DEFAULT_PORT, timeout: float = 0.6) -> Optional[str]:
    """Reply of a running bridge to ``ping`` (e.g. "ok Macro2kBridge 1.0.0 1920 1080"), or None."""
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout + 5.0)  # main thread may be busy loading
            sock.sendall(b"ping\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buf += chunk
        return buf.decode("utf-8", "replace").strip() or None
    except OSError:
        return None


def status(exe_path: str = "", port: int = DEFAULT_PORT) -> dict:
    """:func:`inspect_game` plus whether a bridge currently answers on ``port``."""
    info = inspect_game(exe_path) if exe_path else {"exe": "", "problems": []}
    reply = ping(port)
    info["port"] = int(port)
    info["bridge"] = reply or ""
    info["bridgeRunning"] = bool(reply and reply.startswith("ok"))
    return info
