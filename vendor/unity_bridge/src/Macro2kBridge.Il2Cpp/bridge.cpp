// Macro2k Unity Bridge for IL2CPP games (x64) - a native DLL loaded into the running game.
//
// IL2CPP has no managed runtime to load an assembly into, so the bridge talks to the game
// through the il2cpp_* C API that GameAssembly.dll exports (the same idea as the Mono build,
// which calls mono_*). Same line protocol as the Mono build (see ../../README.md):
//   ping | tap x y [holdMs] [refW refH] | swipe x1 y1 x2 y2 [ms] [refW refH] | probe x y [refW refH]
//
// Threads: a socket server (worker threads) queues commands; everything that touches the game runs
// on Unity's main thread, reached through a WH_GETMESSAGE hook (a poster thread keeps the game's
// message loop turning with WM_NULL). Taps replay uGUI's pointer pipeline through the game's own
// EventSystem / event-handler interfaces, and games that poll the legacy Input manager
// (GetMouseButtonUp ...) get a simulated mouse through breakpoint hooks on the Unity icalls that
// exist only while a tap is in flight.
//
// Build: build.bat   (MSVC, x64)

#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>

#include <atomic>
#include <cmath>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "user32.lib")

static const char* kVersion = "1.1.0";
static const int kDefaultPort = 17820;

// ───────────────────────────────────────────────────────────────────────────────────────────
// logging
// ───────────────────────────────────────────────────────────────────────────────────────────
static void Log(const char* level, const char* fmt, ...)
{
    char msg[1024];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(msg, sizeof msg, fmt, ap);
    va_end(ap);
    char tmp[MAX_PATH];
    GetTempPathA(MAX_PATH, tmp);
    std::string path = std::string(tmp) + "Macro2kBridge.log";
    SYSTEMTIME st;
    GetLocalTime(&st);
    char line[1200];
    snprintf(line, sizeof line, "%02d:%02d:%02d.%03d [%s] %s\r\n", st.wHour, st.wMinute, st.wSecond, st.wMilliseconds, level, msg);
    HANDLE h = CreateFileA(path.c_str(), FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE)
    {
        DWORD written;
        WriteFile(h, line, (DWORD)strlen(line), &written, nullptr);
        CloseHandle(h);
    }
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// il2cpp C API
// ───────────────────────────────────────────────────────────────────────────────────────────
#define IL2CPP_API(X) \
    X(void*, il2cpp_domain_get, ()) \
    X(void*, il2cpp_thread_attach, (void*)) \
    X(void**, il2cpp_domain_get_assemblies, (void*, size_t*)) \
    X(void*, il2cpp_assembly_get_image, (void*)) \
    X(void*, il2cpp_class_from_name, (void*, const char*, const char*)) \
    X(void*, il2cpp_class_get_method_from_name, (void*, const char*, int)) \
    X(void*, il2cpp_class_get_field_from_name, (void*, const char*)) \
    X(void*, il2cpp_runtime_invoke, (void*, void*, void**, void**)) \
    X(void*, il2cpp_object_new, (void*)) \
    X(void*, il2cpp_object_unbox, (void*)) \
    X(void*, il2cpp_object_get_class, (void*)) \
    X(const char*, il2cpp_class_get_name, (void*)) \
    X(void*, il2cpp_class_get_parent, (void*)) \
    X(bool, il2cpp_class_is_assignable_from, (void*, void*)) \
    X(void, il2cpp_field_get_value, (void*, void*, void*)) \
    X(void, il2cpp_field_set_value, (void*, void*, void*)) \
    X(uint32_t, il2cpp_gchandle_new, (void*, bool)) \
    X(void*, il2cpp_gchandle_get_target, (uint32_t)) \
    X(void, il2cpp_gchandle_free, (uint32_t)) \
    X(void*, il2cpp_method_get_param, (void*, uint32_t)) \
    X(void*, il2cpp_class_from_type, (void*)) \
    X(void*, il2cpp_object_get_virtual_method, (void*, void*)) \
    X(void*, il2cpp_class_get_type, (void*)) \
    X(void*, il2cpp_type_get_object, (void*)) \
    X(uint32_t, il2cpp_array_length, (void*))

#define DECLARE(ret, name, args) static ret(*name) args = nullptr;
IL2CPP_API(DECLARE)
static void* (*il2cpp_resolve_icall)(const char*) = nullptr; // optional

static bool ResolveApi(HMODULE ga)
{
    bool ok = true;
    static bool reportedMissing = false;
#define RESOLVE(ret, name, args) \
    name = reinterpret_cast<decltype(name)>(GetProcAddress(ga, #name)); \
    if (!name) { if (!reportedMissing) Log("Error", "GameAssembly.dll does not export " #name); ok = false; }
    IL2CPP_API(RESOLVE)
    il2cpp_resolve_icall = reinterpret_cast<decltype(il2cpp_resolve_icall)>(GetProcAddress(ga, "il2cpp_resolve_icall"));
    if (!ok) reportedMissing = true;
    return ok;
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// il2cpp helpers
// ───────────────────────────────────────────────────────────────────────────────────────────
static void* g_domain = nullptr;
static bool g_exc = false; // the last Call() raised a managed exception

struct Vec2 { float x, y; };

static std::unordered_map<std::string, void*> g_classes;

static void* Cls(const char* ns, const char* name)
{
    std::string key = std::string(ns) + "." + name;
    auto it = g_classes.find(key);
    if (it != g_classes.end()) return it->second;
    void* found = nullptr;
    size_t count = 0;
    void** assemblies = il2cpp_domain_get_assemblies(g_domain, &count);
    for (size_t i = 0; i < count && !found; i++)
        found = il2cpp_class_from_name(il2cpp_assembly_get_image(assemblies[i]), ns, name);
    if (!found) Log("Warning", "class %s not found", key.c_str());
    g_classes[key] = found;
    return found;
}

static void* Method(void* cls, const char* name, int argc)
{
    return cls ? il2cpp_class_get_method_from_name(cls, name, argc) : nullptr;
}

static void* Call(void* method, void* obj, void** args = nullptr)
{
    g_exc = false;
    if (!method) { g_exc = true; return nullptr; }
    void* exc = nullptr;
    void* result = il2cpp_runtime_invoke(method, obj, args, &exc);
    if (exc) { g_exc = true; return nullptr; }
    return result;
}

static bool ToBool(void* boxed) { return boxed && *static_cast<uint8_t*>(il2cpp_object_unbox(boxed)) != 0; }
static int ToInt(void* boxed) { return boxed ? *static_cast<int*>(il2cpp_object_unbox(boxed)) : 0; }
static float ToFloat(void* boxed) { return boxed ? *static_cast<float*>(il2cpp_object_unbox(boxed)) : 0.f; }

// A GC handle: keeps an il2cpp object alive between ticks.
struct Ref
{
    uint32_t h = 0;
    void Set(void* obj) { Free(); if (obj) h = il2cpp_gchandle_new(obj, false); }
    void* Get() const { return h ? il2cpp_gchandle_get_target(h) : nullptr; }
    void Free() { if (h) il2cpp_gchandle_free(h); h = 0; }
};

// Sets a property through its setter, or the auto-property backing field. `arg` is the object itself
// for reference types and a pointer to the value for value types.
static bool SetMember(void* obj, const char* prop, void* arg)
{
    void* k = il2cpp_object_get_class(obj);
    char name[160];
    snprintf(name, sizeof name, "set_%s", prop);
    void* setter = Method(k, name, 1);
    if (setter)
    {
        void* args[1] = { arg };
        Call(setter, obj, args);
        return !g_exc;
    }
    snprintf(name, sizeof name, "<%s>k__BackingField", prop);
    void* field = il2cpp_class_get_field_from_name(k, name);
    if (!field)
    {
        snprintf(name, sizeof name, "m_%c%s", (char)toupper(prop[0]), prop + 1);
        field = il2cpp_class_get_field_from_name(k, name);
    }
    if (!field) return false;
    il2cpp_field_set_value(obj, field, arg);
    return true;
}
static bool SetBool(void* o, const char* p, bool v) { uint8_t b = v ? 1 : 0; return SetMember(o, p, &b); }
static bool SetInt(void* o, const char* p, int v) { return SetMember(o, p, &v); }
static bool SetFloat(void* o, const char* p, float v) { return SetMember(o, p, &v); }
static bool SetVec2(void* o, const char* p, Vec2 v) { return SetMember(o, p, &v); }
static bool SetRef(void* o, const char* p, void* v) { return SetMember(o, p, v); }

static std::string Utf8(void* il2cppString)
{
    if (!il2cppString) return "";
    int length = *reinterpret_cast<int*>(static_cast<char*>(il2cppString) + 0x10);
    const wchar_t* chars = reinterpret_cast<const wchar_t*>(static_cast<char*>(il2cppString) + 0x14);
    if (length <= 0 || length > 4096) return "";
    char out[4200];
    int n = WideCharToMultiByte(CP_UTF8, 0, chars, length, out, sizeof out - 1, nullptr, nullptr);
    return std::string(out, n > 0 ? n : 0);
}

// ── frequently used classes ────────────────────────────────────────────────────────────────
struct Known
{
    void *eventSystem, *pointerEventData, *gameObject, *transform, *component, *behaviour, *unityObject;
    void *time, *screen;
    void *iEnter, *iExit, *iDown, *iUp, *iClick, *iInitDrag, *iBeginDrag, *iDrag, *iEndDrag, *iDrop;
    void *listClass, *raycastResult, *raycastField;
    bool ok;
};
static Known K = {};

static bool LoadKnown()
{
    const char* ev = "UnityEngine.EventSystems";
    K.eventSystem = Cls(ev, "EventSystem");
    K.pointerEventData = Cls(ev, "PointerEventData");
    K.gameObject = Cls("UnityEngine", "GameObject");
    K.transform = Cls("UnityEngine", "Transform");
    K.component = Cls("UnityEngine", "Component");
    K.behaviour = Cls("UnityEngine", "Behaviour");
    K.unityObject = Cls("UnityEngine", "Object");
    K.time = Cls("UnityEngine", "Time");
    K.screen = Cls("UnityEngine", "Screen");
    K.iEnter = Cls(ev, "IPointerEnterHandler");
    K.iExit = Cls(ev, "IPointerExitHandler");
    K.iDown = Cls(ev, "IPointerDownHandler");
    K.iUp = Cls(ev, "IPointerUpHandler");
    K.iClick = Cls(ev, "IPointerClickHandler");
    K.iInitDrag = Cls(ev, "IInitializePotentialDragHandler");
    K.iBeginDrag = Cls(ev, "IBeginDragHandler");
    K.iDrag = Cls(ev, "IDragHandler");
    K.iEndDrag = Cls(ev, "IEndDragHandler");
    K.iDrop = Cls(ev, "IDropHandler");
    K.raycastResult = Cls(ev, "RaycastResult");
    K.raycastField = K.raycastResult ? il2cpp_class_get_field_from_name(K.raycastResult, "m_GameObject") : nullptr;
    K.ok = K.eventSystem && K.pointerEventData && K.gameObject && K.transform && K.component && K.time && K.screen
           && K.iDown && K.iUp && K.iEnter && K.raycastResult && K.raycastField;
    return K.ok;
}

static void* StaticGet(void* cls, const char* getter) { return Call(Method(cls, getter, 0), nullptr); }
static int FrameCount() { return ToInt(StaticGet(K.time, "get_frameCount")); }
static float UnscaledTime() { return ToFloat(StaticGet(K.time, "get_unscaledTime")); }
static void* CurrentEventSystem() { return StaticGet(K.eventSystem, "get_current"); }

static void* ParentOf(void* go)
{
    void* tr = Call(Method(K.gameObject, "get_transform", 0), go);
    void* parent = tr ? Call(Method(K.transform, "get_parent", 0), tr) : nullptr;
    return parent ? Call(Method(K.component, "get_gameObject", 0), parent) : nullptr;
}

static std::string NameOf(void* obj) { return Utf8(Call(Method(K.unityObject, "get_name", 0), obj)); }

static std::string PathOf(void* go)
{
    if (!go) return "";
    std::string path = NameOf(go);
    void* t = ParentOf(go);
    for (int depth = 0; t && depth < 4; depth++, t = ParentOf(t)) path = NameOf(t) + "/" + path;
    for (char& c : path) if (c == ' ') c = '_';
    return path;
}

static std::vector<void*> ComponentsOf(void* go)
{
    std::vector<void*> out;
    void* typeObject = il2cpp_type_get_object(il2cpp_class_get_type(K.component));
    void* args[1] = { typeObject };
    void* array = Call(Method(K.gameObject, "GetComponents", 1), go, args);
    if (!array) return out;
    uint32_t n = il2cpp_array_length(array);
    void** elements = reinterpret_cast<void**>(static_cast<char*>(array) + 0x20);
    for (uint32_t i = 0; i < n; i++) if (elements[i]) out.push_back(elements[i]);
    return out;
}

// ExecuteEvents.ShouldSendToComponent: implements the interface and (for behaviours) is enabled.
static bool CanHandle(void* comp, void* iface)
{
    void* k = il2cpp_object_get_class(comp);
    if (!il2cpp_class_is_assignable_from(iface, k)) return false;
    if (K.behaviour && il2cpp_class_is_assignable_from(K.behaviour, k))
        return ToBool(Call(Method(K.behaviour, "get_isActiveAndEnabled", 0), comp));
    return true;
}

static bool ExecuteOn(void* go, void* ped, void* iface, const char* method)
{
    if (!iface) return false;
    void* interfaceMethod = Method(iface, method, 1);
    if (!interfaceMethod) return false;
    bool any = false;
    for (void* comp : ComponentsOf(go))
    {
        if (!CanHandle(comp, iface)) continue;
        void* target = il2cpp_object_get_virtual_method(comp, interfaceMethod);
        void* args[1] = { ped };
        Call(target ? target : interfaceMethod, comp, args);
        any = true;
    }
    return any;
}

static void* ExecuteHierarchy(void* go, void* ped, void* iface, const char* method)
{
    for (void* t = go; t; t = ParentOf(t))
        if (ExecuteOn(t, ped, iface, method)) return t;
    return nullptr;
}

static void* GetEventHandler(void* go, void* iface)
{
    if (!iface) return nullptr;
    for (void* t = go; t; t = ParentOf(t))
        for (void* comp : ComponentsOf(t))
            if (CanHandle(comp, iface)) return t;
    return nullptr;
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// legacy Input: simulated mouse through breakpoint hooks on the Unity icalls
// ───────────────────────────────────────────────────────────────────────────────────────────
enum HookKind { HK_HELD, HK_DOWN, HK_UP, HK_POS };

struct BpHook
{
    HookKind kind;
    void* addr = nullptr;
    uint8_t original = 0;
    bool on = false;
};

static const int kNoFrame = 0x7FFFFFFF;
static std::vector<BpHook> g_hooks;
static bool g_mouseHeld = false;
static int g_downFrame = kNoFrame, g_upFrame = -1, g_restoreFrame = kNoFrame;
static float g_mouseX = 0, g_mouseY = 0;
static int (*g_frameIcall)() = nullptr;
static PVOID g_veh = nullptr;
static bool g_hooksUnavailable = false;

static int HookFrame()
{
    return g_frameIcall ? g_frameIcall() : 0;
}

static LONG CALLBACK Veh(PEXCEPTION_POINTERS ep)
{
    if (ep->ExceptionRecord->ExceptionCode != EXCEPTION_BREAKPOINT) return EXCEPTION_CONTINUE_SEARCH;
    void* at = ep->ExceptionRecord->ExceptionAddress;
    for (const BpHook& h : g_hooks)
    {
        if (!h.on || h.addr != at) continue;
        CONTEXT* c = ep->ContextRecord;
        int button = (int)(c->Rcx & 0xFFFFFFFF);
        int frame = HookFrame();
        switch (h.kind)
        {
        case HK_HELD: c->Rax = (button == 0 && g_mouseHeld && frame >= g_downFrame) ? 1 : 0; break;
        case HK_DOWN: c->Rax = (button == 0 && frame == g_downFrame) ? 1 : 0; break;
        case HK_UP: c->Rax = (button == 0 && frame == g_upFrame) ? 1 : 0; break;
        case HK_POS:
        {
            float* out = reinterpret_cast<float*>(c->Rcx); // Vector3 through the hidden result pointer
            out[0] = g_mouseX; out[1] = g_mouseY; out[2] = 0.f;
            c->Rax = c->Rcx;
            break;
        }
        }
        c->Rip = *reinterpret_cast<DWORD64*>(c->Rsp); // behave like `ret`: skip the original
        c->Rsp += 8;
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static void* ResolveIcall(const char* base, const char* signature)
{
    if (!il2cpp_resolve_icall) return nullptr;
    char full[256];
    if (signature)
    {
        snprintf(full, sizeof full, "%s(%s)", base, signature);
        if (void* p = il2cpp_resolve_icall(full)) return p;
    }
    return il2cpp_resolve_icall(base);
}

static bool PatchByte(void* addr, uint8_t value, uint8_t* previous)
{
    DWORD old;
    if (!VirtualProtect(addr, 1, PAGE_EXECUTE_READWRITE, &old)) return false;
    if (previous) *previous = *static_cast<uint8_t*>(addr);
    *static_cast<uint8_t*>(addr) = value;
    FlushInstructionCache(GetCurrentProcess(), addr, 1);
    VirtualProtect(addr, 1, old, &old);
    return true;
}

static bool InstallMouseHooks()
{
    if (g_hooksUnavailable) return false;
    if (!g_hooks.empty()) { for (BpHook& h : g_hooks) if (!h.on) { PatchByte(h.addr, 0xCC, &h.original); h.on = true; } return true; }
    g_frameIcall = reinterpret_cast<int (*)()>(ResolveIcall("UnityEngine.Time::get_frameCount", ""));
    struct Spec { HookKind kind; const char* name; const char* sig; };
    const Spec specs[] = {
        { HK_HELD, "UnityEngine.Input::GetMouseButton", "System.Int32" },
        { HK_DOWN, "UnityEngine.Input::GetMouseButtonDown", "System.Int32" },
        { HK_UP, "UnityEngine.Input::GetMouseButtonUp", "System.Int32" },
        { HK_POS, "UnityEngine.Input::get_mousePosition_Injected", "UnityEngine.Vector3&" },
    };
    if (!g_frameIcall) { Log("Warning", "Time.frameCount icall not found; legacy mouse hooks disabled"); g_hooksUnavailable = true; return false; }
    for (const Spec& s : specs)
    {
        void* addr = ResolveIcall(s.name, s.sig);
        if (!addr && s.kind == HK_POS) addr = ResolveIcall("UnityEngine.Input::get_mousePosition", "");
        if (!addr) { Log("Info", "icall %s not found", s.name); continue; }
        BpHook h;
        h.kind = s.kind; h.addr = addr;
        g_hooks.push_back(h);
    }
    if (g_hooks.empty()) { g_hooksUnavailable = true; return false; }
    if (!g_veh) g_veh = AddVectoredExceptionHandler(1, Veh);
    for (BpHook& h : g_hooks)
    {
        if (PatchByte(h.addr, 0xCC, &h.original)) h.on = true;
        Log("Info", "hooked legacy Input icall kind=%d at %p", (int)h.kind, h.addr);
    }
    return true;
}

static void UninstallMouseHooks()
{
    for (BpHook& h : g_hooks)
        if (h.on) { PatchByte(h.addr, h.original, nullptr); h.on = false; }
    g_downFrame = kNoFrame; g_upFrame = -1; g_restoreFrame = kNoFrame;
}

static bool MouseBegin(Vec2 pos)
{
    if (!InstallMouseHooks()) return false;
    g_mouseX = pos.x; g_mouseY = pos.y;
    g_mouseHeld = true;
    g_downFrame = FrameCount() + 1;
    g_upFrame = -1;
    g_restoreFrame = kNoFrame;
    return true;
}
static void MouseMove(Vec2 pos) { g_mouseX = pos.x; g_mouseY = pos.y; }
static void MouseEnd()
{
    if (!g_mouseHeld) return;
    g_mouseHeld = false;
    int now = FrameCount();
    g_upFrame = now + 1 > g_downFrame + 1 ? now + 1 : g_downFrame + 1;
    g_restoreFrame = g_upFrame + 1;
}
static void MouseTick(int frame)
{
    if (!g_hooks.empty() && !g_mouseHeld && g_restoreFrame != kNoFrame && frame >= g_restoreFrame) UninstallMouseHooks();
}

// StandaloneInputModule reads the legacy Input itself: feeding it is enough, and also replaying
// EventSystem events would click twice.
static bool UsesLegacyModule()
{
    void* es = CurrentEventSystem();
    void* module = es ? Call(Method(K.eventSystem, "get_currentInputModule", 0), es) : nullptr;
    for (void* k = module ? il2cpp_object_get_class(module) : nullptr; k; k = il2cpp_class_get_parent(k))
        if (strcmp(il2cpp_class_get_name(k), "StandaloneInputModule") == 0) return true;
    return false;
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// pointer simulation (mirrors uGUI's PointerInputModule)
// ───────────────────────────────────────────────────────────────────────────────────────────
struct Pointer
{
    Ref data, list, target, clickHandler;
    Vec2 position{};
    Vec2 pressPosition{};
    bool dragging = false;
    ~Pointer() { data.Free(); list.Free(); target.Free(); clickHandler.Free(); }
};

static int g_nextPointerId = -100;

static bool NewPointer(Pointer& p, Vec2 pos)
{
    void* es = CurrentEventSystem();
    if (!es) return false;
    void* ped = il2cpp_object_new(K.pointerEventData);
    void* ctorArgs[1] = { es };
    Call(Method(K.pointerEventData, ".ctor", 1), ped, ctorArgs);
    if (g_exc) return false;
    p.data.Set(ped);
    g_nextPointerId = g_nextPointerId <= -10000 ? -100 : g_nextPointerId - 1;
    p.position = p.pressPosition = pos;
    SetInt(ped, "pointerId", g_nextPointerId);
    SetVec2(ped, "position", pos);
    SetVec2(ped, "pressPosition", pos);
    SetInt(ped, "button", 0); // InputButton.Left
    SetBool(ped, "useDragThreshold", true);
    return true;
}

static void* RaycastUpdate(Pointer& p)
{
    void* es = CurrentEventSystem();
    void* ped = p.data.Get();
    if (!es || !ped) return nullptr;
    void* raycastAll = Method(K.eventSystem, "RaycastAll", 2);
    if (!raycastAll) return nullptr;
    void* list = p.list.Get();
    if (!list)
    {
        void* listClass = il2cpp_class_from_type(il2cpp_method_get_param(raycastAll, 1)); // List<RaycastResult>
        list = il2cpp_object_new(listClass);
        Call(Method(listClass, ".ctor", 0), list);
        p.list.Set(list);
    }
    void* listClass = il2cpp_object_get_class(list);
    Call(Method(listClass, "Clear", 0), list);
    void* args[2] = { ped, list };
    Call(raycastAll, es, args);
    int count = ToInt(Call(Method(listClass, "get_Count", 0), list));
    for (int i = 0; i < count; i++)
    {
        void* itemArgs[1] = { &i };
        void* boxed = Call(Method(listClass, "get_Item", 1), list, itemArgs);
        void* go = nullptr;
        if (boxed) il2cpp_field_get_value(boxed, K.raycastField, &go);
        if (!go) continue;
        SetMember(ped, "pointerCurrentRaycast", il2cpp_object_unbox(boxed));
        return go;
    }
    return nullptr;
}

static void PressDown(Pointer& p, void* go)
{
    void* ped = p.data.Get();
    SetBool(ped, "eligibleForClick", true);
    SetVec2(ped, "delta", Vec2{ 0, 0 });
    SetBool(ped, "dragging", false);
    p.dragging = false;
    SetVec2(ped, "pressPosition", p.position);
    p.pressPosition = p.position;

    void* enter = ExecuteHierarchy(go, ped, K.iEnter, "OnPointerEnter");
    SetRef(ped, "pointerEnter", enter);
    void* pressed = ExecuteHierarchy(go, ped, K.iDown, "OnPointerDown");
    void* clickHandler = GetEventHandler(go, K.iClick);
    if (!pressed) pressed = clickHandler;
    SetInt(ped, "clickCount", 1);
    SetFloat(ped, "clickTime", UnscaledTime());
    SetRef(ped, "pointerPress", pressed);
    SetRef(ped, "rawPointerPress", go);
    p.clickHandler.Set(clickHandler);

    void* drag = GetEventHandler(go, K.iDrag);
    SetRef(ped, "pointerDrag", drag);
    if (drag) ExecuteOn(drag, ped, K.iInitDrag, "OnInitializePotentialDrag");
}

static void MoveTo(Pointer& p, Vec2 pos)
{
    void* ped = p.data.Get();
    SetVec2(ped, "delta", Vec2{ pos.x - p.position.x, pos.y - p.position.y });
    SetVec2(ped, "position", pos);
    p.position = pos;
    RaycastUpdate(p);

    void* drag = nullptr;
    void* getDrag = Method(K.pointerEventData, "get_pointerDrag", 0);
    drag = Call(getDrag, ped);
    if (!drag) return;

    if (!p.dragging)
    {
        void* es = CurrentEventSystem();
        int threshold = es ? ToInt(Call(Method(K.eventSystem, "get_pixelDragThreshold", 0), es)) : 10;
        float dx = p.pressPosition.x - pos.x, dy = p.pressPosition.y - pos.y;
        if (dx * dx + dy * dy < (float)threshold * threshold) return;
        ExecuteOn(drag, ped, K.iBeginDrag, "OnBeginDrag");
        p.dragging = true;
        SetBool(ped, "dragging", true);
    }
    // once dragging starts the press is cancelled, as in uGUI (no click)
    void* press = Call(Method(K.pointerEventData, "get_pointerPress", 0), ped);
    if (press && press != drag)
    {
        ExecuteOn(press, ped, K.iUp, "OnPointerUp");
        SetBool(ped, "eligibleForClick", false);
        SetRef(ped, "pointerPress", nullptr);
        SetRef(ped, "rawPointerPress", nullptr);
    }
    ExecuteOn(drag, ped, K.iDrag, "OnDrag");
}

static void ReleasePointer(Pointer& p)
{
    void* ped = p.data.Get();
    void* current = nullptr;
    {
        void* boxed = Call(Method(K.pointerEventData, "get_pointerCurrentRaycast", 0), ped);
        if (boxed) il2cpp_field_get_value(boxed, K.raycastField, &current);
    }
    void* press = Call(Method(K.pointerEventData, "get_pointerPress", 0), ped);
    if (press) ExecuteOn(press, ped, K.iUp, "OnPointerUp");

    void* upClick = current ? GetEventHandler(current, K.iClick) : nullptr;
    void* clickHandler = p.clickHandler.Get();
    bool eligible = ToBool(Call(Method(K.pointerEventData, "get_eligibleForClick", 0), ped));
    if (clickHandler && clickHandler == upClick && eligible)
        ExecuteOn(clickHandler, ped, K.iClick, "OnPointerClick");

    void* drag = Call(Method(K.pointerEventData, "get_pointerDrag", 0), ped);
    if (drag && p.dragging)
    {
        if (current) ExecuteHierarchy(current, ped, K.iDrop, "OnDrop");
        ExecuteOn(drag, ped, K.iEndDrag, "OnEndDrag");
    }
    void* enter = Call(Method(K.pointerEventData, "get_pointerEnter", 0), ped);
    if (enter) ExecuteOn(enter, ped, K.iExit, "OnPointerExit");

    SetBool(ped, "eligibleForClick", false);
    SetBool(ped, "dragging", false);
    SetRef(ped, "pointerPress", nullptr);
    SetRef(ped, "rawPointerPress", nullptr);
    SetRef(ped, "pointerDrag", nullptr);
    SetRef(ped, "pointerEnter", nullptr);
    p.clickHandler.Free();
    p.dragging = false;
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// commands
// ───────────────────────────────────────────────────────────────────────────────────────────
struct Cmd
{
    std::vector<std::string> args;
    std::string reply;
    HANDLE done = CreateEventW(nullptr, TRUE, FALSE, nullptr);
    ~Cmd() { CloseHandle(done); }
    void Complete(const std::string& r) { reply = r; SetEvent(done); }
};

static bool ParseFloat(const std::string& s, float& out)
{
    char* end = nullptr;
    out = strtof(s.c_str(), &end);
    return end && *end == 0 && !s.empty();
}

static Vec2 ToScreen(float x, float y, const std::vector<std::string>& a, size_t refIndex)
{
    float sw = (float)ToInt(StaticGet(K.screen, "get_width")), sh = (float)ToInt(StaticGet(K.screen, "get_height"));
    float sx = x, sy = y, rw, rh;
    if (a.size() > refIndex + 1 && ParseFloat(a[refIndex], rw) && ParseFloat(a[refIndex + 1], rh) && rw > 0 && rh > 0)
    {
        sx = x * sw / rw;
        sy = y * sh / rh;
    }
    return Vec2{ sx, sh - sy };
}

struct Job
{
    Cmd* cmd = nullptr;
    virtual ~Job() {}
    virtual bool Step(int frame, ULONGLONG nowMs) = 0; // true when finished
};

struct TapJob : Job
{
    Vec2 pos{}; float holdMs = 80; float toX = 0, toY = 0; float durationMs = 0; bool swipe = false;
    Pointer p; int phase = 0, lastFrame = -1, startFrame = 0, releaseFrame = 0; ULONGLONG startMs = 0; bool legacy = false;
    Vec2 to{};

    bool Step(int frame, ULONGLONG now) override
    {
        switch (phase)
        {
        case 0:
        {
            if (!NewPointer(p, pos)) { cmd->Complete("err no EventSystem"); return true; }
            void* go = RaycastUpdate(p);
            if (!go) { cmd->Complete("miss"); return true; }
            p.target.Set(go);
            legacy = UsesLegacyModule() && MouseBegin(pos);
            if (!legacy) { PressDown(p, go); MouseBegin(pos); }
            startFrame = frame; startMs = now; lastFrame = frame; phase = 1;
            return false;
        }
        case 1:
        {
            if (frame == lastFrame) return false; // one step per frame; down and up never share a frame
            lastFrame = frame;
            if (swipe)
            {
                float t = durationMs <= 0 ? 1.f : (float)(now - startMs) / durationMs;
                t = t < 0 ? 0 : (t > 1 ? 1 : t);
                Vec2 next{ pos.x + (to.x - pos.x) * t, pos.y + (to.y - pos.y) * t };
                MouseMove(next);
                if (!legacy) MoveTo(p, next);
                if (t < 1.f) return false;
            }
            else if (frame <= startFrame || (float)(now - startMs) < holdMs) return false;
            MouseEnd();
            if (!legacy) { RaycastUpdate(p); ReleasePointer(p); }
            releaseFrame = frame; phase = 2;
            return false;
        }
        default:
            if (frame < releaseFrame + 2) return false; // the module / polling scripts see Up on the following frame
            cmd->Complete("ok " + PathOf(p.target.Get()));
            return true;
        }
    }
};

static std::string Probe(Vec2 pos)
{
    Pointer p;
    if (!NewPointer(p, pos)) return "err no EventSystem";
    void* es = CurrentEventSystem();
    void* module = Call(Method(K.eventSystem, "get_currentInputModule", 0), es);
    std::string out = "ok module=" + std::string(module ? il2cpp_class_get_name(il2cpp_object_get_class(module)) : "none");
    void* raycastAll = Method(K.eventSystem, "RaycastAll", 2);
    void* listClass = il2cpp_class_from_type(il2cpp_method_get_param(raycastAll, 1));
    void* list = il2cpp_object_new(listClass);
    Call(Method(listClass, ".ctor", 0), list);
    p.list.Set(list);
    void* args[2] = { p.data.Get(), list };
    Call(raycastAll, es, args);
    int count = ToInt(Call(Method(listClass, "get_Count", 0), list));
    out += " hits=" + std::to_string(count);
    int shown = 0;
    for (int i = 0; i < count && shown < 6; i++)
    {
        void* itemArgs[1] = { &i };
        void* boxed = Call(Method(listClass, "get_Item", 1), list, itemArgs);
        void* go = nullptr;
        if (boxed) il2cpp_field_get_value(boxed, K.raycastField, &go);
        if (!go) continue;
        shown++;
        void* down = GetEventHandler(go, K.iDown);
        void* click = GetEventHandler(go, K.iClick);
        out += " | " + PathOf(go) + " {down=" + (down ? PathOf(down) : "-") + " click=" + (click ? PathOf(click) : "-");
        if (down)
        {
            out += " comps=";
            for (void* c : ComponentsOf(down)) out += std::string(il2cpp_class_get_name(il2cpp_object_get_class(c))) + ",";
        }
        out += "}";
    }
    return out;
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// main-thread pump
// ───────────────────────────────────────────────────────────────────────────────────────────
static std::atomic<bool> g_running{ false };
static std::mutex g_queueMutex;
static std::deque<Cmd*> g_queue;
static Job* g_job = nullptr;
static HWND g_hwnd = nullptr;
static DWORD g_mainThread = 0;
static HHOOK g_hook = nullptr;
static HMODULE g_self = nullptr;
static SOCKET g_listen = INVALID_SOCKET;
static bool g_inited = false;
static ULONGLONG g_nextInitAttempt = 0;

// uGUI's StandaloneInputModule ignores input while EventSystem.isFocused is false; the field behind it
// is forced on every tick.
static void* g_hasFocusField = nullptr;
static bool g_focusResolved = false;
static void ForceFocus()
{
    void* es = CurrentEventSystem();
    if (!es) return;
    if (!g_focusResolved)
    {
        g_focusResolved = true;
        g_hasFocusField = il2cpp_class_get_field_from_name(K.eventSystem, "m_HasFocus");
        Log("Info", g_hasFocusField ? "EventSystem focus is forced on" : "EventSystem.m_HasFocus not found");
    }
    if (g_hasFocusField)
    {
        uint8_t on = 1;
        il2cpp_field_set_value(es, g_hasFocusField, &on);
    }
}

static bool InitIl2Cpp()
{
    HMODULE ga = GetModuleHandleW(L"GameAssembly.dll");
    if (!ga) { Log("Error", "GameAssembly.dll is not loaded: not an IL2CPP game"); return false; }
    if (!ResolveApi(ga)) return false;
    g_domain = il2cpp_domain_get();
    il2cpp_thread_attach(g_domain); // the main thread is already attached; harmless
    if (!LoadKnown()) { Log("Error", "required UnityEngine classes/members are missing (stripped?)"); return false; }
    Log("Info", "Macro2k Unity Bridge %s ready (IL2CPP)", kVersion);
    return true;
}

static std::string Lower(std::string s)
{
    for (char& c : s) c = (char)tolower((unsigned char)c);
    return s;
}

static void StartCommand(Cmd* cmd)
{
    const std::vector<std::string>& a = cmd->args;
    std::string verb = Lower(a[0]);
    if (verb == "ping")
    {
        int w = ToInt(StaticGet(K.screen, "get_width")), h = ToInt(StaticGet(K.screen, "get_height"));
        cmd->Complete("ok Macro2kBridge " + std::string(kVersion) + " " + std::to_string(w) + " " + std::to_string(h));
    }
    else if (verb == "tap")
    {
        float x, y, hold;
        if (a.size() < 3 || !ParseFloat(a[1], x) || !ParseFloat(a[2], y)) { cmd->Complete("err usage: tap x y [holdMs] [refW refH]"); return; }
        TapJob* job = new TapJob();
        job->cmd = cmd;
        job->pos = ToScreen(x, y, a, 4);
        job->holdMs = a.size() > 3 && ParseFloat(a[3], hold) ? hold : 80.f;
        g_job = job;
    }
    else if (verb == "swipe")
    {
        float x1, y1, x2, y2, ms;
        if (a.size() < 5 || !ParseFloat(a[1], x1) || !ParseFloat(a[2], y1) || !ParseFloat(a[3], x2) || !ParseFloat(a[4], y2))
        {
            cmd->Complete("err usage: swipe x1 y1 x2 y2 [ms] [refW refH]");
            return;
        }
        TapJob* job = new TapJob();
        job->cmd = cmd;
        job->swipe = true;
        job->pos = ToScreen(x1, y1, a, 6);
        job->to = ToScreen(x2, y2, a, 6);
        job->durationMs = a.size() > 5 && ParseFloat(a[5], ms) ? ms : 300.f;
        g_job = job;
    }
    else if (verb == "probe")
    {
        float x, y;
        if (a.size() < 3 || !ParseFloat(a[1], x) || !ParseFloat(a[2], y)) { cmd->Complete("err usage: probe x y [refW refH]"); return; }
        cmd->Complete(Probe(ToScreen(x, y, a, 3)));
    }
    else
    {
        // keys are not implemented in the IL2CPP build; the same reply older plugins gave, so Macro2k
        // falls back to window messages
        cmd->Complete("err unknown command: " + a[0]);
    }
}

static Cmd* PopCommand()
{
    std::lock_guard<std::mutex> lock(g_queueMutex);
    if (g_queue.empty()) return nullptr;
    Cmd* c = g_queue.front();
    g_queue.pop_front();
    return c;
}

static void TickInner()
{
    if (!g_inited)
    {
        ULONGLONG now = GetTickCount64();
        if (now >= g_nextInitAttempt)
        {
            g_inited = InitIl2Cpp();
            if (!g_inited) g_nextInitAttempt = now + 500;
        }
        if (!g_inited)
        {
            while (Cmd* c = PopCommand()) c->Complete("err the IL2CPP API is unavailable; retrying (see the bridge log)");
            return;
        }
    }
    int frame = FrameCount();
    ULONGLONG now = GetTickCount64();
    ForceFocus();
    MouseTick(frame);
    if (g_job && g_job->Step(frame, now)) { delete g_job; g_job = nullptr; }
    if (!g_job)
    {
        if (Cmd* c = PopCommand())
        {
            StartCommand(c);
            if (g_job && g_job->Step(frame, now)) { delete g_job; g_job = nullptr; }
        }
    }
}

// Called from the __except filter, so it runs before SafeTick unwinds (g_job is still valid there).
// Everything that touches a C++ object (std::string, delete) lives here, never in SafeTick itself:
// /EHsc rejects __try/__except in a function that also needs C++ object unwinding.
static int TickFilter(unsigned code)
{
    Log("Error", "access fault while ticking (code 0x%08X)", code);
    if (g_job) { g_job->cmd->Complete("err bridge fault"); delete g_job; g_job = nullptr; }
    return EXCEPTION_EXECUTE_HANDLER;
}

static void SafeTick()
{
    __try
    {
        TickInner();
    }
    __except (TickFilter(GetExceptionCode()))
    {
    }
}

static LRESULT CALLBACK GetMsgProc(int code, WPARAM wParam, LPARAM lParam)
{
    static bool inTick = false;
    static ULONGLONG lastTick = 0;
    if (code >= 0 && g_running && !inTick)
    {
        ULONGLONG now = GetTickCount64();
        if (now != lastTick)
        {
            lastTick = now;
            inTick = true;
            SafeTick();
            inTick = false;
        }
    }
    return CallNextHookEx(g_hook, code, wParam, lParam);
}

// ───────────────────────────────────────────────────────────────────────────────────────────
// server
// ───────────────────────────────────────────────────────────────────────────────────────────
static int EstimateDurationMs(const std::vector<std::string>& a)
{
    std::string verb = Lower(a[0]);
    size_t index = verb == "tap" ? 3 : verb == "swipe" ? 5 : 0;
    float ms;
    return index && a.size() > index && ParseFloat(a[index], ms) && ms > 0 ? (int)ms : 0;
}

static std::string Dispatch(const std::string& line)
{
    std::vector<std::string> args;
    size_t i = 0;
    while (i < line.size())
    {
        while (i < line.size() && isspace((unsigned char)line[i])) i++;
        size_t start = i;
        while (i < line.size() && !isspace((unsigned char)line[i])) i++;
        if (i > start) args.push_back(line.substr(start, i - start));
    }
    if (args.empty()) return "err empty";
    Cmd* cmd = new Cmd();
    cmd->args = args;
    int timeout = EstimateDurationMs(args) + 5000;
    {
        std::lock_guard<std::mutex> lock(g_queueMutex);
        g_queue.push_back(cmd);
    }
    if (g_hwnd) PostMessageW(g_hwnd, WM_NULL, 0, 0);
    if (WaitForSingleObject(cmd->done, (DWORD)timeout) != WAIT_OBJECT_0)
        return "err timeout (game main thread not running?)"; // cmd is left to the pump; freeing it here could race
    std::string reply = cmd->reply;
    delete cmd;
    return reply;
}

static void ClientThread(SOCKET s)
{
    std::string buffer;
    char chunk[512];
    while (g_running)
    {
        int n = recv(s, chunk, sizeof chunk, 0);
        if (n <= 0) break;
        buffer.append(chunk, n);
        size_t nl;
        while ((nl = buffer.find('\n')) != std::string::npos)
        {
            std::string line = buffer.substr(0, nl);
            buffer.erase(0, nl + 1);
            while (!line.empty() && (line.back() == '\r' || line.back() == ' ')) line.pop_back();
            std::string reply = Dispatch(line) + "\n";
            send(s, reply.c_str(), (int)reply.size(), 0);
        }
    }
    closesocket(s);
}

static int ReadPort()
{
    char tmp[MAX_PATH];
    GetTempPathA(MAX_PATH, tmp);
    std::string path = std::string(tmp) + "Macro2kBridge.port";
    HANDLE h = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return kDefaultPort;
    char buf[32] = {};
    DWORD n = 0;
    ReadFile(h, buf, sizeof buf - 1, &n, nullptr);
    CloseHandle(h);
    int port = atoi(buf);
    return port > 0 && port < 65536 ? port : kDefaultPort;
}

static bool StartServer(int port)
{
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;
    g_listen = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons((u_short)port);
    inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
    if (bind(g_listen, reinterpret_cast<sockaddr*>(&addr), sizeof addr) != 0 || listen(g_listen, 8) != 0)
    {
        Log("Error", "cannot listen on 127.0.0.1:%d (WSA error %d); another bridge may use the port", port, WSAGetLastError());
        closesocket(g_listen);
        g_listen = INVALID_SOCKET;
        return false;
    }
    std::thread([] {
        while (g_running)
        {
            SOCKET client = accept(g_listen, nullptr, nullptr);
            if (client == INVALID_SOCKET) break;
            std::thread(ClientThread, client).detach();
        }
    }).detach();
    Log("Info", "Listening on 127.0.0.1:%d", port);
    return true;
}

static BOOL CALLBACK FindUnityWindow(HWND hwnd, LPARAM)
{
    DWORD pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (pid != GetCurrentProcessId()) return TRUE;
    char cls[64] = {};
    GetClassNameA(hwnd, cls, sizeof cls);
    if (strcmp(cls, "UnityWndClass") != 0) return TRUE;
    g_hwnd = hwnd;
    return FALSE;
}

static DWORD WINAPI Startup(LPVOID)
{
    Log("Info", "Macro2kBridge.Il2Cpp %s loading", kVersion);
    for (int i = 0; i < 600 && !g_hwnd; i++)
    {
        EnumWindows(FindUnityWindow, 0);
        if (!g_hwnd) Sleep(100);
    }
    if (!g_hwnd) { Log("Error", "no UnityWndClass window in this process"); return 1; }
    g_mainThread = GetWindowThreadProcessId(g_hwnd, nullptr);

    g_running = true;
    if (!StartServer(ReadPort())) { g_running = false; return 1; }
    g_hook = SetWindowsHookExW(WH_GETMESSAGE, GetMsgProc, g_self, g_mainThread);
    if (!g_hook) { Log("Error", "SetWindowsHookEx failed (%lu)", GetLastError()); g_running = false; return 1; }

    // keep the game's message loop turning so the hook gets to run (Unity pumps messages every frame)
    while (g_running)
    {
        bool busy;
        {
            std::lock_guard<std::mutex> lock(g_queueMutex);
            busy = !g_queue.empty();
        }
        busy = busy || g_job != nullptr;
        PostMessageW(g_hwnd, WM_NULL, 0, 0);
        Sleep(busy ? 4 : 40);
    }
    return 0;
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        g_self = module;
        DisableThreadLibraryCalls(module);
        HANDLE t = CreateThread(nullptr, 0, Startup, nullptr, 0, nullptr);
        if (t) CloseHandle(t);
    }
    return TRUE;
}
