using System;
using System.Collections.Generic;
using System.Reflection;
using System.Runtime.InteropServices;
using UnityEngine;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// Makes the legacy Input manager agree with what the bridge simulates.
    ///
    /// Many games (Star Savior's NKCUIComButton) ignore IPointerUp/Click and poll
    /// Input.GetMouseButtonUp(0) every frame to finish a press, so EventSystem events alone never
    /// complete a click; others read keys with Input.GetKey*. There is no Harmony in an injected
    /// build, so this hooks the JIT'd wrappers of the UnityEngine.Input members itself: 12 bytes at
    /// the entry become `mov rax, hook; jmp rax`, and the displaced prologue is copied to a
    /// trampoline so a hook can still ask the real Input. Hooks exist only while something is
    /// simulated (a tap in flight, a held key) plus a frame or two, then the original bytes are put
    /// back. Unity's frame semantics are kept: Down is visible on the frame after the command, Up
    /// on the frame after the release. Main thread only. x64 only.
    ///
    /// Limits: a caller that inlined the wrapper before the hook was installed keeps calling the
    /// original; the trampoline needs the usual Mono prologue (push rbp; mov rbp,rsp; sub rsp,N;
    /// mov [rbp+d],reg) and without it a hook can't consult the real input and reports only the
    /// simulated state.
    /// </summary>
    internal static unsafe class LegacyInput
    {
        private const int NoFrame = 0x7FFFFFFF; // int.MaxValue is stripped from Unity 6 games
        private const int PatchSize = 12;       // mov rax, imm64 (10) + jmp rax (2)
        private const int PrologueRead = 32;    // bytes read to find a whole-instruction boundary >= PatchSize
        private const int KeepFrames = 2;
        private const bool Diagnostics = false;

        private sealed class Hook
        {
            public MethodBase Target;
            public MethodBase Replacement;
            public IntPtr Address;
            public readonly byte[] Original = new byte[PatchSize];
            public byte[] Prologue;             // Original plus the rest of the last displaced instruction
            public IntPtr Trampoline;
            public bool Applied;
        }

        // simulated mouse
        private static bool _held;
        private static int _downFrame = NoFrame;
        private static int _upFrame = -1;
        private static int _mouseRestoreFrame = NoFrame;
        private static Vector3 _pos;

        // simulated keys
        private static int _keysEventFrame = -1;

        private static Hook[] _mouseHooks, _keyHooks;
        private static Hook _hMouse, _hMouseDown, _hMouseUp, _hMousePos, _hKey, _hKeyDown, _hKeyUp, _hAxis, _hAxisRaw;
        private static bool _mouseUnavailable, _keysUnavailable;

        // ── mouse ───────────────────────────────────────────────────────────────────────────

        /// <summary>A simulated press started at screenPos (Unity screen space).</summary>
        public static bool MouseBegin(Vector2 screenPos)
        {
            if (!InstallMouse()) return false;
            _pos = screenPos;
            _held = true;
            _downFrame = Time.frameCount + 1;
            _upFrame = -1;
            _mouseRestoreFrame = NoFrame;
            if (Diagnostics) ManualLogSource.Write("Debug", "mouse begin frame=" + Time.frameCount + " down=" + _downFrame + " pos=" + _pos);
            return true;
        }

        public static void MouseMove(Vector2 screenPos)
        {
            _pos = screenPos;
        }

        /// <summary>The simulated release; Up is reported on the next frame.</summary>
        public static void MouseEnd()
        {
            if (!_held) return;
            _held = false;
            _upFrame = Math.Max(Time.frameCount + 1, _downFrame + 1);
            _mouseRestoreFrame = _upFrame + 1;
            if (Diagnostics) ManualLogSource.Write("Debug", "mouse end frame=" + Time.frameCount + " up=" + _upFrame);
        }

        // ── keys ────────────────────────────────────────────────────────────────────────────

        /// <summary>KeyInjector pressed or released something: make sure the key hooks are in.</summary>
        public static void KeysChanged()
        {
            _keysEventFrame = Time.frameCount;
            InstallKeys();
        }

        // ── lifecycle ───────────────────────────────────────────────────────────────────────

        /// <summary>Every frame: give the real Input back once the last simulated edge has been seen.</summary>
        public static void Tick()
        {
            if (_mouseHooks != null && !_held && Time.frameCount >= _mouseRestoreFrame) UninstallMouse();
            if (_keyHooks != null && !KeyInjector.Busy && Time.frameCount > _keysEventFrame + KeepFrames) UninstallKeys();
        }

        public static void Shutdown()
        {
            _held = false;
            UninstallMouse();
            UninstallKeys();
        }

        // ── mouse hooks (same signatures as the UnityEngine.Input members) ───────────────────

        private static bool GetMouseButtonHook(int button)
        {
            return (button == 0 && _held && Time.frameCount >= _downFrame) || RealBool(_hMouse, button);
        }

        private static bool GetMouseButtonDownHook(int button)
        {
            return (button == 0 && Time.frameCount == _downFrame) || RealBool(_hMouseDown, button);
        }

        private static bool GetMouseButtonUpHook(int button)
        {
            bool sim = button == 0 && Time.frameCount == _upFrame;
            if (Diagnostics && sim) ManualLogSource.Write("Debug", "GetMouseButtonUp -> true (sim) frame=" + Time.frameCount);
            return sim || RealBool(_hMouseUp, button);
        }

        private static Vector3 MousePositionHook()
        {
            // the simulated pointer owns the position from the press until the frame after the release
            if (_held || Time.frameCount <= _upFrame) return _pos;
            return _hMousePos != null && _hMousePos.Trampoline != IntPtr.Zero
                ? ((delegate*<Vector3>)_hMousePos.Trampoline)()
                : _pos;
        }

        // ── key hooks ────────────────────────────────────────────────────────────────────────

        private static bool GetKeyHook(KeyCode key)
        {
            return KeyInjector.SimHeld(key) || RealKey(_hKey, key);
        }

        private static bool GetKeyDownHook(KeyCode key)
        {
            return KeyInjector.SimDown(key) || RealKey(_hKeyDown, key);
        }

        private static bool GetKeyUpHook(KeyCode key)
        {
            return KeyInjector.SimUp(key) || RealKey(_hKeyUp, key);
        }

        private static float GetAxisHook(string axisName)
        {
            float real = RealAxis(_hAxis, axisName);
            return real != 0f ? real : KeyInjector.SimAxis(axisName);
        }

        private static float GetAxisRawHook(string axisName)
        {
            float real = RealAxis(_hAxisRaw, axisName);
            return real != 0f ? real : KeyInjector.SimAxis(axisName);
        }

        private static bool RealBool(Hook h, int arg)
        {
            return h != null && h.Trampoline != IntPtr.Zero && ((delegate*<int, bool>)h.Trampoline)(arg);
        }

        private static bool RealKey(Hook h, KeyCode key)
        {
            return h != null && h.Trampoline != IntPtr.Zero && ((delegate*<KeyCode, bool>)h.Trampoline)(key);
        }

        private static float RealAxis(Hook h, string name)
        {
            return h != null && h.Trampoline != IntPtr.Zero ? ((delegate*<string, float>)h.Trampoline)(name) : 0f;
        }

        // ── install / uninstall ──────────────────────────────────────────────────────────────

        private static bool InstallMouse()
        {
            if (_mouseUnavailable) return false;
            try
            {
                if (_mouseHooks == null)
                {
                    var list = new List<Hook>();
                    Type[] intArg = { typeof(int) };
                    _hMouse = Add(list, typeof(Input).GetMethod("GetMouseButton", intArg), "GetMouseButtonHook");
                    _hMouseDown = Add(list, typeof(Input).GetMethod("GetMouseButtonDown", intArg), "GetMouseButtonDownHook");
                    _hMouseUp = Add(list, typeof(Input).GetMethod("GetMouseButtonUp", intArg), "GetMouseButtonUpHook");
                    PropertyInfo position = typeof(Input).GetProperty("mousePosition", BindingFlags.Public | BindingFlags.Static);
                    _hMousePos = Add(list, position != null ? position.GetGetMethod() : null, "MousePositionHook");
                    if (list.Count == 0) throw new InvalidOperationException("no Input mouse members found");
                    _mouseHooks = list.ToArray();
                }
                Apply(_mouseHooks);
                return true;
            }
            catch (Exception e)
            {
                _mouseUnavailable = true;
                ManualLogSource.Write("Warning", "Legacy mouse hooks unavailable: " + e.Message);
                UninstallMouse();
                return false;
            }
        }

        private static bool InstallKeys()
        {
            if (_keysUnavailable) return false;
            try
            {
                if (_keyHooks == null)
                {
                    var list = new List<Hook>();
                    Type[] keyArg = { typeof(KeyCode) };
                    Type[] axisArg = { typeof(string) };
                    _hKey = Add(list, typeof(Input).GetMethod("GetKey", keyArg), "GetKeyHook");
                    _hKeyDown = Add(list, typeof(Input).GetMethod("GetKeyDown", keyArg), "GetKeyDownHook");
                    _hKeyUp = Add(list, typeof(Input).GetMethod("GetKeyUp", keyArg), "GetKeyUpHook");
                    _hAxis = Add(list, typeof(Input).GetMethod("GetAxis", axisArg), "GetAxisHook");
                    _hAxisRaw = Add(list, typeof(Input).GetMethod("GetAxisRaw", axisArg), "GetAxisRawHook");
                    if (list.Count == 0) throw new InvalidOperationException("no Input key members found");
                    _keyHooks = list.ToArray();
                }
                Apply(_keyHooks);
                return true;
            }
            catch (Exception e)
            {
                _keysUnavailable = true;
                ManualLogSource.Write("Warning", "Legacy key hooks unavailable: " + e.Message);
                UninstallKeys();
                return false;
            }
        }

        private static Hook Add(List<Hook> list, MethodBase target, string replacementName)
        {
            if (target == null) return null;
            var h = new Hook
            {
                Target = target,
                Replacement = typeof(LegacyInput).GetMethod(replacementName, BindingFlags.NonPublic | BindingFlags.Static),
                Address = CodeAddress(target),
            };
            Marshal.Copy(h.Address, h.Original, 0, PatchSize);
            var head = new byte[PrologueRead];
            Marshal.Copy(h.Address, head, 0, PrologueRead);
            h.Prologue = head;
            h.Trampoline = MakeTrampoline(h.Address, head);
            ManualLogSource.Write("Info", "Input." + target.Name + " entry " + BitConverter.ToString(h.Original)
                                          + (h.Trampoline == IntPtr.Zero ? " (no trampoline: unknown prologue)" : ""));
            list.Add(h);
            return h;
        }

        private static void Apply(Hook[] hooks)
        {
            foreach (Hook h in hooks)
            {
                if (h.Applied) continue;
                long hook = CodeAddress(h.Replacement).ToInt64();
                var code = new byte[PatchSize];
                code[0] = 0x48; code[1] = 0xB8;           // mov rax, imm64
                Array.Copy(BitConverter.GetBytes(hook), 0, code, 2, 8);
                code[10] = 0xFF; code[11] = 0xE0;         // jmp rax
                Write(h.Address, code);
                h.Applied = true;
            }
        }

        private static void UninstallMouse()
        {
            Restore(_mouseHooks);
            _mouseHooks = null;
            _hMouse = _hMouseDown = _hMouseUp = _hMousePos = null;
            _downFrame = NoFrame;
            _upFrame = -1;
            _mouseRestoreFrame = NoFrame;
        }

        private static void UninstallKeys()
        {
            Restore(_keyHooks);
            _keyHooks = null;
            _hKey = _hKeyDown = _hKeyUp = _hAxis = _hAxisRaw = null;
        }

        private static void Restore(Hook[] hooks)
        {
            if (hooks == null) return;
            foreach (Hook h in hooks)
            {
                if (h.Applied)
                {
                    try { Write(h.Address, h.Original); }
                    catch (Exception e) { ManualLogSource.Write("Error", "Restoring Input." + h.Target.Name + " failed: " + e.Message); }
                    h.Applied = false;
                }
                if (h.Trampoline != IntPtr.Zero)
                {
                    VirtualFree(h.Trampoline, UIntPtr.Zero, 0x8000); // MEM_RELEASE
                    h.Trampoline = IntPtr.Zero;
                }
            }
        }

        /// <summary>
        /// Length of the Mono JIT prologue push rbp; mov rbp,rsp; sub rsp,(imm8|imm32); mov [rbp+disp8],reg
        /// (12 or 15 bytes, whole instructions, no rip-relative operands), or -1 for anything else.
        /// </summary>
        private static int PrologueLength(byte[] b)
        {
            if (b[0] != 0x55 || b[1] != 0x48 || b[2] != 0x8B || b[3] != 0xEC) return -1;
            int next;
            if (b[4] == 0x48 && b[5] == 0x83 && b[6] == 0xEC) next = 8;        // sub rsp, imm8
            else if (b[4] == 0x48 && b[5] == 0x81 && b[6] == 0xEC) next = 11;  // sub rsp, imm32
            else return -1;
            if (b[next] != 0x48 || b[next + 1] != 0x89 || (b[next + 2] & 0xC7) != 0x45) return -1; // mov [rbp+disp8], reg
            return next + 4;
        }

        /// <summary>The displaced prologue plus a jump back into the original body, or Zero for an unknown prologue.</summary>
        private static IntPtr MakeTrampoline(IntPtr target, byte[] head)
        {
            int length = PrologueLength(head);
            if (length < PatchSize) return IntPtr.Zero;

            IntPtr mem = VirtualAlloc(IntPtr.Zero, (UIntPtr)64, 0x3000, 0x40); // MEM_COMMIT|MEM_RESERVE, RWX
            if (mem == IntPtr.Zero) return IntPtr.Zero;
            var code = new byte[64];
            Array.Copy(head, code, length);
            code[length] = 0x48; code[length + 1] = 0xB8;  // mov rax, target+length
            Array.Copy(BitConverter.GetBytes(target.ToInt64() + length), 0, code, length + 2, 8);
            code[length + 10] = 0xFF; code[length + 11] = 0xE0; // jmp rax
            Marshal.Copy(code, 0, mem, code.Length);
            return mem;
        }

        /// <summary>
        /// Address of a method's JIT'd code (for an extern Input member: its native-call wrapper).
        /// RuntimeHelpers.PrepareMethod / GetFunctionPointer are stripped from Unity 6 games, so
        /// this asks the game's Mono runtime directly.
        /// </summary>
        private static IntPtr CodeAddress(MethodBase method)
        {
            IntPtr code = mono_compile_method(method.MethodHandle.Value);
            if (code == IntPtr.Zero) throw new InvalidOperationException("mono_compile_method failed for " + method.Name);
            return code;
        }

        private static void Write(IntPtr address, byte[] code)
        {
            uint old;
            if (!VirtualProtect(address, (UIntPtr)(uint)code.Length, 0x40, out old))
                throw new InvalidOperationException("VirtualProtect failed");
            Marshal.Copy(code, 0, address, code.Length);
            FlushInstructionCache(GetCurrentProcess(), address, (UIntPtr)(uint)code.Length);
            uint ignored;
            VirtualProtect(address, (UIntPtr)(uint)code.Length, old, out ignored);
        }

        [DllImport("mono-2.0-bdwgc.dll")]
        private static extern IntPtr mono_compile_method(IntPtr method);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool VirtualProtect(IntPtr address, UIntPtr size, uint newProtect, out uint oldProtect);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern IntPtr VirtualAlloc(IntPtr address, UIntPtr size, uint allocationType, uint protect);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool VirtualFree(IntPtr address, UIntPtr size, uint freeType);

        [DllImport("kernel32.dll")]
        private static extern bool FlushInstructionCache(IntPtr process, IntPtr address, UIntPtr size);

        [DllImport("kernel32.dll")]
        private static extern IntPtr GetCurrentProcess();
    }
}
