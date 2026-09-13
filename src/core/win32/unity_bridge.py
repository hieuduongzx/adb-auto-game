"""Deploy and probe the Macro2k Unity Bridge for Unity games.

The bridge is a generic BepInEx 5 plugin (``vendor/unity_bridge``) that runs
inside a Mono Unity game and performs taps/swipes through Unity's EventSystem
on commands sent over 127.0.0.1 (see ``Win32Controller``'s ``unity_bridge``
input mode). This module inspects a game folder, copies BepInEx + the plugin
into it, and pings a running bridge.
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

    if os.path.isfile(os.path.join(game_dir, "GameAssembly.dll")) \
            or os.path.isdir(os.path.join(data_dir, "il2cpp_data")):
        info["backend"] = "IL2CPP"
        problems.append("Game build IL2CPP — Unity Bridge hiện chỉ hỗ trợ game Mono (BepInEx 5).")
    else:
        info["backend"] = "Mono"

    info["arch"] = _pe_arch(player if os.path.isfile(player) else exe_path)
    if info["arch"] and info["arch"] != "x64":
        problems.append(f"Game {info['arch']} — bản BepInEx đi kèm chỉ dành cho x64.")

    core = os.path.join(game_dir, "BepInEx", "core")
    bepinex5 = False
    if os.path.isfile(os.path.join(core, "BepInEx.Core.dll")):
        info["bepinex"] = True
        info["bepinexVersion"] = _file_version(os.path.join(core, "BepInEx.Core.dll")) or "6.x"
        problems.append("Game đang dùng BepInEx 6 — plugin Unity Bridge viết cho BepInEx 5.")
    elif os.path.isfile(os.path.join(core, "BepInEx.dll")):
        bepinex5 = True
        info["bepinex"] = True
        info["bepinexVersion"] = _file_version(os.path.join(core, "BepInEx.dll")) or "5.x"
        info["bepinexOutdated"] = _version_tuple(info["bepinexVersion"]) < _version_tuple(info["vendorBepinexVersion"])

    doorstop = [n for n in ("winhttp.dll", "version.dll") if os.path.isfile(os.path.join(game_dir, n))]
    info["doorstop"] = bool(doorstop)
    if doorstop:
        # Doorstop 4 (BepInEx 5.4.23+) writes .doorstop_version; 3.x has none.
        info["doorstopVersion"] = _read_text(os.path.join(game_dir, ".doorstop_version")) or "3.x"
    if doorstop and not info["bepinex"]:
        problems.append(f"Thư mục game đã có {doorstop[0]} nhưng không có BepInEx "
                        "(có thể là mod loader khác) — không ghi đè.")
    if bepinex5 and not doorstop and info["bepinexVersion"] != info["vendorBepinexVersion"]:
        # The bundled Doorstop 4 renamed its config keys and env vars; it only
        # pairs with the bundled BepInEx core, not an older 5.4.22 one.
        problems.append(f"BepInEx {info['bepinexVersion']} có sẵn nhưng thiếu doorstop (winhttp.dll). "
                        f"Doorstop đi kèm chỉ khớp BepInEx {info['vendorBepinexVersion']} — "
                        "hãy cài lại BepInEx bản đó đè lên thư mục game.")

    installed = os.path.join(game_dir, PLUGIN_REL)
    info["pluginInstalled"] = os.path.isfile(installed)
    if not os.path.isfile(PLUGIN_DLL):
        problems.append("Thiếu vendor/unity_bridge/plugin/Macro2kBridge.dll — build plugin trước.")
    elif info["pluginInstalled"]:
        try:
            info["pluginCurrent"] = _sha256(installed) == _sha256(PLUGIN_DLL)
        except OSError:
            info["pluginCurrent"] = False
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
    """Install BepInEx 5 (when absent) and the bridge plugin into a game folder.

    Existing BepInEx installs, configs and other plugins are left untouched."""
    info = inspect_game(exe_path)
    if info["problems"]:
        return {"ok": False, "error": " ".join(info["problems"]), **info}

    game_dir = info["gameDir"]
    actions: List[str] = []
    try:
        if not info["bepinex"]:
            _copy_tree(BEPINEX_DIR, game_dir, overwrite=False)
            actions.append(f"Cài BepInEx {info['vendorBepinexVersion']} x64")
        elif not info["doorstop"]:
            # inspect_game only lets this through when the game's BepInEx
            # matches the bundled one, so the bundled Doorstop pairs with it.
            for name in _DOORSTOP_FILES:
                target = os.path.join(game_dir, name)
                if not os.path.exists(target):
                    shutil.copy2(os.path.join(BEPINEX_DIR, name), target)
            actions.append("Bổ sung doorstop (winhttp.dll) cho BepInEx có sẵn")

        target = os.path.join(game_dir, PLUGIN_REL)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(PLUGIN_DLL, target)
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
