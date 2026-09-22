using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;

namespace Macro2k.UnityBridge
{
    /// <summary>Plugin metadata used by InputBridge (the ping reply).</summary>
    internal static class Macro2kBridgePlugin
    {
        public const string PluginGuid = "com.macro2k.unitybridge";
        public const string PluginVersion = "1.2.0";
    }

    /// <summary>Appends log lines to the Macro2kBridge.log file in %TEMP% (no logging framework in a stripped game).</summary>
    internal sealed class ManualLogSource
    {
        private static readonly object Gate = new object();
        internal static readonly string Path_ = Path.Combine(Path.GetTempPath(), "Macro2kBridge.log");

        public void LogInfo(object message) { Write("Info", message); }
        public void LogWarning(object message) { Write("Warning", message); }
        public void LogError(object message) { Write("Error", message); }

        internal static void Write(string level, object message)
        {
            try
            {
                byte[] line = System.Text.Encoding.UTF8.GetBytes(DateTime.Now.ToString("HH:mm:ss.fff") + " [" + level + "] " + message + "\r\n");
                lock (Gate)
                    using (var fs = new FileStream(Path_, FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
                        fs.Write(line, 0, line.Length); // File.AppendAllText is stripped in Unity 6 games
            }
            catch { }
        }
    }
}

namespace Macro2k.UnityBridge.Inject
{
    /// <summary>
    /// Entry point called by Macro2kInjector on a thread it attached to Mono; that thread is
    /// not Unity's main thread, so the GameObject is created from a main-thread callback.
    /// </summary>
    public static class Loader
    {
        private static readonly ManualLogSource Log = new ManualLogSource();
        private static bool _loaded;
        private static bool _created;
        private static InputBridge _bridge;

        public static void Load()
        {
            if (_loaded) return;
            _loaded = true;
            try
            {
                ManualLogSource.Write("Info", "Macro2k Unity Bridge " + Macro2kBridgePlugin.PluginVersion + " loading (Unity " + Application.unityVersion + ")");
                // Any of these fires on the main thread; Application.onBeforeRender and the
                // Camera callbacks are stripped from Unity 6 games, these three are not.
                // SRP fires every frame; scene loads and focus changes cover other pipelines.
                // Each is its own method so a Unity version without one only loses that hook.
                int hooked = 0;
                if (TryHook("RenderPipelineManager.beginContextRendering", HookSrp)) hooked++;
                if (TryHook("SceneManager.sceneLoaded", HookScene)) hooked++;
                if (TryHook("Application.focusChanged", HookFocus)) hooked++;
                if (hooked == 0) throw new InvalidOperationException("no main-thread hook is available in this Unity version");
            }
            catch (Exception e)
            {
                _loaded = false;
                ManualLogSource.Write("Error", "Load failed: " + e);
                throw;
            }
        }

        /// <summary>Port Macro2k wrote to %TEMP%\Macro2kBridge.port before injecting (default 17820).</summary>
        private static int ReadPort()
        {
            try
            {
                string path = Path.Combine(Path.GetTempPath(), "Macro2kBridge.port");
                if (File.Exists(path))
                {
                    byte[] raw = new byte[32];
                    int n;
                    using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                        n = fs.Read(raw, 0, raw.Length);
                    int port;
                    if (int.TryParse(System.Text.Encoding.ASCII.GetString(raw, 0, n).Trim(), out port) && port > 0 && port < 65536)
                        return port;
                }
            }
            catch { }
            return 17820;
        }

        private static bool TryHook(string name, Action hook)
        {
            try
            {
                hook();
                return true;
            }
            catch (Exception e)
            {
                ManualLogSource.Write("Warning", name + " unavailable: " + e.Message);
                return false;
            }
        }

        private static void HookSrp() { RenderPipelineManager.beginContextRendering += OnContext; }
        private static void HookScene() { SceneManager.sceneLoaded += OnScene; }
        private static void HookFocus() { Application.focusChanged += OnFocus; }
        private static void UnhookSrp() { RenderPipelineManager.beginContextRendering -= OnContext; }
        private static void UnhookScene() { SceneManager.sceneLoaded -= OnScene; }
        private static void UnhookFocus() { Application.focusChanged -= OnFocus; }

        private static void OnContext(ScriptableRenderContext context, List<Camera> cameras) { CreateBehaviour(); }
        private static void OnScene(Scene scene, LoadSceneMode mode) { CreateBehaviour(); }
        private static void OnFocus(bool focus) { CreateBehaviour(); }

        private static void CreateBehaviour()
        {
            if (_created) return;
            _created = true;
            TryHook("unhook SRP", UnhookSrp);
            TryHook("unhook scene", UnhookScene);
            TryHook("unhook focus", UnhookFocus);
            try
            {
                int port = ReadPort();

                var go = new GameObject("Macro2kBridge");
                UnityEngine.Object.DontDestroyOnLoad(go);
                go.hideFlags = HideFlags.HideAndDontSave;
                var behaviour = go.AddComponent<BridgeBehaviour>();
                _bridge = new InputBridge(behaviour, Log, port, true);
                behaviour.Bridge = _bridge;
                _bridge.Start();
            }
            catch (Exception e)
            {
                ManualLogSource.Write("Error", "Start failed: " + e);
            }
        }
    }

    /// <summary>Ticks the bridge on the main thread every frame.</summary>
    public sealed class BridgeBehaviour : MonoBehaviour
    {
        internal InputBridge Bridge;

        private void Update() { if (Bridge != null) Bridge.Tick(); }

        private void OnDestroy() { if (Bridge != null) Bridge.Stop(); }
    }
}
