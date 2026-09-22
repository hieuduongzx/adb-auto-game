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
using UnityEngine;
using UnityEngine.EventSystems;

namespace Macro2k.UnityBridge
{
    /// <summary>
    /// Local input bridge for external macros.
    ///
    /// Listens on 127.0.0.1:port for newline-delimited text commands and performs
    /// taps/swipes inside the game through Unity's EventSystem (raycast +
    /// ExecuteEvents). Needs no cursor, no focus; the window may be covered.
    ///
    /// Coordinates are client-area pixels with a top-left origin; refW/refH is
    /// the sender's client size, used to scale into Screen.width/height.
    ///   ping                               -> ok Macro2kBridge &lt;ver&gt; &lt;screenW&gt; &lt;screenH&gt;
    ///   tap x y [holdMs] [refW refH]       -> ok &lt;object path&gt; | miss | err &lt;msg&gt;
    ///   swipe x1 y1 x2 y2 [ms] [refW refH] -> ok &lt;object path&gt; | miss | err &lt;msg&gt;
    ///   key vk [holdMs]                    -> ok key &lt;name&gt; | err &lt;msg&gt;   (down, hold, up)
    ///   keydown vk                         -> ok keydown &lt;name&gt;           (held until keyup — walking)
    ///   keyup vk | keyup all               -> ok keyup &lt;name&gt;
    /// vk is a Windows virtual-key code. Keys reach both the Input System and the
    /// legacy Input manager — see <see cref="KeyInjector"/>.
    ///
    /// "miss" means no EventSystem target under the point (e.g. the game polls
    /// Input directly); the sender should fall back to another input method.
    ///
    /// Only APIs present since Unity 2018 are used directly; the Input System
    /// package is touched through reflection because many games don't ship it.
    /// </summary>
    internal sealed class InputBridge
    {
        private const float DefaultTapHoldMs = 80f;
        private const int TimeoutMarginMs = 5000;

        private readonly MonoBehaviour _runner;
        private readonly ManualLogSource _log;
        private readonly int _port;
        private readonly bool _ignoreFocus;
        private readonly ConcurrentQueue<BridgeCommand> _queue = new ConcurrentQueue<BridgeCommand>();

        // Socket, not TcpListener: Unity 6 games strip TcpListener from System.dll
        private Socket _listener;
        private volatile bool _running;
        private bool _focusApplied;
        private int _nextPointerId = -100;

        internal static InputBridge Active { get; private set; }
        internal bool IgnoreFocus => _ignoreFocus && _running;

        public InputBridge(MonoBehaviour runner, ManualLogSource log, int port, bool ignoreFocus)
        {
            _runner = runner;
            _log = log;
            _port = port;
            _ignoreFocus = ignoreFocus;
        }

        #region Lifecycle

        public void Start()
        {
            if (_running) return;
            try
            {
                _listener = new Socket(AddressFamily.InterNetwork, SocketType.Stream, ProtocolType.Tcp);
                _listener.Bind(new IPEndPoint(IPAddress.Loopback, _port));
                _listener.Listen(8);
            }
            catch (Exception e)
            {
                _log.LogError($"Cannot listen on 127.0.0.1:{_port} ({e.Message}). " +
                              "Another bridge (or app) may already use this port.");
                try { _listener?.Close(); } catch { }
                _listener = null;
                return;
            }

            _running = true;
            Active = this;
            KeyInjector.Log = _log;
            new Thread(AcceptLoop) { IsBackground = true, Name = "Macro2kBridge-Accept" }.Start();
            _log.LogInfo($"Listening on 127.0.0.1:{_port}");
        }

        public void Stop()
        {
            if (!_running) return;
            _running = false;
            if (Active == this) Active = null;

            try { _listener?.Close(); } catch { }
            _listener = null;

            while (_queue.TryDequeue(out var cmd)) cmd.Complete("err bridge stopped");
            ReleaseAllKeys();
            LegacyInput.Shutdown();
            _log.LogInfo("Stopped");
        }

        /// <summary>Main thread, every frame.</summary>
        public void Tick()
        {
            if (!_running) return;
            LegacyInput.Tick();
            if (_ignoreFocus) ForceEventSystemFocus();

            // Applied lazily: the Input System settings object may not exist yet
            // at startup.
            if (!_focusApplied)
            {
                _focusApplied = true;
                ApplyBackgroundInput();
            }

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

        #endregion

        #region Background input (focus)

        private void ApplyBackgroundInput()
        {
            if (!_ignoreFocus) return;

            // Reflection: Unity 6 games strip engine members, and the setter is
            // often gone (then the game's own Player Setting stays in effect).
            MethodInfo setRunInBackground = typeof(Application)
                .GetProperty("runInBackground", BindingFlags.Public | BindingFlags.Static)?.GetSetMethod();
            if (setRunInBackground != null)
                setRunInBackground.Invoke(null, new object[] { true });
            else
                _log.LogWarning("Application.runInBackground is stripped from this game; it is " +
                                (Application.runInBackground ? "enabled" : "DISABLED, the game pauses while unfocused") +
                                " in its Player Settings.");

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

            // EventSystem.isFocused is not patched: the pointer simulation below drives
            // ExecuteEvents itself and does not depend on it.
        }

        private static FieldInfo _hasFocusField;
        private static bool _hasFocusResolved;

        /// <summary>
        /// uGUI's StandaloneInputModule ignores input while EventSystem.isFocused is false (window not
        /// in front). The BepInEx builds patched that getter with Harmony; here the field behind it is set
        /// every frame instead, since a getter this small is usually inlined into its callers.
        /// </summary>
        private void ForceEventSystemFocus()
        {
            EventSystem es = EventSystem.current;
            if (es == null) return;
            if (!_hasFocusResolved)
            {
                _hasFocusResolved = true;
                _hasFocusField = typeof(EventSystem).GetField("m_HasFocus", BindingFlags.NonPublic | BindingFlags.Instance);
                _log.LogInfo(_hasFocusField != null ? "EventSystem focus is forced on" : "EventSystem.m_HasFocus not found; unfocused windows may ignore input");
            }
            if (_hasFocusField != null) _hasFocusField.SetValue(es, true);
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
                Socket client;
                try
                {
                    client = _listener.Accept();
                }
                catch
                {
                    break; // listener stopped
                }
                ThreadPool.QueueUserWorkItem(_ => HandleClient(client));
            }
        }

        private void HandleClient(Socket client)
        {
            try
            {
                using (client)
                using (var stream = new NetworkStream(client, false))
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true })
                {
                    string line;
                    while (_running && (line = reader.ReadLine()) != null)
                    {
                        writer.Write(Dispatch(line) + "\n"); // TextWriter.NewLine's setter is stripped in Unity 6 games
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
                    _runner.StartCoroutine(TapRoutine(cmd, ToScreen(x, y, a, 4), holdMs / 1000f));
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
                    _runner.StartCoroutine(SwipeRoutine(cmd, ToScreen(x1, y1, a, 6), ToScreen(x2, y2, a, 6), ms / 1000f));
                    return;
                }

                case "key":
                case "keydown":
                case "keyup":
                    ExecuteKey(cmd);
                    return;

                case "probe":
                {
                    if (a.Length < 3 || !TryParse(a[1], out float x) || !TryParse(a[2], out float y))
                    {
                        cmd.Complete("err usage: probe x y [refW refH]");
                        return;
                    }
                    cmd.Complete(Probe(ToScreen(x, y, a, 3)));
                    return;
                }

                default:
                    cmd.Complete("err unknown command: " + a[0]);
                    return;
            }
        }

        /// <summary>Diagnostics: what an EventSystem raycast finds at a point and who would handle it.</summary>
        private string Probe(Vector2 pos)
        {
            Pointer p = NewPointer(pos);
            if (p == null) return "err no EventSystem";
            EventSystem es = EventSystem.current;
            var results = new List<RaycastResult>();
            es.RaycastAll(p.Data, results);
            var sb = new StringBuilder("ok module=");
            sb.Append(es.currentInputModule != null ? es.currentInputModule.GetType().Name : "none");
            sb.Append(" hits=").Append(results.Count);
            int shown = 0;
            foreach (RaycastResult r in results)
            {
                if (r.gameObject == null || shown++ >= 6) continue;
                GameObject down = ExecuteEvents.GetEventHandler<IPointerDownHandler>(r.gameObject);
                GameObject click = ExecuteEvents.GetEventHandler<IPointerClickHandler>(r.gameObject);
                sb.Append(" | ").Append(PathOf(r.gameObject))
                  .Append(" {down=").Append(down != null ? PathOf(down) : "-")
                  .Append(" click=").Append(click != null ? PathOf(click) : "-");
                if (down != null)
                {
                    sb.Append(" comps=");
                    foreach (Component c in down.GetComponents<Component>())
                    {
                        if (c == null) continue;
                        sb.Append(c.GetType().FullName);
                        foreach (Type t in c.GetType().GetInterfaces())
                            if (typeof(IEventSystemHandler).IsAssignableFrom(t) && t != typeof(IEventSystemHandler))
                                sb.Append('+').Append(t.Name);
                        sb.Append(',');
                    }
                }
                sb.Append('}');
            }
            return sb.ToString();
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
                    _runner.StartCoroutine(KeyRoutine(cmd, key, holdMs / 1000f));
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

            // StandaloneInputModule reads the legacy Input itself: feeding it through LegacyInput is enough,
            // and also running the EventSystem simulation would click twice.
            if (UsesLegacyInputModule() && LegacyInput.MouseBegin(pos))
            {
                float legacyReleaseAt = Time.unscaledTime + holdSeconds;
                yield return null;
                while (Time.unscaledTime < legacyReleaseAt) yield return null;
                LegacyInput.MouseEnd();
                yield return null;
                yield return null; // the module sees Up on the frame after the release
                cmd.Complete("ok " + PathOf(target));
                yield break;
            }

            if (!TryStep(() => PressDown(p, target), cmd)) yield break;
            LegacyInput.MouseBegin(pos);

            float releaseAt = Time.unscaledTime + holdSeconds;
            yield return null; // down and up never share a frame
            while (Time.unscaledTime < releaseAt) yield return null;

            LegacyInput.MouseEnd();
            if (!TryStep(() => { RaycastUpdate(p); Release(p); }, cmd)) yield break;
            cmd.Complete("ok " + PathOf(target));
        }

        private IEnumerator SwipeRoutine(BridgeCommand cmd, Vector2 from, Vector2 to, float seconds)
        {
            Pointer p = NewPointer(from);
            if (p == null) { cmd.Complete("err no EventSystem"); yield break; }

            GameObject target = RaycastUpdate(p);
            if (target == null) { cmd.Complete("miss"); yield break; }

            if (UsesLegacyInputModule() && LegacyInput.MouseBegin(from))
            {
                yield return null;
                float legacyStart = Time.unscaledTime;
                float progress = 0f;
                while (progress < 1f)
                {
                    progress = seconds <= 0f ? 1f : Mathf.Clamp01((Time.unscaledTime - legacyStart) / seconds);
                    LegacyInput.MouseMove(Vector2.Lerp(from, to, progress));
                    yield return null;
                }
                LegacyInput.MouseEnd();
                yield return null;
                yield return null;
                cmd.Complete("ok " + PathOf(target));
                yield break;
            }

            if (!TryStep(() => PressDown(p, target), cmd)) yield break;
            LegacyInput.MouseBegin(from);
            yield return null;

            float start = Time.unscaledTime;
            float t = 0f;
            while (t < 1f)
            {
                t = seconds <= 0f ? 1f : Mathf.Clamp01((Time.unscaledTime - start) / seconds);
                Vector2 next = Vector2.Lerp(from, to, t);
                LegacyInput.MouseMove(next);
                if (!TryStep(() => Move(p, next), cmd)) { LegacyInput.MouseEnd(); yield break; }
                yield return null;
            }

            LegacyInput.MouseEnd();
            if (!TryStep(() => Release(p), cmd)) yield break;
            cmd.Complete("ok " + PathOf(target));
        }

        private static bool UsesLegacyInputModule()
        {
            EventSystem es = EventSystem.current;
            BaseInputModule module = es != null ? es.currentInputModule : null;
            for (Type t = module != null ? module.GetType() : null; t != null; t = t.BaseType)
            {
                if (t.Name == "StandaloneInputModule") return true;
            }
            return false;
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
            var results = new List<RaycastResult>();
            EventSystem.current.RaycastAll(p.Data, results);

            RaycastResult hit = default;
            foreach (RaycastResult r in results)
            {
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

        private static bool TryParse(string s, out float value)
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

        private sealed class BridgeCommand
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


    /// <summary>
    /// Simulated keys for the bridge. Keeps the set of held keys and feeds it to
    /// both input stacks a game may read:
    ///  - Input System (reflection — many games don't ship it): queues a
    ///    KeyboardState holding every held key, so InputActions / PlayerInput and
    ///    Keyboard.current.xKey.isPressed / wasPressedThisFrame all see it. Window
    ///    messages from outside can't do this: the Input System identifies keys by
    ///    scan code and ignores messages while the window is unfocused.
    ///  - Legacy Input manager: LegacyInput hooks Input.GetKey / GetKeyDown /
    ///    GetKeyUp and GetAxis(Raw) "Horizontal" / "Vertical" (WASD + arrows).
    /// Main thread only (Tick / coroutines). The real keyboard keeps working; a
    /// state event from a physical key can override the simulated state until the
    /// next Press / Release.
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
        private static bool _inputSystemOff;
        // GetKeyDown / GetKeyUp answer true on the frame AFTER the command, so every
        // script's Update in that frame sees it exactly once (commands run mid-frame).
        private static readonly Dictionary<KeyCode, int> DownFrame = new Dictionary<KeyCode, int>();
        private static readonly Dictionary<KeyCode, int> UpFrame = new Dictionary<KeyCode, int>();

        private static bool _inputSystemResolved;
        private static Type _keyType;
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
                _stateCtor = state.GetConstructor(new[] { _keyType.MakeArrayType() });
                foreach (MethodInfo m in inputSystem.GetMethods(BindingFlags.Public | BindingFlags.Static))
                {
                    // QueueStateEvent<TState>(InputDevice device, TState state, double time = -1)
                    if (m.Name == "QueueStateEvent" && m.IsGenericMethodDefinition && m.GetParameters().Length == 3)
                    {
                        _queueStateEvent = m.MakeGenericMethod(state);
                        break;
                    }
                }
                if (_keyboardCurrent == null || _stateCtor == null || _queueStateEvent == null)
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
            LegacyInput.KeysChanged();
            PushKeyboardState();
        }

        internal static void Release(MappedKey key)
        {
            Held.Remove(key.Vk);
            if (key.LegacyKey.HasValue) UpFrame[key.LegacyKey.Value] = Time.frameCount + 1;
            LegacyInput.KeysChanged();
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
            LegacyInput.KeysChanged();
            PushKeyboardState();
        }

        private static object[] SnapshotKeys()
        {
            var pressed = new List<object>();
            foreach (MappedKey key in Held.Values)
            {
                if (key.NewKey != null) pressed.Add(key.NewKey);
            }
            return pressed.ToArray();
        }

        private static void PushKeyboardState()
        {
            // InputState.Change, reapplied after every InputSystem.Update. A single
            // QueueStateEvent is overwritten by the real keyboard on the next frame,
            // which is why a Key node used to report success and the game saw nothing.
            if (_inputSystemOff) return;
            try
            {
                InputSystemKeys.Collect = SnapshotKeys;
                InputSystemKeys.Apply(SnapshotKeys());
            }
            catch (Exception e)
            {
                _inputSystemOff = true;
                Log?.LogWarning("Input System key injection unavailable (" + e.GetType().Name + ": " + e.Message +
                                "); legacy Input.GetKey hooks only");
            }
        }

        /// <summary>edge 0 = held, 1 = down this frame, 2 = up this frame. Name is a KeyCode name.</summary>
        internal static bool SimNamed(string name, int edge)
        {
            if (string.IsNullOrEmpty(name)) return false;
            try
            {
                if (!Enum.IsDefined(typeof(KeyCode), name))
                {
                    // "space" / "SPACE" — Enum.Parse without ignoreCase misses them.
                    string titled = char.ToUpperInvariant(name[0]) + name.Substring(1);
                    if (!Enum.IsDefined(typeof(KeyCode), titled)) return false;
                    name = titled;
                }
                var code = (KeyCode)Enum.Parse(typeof(KeyCode), name);
                if (edge == 1) return SimDown(code);
                if (edge == 2) return SimUp(code);
                return SimHeld(code);
            }
            catch
            {
                return false;
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

        #region Legacy Input (see LegacyInput.cs: it hooks Input.GetKey / GetKeyDown / GetKeyUp / GetAxis while keys are held)

        internal static bool SimHeld(KeyCode key)
        {
            return Held.Count > 0 && IsHeld(key);
        }

        // GetKeyDown / GetKeyUp answer true on the frame AFTER the command (see DownFrame / UpFrame).
        internal static bool SimDown(KeyCode key)
        {
            int frame;
            return DownFrame.TryGetValue(key, out frame) && frame == Time.frameCount;
        }

        internal static bool SimUp(KeyCode key)
        {
            int frame;
            return UpFrame.TryGetValue(key, out frame) && frame == Time.frameCount;
        }

        /// <summary>WASD / arrows as the "Horizontal" / "Vertical" axes; 0 when nothing simulated applies.</summary>
        internal static float SimAxis(string axisName)
        {
            if (Held.Count == 0) return 0f;
            if (axisName == "Horizontal")
            {
                return (IsHeld(KeyCode.D) || IsHeld(KeyCode.RightArrow) ? 1f : 0f)
                       - (IsHeld(KeyCode.A) || IsHeld(KeyCode.LeftArrow) ? 1f : 0f);
            }
            if (axisName == "Vertical")
            {
                return (IsHeld(KeyCode.W) || IsHeld(KeyCode.UpArrow) ? 1f : 0f)
                       - (IsHeld(KeyCode.S) || IsHeld(KeyCode.DownArrow) ? 1f : 0f);
            }
            return 0f;
        }

        /// <summary>True while the legacy hooks still have something to report (held keys or a pending edge).</summary>
        internal static bool Busy
        {
            get { return Held.Count > 0; }
        }

        #endregion
    }
}
