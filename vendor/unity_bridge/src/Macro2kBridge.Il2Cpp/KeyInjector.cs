using System;
using System.Collections.Generic;
using System.Reflection;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// Simulated keys for the bridge (IL2CPP build). Keeps the set of held keys and
    /// feeds it to both input stacks a game may read:
    ///  - Legacy Input manager: Harmony postfixes on Input.GetKey / GetKeyDown /
    ///    GetKeyUp and GetAxis(Raw) "Horizontal" / "Vertical" (WASD + arrows).
    ///    Il2CppInterop's Harmony support patches the native method, so calls made
    ///    by the game's own compiled code see the postfix too.
    ///  - Input System (reflection, best effort — many games don't ship it): queues
    ///    a KeyboardState holding every held key. Its interop signatures are
    ///    Il2CppStructArray based and vary per version; when the lookup fails the
    ///    bridge logs it once and keys keep working through the legacy patches.
    /// Main thread only (Tick / routines). The real keyboard keeps working; a state
    /// event from a physical key can override the simulated state until the next
    /// Press / Release.
    /// </summary>
    internal static class KeyInjector
    {
        internal struct MappedKey
        {
            public int Vk;
            public string Name;
            public object NewKey;       // UnityEngine.InputSystem.Key, boxed; null without the Input System
            public KeyCode? LegacyKey;
        }

        internal static ManualLogSource Log;

        private static readonly Dictionary<int, MappedKey> Held = new Dictionary<int, MappedKey>();
        // GetKeyDown / GetKeyUp answer true on the frame AFTER the command, so every
        // script's Update in that frame sees it exactly once (commands run mid-frame).
        private static readonly Dictionary<KeyCode, int> DownFrame = new Dictionary<KeyCode, int>();
        private static readonly Dictionary<KeyCode, int> UpFrame = new Dictionary<KeyCode, int>();
        private static bool _patched;

        private static bool _inputSystemResolved;
        private static Type _keyType;
        private static Type _keyArrayType;      // Il2CppStructArray<Key>
        private static PropertyInfo _arrayItem;
        private static PropertyInfo _keyboardCurrent;
        private static ConstructorInfo _stateCtor;
        private static MethodInfo _queueStateEvent;

        private static void ResolveInputSystem()
        {
            if (_inputSystemResolved) return;
            _inputSystemResolved = true;
            try
            {
                _keyType = InputBridge.FindType("UnityEngine.InputSystem.Key");
                Type keyboard = InputBridge.FindType("UnityEngine.InputSystem.Keyboard");
                Type state = InputBridge.FindType("UnityEngine.InputSystem.LowLevel.KeyboardState");
                Type inputSystem = InputBridge.FindType("UnityEngine.InputSystem.InputSystem");
                if (_keyType == null || keyboard == null || state == null || inputSystem == null)
                {
                    Log?.LogInfo("Input System not present; keys go through the legacy Input manager only");
                    return;
                }
                _keyboardCurrent = keyboard.GetProperty("current", BindingFlags.Public | BindingFlags.Static);

                // KeyboardState(params Key[]) -> KeyboardState(Il2CppStructArray<Key>)
                foreach (ConstructorInfo ctor in state.GetConstructors())
                {
                    ParameterInfo[] ps = ctor.GetParameters();
                    if (ps.Length == 1 && ps[0].ParameterType.IsGenericType
                        && ps[0].ParameterType.Name.StartsWith("Il2CppStructArray", StringComparison.Ordinal))
                    {
                        _stateCtor = ctor;
                        _keyArrayType = ps[0].ParameterType;
                        _arrayItem = _keyArrayType.GetProperty("Item", new[] { typeof(int) });
                        break;
                    }
                }

                foreach (MethodInfo m in inputSystem.GetMethods(BindingFlags.Public | BindingFlags.Static))
                {
                    // QueueStateEvent<TState>(InputDevice device, TState state, double time = -1)
                    if (m.Name == "QueueStateEvent" && m.IsGenericMethodDefinition && m.GetParameters().Length == 3)
                    {
                        _queueStateEvent = m.MakeGenericMethod(state);
                        break;
                    }
                }
                if (_keyboardCurrent == null || _stateCtor == null || _arrayItem == null || _queueStateEvent == null)
                {
                    Log?.LogWarning("Input System found but its keyboard API differs; keys use the legacy Input manager only");
                    _queueStateEvent = null;
                }
            }
            catch (Exception e)
            {
                _queueStateEvent = null;
                Log?.LogWarning($"Input System keyboard lookup failed: {e.Message}");
            }
        }

        internal static bool TryMap(int vk, out MappedKey key)
        {
            key = default;
            string name, newName, legacyName;
            if (vk >= 0x41 && vk <= 0x5A)
            {
                name = newName = legacyName = ((char)vk).ToString();
            }
            else if (vk >= 0x30 && vk <= 0x39)
            {
                name = ((char)vk).ToString();
                newName = "Digit" + name;
                legacyName = "Alpha" + name;
            }
            else if (vk >= 0x70 && vk <= 0x7B)
            {
                name = newName = legacyName = "F" + (vk - 0x6F);
            }
            else if (vk >= 0x60 && vk <= 0x69)
            {
                int n = vk - 0x60;
                name = newName = "Numpad" + n;
                legacyName = "Keypad" + n;
            }
            else
            {
                switch (vk)
                {
                    case 0x08: name = newName = legacyName = "Backspace"; break;
                    case 0x09: name = newName = legacyName = "Tab"; break;
                    case 0x0D: name = newName = "Enter"; legacyName = "Return"; break;
                    case 0x10: case 0xA0: name = "Shift"; newName = legacyName = "LeftShift"; break;
                    case 0xA1: name = newName = legacyName = "RightShift"; break;
                    case 0x11: case 0xA2: name = "Ctrl"; newName = "LeftCtrl"; legacyName = "LeftControl"; break;
                    case 0xA3: name = newName = "RightCtrl"; legacyName = "RightControl"; break;
                    case 0x12: case 0xA4: name = "Alt"; newName = legacyName = "LeftAlt"; break;
                    case 0xA5: name = newName = legacyName = "RightAlt"; break;
                    case 0x1B: name = newName = legacyName = "Escape"; break;
                    case 0x20: name = newName = legacyName = "Space"; break;
                    case 0x21: name = newName = legacyName = "PageUp"; break;
                    case 0x22: name = newName = legacyName = "PageDown"; break;
                    case 0x23: name = newName = legacyName = "End"; break;
                    case 0x24: name = newName = legacyName = "Home"; break;
                    case 0x25: name = newName = legacyName = "LeftArrow"; break;
                    case 0x26: name = newName = legacyName = "UpArrow"; break;
                    case 0x27: name = newName = legacyName = "RightArrow"; break;
                    case 0x28: name = newName = legacyName = "DownArrow"; break;
                    case 0x2D: name = newName = legacyName = "Insert"; break;
                    case 0x2E: name = newName = legacyName = "Delete"; break;
                    default: return false;
                }
            }

            ResolveInputSystem();
            object newKey = null;
            if (_keyType != null && Enum.IsDefined(_keyType, newName)) newKey = Enum.Parse(_keyType, newName);
            KeyCode? legacyKey = null;
            if (Enum.IsDefined(typeof(KeyCode), legacyName)) legacyKey = (KeyCode)Enum.Parse(typeof(KeyCode), legacyName);
            if (newKey == null && legacyKey == null) return false;

            key = new MappedKey { Vk = vk, Name = name, NewKey = newKey, LegacyKey = legacyKey };
            return true;
        }

        internal static void Press(MappedKey key)
        {
            Held[key.Vk] = key;
            if (key.LegacyKey.HasValue) DownFrame[key.LegacyKey.Value] = Time.frameCount + 1;
            PushKeyboardState();
        }

        internal static void Release(MappedKey key)
        {
            Held.Remove(key.Vk);
            if (key.LegacyKey.HasValue) UpFrame[key.LegacyKey.Value] = Time.frameCount + 1;
            // Pushed even when the key wasn't held — clears a key stuck by an earlier run.
            PushKeyboardState();
        }

        internal static void ReleaseAll()
        {
            if (Held.Count == 0) return;
            foreach (MappedKey key in Held.Values)
            {
                if (key.LegacyKey.HasValue) UpFrame[key.LegacyKey.Value] = Time.frameCount + 1;
            }
            Held.Clear();
            PushKeyboardState();
        }

        private static void PushKeyboardState()
        {
            ResolveInputSystem();
            if (_queueStateEvent == null) return;

            try
            {
                object keyboard = _keyboardCurrent.GetValue(null, null);
                if (keyboard == null) return;

                var pressed = new List<object>();
                foreach (MappedKey key in Held.Values)
                {
                    if (key.NewKey != null) pressed.Add(key.NewKey);
                }
                object keys = Activator.CreateInstance(_keyArrayType, (long)pressed.Count);
                for (int i = 0; i < pressed.Count; i++) _arrayItem.SetValue(keys, pressed[i], new object[] { i });

                object state = _stateCtor.Invoke(new[] { keys });
                _queueStateEvent.Invoke(null, new[] { keyboard, state, -1.0 });
            }
            catch (Exception e)
            {
                // Don't retry every keypress: the legacy patches still work.
                _queueStateEvent = null;
                Log?.LogWarning($"Input System key injection disabled: {(e.InnerException ?? e).Message}");
            }
        }

        private static bool IsHeld(KeyCode code)
        {
            foreach (MappedKey key in Held.Values)
            {
                if (key.LegacyKey == code) return true;
            }
            return false;
        }

        #region Legacy Input patches

        internal static void ApplyLegacyPatches()
        {
            if (_patched) return;
            _patched = true;
            try
            {
                var harmony = new Harmony(Macro2kBridgePlugin.PluginGuid);
                Type self = typeof(KeyInjector);
                Type[] keyArg = { typeof(KeyCode) };
                Type[] axisArg = { typeof(string) };
                harmony.Patch(AccessTools.Method(typeof(Input), nameof(Input.GetKey), keyArg),
                    postfix: new HarmonyMethod(self, nameof(GetKeyPostfix)));
                harmony.Patch(AccessTools.Method(typeof(Input), nameof(Input.GetKeyDown), keyArg),
                    postfix: new HarmonyMethod(self, nameof(GetKeyDownPostfix)));
                harmony.Patch(AccessTools.Method(typeof(Input), nameof(Input.GetKeyUp), keyArg),
                    postfix: new HarmonyMethod(self, nameof(GetKeyUpPostfix)));
                harmony.Patch(AccessTools.Method(typeof(Input), nameof(Input.GetAxis), axisArg),
                    postfix: new HarmonyMethod(self, nameof(GetAxisPostfix)));
                harmony.Patch(AccessTools.Method(typeof(Input), nameof(Input.GetAxisRaw), axisArg),
                    postfix: new HarmonyMethod(self, nameof(GetAxisPostfix)));
                Log?.LogInfo("Legacy Input key patches applied");
            }
            catch (Exception e)
            {
                Log?.LogWarning($"Legacy Input key patches failed: {e.Message}");
            }
        }

        public static void GetKeyPostfix(KeyCode key, ref bool __result)
        {
            if (!__result && Held.Count > 0 && IsHeld(key)) __result = true;
        }

        public static void GetKeyDownPostfix(KeyCode key, ref bool __result)
        {
            if (!__result && DownFrame.TryGetValue(key, out int frame) && frame == Time.frameCount) __result = true;
        }

        public static void GetKeyUpPostfix(KeyCode key, ref bool __result)
        {
            if (!__result && UpFrame.TryGetValue(key, out int frame) && frame == Time.frameCount) __result = true;
        }

        public static void GetAxisPostfix(string axisName, ref float __result)
        {
            if (__result != 0f || Held.Count == 0) return;
            float value = 0f;
            if (axisName == "Horizontal")
            {
                value = (IsHeld(KeyCode.D) || IsHeld(KeyCode.RightArrow) ? 1f : 0f)
                        - (IsHeld(KeyCode.A) || IsHeld(KeyCode.LeftArrow) ? 1f : 0f);
            }
            else if (axisName == "Vertical")
            {
                value = (IsHeld(KeyCode.W) || IsHeld(KeyCode.UpArrow) ? 1f : 0f)
                        - (IsHeld(KeyCode.S) || IsHeld(KeyCode.DownArrow) ? 1f : 0f);
            }
            if (value != 0f) __result = value;
        }

        #endregion
    }
}
