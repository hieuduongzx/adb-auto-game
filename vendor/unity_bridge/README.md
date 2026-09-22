# Unity Bridge

In-game input bridge for Macro2k's `unity_bridge` Win32 input mode. A DLL injected
into the running game listens on `127.0.0.1:17820` and performs taps/swipes through
Unity's EventSystem and key presses through the Input System and the legacy Input
manager — no cursor, no focus, the window may be covered.

No BepInEx, nothing is ever copied into the game folder: `Macro2kInjector.exe`
loads the bridge DLL straight into the running process. Two builds share one
protocol; Macro2k picks the right one from the game folder (`GameAssembly.dll` /
`il2cpp_data` → IL2CPP, otherwise Mono):

| Game backend | Injection | Plugin |
|---|---|---|
| Mono | managed DLL, via the game's own Mono runtime (`Macro2kInjector.exe inject`) | `plugin_inject/Macro2kBridge.Inject.dll` |
| IL2CPP | native DLL, `LoadLibraryA` (`Macro2kInjector.exe loadlibrary`) | `plugin_il2cpp/Macro2kBridge.Il2Cpp.dll` |

```
vendor/unity_bridge/
├── injector/              Macro2kInjector.exe (x64, .NET Framework 4.7.2 — ships with Windows)
├── plugin_inject/         built Mono plugin that gets injected (managed DLL)
├── plugin_il2cpp/         built IL2CPP plugin that gets injected (native DLL)
└── src/
    ├── Macro2kBridge.Inject/  Mono plugin source (C#, net472): InputBridge.cs (protocol + uGUI
    │                          simulation), LegacyInput.cs (legacy Input hooks), Loader.cs (entry point)
    ├── Macro2kInjector/       injector source (both injection modes)
    └── Macro2kBridge.Il2Cpp/  IL2CPP plugin source (bridge.cpp, native C++, MSVC)
```

### Why no BepInEx

BepInEx was the original approach (Doorstop-hijack the process, load a managed
plugin through it) and still works for most games, but two things ruled it out:

- **Unity 6 Mono games can strip their runtime library.** Tried on a Unity
  6000.0.61f1 game: `mscorlib.dll` has no `Module.GetPEKind`, no
  `File.ReadAllLines`, no Reflection.Emit, and engine members such as
  `Application.runInBackground`'s setter or `TcpListener` are gone too. BepInEx's
  preloader dies on `Module.GetPEKind` before it even loads a plugin. Replacing
  `BepInEx/core`'s corlibs with full ones (BepInEx's documented fix) makes BepInEx
  start, but then **the game renders black** — with or without any plugin. Patching
  BepInEx's `GetPEKind` calls instead gets the game rendering again, but the next
  stripped API breaks the preloader, and `Supports SRE: False` rules out
  Harmony/MonoMod anyway.
- **IL2CPP has no managed runtime to load a plugin into in the first place.**
  BepInEx's IL2CPP support works by hijacking the process at startup (via
  Doorstop) and hosting its own .NET runtime + Il2CppInterop bindings before
  Unity initializes. That only works from process start, needs the game's
  interop assemblies generated up front, and is a lot of moving parts for
  something a much smaller native DLL can do directly (below).

Injecting after the game is already running sidesteps both: the Mono build talks
to the Mono runtime that's already loaded (`mono_thread_attach`,
`mono_assembly_load_from_full`, ...), and the IL2CPP build talks to the
`il2cpp_*` C API that `GameAssembly.dll` itself exports — no interop generation,
no embedded runtime.

### Injector

```
Macro2kInjector.exe inject <pid> <assembly.dll> <namespace> <class> <method>   -> "ok" | "err <message>"
Macro2kInjector.exe loadlibrary <pid> <native.dll>                             -> "ok" | "err <message>"
Macro2kInjector.exe launchlibrary <exe> <native.dll> <arguments>               -> "ok <pid>" | "err <message>"
```

`inject` (Mono): resolves the game's already-loaded `mono-2.0-*.dll` exports (read
locally to get the offsets, since a well-known system DLL loads at the same
address in every process), copies the assembly and a small x64 stub into the
target process, and runs the stub on a remote thread: `mono_thread_attach` →
`mono_image_open_from_data` → `mono_assembly_load_from_full` →
`mono_class_from_name` → `mono_runtime_invoke` on
`Macro2k.UnityBridge.Inject.Loader.Load()` → `mono_thread_detach`. `Load()` runs
on that remote thread, not Unity's main thread, so it hooks
`RenderPipelineManager.beginContextRendering` / `SceneManager.sceneLoaded` /
`Application.focusChanged` (whichever fires first — `Application.onBeforeRender`
and the Camera callbacks are stripped from Unity 6 games) to reach the main
thread and create the bridge's `GameObject` there.

`loadlibrary` (IL2CPP): the classic `CreateRemoteThread(LoadLibraryA)` injection
of a native DLL. `bridge.cpp`'s `DllMain` does the rest: it resolves the
`il2cpp_*` exports from `GameAssembly.dll`, waits for the game's `UnityWndClass`
window, and installs a `WH_GETMESSAGE` hook on the main thread (a background
thread keeps posting `WM_NULL` so the hook fires every frame even when the
window doesn't otherwise get messages).

`launchlibrary` starts the game suspended, injects the IL2CPP DLL, then resumes
the main thread. The **Launch program** workflow node exposes this as **Inject
Unity Bridge before startup** for games that only accept injection before their
startup protection is initialized.

Both modes: Macro2k injects automatically when a `unity_bridge` workflow attaches
to the game (`Win32Controller._inject_bridge` → `unity_bridge.ensure_injected`)
and from the designer's deploy dialog. The injection lives in the process, so it
happens again on every game start; the port is handed over in
`%TEMP%\Macro2kBridge.port` and the bridge logs to `%TEMP%\Macro2kBridge.log`.
The game must run as the same user (not elevated unless Macro2k is too), x64
only. Anti-cheat may detect process injection — **never inject into a game with
kernel-mode anti-cheat** (a driver such as `.sys`/kernel service shipped with the

`unity_bridge._vendor_dir()` (`src/core/win32/unity_bridge.py`) resolves where the
injector + plugin DLLs live: a packaged single-workflow **Runner** ships them
*inside* `_internal/vendor/unity_bridge/` (a private implementation detail, unlike
adb/scrcpy which stay in the visible external `vendor/` — see
`packaging/build_runner.py`'s `_copy_vendor`), while a full Designer/Hub build and
running from source keep the external `vendor/unity_bridge/` (unchanged; falls
back there when nothing is bundled into `_internal`/`_macro2k`).
game); there is no way to make that safe.

### Mono plugin notes

Compiled against the target game's own `mscorlib`/`System`/`UnityEngine` (no
framework reference assemblies), so the compiler rejects every API a game's
Unity 6 stripping removed: `TcpListener` → `Socket`, `File.AppendAllText` →
manual `FileStream`, `TextWriter.NewLine`'s setter and
`Application.runInBackground`'s setter are worked around already (see
`InputBridge.cs`). No Harmony, so legacy `Input.GetKey*`/`GetMouseButton*` and
`EventSystem.isFocused` are not patched the BepInEx way; instead
`LegacyInput.cs` breakpoint-hooks the JIT'd `Input` icall wrappers directly
(`0xCC` + a vectored exception handler) only while a tap/key is simulated, with
a trampoline to the original body for games that also poll the real mouse/keys.
`EventSystem.isFocused` is forced by writing its backing field every tick
instead of patching the getter.

### IL2CPP plugin notes

`bridge.cpp` is a small native x64 DLL — no Il2CppInterop, no embedded .NET
runtime. It calls `il2cpp_class_from_name` / `il2cpp_runtime_invoke` etc.
directly to find `EventSystem`, build a `PointerEventData`, raycast, and drive
`IPointerDownHandler`/`IPointerUpHandler`/`IPointerClickHandler`/drag handlers
through `ExecuteEvents`-equivalent logic — mirroring uGUI's own
`PointerInputModule`. Games whose input module is `StandaloneInputModule`
(reads the legacy `Input` manager itself) are fed through the same
breakpoint-hook technique as the Mono build instead, to avoid a double click.
`EventSystem.isFocused` is forced the same way (its backing field, every tick).
Keys use the same `key` / `keydown` / `keyup` commands as Mono: `GetKey*`
icalls, and `InputState.Change` when the game ships the Input System. Games
whose IL2CPP metadata is encrypted/obfuscated past what stock
`il2cpp_class_from_name` can resolve won't work.

## Deploy / inject

Pick **Unity bridge** as the Win32 input mode (toolbar, Project settings, or the
new-project dialog). Macro2k injects into the running game; if the game isn't
running yet, it injects the next time a `unity_bridge` workflow attaches to it.
Leftover `BepInEx/`, `winhttp.dll`, `doorstop_config.ini`, `.doorstop_version`,
`dotnet/` from an older Macro2k version that still used BepInEx are removed from
the game folder first (a "modded" BepInEx install can itself trip anti-cheat
even though Macro2k no longer uses it).

Implementation: `src/core/win32/unity_bridge.py` (inspect/deploy/inject/ping) and
`Win32Controller._tap_bridge` / `_swipe_bridge` / `_inject_bridge` (client).

## Supported games

- Unity **Mono** builds, x64, Unity 2018.3+
- Unity **IL2CPP** builds, x64, whose metadata isn't encrypted/obfuscated past
  what `il2cpp_class_from_name` can resolve
- Not supported: x86, games with kernel-mode anti-cheat (do not attempt)

## Protocol

One command per line, one reply per line. Coordinates are client-area pixels
(top-left origin); `refW refH` is the sender's client size.

| Command | Reply |
|---|---|
| `ping` | `ok Macro2kBridge <version> <screenW> <screenH>` |
| `tap x y [holdMs] [refW refH]` | `ok <object path>` · `miss` · `err <message>` |
| `swipe x1 y1 x2 y2 [ms] [refW refH]` | `ok <object path>` · `miss` · `err <message>` |
| `probe x y [refW refH]` | `ok module=<name> hits=<n> \| <path> {down=... click=... comps=...} ...` (diagnostics) |
| `key vk [holdMs]` | `ok key <name>` · `err <message>` (replies after the release) |
| `keydown vk` | `ok keydown <name>` — stays held until `keyup` |
| `keyup vk` · `keyup all` | `ok keyup <name>` |

`miss` = no EventSystem target under the point (e.g. world objects the game
reads from `Input` directly); Macro2k then falls back to anchored touch.

`vk` is a Windows virtual-key code (letters, digits, F1–F12, numpad digits,
arrows, Enter/Esc/Space/Tab/Backspace, Shift/Ctrl/Alt, Insert/Delete/Home/End/
PageUp/PageDown). Both builds report the key through legacy `Input.GetKey` /
`GetKeyDown` / `GetKeyUp` (and, on Mono, `GetAxis(Raw)` `Horizontal` /
`Vertical`). The Input System does not keep a one-shot `KeyboardState`: the
next update reads the real keyboard, which has no scan code, and that empty
state used to replace the simulated one before gameplay saw it. While a key is
held the bridge drops those real keyboard events and writes the held set with
`InputState.Change`, so `isPressed` stays true and `wasPressedThisFrame` is
true only on the transition. Keys still held are released when the bridge
stops; Macro2k also sends `keyup` for them when a run stops. A plugin older
than 1.2.0 answers `err unknown command` for `key` on IL2CPP and Macro2k falls
back to window messages.

Config: `Port` comes from `%TEMP%\Macro2kBridge.port` (written by Macro2k before
injecting); `IgnoreFocus` is always on.

## Build

```
dotnet build vendor/unity_bridge/src/Macro2kInjector -c Release
```

Mono plugin — must be compiled against the **target game's own** `Managed`
folder (not a generic Unity install), so the compiler catches APIs that game's
build stripped:

```
dotnet build vendor/unity_bridge/src/Macro2kBridge.Inject -c Release -p:UnityManagedDir="<Game>_Data\Managed"
```

IL2CPP plugin — MSVC, x64 (Visual Studio's "Desktop development with C++"
workload; `build.bat` finds `vcvars64.bat` under `Program Files\Microsoft Visual
Studio\*\*\VC\Auxiliary\Build`):

```
vendor\unity_bridge\src\Macro2kBridge.Il2Cpp\build.bat
```
