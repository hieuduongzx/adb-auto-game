using BepInEx;
using BepInEx.Configuration;
using BepInEx.Unity.IL2CPP;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// BepInEx 6 (IL2CPP) entry point. Reads config, owns the
    /// <see cref="InputBridge"/> and hands it to a hidden component that drives it
    /// from Unity's main thread every frame.
    /// </summary>
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class Macro2kBridgePlugin : BasePlugin
    {
        public const string PluginGuid = "com.macro2k.unitybridge";
        public const string PluginName = "Macro2k Unity Bridge";
        public const string PluginVersion = "1.1.0";

        private InputBridge _bridge;

        public override void Load()
        {
            ConfigEntry<int> port = Config.Bind("Bridge", "Port", 17820,
                "TCP port on 127.0.0.1 that Macro2k connects to.");
            ConfigEntry<bool> ignoreFocus = Config.Bind("Bridge", "IgnoreFocus", true,
                "Let Unity's EventSystem / Input System process input while the game window is unfocused.");

            _bridge = new InputBridge(Log, port.Value, ignoreFocus.Value);
            if (!_bridge.Start()) return;

            ClassInjector.RegisterTypeInIl2Cpp<BridgeBehaviour>();
            var host = new GameObject("Macro2kBridge") { hideFlags = HideFlags.HideAndDontSave };
            Object.DontDestroyOnLoad(host);
            BridgeBehaviour.Bridge = _bridge;
            host.AddComponent<BridgeBehaviour>();
        }

        public override bool Unload()
        {
            _bridge?.Stop();
            return base.Unload();
        }
    }

    /// <summary>Per-frame driver. Injected into IL2CPP, so it needs the IntPtr constructor.</summary>
    public class BridgeBehaviour : MonoBehaviour
    {
        internal static InputBridge Bridge;

        public BridgeBehaviour(System.IntPtr ptr) : base(ptr) { }

        private void Update()
        {
            Bridge?.Tick();
        }

        private void OnDestroy()
        {
            // HideAndDontSave + DontDestroyOnLoad: only fires when the game quits.
            Bridge?.Stop();
        }
    }
}
