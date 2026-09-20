# Unity Bridge

In-game input bridge for Macro2k's `unity_bridge` Win32 input mode. A BepInEx
plugin runs inside a Unity game, listens on `127.0.0.1:17820` and performs
taps/swipes through Unity's EventSystem and key presses through the Input System
and the legacy Input manager — no cursor, no focus, the window may be covered.

Two builds share one protocol; Macro2k picks the right one from the game folder
(`GameAssembly.dll` / `il2cpp_data` → IL2CPP, otherwise Mono):

| Game backend | BepInEx | Plugin |
|---|---|---|
| Mono | 5.4.23.5 (`bepinex5_x64/`) | `plugin/Macro2kBridge.dll` |
| IL2CPP | 6.0.0-be.788 (`bepinex6_il2cpp_x64/`) | `plugin_il2cpp/Macro2kBridge.dll` |

```
vendor/unity_bridge/
├── bepinex5_x64/          BepInEx 5.4.23.5 x64, unmodified official zip (Doorstop 4.5.0)
├── bepinex6_il2cpp_x64/   BepInEx 6.0.0-be.788 Unity.IL2CPP x64, unmodified official zip (Doorstop 4.5.0, .NET 6 in dotnet/)
├── plugin/                built Mono plugin that gets deployed
├── plugin_il2cpp/         built IL2CPP plugin that gets deployed
└── src/
    ├── Macro2kBridge/         Mono plugin source (C#, net472)
    └── Macro2kBridge.Il2Cpp/  IL2CPP plugin source (C#, net6.0, Il2CppInterop)
```

## Deploy

Pick **Unity bridge** as the Win32 input mode (toolbar, Project settings, or the
new-project dialog). Macro2k offers to deploy into the game folder:

- `BepInEx/` + `winhttp.dll` + `doorstop_config.ini` + `.doorstop_version` (IL2CPP: plus `dotnet/`) — only when the game has no BepInEx yet
- `BepInEx/plugins/Macro2kBridge/Macro2kBridge.dll` — always (update)

An existing BepInEx install is never upgraded (other mods may depend on it);
the dialog only notes when it differs from the bundled one. Doorstop 4 renamed
its `doorstop_config.ini` keys, so it is only added to an existing install whose
BepInEx build matches the bundled one. A game with the wrong BepInEx generation
(5 on an IL2CPP game, 6 on a Mono game, or BepInEx 6 without the IL2CPP loader)
is reported as a problem instead of being overwritten.

To update the bundled BepInEx 5, replace `bepinex5_x64/` with the contents of the
official `BepInEx_win_x64_<version>.zip` — the version is read from `BepInEx.dll`.
To update BepInEx 6, replace `bepinex6_il2cpp_x64/` with the contents of a
`BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.<build>+<hash>.zip` from
<https://builds.bepinex.dev/projects/bepinex_be>, set `BEPINEX6_VERSION` in
`src/core/win32/unity_bridge.py`, then rebuild the IL2CPP plugin.

On an IL2CPP game's first start BepInEx 6 generates `BepInEx/interop` from
`GameAssembly.dll` + `global-metadata.dat` — this takes a minute and the log says
so. Games that encrypt or protect their metadata can't be interop-generated and
can't host the bridge.

Restart the game afterwards. `BepInEx/LogOutput.log` should show
`[Macro2k Unity Bridge] Listening on 127.0.0.1:17820`.

Implementation: `src/core/win32/unity_bridge.py` (inspect/deploy/ping) and
`Win32Controller._tap_bridge` / `_swipe_bridge` (client).

## Supported games

- Unity **Mono** builds, x64, Unity 2018.3+ (.NET 4.x scripting runtime) — BepInEx 5
- Unity **IL2CPP** builds, x64, Unity 2018.4+ whose metadata BepInEx 6 can read — BepInEx 6
- Not supported: x86, games already on BepInEx of the other generation

Games with anti-cheat may detect BepInEx.

IL2CPP notes: taps/swipes go through the same EventSystem path. Legacy `Input`
key patches rely on Il2CppInterop's Harmony support; the Input System keyboard
injection is best effort (its interop signatures vary) and disables itself with
a log line if the lookup fails — keys then work only for games reading the legacy
`Input` manager.

## Protocol

One command per line, one reply per line. Coordinates are client-area pixels
(top-left origin); `refW refH` is the sender's client size.

| Command | Reply |
|---|---|
| `ping` | `ok Macro2kBridge <version> <screenW> <screenH>` |
| `tap x y [holdMs] [refW refH]` | `ok <object path>` · `miss` · `err <message>` |
| `swipe x1 y1 x2 y2 [ms] [refW refH]` | `ok <object path>` · `miss` · `err <message>` |
| `key vk [holdMs]` | `ok key <name>` · `err <message>` (replies after the release) |
| `keydown vk` | `ok keydown <name>` — stays held until `keyup` |
| `keyup vk` · `keyup all` | `ok keyup <name>` |

`miss` = no EventSystem target under the point (e.g. world objects the game
reads from `Input` directly); Macro2k then falls back to anchored touch.

`vk` is a Windows virtual-key code (letters, digits, F1–F12, numpad digits,
arrows, Enter/Esc/Space/Tab/Backspace, Shift/Ctrl/Alt, Insert/Delete/Home/End/
PageUp/PageDown). A held key is queued as a `KeyboardState` into the Input System
(found by reflection; skipped when the game doesn't ship it) and reported by
Harmony postfixes on `Input.GetKey/GetKeyDown/GetKeyUp` and `GetAxis(Raw)`
`Horizontal`/`Vertical`. Keys still held are released when the bridge stops;
Macro2k also sends `keyup` for them when a run stops. A plugin older than 1.1.0
answers `err unknown command` and Macro2k falls back to window messages.

Config (`BepInEx/config/com.macro2k.unitybridge.cfg`): `Port`, `IgnoreFocus`.

## Build the plugin

```
dotnet build vendor/unity_bridge/src/Macro2kBridge -c Release -p:UnityManagedDir="<Game>_Data\Managed"
```

`UnityManagedDir` is any Unity game's `Managed` folder (compile-time references
only, nothing from it is shipped). The build copies the DLL to `plugin/`.

IL2CPP plugin:

```
dotnet build vendor/unity_bridge/src/Macro2kBridge.Il2Cpp -c Release -p:Il2CppInteropDir="<Game>\BepInEx\interop"
```

`Il2CppInteropDir` is the `BepInEx/interop` folder BepInEx 6 generated for any
IL2CPP game (compile-time references only; the running game's own interop is
bound at load). BepInEx runtime references come from `bepinex6_il2cpp_x64/`.
The build copies the DLL to `plugin_il2cpp/`. Needs the .NET SDK (targets net6.0;
the targeting pack is restored from NuGet).
