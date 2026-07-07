"""Win32 DLL injection — used to load the Unity speed-hack ``cheat.dll`` into a
running game process.

For ADB (Android) projects the speed hack stays on Frida (``FridaSpeedhackManager``).
For **Win32 + Unity** projects there is no Frida/ADB to talk to, so instead we
inject ``vendor/cheat.dll`` — a native x64 overlay that detects the Unity backend
(Mono / IL2CPP) and hooks ``UnityEngine.Time::set_timeScale``. The DLL reads its
speed from ``cheat_config.ini`` (``[SpeedHack] Enabled=/Speed=``) sitting next to
the game executable, so we drop that file before injecting to preseed the speed.

Injection is the classic ``CreateRemoteThread`` + ``LoadLibraryW`` technique via
raw ctypes (no extra dependency). Constraints, enforced with clear errors:

* ``cheat.dll`` is x64, so the **target process must be 64-bit** and this Python
  host must be 64-bit too (a 32-bit host cannot ``CreateRemoteThread`` into a
  64-bit target across the WOW64 barrier).
* The tool must run at an integrity level >= the game's (same UIPI rule as
  input); injecting into an elevated game from a non-elevated tool fails with
  ``Access is denied``.
"""
from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from typing import List, Optional

from src.utils import log_error, log_info, log_success, log_warning

# ── Win32 constants ───────────────────────────────────────────────────────────
_PROCESS_CREATE_THREAD = 0x0002
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_PROCESS_VM_OPERATION = 0x0008
_PROCESS_VM_WRITE = 0x0020
_PROCESS_VM_READ = 0x0010
_MEM_COMMIT = 0x1000
_MEM_RESERVE = 0x2000
_MEM_RELEASE = 0x8000
_PAGE_READWRITE = 0x04
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0x0

# Module-name markers that identify a Unity game and its scripting backend.
_UNITY_MARKER = "unityplayer.dll"
_IL2CPP_MARKER = "gameassembly.dll"
_MONO_MARKERS = ("mono-2.0-bdwgc.dll", "mono-2.0-sgen.dll", "mono-2.0.dll", "mono.dll")


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    return k


def _psapi():
    # Module enumeration lives in psapi on older Windows, kernel32 on newer; the
    # psapi shim forwards either way, so load it directly for portability.
    return ctypes.WinDLL("psapi", use_last_error=True)


def python_is_64bit() -> bool:
    return struct.calcsize("P") == 8


def _win_err(where: str) -> None:
    code = ctypes.get_last_error()
    msg = ctypes.FormatError(code).strip() if code else ""
    if code == 5:
        log_error(
            f"[cheat] {where} bị chặn (Access is denied, err 5) — game chạy quyền "
            "cao hơn tool. Mở lại tool bằng 'Run as Administrator'."
        )
    else:
        log_error(f"[cheat] {where} lỗi (err {code}): {msg}")


def pid_from_hwnd(hwnd: int) -> Optional[int]:
    """Owning process id of a top-level window."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(pid.value) or None
    except Exception as exc:  # pragma: no cover
        log_warning(f"[cheat] không lấy được PID từ cửa sổ: {exc}")
        return None


def _open_process(access: int, pid: int):
    k = _kernel32()
    # HANDLE is pointer-sized; without a restype ctypes truncates it to 32-bit.
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(access, False, pid)
    return h or None


def process_is_64bit(pid: int) -> Optional[bool]:
    """True if the target process is 64-bit, False if 32-bit (WOW64), None on error.

    On a 64-bit OS ``IsWow64Process`` is False for native 64-bit processes and
    True for 32-bit ones. (This tool only supports 64-bit Windows, which is the
    only place a modern Unity game + x64 cheat.dll runs.)
    """
    k = _kernel32()
    h = _open_process(_PROCESS_QUERY_LIMITED_INFORMATION, pid)
    if not h:
        h = _open_process(_PROCESS_QUERY_INFORMATION, pid)
    if not h:
        _win_err("OpenProcess (arch check)")
        return None
    try:
        k.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        k.IsWow64Process.restype = wintypes.BOOL
        wow64 = wintypes.BOOL(0)
        if not k.IsWow64Process(h, ctypes.byref(wow64)):
            return None
        return not bool(wow64.value)
    finally:
        k.CloseHandle(h)


def list_modules(pid: int) -> List[str]:
    """Lower-cased base names of every module loaded in the target process."""
    k = _kernel32()
    ps = _psapi()
    # HMODULE / handle args are pointer-sized; without explicit argtypes ctypes
    # narrows them to 32-bit int and overflows on real 64-bit module handles.
    ps.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
    ]
    ps.EnumProcessModulesEx.restype = wintypes.BOOL
    ps.GetModuleBaseNameW.argtypes = [
        wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD,
    ]
    ps.GetModuleBaseNameW.restype = wintypes.DWORD
    h = _open_process(_PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, pid)
    if not h:
        h = _open_process(_PROCESS_QUERY_LIMITED_INFORMATION | _PROCESS_VM_READ, pid)
    if not h:
        _win_err("OpenProcess (module list)")
        return []
    try:
        arr_type = wintypes.HMODULE * 1024
        mods = arr_type()
        needed = wintypes.DWORD(0)
        # LIST_MODULES_ALL = 0x03 — include both 32- and 64-bit modules.
        if not ps.EnumProcessModulesEx(
            h, mods, ctypes.sizeof(mods), ctypes.byref(needed), 0x03
        ):
            _win_err("EnumProcessModulesEx")
            return []
        count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), 1024)
        names: List[str] = []
        buf = ctypes.create_unicode_buffer(260)
        for i in range(count):
            if ps.GetModuleBaseNameW(h, mods[i], buf, 260):
                names.append(buf.value.lower())
        return names
    finally:
        k.CloseHandle(h)


def detect_unity_backend(pid: int) -> Optional[str]:
    """Return ``"il2cpp"`` / ``"mono"`` if the process is a Unity game, else None."""
    mods = list_modules(pid)
    if not mods:
        return None
    is_unity = _UNITY_MARKER in mods
    if _IL2CPP_MARKER in mods:
        return "il2cpp"
    if any(m in mods for m in _MONO_MARKERS):
        return "mono"
    # UnityPlayer with no scripting DLL yet visible (still starting up) — treat
    # as Unity of unknown backend rather than "not Unity".
    return "unknown" if is_unity else None


def module_loaded(pid: int, dll_name: str) -> bool:
    return dll_name.lower() in list_modules(pid)


def process_image_path(pid: int) -> Optional[str]:
    """Full path to the target's executable (for placing ``cheat_config.ini``)."""
    k = _kernel32()
    h = _open_process(_PROCESS_QUERY_LIMITED_INFORMATION, pid)
    if not h:
        h = _open_process(_PROCESS_QUERY_INFORMATION, pid)
    if not h:
        return None
    try:
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
        ]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k.CloseHandle(h)


def write_cheat_config(dll_dir: str, speed: float, enabled: bool = True) -> Optional[str]:
    """Write ``cheat_config.ini`` next to ``cheat.dll`` so the DLL loads the speed.

    ``cheat.dll`` resolves its config path from its **own module path**
    (``Config::GetConfigPath`` → ``GetModuleFileNameA(hDll)``), i.e. the
    directory the DLL was loaded from — which is ``vendor/`` when injected via
    ``LoadLibraryW`` with an absolute path. Writing it next to the game exe has
    no effect; it must sit next to the DLL.

    Mirrors the key/section layout baked into cheat.dll: ``[Settings]`` with
    ``AutoSaveConfig`` and ``[SpeedHack]`` with ``Enabled`` / ``Speed``. Returns
    the path written, or None on failure.
    """
    try:
        path = os.path.join(dll_dir, "cheat_config.ini")
        try:
            scale = float(speed)
        except (TypeError, ValueError):
            scale = 2.0
        content = (
            "[Settings]\n"
            "AutoSaveConfig=1\n"
            "\n"
            "[SpeedHack]\n"
            f"Enabled={1 if enabled else 0}\n"
            f"Speed={scale:g}\n"
        )
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return path
    except Exception as exc:
        log_warning(f"[cheat] không ghi được cheat_config.ini: {exc}")
        return None


def inject_dll(pid: int, dll_path: str) -> bool:
    """Load ``dll_path`` into process ``pid`` via CreateRemoteThread+LoadLibraryW."""
    dll_path = os.path.abspath(dll_path)
    if not os.path.isfile(dll_path):
        log_error(f"[cheat] không tìm thấy DLL: {dll_path}")
        return False

    k = _kernel32()
    # Prototype the calls whose args/returns are pointer-sized so ctypes doesn't
    # truncate 64-bit handles/addresses to 32 bits.
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.VirtualAllocEx.restype = wintypes.LPVOID
    k.VirtualAllocEx.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD,
    ]
    k.WriteProcessMemory.restype = wintypes.BOOL
    k.WriteProcessMemory.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID, ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    k.GetModuleHandleW.restype = wintypes.HMODULE
    k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    k.GetProcAddress.restype = wintypes.LPVOID
    k.GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
    k.CreateRemoteThread.restype = wintypes.HANDLE
    k.CreateRemoteThread.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID,
        wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID,
    ]
    k.VirtualFreeEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.GetExitCodeThread.restype = wintypes.BOOL
    k.GetExitCodeThread.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]

    access = (
        _PROCESS_CREATE_THREAD | _PROCESS_QUERY_INFORMATION
        | _PROCESS_VM_OPERATION | _PROCESS_VM_WRITE | _PROCESS_VM_READ
    )
    h = k.OpenProcess(access, False, pid)
    if not h:
        _win_err("OpenProcess (inject)")
        return False

    remote_mem = None
    thread = None
    try:
        # LoadLibraryW lives in kernel32, mapped at the same address in every
        # process this session, so our local address is valid in the target.
        load_lib = k.GetProcAddress(k.GetModuleHandleW("kernel32.dll"), b"LoadLibraryW")
        if not load_lib:
            _win_err("GetProcAddress(LoadLibraryW)")
            return False

        path_bytes = ctypes.create_unicode_buffer(dll_path)
        size = ctypes.sizeof(path_bytes)
        remote_mem = k.VirtualAllocEx(h, None, size, _MEM_COMMIT | _MEM_RESERVE, _PAGE_READWRITE)
        if not remote_mem:
            _win_err("VirtualAllocEx")
            return False
        written = ctypes.c_size_t(0)
        if not k.WriteProcessMemory(h, remote_mem, path_bytes, size, ctypes.byref(written)):
            _win_err("WriteProcessMemory")
            return False

        thread = k.CreateRemoteThread(h, None, 0, load_lib, remote_mem, 0, None)
        if not thread:
            _win_err("CreateRemoteThread")
            return False

        # Wait for LoadLibraryW to return; its exit code is the loaded HMODULE
        # (low 32 bits) — 0 means the DLL failed to load in the target.
        if k.WaitForSingleObject(thread, 10000) != _WAIT_OBJECT_0:
            log_warning("[cheat] CreateRemoteThread không kết thúc trong 10s")
            return False
        exit_code = wintypes.DWORD(0)
        k.GetExitCodeThread(thread, ctypes.byref(exit_code))
        ec = exit_code.value
        # A successful LoadLibraryW returns the HMODULE (low 32 bits, non-zero).
        # If DllMain raises an unhandled exception the thread exits with the
        # exception code instead — NT status codes live at >= 0xC0000000
        # (e.g. 0xC0000005 = access violation), which never collides with a real
        # user-space HMODULE. Distinguish the two so a crashed DllMain isn't
        # mistaken for a successful load.
        if ec == 0:
            log_error(
                "[cheat] LoadLibraryW trả về 0 — DLL không nạp được vào game "
                "(sai kiến trúc, thiếu dependency, hoặc anti-cheat chặn)."
            )
            return False
        if ec == 0xFFFFFFFF:
            log_error(
                "[cheat] remote thread bị kill (exit code 0xFFFFFFFF) — "
                "anti-cheat đã chặn CreateRemoteThread. Game có thể có "
                "mhyprot/ACE/EAC. Thử: inject trước khi game chạy (dùng "
                "CREATE_SUSPENDED) hoặc inject vào 1 process khác không có anti-cheat."
            )
            return False
        if ec >= 0xC0000000:
            log_error(
                f"[cheat] DllMain crash trong game (exit code 0x{ec:08X} = NT "
                f"status) — DLL nạp xong nhưng DllMain lỗi. Thường do anti-cheat "
                f"can thiệp hoặc conflict với hook có sẵn."
            )
            return False
        log_info(f"[cheat] LoadLibraryW exit code 0x{ec:08X} (HMODULE thấp 32-bit)")
        return True
    finally:
        if remote_mem:
            k.VirtualFreeEx(h, remote_mem, 0, _MEM_RELEASE)
        if thread:
            k.CloseHandle(thread)
        k.CloseHandle(h)


# ── STARTUPINFOW / PROCESS_INFORMATION for CreateProcessW ─────────────────────
class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPBYTE),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


# ── Constants for launch_and_inject ───────────────────────────────────────────
_CREATE_SUSPENDED = 0x00000004
_NORMAL_PRIORITY_CLASS = 0x00000020


def launch_and_inject(game_path: str, dll_path: str, speed: Optional[float] = None) -> dict:
    """Start ``game_path`` suspended, inject ``dll_path`` before it runs, then resume.

    This is the technique GameHook uses (``main.cpp`` in base_GameHook): many
    anti-cheats (mhyprot/ACE/EAC) hook ``CreateRemoteThread``/``LoadLibrary``
    *after* they initialise, which happens once the main thread runs. By
    creating the process suspended we inject *before* the anti-cheat is alive,
    so the thread isn't killed and the DLL maps cleanly.

    The config must be written *before* this call (or pass ``speed`` and it
    writes it to the DLL's directory).

    Returns ``{"ok": bool, "reason": str, "pid": int|None}``.
    """
    result: dict = {"ok": False, "reason": "", "pid": None}
    if os.name != "nt":
        result["reason"] = "cheat.dll chỉ chạy trên Windows"
        return result
    if not python_is_64bit():
        result["reason"] = "tool đang chạy Python 32-bit — cần Python 64-bit"
        return result
    dll_path = os.path.abspath(dll_path)
    if not os.path.isfile(dll_path):
        result["reason"] = f"không tìm thấy DLL: {dll_path}"
        return result
    game_path = os.path.abspath(game_path)
    if not os.path.isfile(game_path):
        result["reason"] = f"không tìm thấy game: {game_path}"
        return result

    # Preseed speed into the config sitting next to cheat.dll.
    if speed is not None:
        dll_dir = os.path.dirname(dll_path)
        written = write_cheat_config(dll_dir, speed, enabled=True)
        if written:
            log_info(f"[cheat] đã ghi speed x{speed:g} vào {written}")

    k = _kernel32()
    k.CreateProcessW.restype = wintypes.BOOL
    k.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
        wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW), ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    k.ResumeThread.restype = wintypes.DWORD
    k.ResumeThread.argtypes = [wintypes.HANDLE]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.TerminateProcess.restype = wintypes.BOOL
    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]

    si = _STARTUPINFOW()
    si.cb = ctypes.sizeof(si)
    pi = _PROCESS_INFORMATION()
    cmd = ctypes.create_unicode_buffer(f'"{game_path}"')
    work_dir = os.path.dirname(game_path)
    if not k.CreateProcessW(
        game_path, cmd, None, None, False,
        _CREATE_SUSPENDED | _NORMAL_PRIORITY_CLASS,
        None, work_dir, ctypes.byref(si), ctypes.byref(pi),
    ):
        _win_err("CreateProcessW (suspended)")
        result["reason"] = "khởi động game (suspended) thất bại"
        return result

    pid = pi.dwProcessId
    try:
        log_info(f"[cheat] game PID {pid} đang suspend, inject cheat.dll…")
        if not inject_dll(pid, dll_path):
            log_error("[cheat] inject vào process suspend thất bại — tắt game")
            k.TerminateProcess(pi.hProcess, 1)
            result["reason"] = "inject thất bại (xem log)"
            return result
        log_success(f"[cheat] cheat.dll đã nạp — resume game")
        k.ResumeThread(pi.hThread)
        result["ok"] = True
        result["pid"] = pid
        result["reason"] = "đã launch game + inject cheat.dll (CREATE_SUSPENDED)"
        return result
    finally:
        k.CloseHandle(pi.hThread)
        k.CloseHandle(pi.hProcess)


def inject_unity_cheat(
    pid: int, dll_path: str, speed: Optional[float] = None, force: bool = False
) -> dict:
    """Full Win32 speed-hack path: verify → preseed config → inject cheat.dll.

    Returns ``{"ok": bool, "reason": str, "backend": str|None, "already": bool}``.
    ``reason`` is a short human message (logged by the caller as needed).
    """
    result = {"ok": False, "reason": "", "backend": None, "already": False}

    if os.name != "nt":
        result["reason"] = "cheat.dll chỉ chạy trên Windows"
        return result
    if not python_is_64bit():
        result["reason"] = (
            "tool đang chạy Python 32-bit — không thể inject vào game 64-bit. "
            "Chạy tool bằng Python 64-bit."
        )
        return result

    is64 = process_is_64bit(pid)
    if is64 is False:
        result["reason"] = "game là tiến trình 32-bit — cheat.dll là bản x64, không tương thích"
        return result

    backend = detect_unity_backend(pid)
    result["backend"] = backend
    if backend is None:
        result["reason"] = (
            "không phát hiện Unity (UnityPlayer.dll/GameAssembly.dll/mono) trong "
            "tiến trình — cheat.dll chỉ dành cho game Unity"
        )
        return result

    # Always (re)write the config next to cheat.dll before injecting — the DLL
    # reads ``cheat_config.ini`` from its own module directory on load, so this
    # is what preseeds the speed. Also write it when already injected: the DLL
    # only reads the file once at startup, so a re-press won't change the live
    # speed (that's done via the in-game overlay), but it keeps the file correct
    # for the next game restart.
    if speed is not None:
        dll_dir = os.path.dirname(os.path.abspath(dll_path))
        written = write_cheat_config(dll_dir, speed, enabled=True)
        if written:
            log_info(f"[cheat] đã ghi speed x{speed:g} vào {written}")

    dll_name = os.path.basename(dll_path).lower()
    if not force and module_loaded(pid, dll_name):
        result["ok"] = True
        result["already"] = True
        result["reason"] = "cheat.dll đã được inject trước đó (đổi speed qua menu overlay)"
        return result

    if inject_dll(pid, dll_path):
        # Best-effort verification: confirm the DLL is now in the target's
        # module list. ``EnumProcessModulesEx`` can transiently miss a just-loaded
        # module (or fail to open the process a second time once anti-cheat has
        # re-protected it), so retry a few times and treat "couldn't enumerate"
        # as inconclusive rather than failure. The LoadLibraryW exit-code check
        # above is the authoritative success signal.
        import time as _time
        verified = None  # None = couldn't check; True/False = checked
        for _attempt in range(4):
            mods = list_modules(pid)
            if not mods:
                # OpenProcess for enum failed — anti-cheat may have locked the
                # process down after we injected. Don't treat as "rejected".
                verified = None
                break
            if dll_name in mods:
                verified = True
                break
            verified = False
            _time.sleep(0.15)
        if verified is False:
            log_warning(
                "[cheat] ⚠ LoadLibraryW trả về HMODULE nhưng cheat.dll không thấy "
                "trong module list sau khi verify — DLL có thể bị anti-cheat gỡ "
                "ngay sau khi nạp. Nếu bấm F12 trong game vẫn mở menu overlay thì "
                "DLL đang chạy bình thường (verify bị false negative)."
            )
        elif verified is None:
            log_info("[cheat] không verify được module list (process bị lock) — tin exit code")
        else:
            log_success(f"[cheat] đã xác nhận cheat.dll nằm trong module list của game")
        result["ok"] = True
        result["reason"] = f"đã inject cheat.dll (Unity/{backend})"
    else:
        result["reason"] = "inject cheat.dll thất bại (xem log ở trên)"
    return result
