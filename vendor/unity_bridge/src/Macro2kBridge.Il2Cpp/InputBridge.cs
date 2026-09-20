using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;
using UnityEngine.EventSystems;
using Il2CppRaycastList = Il2CppSystem.Collections.Generic.List<UnityEngine.EventSystems.RaycastResult>;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// Local input bridge for external macros — the IL2CPP (BepInEx 6) build.
    /// Same wire protocol as the Mono build (see ../Macro2kBridge/InputBridge.cs):
    ///   ping | tap x y [holdMs] [refW refH] | swipe x1 y1 x2 y2 [ms] [refW refH]
    ///   key vk [holdMs] | keydown vk | keyup vk|all
    /// Taps/swipes go through Unity's EventSystem (raycast + ExecuteEvents), keys
    /// through Harmony postfixes on the legacy Input manager and, best effort,
    /// the Input System. No cursor, no focus; the window may be covered.
    ///
    /// IL2CPP differences: game objects are Il2CppInterop proxies, coroutines are
    /// stepped by <see cref="Tick"/> instead of MonoBehaviour.StartCoroutine
    /// (managed iterators can't be handed to Unity), and only the main thread may
    /// touch Unity — the socket threads just queue commands.
    /// </summary>
    internal sealed class InputBridge
    {
        private const float DefaultTapHoldMs = 80f;
        private const int TimeoutMarginMs = 5000;

        private readonly ManualLogSource _log;
        private readonly int _port;
        private readonly bool _ignoreFocus;
        private readonly ConcurrentQueue<BridgeCommand> _queue = new ConcurrentQueue<BridgeCommand>();
        private readonly List<Routine> _routines = new List<Routine>();

        private TcpListener _listener;
        private volatile bool _running;
        private bool _focusApplied;
        private int _nextPointerId = -100;

        internal static InputBridge Active { get; private set; }
        internal bool IgnoreFocus => _ignoreFocus && _running;

        public InputBridge(ManualLogSource log, int port, bool ignoreFocus)
        {
            _log = log;
            _port = port;
            _ignoreFocus = ignoreFocus;
        }

        #region Lifecycle

        public bool Start()
        {
            if (_running) return true;
            try
            {
                _listener = new TcpListener(IPAddress.Loopback, _port);
                _listener.Start();
            }
            catch (Exception e)
            {
                _log.LogError($"Cannot listen on 127.0.0.1:{_port} ({e.Message}). " +
                              "Another bridge (or app) may already use this port.");
                _listener = null;
                return false;
            }

            _running = true;
            Active = this;
            // Early (plugin load), before game code calls Input.GetKey.
            KeyInjector.Log = _log;
            KeyInjector.ApplyLegacyPatches();
            new Thread(AcceptLoop) { IsBackground = true, Name = "Macro2kBridge-Accept" }.Start();
            _log.LogInfo($"Listening on 127.0.0.1:{_port}");
            return true;
        }

        public void Stop()
        {
            if (!_running) return;
            _running = false;
            if (Active == this) Active = null;

            try { _listener?.Stop(); } catch { }
            _listener = null;

            while (_queue.TryDequeue(out var cmd)) cmd.Complete("err bridge stopped");
            foreach (Routine r in _routines) r.Cmd.Complete("err bridge stopped");
            _routines.Clear();
            ReleaseAllKeys();
            _log.LogInfo("Stopped");
        }

        /// <summary>Main thread, every frame.</summary>
        public void Tick()
        {
            if (!_running) return;

            // Applied lazily: the Input System settings object may not exist yet
            // when BepInEx loads plugins.
            if (!_focusApplied)
            {
                _focusApplied = true;
                ApplyBackgroundInput();
            }

            // Running routines first: one started this frame takes its first step
            // right away, so its next step must land on the next frame.
            StepRoutines();

            while (_queue.TryDequeue(out var cmd))
            {
                try
                {
                    Execute(cmd);
                }
                catch (Exception e)
                {
                    cmd.Complete("err " + e.Message);
                }
            }
        }

        private sealed class Routine
        {
            public IEnumerator Steps;
            public BridgeCommand Cmd;
        }

        private void Schedule(BridgeCommand cmd, IEnumerator steps)
        {
            var routine = new Routine { Steps = steps, Cmd = cmd };
            if (Step(routine)) _routines.Add(routine);
        }

        private void StepRoutines()
        {
            for (int i = _routines.Count - 1; i >= 0; i--)
            {
                if (!Step(_routines[i])) _routines.RemoveAt(i);
            }
        }

        /// <summary>Advance one frame. Returns false when the routine is finished.</summary>
        private bool Step(Routine routine)
        {
            try
            {
                return routine.Steps.MoveNext();
            }
            catch (Exception e)
            {
                _log.LogWarning($"Command error: {e}");
                routine.Cmd.Complete("err " + e.Message);
                return false;
            }
        }

        #endregion

        #region Background input (focus)

        private void ApplyBackgroundInput()
        {
            if (!_ignoreFocus) return;

            Application.runInBackground = true;

            // UnityEngine.InputSystem.InputSystem.settings.backgroundBehavior = IgnoreFocus
            try
            {
                Type inputSystem = FindType("UnityEngine.InputSystem.InputSystem");
                object settings = inputSystem?.GetProperty("settings", BindingFlags.Public | BindingFlags.Static)?.GetValue(null, null);
                PropertyInfo behavior = settings?.GetType().GetProperty("backgroundBehavior");
                if (behavior != null && Enum.IsDefined(behavior.PropertyType, "IgnoreFocus"))
                {
                    behavior.SetValue(settings, Enum.Parse(behavior.PropertyType, "IgnoreFocus"), null);
                    _log.LogInfo("Input System backgroundBehavior = IgnoreFocus");
                }
            }
            catch (Exception e)
            {
                _log.LogWarning($"Input System settings not changed: {e.Message}");
            }

            // EventSystem.isFocused -> true (uGUI input modules skip input while unfocused)
            try
            {
                MethodInfo getter = AccessTools.PropertyGetter(typeof(EventSystem), "isFocused");
                if (getter == null)
                {
                    _log.LogInfo("EventSystem.isFocused not present in this Unity version; skipped");
                    return;
                }
                var harmony = new Harmony(Macro2kBridgePlugin.PluginGuid);
                harmony.Patch(getter, postfix: new HarmonyMethod(typeof(InputBridgePatches), nameof(InputBridgePatches.IsFocusedPostfix)));
                _log.LogInfo("EventSystem.isFocused patched");
            }
            catch (Exception e)
            {
                _log.LogWarning($"EventSystem.isFocused patch failed: {e.Message}");
            }
        }

        internal static Type FindType(string fullName)
        {
            foreach (Assembly asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    Type t = asm.GetType(fullName, false);
                    if (t != null) return t;
                }
                catch { }
            }
            return null;
        }

        #endregion

        #region Networking (background threads)

        private void AcceptLoop()
        {
            while (_running)
            {
                TcpClient client;
                try
                {
                    client = _listener.AcceptTcpClient();
                }
                catch
                {
                    break; // listener stopped
                }
                ThreadPool.QueueUserWorkItem(_ => HandleClient(client));
            }
        }

        private void HandleClient(TcpClient client)
        {
            try
            {
                using (client)
                using (NetworkStream stream = client.GetStream())
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true, NewLine = "\n" })
                {
                    string line;
                    while (_running && (line = reader.ReadLine()) != null)
                    {
                        writer.WriteLine(Dispatch(line));
                    }
                }
            }
            catch
            {
                // client went away mid-command
            }
        }

        private string Dispatch(string line)
        {
            string[] args = line.Trim().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            if (args.Length == 0) return "err empty";

            var cmd = new BridgeCommand(args);
            _queue.Enqueue(cmd);

            int timeout = EstimateDurationMs(args) + TimeoutMarginMs;
            if (!cmd.Done.Wait(timeout)) return "err timeout (game main thread not running?)";
            return cmd.Result ?? "err no result";
        }

        private static int EstimateDurationMs(string[] args)
        {
            int index;
            switch (args[0].ToLowerInvariant())
            {
                case "tap": index = 3; break;
                case "swipe": index = 5; break;
                case "key": index = 2; break;
                default: return 0;
            }
            return args.Length > index && TryParse(args[index], out float ms) ? Math.Max(0, (int)ms) : 0;
        }

        #endregion

        #region Commands (main thread)

        private void Execute(BridgeCommand cmd)
        {
            string[] a = cmd.Args;
            switch (a[0].ToLowerInvariant())
            {
                case "ping":
                    cmd.Complete($"ok Macro2kBridge {Macro2kBridgePlugin.PluginVersion} {Screen.width} {Screen.height}");
                    return;

                case "tap":
                {
                    if (a.Length < 3 || !TryParse(a[1], out float x) || !TryParse(a[2], out float y))
                    {
                        cmd.Complete("err usage: tap x y [holdMs] [refW refH]");
                        return;
                    }
                    float holdMs = a.Length > 3 && TryParse(a[3], out float h) ? h : DefaultTapHoldMs;
                    Schedule(cmd, TapRoutine(cmd, ToScreen(x, y, a, 4), holdMs / 1000f));
                    return;
                }

                case "swipe":
                {
                    if (a.Length < 5
                        || !TryParse(a[1], out float x1) || !TryParse(a[2], out float y1)
                        || !TryParse(a[3], out float x2) || !TryParse(a[4], out float y2))
                    {
                        cmd.Complete("err usage: swipe x1 y1 x2 y2 [ms] [refW refH]");
                        return;
                    }
                    float ms = a.Length > 5 && TryParse(a[5], out float d) ? d : 300f;
                    Schedule(cmd, SwipeRoutine(cmd, ToScreen(x1, y1, a, 6), ToScreen(x2, y2, a, 6), ms / 1000f));
                    return;
                }

                case "key":
                case "keydown":
                case "keyup":
                    ExecuteKey(cmd);
                    return;

                default:
                    cmd.Complete("err unknown command: " + a[0]);
                    return;
            }
        }

        private void ExecuteKey(BridgeCommand cmd)
        {
            string[] a = cmd.Args;
            string verb = a[0].ToLowerInvariant();
            if (verb == "keyup" && a.Length > 1 && a[1].Equals("all", StringComparison.OrdinalIgnoreCase))
            {
                ReleaseAllKeys();
                cmd.Complete("ok keyup all");
                return;
            }
            if (a.Length < 2 || !int.TryParse(a[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out int vk))
            {
                cmd.Complete($"err usage: {verb} vk" + (verb == "key" ? " [holdMs]" : ""));
                return;
            }
            if (!KeyInjector.TryMap(vk, out KeyInjector.MappedKey key))
            {
                cmd.Complete($"err unsupported key VK {vk}");
                return;
            }

            switch (verb)
            {
                case "keydown":
                    KeyInjector.Press(key);
                    cmd.Complete("ok keydown " + key.Name);
                    return;
                case "keyup":
                    KeyInjector.Release(key);
                    cmd.Complete("ok keyup " + key.Name);
                    return;
                default:
                    float holdMs = a.Length > 2 && TryParse(a[2], out float h) ? h : DefaultTapHoldMs;
                    Schedule(cmd, KeyRoutine(cmd, key, holdMs / 1000f));
                    return;
            }
        }

        private static IEnumerator KeyRoutine(BridgeCommand cmd, KeyInjector.MappedKey key, float holdSeconds)
        {
            try
            {
                KeyInjector.Press(key);
            }
            catch (Exception e)
            {
                cmd.Complete("err " + e.Message);
                yield break;
            }

            float releaseAt = Time.unscaledTime + holdSeconds;
            yield return null; // down and up never share a frame
            while (Time.unscaledTime < releaseAt) yield return null;

            try
            {
                KeyInjector.Release(key);
                cmd.Complete("ok key " + key.Name);
            }
            catch (Exception e)
            {
                cmd.Complete("err " + e.Message);
            }
        }

        private void ReleaseAllKeys()
        {
            try
            {
                KeyInjector.ReleaseAll();
            }
            catch (Exception e)
            {
                _log.LogWarning($"Releasing keys failed: {e.Message}");
            }
        }

        private IEnumerator TapRoutine(BridgeCommand cmd, Vector2 pos, float holdSeconds)
        {
            Pointer p = NewPointer(pos);
            if (p == null) { cmd.Complete("err no EventSystem"); yield break; }

            GameObject target = RaycastUpdate(p);
            if (target == null) { cmd.Complete("miss"); yield break; }
            string path = PathOf(target);

            if (!TryStep(() => PressDown(p, target), cmd)) yield break;

            float releaseAt = Time.unscaledTime + holdSeconds;
            yield return null; // down and up never share a frame
            while (Time.unscaledTime < releaseAt) yield return null;

            if (!TryStep(() => { RaycastUpdate(p); Release(p); }, cmd)) yield break;
            cmd.Complete("ok " + path);
        }

        private IEnumerator SwipeRoutine(BridgeCommand cmd, Vector2 from, Vector2 to, float seconds)
        {
            Pointer p = NewPointer(from);
            if (p == null) { cmd.Complete("err no EventSystem"); yield break; }

            GameObject target = RaycastUpdate(p);
            if (target == null) { cmd.Complete("miss"); yield break; }
            string path = PathOf(target);

            if (!TryStep(() => PressDown(p, target), cmd)) yield break;
            yield return null;

            float start = Time.unscaledTime;
            float t = 0f;
            while (t < 1f)
            {
                t = seconds <= 0f ? 1f : Mathf.Clamp01((Time.unscaledTime - start) / seconds);
                Vector2 next = Vector2.Lerp(from, to, t);
                if (!TryStep(() => Move(p, next), cmd)) yield break;
                yield return null;
            }

            if (!TryStep(() => Release(p), cmd)) yield break;
            cmd.Complete("ok " + path);
        }

        /// <summary>A game handler throwing must not leave the command hanging.</summary>
        private bool TryStep(Action step, BridgeCommand cmd)
        {
            try
            {
                step();
                return true;
            }
            catch (Exception e)
            {
                _log.LogWarning($"Pointer step error: {e}");
                cmd.Complete("err " + e.Message);
                return false;
            }
        }

        #endregion

        #region Pointer simulation (mirrors uGUI PointerInputModule)

        /// <summary>
        /// Event data plus the click target. The click target is kept here rather
        /// than in PointerEventData.pointerClick, which older Unity versions lack.
        /// </summary>
        private sealed class Pointer
        {
            public PointerEventData Data;
            public GameObject ClickHandler;
        }

        private Pointer NewPointer(Vector2 pos)
        {
            EventSystem es = EventSystem.current;
            if (es == null) return null;

            // Private pointer id so the real mouse/touch state of the input module is untouched.
            _nextPointerId = _nextPointerId <= -10000 ? -100 : _nextPointerId - 1;
            return new Pointer
            {
                Data = new PointerEventData(es)
                {
                    pointerId = _nextPointerId,
                    position = pos,
                    pressPosition = pos,
                    button = PointerEventData.InputButton.Left,
                    useDragThreshold = true,
                },
            };
        }

        private static GameObject RaycastUpdate(Pointer p)
        {
            var results = new Il2CppRaycastList();
            EventSystem.current.RaycastAll(p.Data, results);

            RaycastResult hit = default;
            for (int i = 0; i < results.Count; i++)
            {
                RaycastResult r = results[i];
                if (r.gameObject != null) { hit = r; break; }
            }
            p.Data.pointerCurrentRaycast = hit;
            return hit.gameObject;
        }

        private static void PressDown(Pointer p, GameObject go)
        {
            PointerEventData ped = p.Data;
            ped.eligibleForClick = true;
            ped.delta = Vector2.zero;
            ped.dragging = false;
            ped.pressPosition = ped.position;
            ped.pointerPressRaycast = ped.pointerCurrentRaycast;

            ped.pointerEnter = ExecuteEvents.ExecuteHierarchy(go, ped, ExecuteEvents.pointerEnterHandler);

            GameObject pressed = ExecuteEvents.ExecuteHierarchy(go, ped, ExecuteEvents.pointerDownHandler);
            GameObject clickHandler = ExecuteEvents.GetEventHandler<IPointerClickHandler>(go);
            if (pressed == null) pressed = clickHandler;

            ped.clickCount = 1;
            ped.clickTime = Time.unscaledTime;
            ped.pointerPress = pressed;
            ped.rawPointerPress = go;
            p.ClickHandler = clickHandler;

            ped.pointerDrag = ExecuteEvents.GetEventHandler<IDragHandler>(go);
            if (ped.pointerDrag != null)
            {
                ExecuteEvents.Execute(ped.pointerDrag, ped, ExecuteEvents.initializePotentialDrag);
            }
        }

        private static void Move(Pointer p, Vector2 pos)
        {
            PointerEventData ped = p.Data;
            ped.delta = pos - ped.position;
            ped.position = pos;
            RaycastUpdate(p);

            if (ped.pointerDrag == null) return;

            if (!ped.dragging)
            {
                int threshold = EventSystem.current != null ? EventSystem.current.pixelDragThreshold : 10;
                bool pastThreshold = !ped.useDragThreshold
                                     || (ped.pressPosition - ped.position).sqrMagnitude >= threshold * threshold;
                if (!pastThreshold) return;

                ExecuteEvents.Execute(ped.pointerDrag, ped, ExecuteEvents.beginDragHandler);
                ped.dragging = true;
            }

            // Once dragging starts the press is cancelled, as in uGUI (no click).
            if (ped.pointerPress != null && ped.pointerPress != ped.pointerDrag)
            {
                ExecuteEvents.Execute(ped.pointerPress, ped, ExecuteEvents.pointerUpHandler);
                ped.eligibleForClick = false;
                ped.pointerPress = null;
                ped.rawPointerPress = null;
            }

            ExecuteEvents.Execute(ped.pointerDrag, ped, ExecuteEvents.dragHandler);
        }

        private static void Release(Pointer p)
        {
            PointerEventData ped = p.Data;
            GameObject current = ped.pointerCurrentRaycast.gameObject;

            if (ped.pointerPress != null)
            {
                ExecuteEvents.Execute(ped.pointerPress, ped, ExecuteEvents.pointerUpHandler);
            }

            GameObject upClick = current != null ? ExecuteEvents.GetEventHandler<IPointerClickHandler>(current) : null;
            if (p.ClickHandler != null && p.ClickHandler == upClick && ped.eligibleForClick)
            {
                ExecuteEvents.Execute(p.ClickHandler, ped, ExecuteEvents.pointerClickHandler);
            }

            if (ped.pointerDrag != null && ped.dragging)
            {
                if (current != null) ExecuteEvents.ExecuteHierarchy(current, ped, ExecuteEvents.dropHandler);
                ExecuteEvents.Execute(ped.pointerDrag, ped, ExecuteEvents.endDragHandler);
            }

            if (ped.pointerEnter != null)
            {
                ExecuteEvents.Execute(ped.pointerEnter, ped, ExecuteEvents.pointerExitHandler);
            }

            ped.eligibleForClick = false;
            ped.dragging = false;
            ped.pointerPress = null;
            ped.rawPointerPress = null;
            ped.pointerDrag = null;
            ped.pointerEnter = null;
            p.ClickHandler = null;
        }

        #endregion

        #region Helpers

        /// <summary>Client pixel (top-left origin) -> Unity screen (bottom-left), scaled by refW/refH.</summary>
        private static Vector2 ToScreen(float x, float y, string[] args, int refIndex)
        {
            float sx = x, sy = y;
            if (args.Length > refIndex + 1
                && TryParse(args[refIndex], out float refW) && TryParse(args[refIndex + 1], out float refH)
                && refW > 0 && refH > 0)
            {
                sx = x * Screen.width / refW;
                sy = y * Screen.height / refH;
            }
            return new Vector2(sx, Screen.height - sy);
        }

        internal static bool TryParse(string s, out float value)
        {
            return float.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out value);
        }

        private static string PathOf(GameObject go)
        {
            if (go == null) return "";
            var sb = new StringBuilder(go.name);
            Transform t = go.transform.parent;
            for (int depth = 0; t != null && depth < 4; depth++, t = t.parent)
            {
                sb.Insert(0, t.name + "/");
            }
            return sb.ToString().Replace(' ', '_');
        }

        #endregion

        internal sealed class BridgeCommand
        {
            public readonly string[] Args;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
            public string Result;

            public BridgeCommand(string[] args)
            {
                Args = args;
            }

            public void Complete(string result)
            {
                if (Done.IsSet) return;
                Result = result;
                Done.Set();
            }
        }
    }

    internal static class InputBridgePatches
    {
        public static void IsFocusedPostfix(ref bool __result)
        {
            if (InputBridge.Active?.IgnoreFocus == true) __result = true;
        }
    }
}
