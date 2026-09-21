using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;

// Macro2kInjector inject <pid> <assembly.dll> <namespace> <class> <method>
// Macro2kInjector loadlibrary <pid> <native.dll>
// Macro2kInjector launchlibrary <exe> <native.dll> <arguments>
//
// Prints one line: "ok" or "err <message>". Exit code 0 on success.
//
// "inject" (Mono games): resolve the game's mono-2.0-*.dll exports (loaded locally to get the
// offsets), copy the assembly and a small x64 stub into the game, and run the stub on a remote
// thread:
//   mono_thread_attach(mono_get_root_domain())
//   image = mono_image_open_from_data(bytes)  ->  assembly = mono_assembly_load_from_full(image)
//   class = mono_class_from_name(...)         ->  mono_runtime_invoke(class.method)
//   mono_thread_detach(thread)
// The invoked method must be public static void with no parameters.
//
// "loadlibrary" (IL2CPP games, which have no managed runtime to load an assembly into): the
// classic CreateRemoteThread(LoadLibraryW) injection of a native DLL; its DllMain does the rest
// (see vendor/unity_bridge/src/Macro2kBridge.Il2Cpp/bridge.cpp).
internal static class Program
{
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length == 6 && args[0] == "inject")
            {
                string result = Injector.Inject(int.Parse(args[1]), args[2], args[3], args[4], args[5]);
                Console.WriteLine(result == null ? "ok" : "err " + result);
                return result == null ? 0 : 1;
            }
            if (args.Length == 3 && args[0] == "loadlibrary")
            {
                string result = Injector.LoadLibraryInto(int.Parse(args[1]), args[2]);
                Console.WriteLine(result == null ? "ok" : "err " + result);
                return result == null ? 0 : 1;
            }
            if (args.Length == 4 && args[0] == "launchlibrary")
            {
                int pid;
                string result = Injector.LaunchWithLibrary(args[1], args[2], args[3], out pid);
                Console.WriteLine(result == null ? "ok " + pid : "err " + result);
                return result == null ? 0 : 1;
            }
            Console.WriteLine("err usage: Macro2kInjector inject <pid> <assembly.dll> <namespace> <class> <method>"
                              + " | Macro2kInjector loadlibrary <pid> <native.dll>"
                              + " | Macro2kInjector launchlibrary <exe> <native.dll> <arguments>");
            return 2;
        }
        catch (Exception e)
        {
            Console.WriteLine("err " + e.Message);
            return 1;
        }
    }
}

internal static class Injector
{
    private static readonly string[] Exports =
    {
        "mono_get_root_domain", "mono_thread_attach", "mono_thread_detach", "mono_image_open_from_data",
        "mono_assembly_load_from_full", "mono_assembly_get_image", "mono_class_from_name",
        "mono_class_get_method_from_name", "mono_runtime_invoke",
    };

    // 8-byte slots in the data block
    private const int SlotRoot = 0, SlotThread = 8, SlotImage = 16, SlotAssembly = 24, SlotImage2 = 32,
        SlotClass = 40, SlotMethod = 48, SlotExc = 56, SlotStatus = 64, DataSize = 128;

    public static string LaunchWithLibrary(string exePath, string dllPath, string arguments, out int pid)
    {
        pid = 0;
        exePath = Path.GetFullPath(exePath);
        if (!File.Exists(exePath)) return "executable not found: " + exePath;
        dllPath = Path.GetFullPath(dllPath);
        if (!File.Exists(dllPath)) return "DLL not found: " + dllPath;

        var startup = new NativeMethods.STARTUPINFO();
        startup.cb = Marshal.SizeOf(typeof(NativeMethods.STARTUPINFO));
        NativeMethods.PROCESS_INFORMATION process;
        string commandLine = QuoteArgument(exePath) + (string.IsNullOrWhiteSpace(arguments) ? "" : " " + arguments);
        var command = new StringBuilder(commandLine);
        if (!NativeMethods.CreateProcess(exePath, command, IntPtr.Zero, IntPtr.Zero, false,
                NativeMethods.CREATE_SUSPENDED, IntPtr.Zero, Path.GetDirectoryName(exePath),
                ref startup, out process))
            return "CreateProcess failed: " + new Win32Exception().Message;

        pid = unchecked((int)process.dwProcessId);
        try
        {
            string error = LoadLibraryInto(pid, dllPath);
            if (error != null)
            {
                NativeMethods.TerminateProcess(process.hProcess, 1);
                pid = 0;
                return error;
            }
            if (NativeMethods.ResumeThread(process.hThread) == uint.MaxValue)
            {
                string errorText = "ResumeThread failed: " + new Win32Exception().Message;
                NativeMethods.TerminateProcess(process.hProcess, 1);
                pid = 0;
                return errorText;
            }
            return null;
        }
        finally
        {
            NativeMethods.CloseHandle(process.hThread);
            NativeMethods.CloseHandle(process.hProcess);
        }
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    /// <summary>Classic CreateRemoteThread(LoadLibraryA) injection of a native DLL (IL2CPP games).</summary>
    public static string LoadLibraryInto(int pid, string dllPath)
    {
        dllPath = Path.GetFullPath(dllPath);
        if (!File.Exists(dllPath)) return "DLL not found: " + dllPath;

        IntPtr kernel32 = NativeMethods.GetModuleHandle("kernel32.dll");
        IntPtr loadLibraryA = kernel32 != IntPtr.Zero ? NativeMethods.GetProcAddress(kernel32, "LoadLibraryA") : IntPtr.Zero;
        if (loadLibraryA == IntPtr.Zero) return "LoadLibraryA not found in kernel32.dll";

        IntPtr h = NativeMethods.OpenProcess(NativeMethods.PROCESS_ALL_ACCESS, false, pid);
        if (h == IntPtr.Zero) return "OpenProcess failed: " + new Win32Exception().Message + " (run as the same user / administrator)";
        try
        {
            // Match the proven amriHook path exactly. LoadLibraryW is normally equivalent, but this
            // game's loader accepts the ANSI remote-thread path while rejecting the wide variant.
            byte[] pathBytes = Encoding.Default.GetBytes(dllPath + "\0");
            IntPtr pathAddr = NativeMethods.VirtualAllocEx(h, IntPtr.Zero, (UIntPtr)(uint)pathBytes.Length,
                NativeMethods.MEM_COMMIT | NativeMethods.MEM_RESERVE, NativeMethods.PAGE_READWRITE);
            if (pathAddr == IntPtr.Zero) return "VirtualAllocEx failed: " + new Win32Exception().Message;
            try
            {
                UIntPtr written;
                if (!NativeMethods.WriteProcessMemory(h, pathAddr, pathBytes, (UIntPtr)(uint)pathBytes.Length, out written))
                    return "WriteProcessMemory failed: " + new Win32Exception().Message;

                uint tid;
                IntPtr thread = NativeMethods.CreateRemoteThread(h, IntPtr.Zero, 0, loadLibraryA, pathAddr, 0, out tid);
                if (thread == IntPtr.Zero) return "CreateRemoteThread failed: " + new Win32Exception().Message;
                try
                {
                    uint wait = NativeMethods.WaitForSingleObject(thread, 30000);
                    if (wait != 0) return "LoadLibrary did not finish in 30 s (game busy?)";
                    uint exitCode;
                    NativeMethods.GetExitCodeThread(thread, out exitCode);
                    // LoadLibraryA's return value (the loaded module handle, or 0 on failure) becomes the thread's exit code.
                    if (exitCode == 0) return "LoadLibrary failed inside the game process (bad DLL, missing dependency, or a load-time crash).";
                    // A non-zero remote-thread exit code is not sufficient: an exception status is also non-zero,
                    // and security software can unload a newly loaded module immediately after LoadLibrary returns.
                    // Confirm that Windows still reports the requested DLL in the target process.
                    string verifyError = VerifyModuleLoaded(pid, dllPath);
                    if (verifyError != null) return verifyError + " (remote thread exit code 0x" + exitCode.ToString("X8") + ")";
                    return null;
                }
                finally
                {
                    NativeMethods.CloseHandle(thread);
                }
            }
            finally
            {
                NativeMethods.VirtualFreeEx(h, pathAddr, UIntPtr.Zero, NativeMethods.MEM_RELEASE);
            }
        }
        finally
        {
            NativeMethods.CloseHandle(h);
        }
    }

    private static string VerifyModuleLoaded(int pid, string dllPath)
    {
        string expected = Path.GetFullPath(dllPath);
        Exception lastError = null;
        for (int attempt = 0; attempt < 10; attempt++)
        {
            try
            {
                Process process = Process.GetProcessById(pid);
                process.Refresh();
                foreach (ProcessModule module in process.Modules)
                {
                    if (string.Equals(Path.GetFullPath(module.FileName), expected, StringComparison.OrdinalIgnoreCase))
                        return null;
                }
            }
            catch (Exception e) when (e is Win32Exception || e is InvalidOperationException)
            {
                lastError = e;
            }
            System.Threading.Thread.Sleep(100);
        }
        if (lastError != null)
            return "LoadLibrary returned success, but the loaded module could not be verified: " + lastError.Message;
        return "the remote loader returned a non-zero value, but the DLL is not present in the target process";
    }

    public static string Inject(int pid, string dllPath, string ns, string cls, string method)
    {
        if (!File.Exists(dllPath)) return "assembly not found: " + dllPath;
        byte[] assembly = File.ReadAllBytes(dllPath);

        Process process = Process.GetProcessById(pid);
        ProcessModule mono = process.Modules.Cast<ProcessModule>().FirstOrDefault(m =>
        {
            string n = m.ModuleName.ToLowerInvariant();
            return n == "mono.dll" || (n.StartsWith("mono-2.0-") && n.EndsWith(".dll"));
        });
        if (mono == null) return "no Mono runtime in the process (IL2CPP game?)";

        // exports: load the same DLL locally without running it, remote address = remote base + local offset
        IntPtr lib = NativeMethods.LoadLibraryEx(mono.FileName, IntPtr.Zero, NativeMethods.DONT_RESOLVE_DLL_REFERENCES);
        if (lib == IntPtr.Zero) return "cannot read " + mono.FileName;
        var fn = new Dictionary<string, long>();
        foreach (string name in Exports)
        {
            IntPtr local = NativeMethods.GetProcAddress(lib, name);
            if (local == IntPtr.Zero) return "Mono export missing: " + name;
            fn[name] = mono.BaseAddress.ToInt64() + (local.ToInt64() - lib.ToInt64());
        }

        IntPtr h = NativeMethods.OpenProcess(NativeMethods.PROCESS_ALL_ACCESS, false, pid);
        if (h == IntPtr.Zero) return "OpenProcess failed: " + new Win32Exception().Message + " (run as the same user / administrator)";
        var allocations = new List<IntPtr>();
        try
        {
            IntPtr bytesAddr = Alloc(h, assembly.Length, false, allocations);
            Write(h, bytesAddr, assembly);
            byte[] strings = new byte[0];
            var offsets = new Dictionary<string, int>();
            using (var ms = new MemoryStream())
            {
                foreach (string s in new[] { "", ns, cls, method })
                {
                    offsets[s] = (int)ms.Length;
                    byte[] b = Encoding.UTF8.GetBytes(s);
                    ms.Write(b, 0, b.Length);
                    ms.WriteByte(0);
                }
                strings = ms.ToArray();
            }
            IntPtr strAddr = Alloc(h, strings.Length, false, allocations);
            Write(h, strAddr, strings);
            IntPtr data = Alloc(h, DataSize, false, allocations);
            Write(h, data, new byte[DataSize]);

            long d = data.ToInt64();
            long str(string s) { return strAddr.ToInt64() + offsets[s]; }

            var a = new Asm();
            a.Prolog();
            a.CallImm(fn["mono_get_root_domain"]);
            a.StoreRax(d + SlotRoot);
            a.LoadSlot(Asm.Rcx, d + SlotRoot);
            a.CallImm(fn["mono_thread_attach"]);
            a.StoreRax(d + SlotThread);

            a.SetImm(Asm.Rcx, bytesAddr.ToInt64());
            a.SetImm(Asm.Rdx, assembly.Length);
            a.SetImm(Asm.R8, 1);                       // need_copy
            a.SetImm(Asm.R9, d + SlotStatus);
            a.CallImm(fn["mono_image_open_from_data"]);
            a.StoreRax(d + SlotImage);
            a.JumpIfRaxZero();

            a.LoadSlot(Asm.Rcx, d + SlotImage);
            a.SetImm(Asm.Rdx, str(""));
            a.SetImm(Asm.R8, d + SlotStatus);
            a.SetImm(Asm.R9, 0);                       // refonly
            a.CallImm(fn["mono_assembly_load_from_full"]);
            a.StoreRax(d + SlotAssembly);
            a.JumpIfRaxZero();

            a.LoadSlot(Asm.Rcx, d + SlotAssembly);
            a.CallImm(fn["mono_assembly_get_image"]);
            a.StoreRax(d + SlotImage2);
            a.JumpIfRaxZero();

            a.LoadSlot(Asm.Rcx, d + SlotImage2);
            a.SetImm(Asm.Rdx, str(ns));
            a.SetImm(Asm.R8, str(cls));
            a.CallImm(fn["mono_class_from_name"]);
            a.StoreRax(d + SlotClass);
            a.JumpIfRaxZero();

            a.LoadSlot(Asm.Rcx, d + SlotClass);
            a.SetImm(Asm.Rdx, str(method));
            a.SetImm(Asm.R8, 0);                       // any parameter count is fine for 0
            a.CallImm(fn["mono_class_get_method_from_name"]);
            a.StoreRax(d + SlotMethod);
            a.JumpIfRaxZero();

            a.LoadSlot(Asm.Rcx, d + SlotMethod);
            a.SetImm(Asm.Rdx, 0);
            a.SetImm(Asm.R8, 0);
            a.SetImm(Asm.R9, d + SlotExc);
            a.CallImm(fn["mono_runtime_invoke"]);

            a.Label();                                 // end: detach the thread again
            a.LoadSlot(Asm.Rcx, d + SlotThread);
            a.CallImm(fn["mono_thread_detach"]);
            a.Epilog();
            byte[] code = a.ToBytes();

            IntPtr codeAddr = Alloc(h, code.Length, true, allocations);
            Write(h, codeAddr, code);

            uint tid;
            IntPtr thread = NativeMethods.CreateRemoteThread(h, IntPtr.Zero, 0, codeAddr, IntPtr.Zero, 0, out tid);
            if (thread == IntPtr.Zero) return "CreateRemoteThread failed: " + new Win32Exception().Message;
            uint wait = NativeMethods.WaitForSingleObject(thread, 30000);
            NativeMethods.CloseHandle(thread);
            if (wait != 0) return "the injected stub did not finish in 30 s (game busy?)";

            byte[] result = Read(h, data, DataSize);
            long V(int slot) { return BitConverter.ToInt64(result, slot); }
            if (V(SlotImage) == 0) return "mono_image_open_from_data failed (status " + BitConverter.ToInt32(result, SlotStatus) + ")";
            if (V(SlotAssembly) == 0) return "mono_assembly_load_from_full failed (status " + BitConverter.ToInt32(result, SlotStatus) + ")";
            if (V(SlotClass) == 0) return "class not found: " + ns + "." + cls;
            if (V(SlotMethod) == 0) return "method not found: " + method;
            if (V(SlotExc) != 0) return "the entry method threw an exception (see the log written by the assembly)";
            return null;
        }
        finally
        {
            // the code/data/strings can go; the assembly bytes were copied by Mono (need_copy = 1)
            foreach (IntPtr p in allocations) NativeMethods.VirtualFreeEx(h, p, UIntPtr.Zero, NativeMethods.MEM_RELEASE);
            NativeMethods.CloseHandle(h);
        }
    }

    private static IntPtr Alloc(IntPtr h, int size, bool exec, List<IntPtr> track)
    {
        IntPtr p = NativeMethods.VirtualAllocEx(h, IntPtr.Zero, (UIntPtr)(uint)size,
            NativeMethods.MEM_COMMIT | NativeMethods.MEM_RESERVE, exec ? NativeMethods.PAGE_EXECUTE_READWRITE : NativeMethods.PAGE_READWRITE);
        if (p == IntPtr.Zero) throw new Win32Exception("VirtualAllocEx failed");
        track.Add(p);
        return p;
    }

    private static void Write(IntPtr h, IntPtr addr, byte[] bytes)
    {
        UIntPtr n;
        if (!NativeMethods.WriteProcessMemory(h, addr, bytes, (UIntPtr)(uint)bytes.Length, out n))
            throw new Win32Exception("WriteProcessMemory failed");
    }

    private static byte[] Read(IntPtr h, IntPtr addr, int size)
    {
        byte[] buf = new byte[size];
        UIntPtr n;
        if (!NativeMethods.ReadProcessMemory(h, addr, buf, (UIntPtr)(uint)size, out n))
            throw new Win32Exception("ReadProcessMemory failed");
        return buf;
    }

    /// <summary>Tiny x64 (Windows ABI) emitter: only rax/rcx/rdx/r8-r10, all caller-saved.</summary>
    private sealed class Asm
    {
        public const int Rcx = 0, Rdx = 1, R8 = 2, R9 = 3;
        private readonly List<byte> _b = new List<byte>();
        private readonly List<int> _jumps = new List<int>(); // offsets of rel32 fields to patch to the end label
        private int _label = -1;

        public void Prolog() { _b.AddRange(new byte[] { 0x48, 0x83, 0xEC, 0x38 }); }  // sub rsp,0x38 (shadow space + alignment)
        public void Epilog() { _b.AddRange(new byte[] { 0x48, 0x83, 0xC4, 0x38, 0xC3 }); } // add rsp,0x38 ; ret

        public void SetImm(int reg, long v)
        {
            switch (reg)
            {
                case Rcx: _b.AddRange(new byte[] { 0x48, 0xB9 }); break;
                case Rdx: _b.AddRange(new byte[] { 0x48, 0xBA }); break;
                case R8: _b.AddRange(new byte[] { 0x49, 0xB8 }); break;
                default: _b.AddRange(new byte[] { 0x49, 0xB9 }); break;
            }
            _b.AddRange(BitConverter.GetBytes(v));
        }

        public void LoadSlot(int reg, long addr)
        {
            _b.AddRange(new byte[] { 0x49, 0xBA }); _b.AddRange(BitConverter.GetBytes(addr)); // mov r10, addr
            switch (reg)
            {
                case Rcx: _b.AddRange(new byte[] { 0x49, 0x8B, 0x0A }); break;   // mov rcx,[r10]
                case Rdx: _b.AddRange(new byte[] { 0x49, 0x8B, 0x12 }); break;
                case R8: _b.AddRange(new byte[] { 0x4D, 0x8B, 0x02 }); break;
                default: _b.AddRange(new byte[] { 0x4D, 0x8B, 0x0A }); break;
            }
        }

        public void StoreRax(long addr)
        {
            _b.AddRange(new byte[] { 0x49, 0xBA }); _b.AddRange(BitConverter.GetBytes(addr)); // mov r10, addr
            _b.AddRange(new byte[] { 0x49, 0x89, 0x02 });                                     // mov [r10], rax
        }

        public void CallImm(long target)
        {
            _b.AddRange(new byte[] { 0x48, 0xB8 }); _b.AddRange(BitConverter.GetBytes(target)); // mov rax, target
            _b.AddRange(new byte[] { 0xFF, 0xD0 });                                             // call rax
        }

        public void JumpIfRaxZero()
        {
            _b.AddRange(new byte[] { 0x48, 0x85, 0xC0, 0x0F, 0x84 }); // test rax,rax ; jz rel32
            _jumps.Add(_b.Count);
            _b.AddRange(new byte[] { 0, 0, 0, 0 });
        }

        public void Label() { _label = _b.Count; }

        public byte[] ToBytes()
        {
            byte[] code = _b.ToArray();
            foreach (int at in _jumps) Array.Copy(BitConverter.GetBytes(_label - (at + 4)), 0, code, at, 4);
            return code;
        }
    }
}

internal static class NativeMethods
{
    public const uint PROCESS_ALL_ACCESS = 0x1F0FFF;
    public const uint MEM_COMMIT = 0x1000, MEM_RESERVE = 0x2000, MEM_RELEASE = 0x8000;
    public const uint PAGE_READWRITE = 0x04, PAGE_EXECUTE_READWRITE = 0x40;
    public const uint DONT_RESOLVE_DLL_REFERENCES = 0x1;
    public const uint CREATE_SUSPENDED = 0x00000004;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct STARTUPINFO
    {
        public int cb;
        public string lpReserved;
        public string lpDesktop;
        public string lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct PROCESS_INFORMATION
    {
        public IntPtr hProcess, hThread;
        public uint dwProcessId, dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr VirtualAllocEx(IntPtr h, IntPtr addr, UIntPtr size, uint type, uint protect);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool VirtualFreeEx(IntPtr h, IntPtr addr, UIntPtr size, uint type);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool WriteProcessMemory(IntPtr h, IntPtr addr, byte[] buf, UIntPtr size, out UIntPtr written);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, UIntPtr size, out UIntPtr read);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern IntPtr CreateRemoteThread(IntPtr h, IntPtr attr, uint stack, IntPtr start, IntPtr param, uint flags, out uint id);
    [DllImport("kernel32.dll")] public static extern uint WaitForSingleObject(IntPtr h, uint ms);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, SetLastError = true)] public static extern IntPtr GetProcAddress(IntPtr lib, string name);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] public static extern IntPtr GetModuleHandle(string name);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool GetExitCodeThread(IntPtr thread, out uint exitCode);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern bool CreateProcess(string applicationName, StringBuilder commandLine,
        IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles, uint creationFlags,
        IntPtr environment, string currentDirectory, ref STARTUPINFO startupInfo,
        out PROCESS_INFORMATION processInformation);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)] public static extern bool TerminateProcess(IntPtr process, uint exitCode);
}
