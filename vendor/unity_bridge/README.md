# Unity Bridge

In-game input bridge for Macro2k's `unity_bridge` Win32 input mode. A BepInEx 5
plugin runs inside a Unity game, listens on `127.0.0.1:17820` and performs
taps/swipes through Unity's EventSystem and key presses through the Input System
and the legacy Input manager — no cursor, no focus, the window may be covered.

```
vendor/unity_bridge/
├── bepinex5_x64/          BepInEx 5.4.23.5 x64, unmodified official zip (Doorstop 4.5.0)
├── plugin/
│   └── Macro2kBridge.dll  built plugin that gets deployed
└── src/Macro2kBridge/     plugin source (C#, net472)
```

## Deploy

Pick **Unity bridge** as the Win32 input mode (toolbar, Project settings, or the
new-project dialog). Macro2k offers to deploy into the game folder:

- `BepInEx/` + `winhttp.dll` + `doorstop_config.ini` + `.doorstop_version` — only when the game has no BepInEx yet
- `BepInEx/plugins/Macro2kBridge/Macro2kBridge.dll` — always (update)

An existing BepInEx 5 install is never upgraded (other mods may depend on it);
the dialog only notes when it is older than the bundled one. Doorstop 4 renamed
its `doorstop_config.ini` keys, so it is only added to an existing install whose
BepInEx version matches the bundled one.

To update the bundled BepInEx, replace `bepinex5_x64/` with the contents of the
official `BepInEx_win_x64_<version>.zip` — the version is read from `BepInEx.dll`.

Restart the game afterwards. `BepInEx/LogOutput.log` should show
`[Macro2k Unity Bridge] Listening on 127.0.0.1:17820`.

Implementation: `src/core/win32/unity_bridge.py` (inspect/deploy/ping) and
`Win32Controller._tap_bridge` / `_swipe_bridge` (client).

## Supported games

- Unity **Mono** builds, x64, Unity 2018.3+ (.NET 4.x scripting runtime)
- Not supported: IL2CPP builds (`GameAssembly.dll`), x86, games already on BepInEx 6

Games with anti-cheat may detect BepInEx.

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
