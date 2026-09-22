using System;
using System.Reflection;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.LowLevel;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// Keeps simulated keys visible to the Input System.
    ///
    /// Queueing one KeyboardState from a MonoBehaviour is not enough: the next
    /// input update reads the real keyboard (nothing is down — the window may
    /// be unfocused and Macro2k never sent a scan code) and that state replaces
    /// the simulated one before gameplay reads it. While a key is simulated,
    /// real keyboard events are swallowed and the held set is written with
    /// InputState.Change, which updates the device immediately. The write is
    /// repeated at the end of InputSystem.Update so every script in the
    /// following player Update sees the same state, and only on a change, so
    /// wasPressedThisFrame does not stay true for the whole hold.
    /// </summary>
    internal static class InputSystemKeys
    {
        internal static Func<object[]> Collect;

        private static bool _installed;
        private static bool _blocking;
        private static bool _applied;
        private static int _appliedHash;
        private static IntPtr _updateTrampoline;
        private static readonly object Gate = new object();

        internal static void Apply(object[] boxedKeys)
        {
            Install();
            if (boxedKeys != null && boxedKeys.Length > 1)
                Array.Sort(boxedKeys, (a, b) => ((int)(Key)a).CompareTo((int)(Key)b));
            int hash = Hash(boxedKeys);
            // Swallow before the write. Change itself does not go through onEvent,
            // so this only drops the real keyboard events that would undo it.
            _blocking = true;
            if (!_applied || hash != _appliedHash)
            {
                Keyboard keyboard = Keyboard.current;
                if (keyboard == null)
                {
                    ManualLogSource.Write("Warning", "Input System has no Keyboard.current yet; will retry");
                    return;
                }
                var keys = new Key[boxedKeys == null ? 0 : boxedKeys.Length];
                for (int i = 0; i < keys.Length; i++) keys[i] = (Key)boxedKeys[i];
                InputState.Change(keyboard, new KeyboardState(keys));
                _appliedHash = hash;
                _applied = true;
            }
            _blocking = boxedKeys != null && boxedKeys.Length > 0;
        }

        private static void Install()
        {
            if (_installed) return;
            lock (Gate)
            {
                if (_installed) return;
                InputSystem.onEvent += OnEvent;
                MethodInfo update = typeof(InputSystem).GetMethod("Update", BindingFlags.Public | BindingFlags.Static, null,
                    new[] { typeof(InputUpdateType) }, null);
                MethodInfo hook = typeof(InputSystemKeys).GetMethod("UpdateHook", BindingFlags.NonPublic | BindingFlags.Static);
                _updateTrampoline = LegacyInput.HookPermanent(update, hook);
                _installed = true;
                if (_updateTrampoline == IntPtr.Zero)
                    ManualLogSource.Write("Warning", "InputSystem.Update was not wrapped; keys apply from the bridge tick only");
                else
                    ManualLogSource.Write("Info", "Input System keys: real keyboard events are held off while a key is simulated");
            }
        }

        // Same shape as InputSystem.Update(InputUpdateType): run the real update, then
        // put the simulated set back on top of whatever the OS keyboard just wrote.
        private static unsafe void UpdateHook(InputUpdateType type)
        {
            if (_updateTrampoline != IntPtr.Zero)
                ((delegate*<int, void>)_updateTrampoline)((int)type);
            if (Collect == null || (!_blocking && !_applied)) return;
            try
            {
                Apply(Collect());
            }
            catch (Exception e)
            {
                ManualLogSource.Write("Warning", "Input System key refresh failed: " + e.Message);
            }
        }

        private static void OnEvent(InputEventPtr eventPtr, InputDevice device)
        {
            if (_blocking && device is Keyboard) eventPtr.handled = true;
        }

        private static int Hash(object[] keys)
        {
            if (keys == null || keys.Length == 0) return 0;
            int h = keys.Length;
            for (int i = 0; i < keys.Length; i++) h = (h * 31) + (keys[i] == null ? 0 : (int)(Key)keys[i]);
            return h;
        }
    }
}
