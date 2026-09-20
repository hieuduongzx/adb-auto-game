"""Deploy and probe the Macro2k Unity Bridge for Unity games.

The bridge is a generic BepInEx plugin (``vendor/unity_bridge``) that runs
inside a Unity game and performs taps/swipes through Unity's EventSystem on
commands sent over 127.0.0.1 (see ``Win32Controller``'s ``unity_bridge`` input
mode). It comes in two builds: BepInEx 5 for Mono games and BepInEx 6 for
IL2CPP games. This module inspects a game folder, copies the matching BepInEx
pack + plugin into it, and pings a running bridge.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import socket
import struct
from typing import List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
VENDOR_DIR = os.path.join(_PROJECT_ROOT, "vendor", "unity_bridge")
BEPINEX_DIR = os.path.join(VENDOR_DIR, "bepinex5_x64")
PLUGIN_DLL = os.path.join(VENDOR_DIR, "plugin", "Macro2kBridge.dll")
# IL2CPP games: BepInEx 6 (bleeding edge, Unity.IL2CPP; ships its own .NET 6 in dotnet/).
BEPINEX6_DIR = os.path.join(VENDOR_DIR, "bepinex6_il2cpp_x64")
BEPINEX6_VERSION = "6.0.0-be.788"  # keep in sync with the pack in BEPINEX6_DIR
PLUGIN_DLL_IL2CPP = os.path.join(VENDOR_DIR, "plugin_il2cpp", "Macro2kBridge.dll")
PLUGIN_REL = os.path.join("BepInEx", "plugins", "Macro2kBridge", "Macro2kBridge.dll")
DEFAULT_PORT = 17820
# Doorstop loader files shipped at the game root next to the exe.
_DOORSTOP_FILES = ("winhttp.dll", "doorstop_config.ini", ".doorstop_version")

_PE_MACHINE = {0x8664: "x64", 0x014C: "x86", 0xAA64: "arm64"}


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _file_version(path: str) -> str:
    try:
        import win32api
        info = win32api.GetFileVersionInfo(path, "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return ""


def _version_tuple(version: str) -> tuple:
    parts = [int(p) for p in re.findall(r"\d+", version or "")]
    return tuple(parts + [0] * (4 - len(parts)))[:4]


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def vendored_bepinex_version() -> str:
    """Version of the BepInEx 5 pack in vendor/ (e.g. "5.4.23.5")."""
    return _file_version(os.path.join(BEPINEX_DIR, "BepInEx", "core", "BepInEx.dll")) or "5.x"


def _same_file(a: str, b: str) -> bool:
    try:
        return _sha256(a) == _sha256(b)
    except OSError:
        return False


def inspect_game(exe_path: str) -> dict:
    """Describe a game install as seen by the deployer.

    ``problems`` lists everything that blocks a deploy; it is empty when
    :func:`deploy` can proceed."""
    info = {
        "exe": exe_path or "", "gameDir": "", "unity": False, "backend": "", "arch": "",
        "bepinex": False, "bepinexVersion": "", "bepinexOutdated": False,
        "vendorBepinexVersion": vendored_bepinex_version(),
        "doorstop": False, "doorstopVersion": "",
        "pluginInstalled": False, "pluginCurrent": False, "problems": [],
    }
    problems: List[str] = info["problems"]
    if not exe_path or not os.path.isfile(exe_path):
        problems.append("Không tìm thấy file exe của game.")
        return info

    game_dir = os.path.dirname(os.path.abspath(exe_path))
    info["gameDir"] = game_dir
    data_dir = os.path.join(game_dir, os.path.splitext(os.path.basename(exe_path))[0] + "_Data")
    player = os.path.join(game_dir, "UnityPlayer.dll")

    info["unity"] = os.path.isdir(data_dir) and (
        os.path.isfile(player)
        or os.path.isdir(os.path.join(data_dir, "Managed"))
        or os.path.isdir(os.path.join(data_dir, "il2cpp_data")))
    if not info["unity"]:
        problems.append("Không phải game Unity (thiếu thư mục <tên exe>_Data bên cạnh exe). "
                        "Hãy chọn đúng exe của game, không phải launcher.")
        return info

    il2cpp = os.path.isfile(os.path.join(game_dir, "GameAssembly.dll"))         or os.path.isdir(os.path.join(data_dir, "il2cpp_data"))
    info["backend"] = "IL2CPP" if il2cpp else "Mono"
    info["flavor"] = "il2cpp" if il2cpp else "mono"
    bundled_bepinex_dir = BEPINEX6_DIR if il2cpp else BEPINEX_DIR
    bundled_plugin = PLUGIN_DLL_IL2CPP if il2cpp else PLUGIN_DLL
    if il2cpp:
        info["vendorBepinexVersion"] = BEPINEX6_VERSION

    info["arch"] = _pe_arch(player if os.path.isfile(player) else exe_path)
    if info["arch"] and info["arch"] != "x64":
        problems.append(f"Game {info['arch']} — bản BepInEx đi kèm chỉ dành cho x64.")

    core = os.path.join(game_dir, "BepInEx", "core")
    has_core6 = os.path.isfile(os.path.join(core, "BepInEx.Core.dll"))
    has_core5 = os.path.isfile(os.path.join(core, "BepInEx.dll"))
    # The bundled Doorstop 4 renamed its config keys and env vars; it only pairs
    # with the bundled BepInEx core, not an older one.
    doorstop_pairs = False
    if il2cpp:
        loader = os.path.join(core, "BepInEx.Unity.IL2CPP.dll")
        if has_core6 and os.path.isfile(loader):
            info["bepinex"] = True
            doorstop_pairs = _same_file(loader, os.path.join(BEPINEX6_DIR, "BepInEx", "core", "BepInEx.Unity.IL2CPP.dll"))
            info["bepinexVersion"] = BEPINEX6_VERSION if doorstop_pairs else "6.x"
            info["bepinexOutdated"] = not doorstop_pairs
        elif has_core6:
            problems.append("Game đang có BepInEx 6 bản Mono (thiếu BepInEx.Unity.IL2CPP.dll) — không dùng được "
                            "cho game IL2CPP, hãy gỡ hoặc thay bằng bản Unity.IL2CPP.")
        elif has_core5:
            problems.append("Game IL2CPP đang có BepInEx 5 (chỉ chạy được game Mono) — hãy gỡ BepInEx cũ "
                            "rồi triển khai lại để cài BepInEx 6.")
    elif has_core6:
        problems.append("Game đang dùng BepInEx 6 — plugin Unity Bridge cho game Mono viết cho BepInEx 5.")
    elif has_core5:
        info["bepinex"] = True
        info["bepinexVersion"] = _file_version(os.path.join(core, "BepInEx.dll")) or "5.x"
        info["bepinexOutdated"] = _version_tuple(info["bepinexVersion"]) < _version_tuple(info["vendorBepinexVersion"])
        doorstop_pairs = info["bepinexVersion"] == info["vendorBepinexVersion"]

    doorstop = [n for n in ("winhttp.dll", "version.dll") if os.path.isfile(os.path.join(game_dir, n))]
    info["doorstop"] = bool(doorstop)
    if doorstop:
        # Doorstop 4 (BepInEx 5.4.23+) writes .doorstop_version; 3.x has none.
        info["doorstopVersion"] = _read_text(os.path.join(game_dir, ".doorstop_version")) or "3.x"
    if doorstop and not (has_core5 or has_core6):
        problems.append(f"Thư mục game đã có {doorstop[0]} nhưng không có BepInEx "
                        "(có thể là mod loader khác) — không ghi đè.")
    if info["bepinex"] and not doorstop and not doorstop_pairs:
        problems.append(f"BepInEx {info['bepinexVersion']} có sẵn nhưng thiếu doorstop (winhttp.dll). "
                        f"Doorstop đi kèm chỉ khớp BepInEx {info['vendorBepinexVersion']} — "
                        "hãy cài lại BepInEx bản đó đè lên thư mục game.")

    installed = os.path.join(game_dir, PLUGIN_REL)
    info["pluginInstalled"] = os.path.isfile(installed)
    if not os.path.isfile(bundled_plugin):
        problems.append(f"Thiếu vendor/unity_bridge/{'plugin_il2cpp' if il2cpp else 'plugin'}/Macro2kBridge.dll — "
                        "build plugin trước.")
    elif info["pluginInstalled"]:
        info["pluginCurrent"] = _same_file(installed, bundled_plugin)
    return info


def _copy_tree(src: str, dst: str, overwrite: bool) -> int:
    copied = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_dir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_dir, exist_ok=True)
        for name in files:
            target = os.path.join(target_dir, name)
            if not overwrite and os.path.exists(target):
                continue
            shutil.copy2(os.path.join(root, name), target)
            copied += 1
    return copied


def deploy(exe_path: str) -> dict:
    """Install BepInEx (when absent) and the bridge plugin into a game folder.

    Mono games get BepInEx 5 + the Mono plugin, IL2CPP games BepInEx 6 + the
    IL2CPP plugin. Existing BepInEx installs, configs and other plugins are
    left untouched."""
    info = inspect_game(exe_path)
    if info["problems"]:
        return {"ok": False, "error": " ".join(info["problems"]), **info}

    il2cpp = info["flavor"] == "il2cpp"
    pack_dir = BEPINEX6_DIR if il2cpp else BEPINEX_DIR
    plugin_dll = PLUGIN_DLL_IL2CPP if il2cpp else PLUGIN_DLL
    game_dir = info["gameDir"]
    actions: List[str] = []
    try:
        if not info["bepinex"]:
            _copy_tree(pack_dir, game_dir, overwrite=False)
            actions.append(f"Cài BepInEx {info['vendorBepinexVersion']} x64")
        elif not info["doorstop"]:
            # inspect_game only lets this through when the game's BepInEx
            # matches the bundled one, so the bundled Doorstop pairs with it.
            for name in _DOORSTOP_FILES:
                target = os.path.join(game_dir, name)
                if not os.path.exists(target):
                    shutil.copy2(os.path.join(pack_dir, name), target)
            if il2cpp:  # Doorstop's [Il2Cpp] section points at the bundled .NET 6 runtime
                _copy_tree(os.path.join(pack_dir, "dotnet"), os.path.join(game_dir, "dotnet"), overwrite=False)
            actions.append("Bổ sung doorstop (winhttp.dll) cho BepInEx có sẵn")

        target = os.path.join(game_dir, PLUGIN_REL)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(plugin_dll, target)
        actions.append("Cập nhật Macro2kBridge.dll" if info["pluginInstalled"] else "Cài Macro2kBridge.dll")
    except PermissionError as exc:
        return {"ok": False, "error": f"Không ghi được vào thư mục game ({exc}). "
                                      "Tắt game hoặc chạy Macro2k với quyền Administrator rồi thử lại.",
                "actions": actions, **info}
    except OSError as exc:
        return {"ok": False, "error": f"Lỗi copy file: {exc}", "actions": actions, **info}

    return {"ok": True, "actions": actions, **inspect_game(exe_path)}


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
