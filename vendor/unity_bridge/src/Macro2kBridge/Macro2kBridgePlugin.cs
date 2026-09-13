using BepInEx;
using BepInEx.Configuration;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// BepInEx entry point. Reads config, owns the <see cref="InputBridge"/> and
    /// drives it from Unity's main thread.
    /// </summary>
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class Macro2kBridgePlugin : BaseUnityPlugin
    {
        public const string PluginGuid = "com.macro2k.unitybridge";
        public const string PluginName = "Macro2k Unity Bridge";
        public const string PluginVersion = "1.1.0";

        private InputBridge _bridge;

        private void Awake()
        {
            ConfigEntry<int> port = Config.Bind("Bridge", "Port", 17820,
                "TCP port on 127.0.0.1 that Macro2k connects to.");
            ConfigEntry<bool> ignoreFocus = Config.Bind("Bridge", "IgnoreFocus", true,
                "Let Unity's EventSystem / Input System process input while the game window is unfocused.");

            _bridge = new InputBridge(this, Logger, port.Value, ignoreFocus.Value);
            _bridge.Start();
        }

        private void Update()
        {
            _bridge?.Tick();
        }

        private void OnDestroy()
        {
            _bridge?.Stop();
        }
    }
}
