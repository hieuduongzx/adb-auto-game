/* Macro2k shared theme controller — dark/light theme + comfortable/compact
   density, persisted and applied before first paint.

   Load this early (before the app stylesheet) on every surface:
     <script src="../shared/theme.js"></script>

   Behaviour:
   • Applies `data-theme` / `data-density` to <html> immediately from
     localStorage so the first paint already uses the right theme (no flash).
   • Once `window.pywebview.api.get_settings()` is available it reconciles with
     the persisted backend settings (the source of truth across apps) and
     re-applies if they differ.
   • Exposes `window.uiTheme.set(theme)` / `window.uiTheme.setDensity(d)` and
     `window.uiTheme.toggle()` for settings UIs, which apply + persist.
*/
(function () {
  "use strict";
  var LS_THEME = "m2k-theme";
  var LS_DENSITY = "m2k-density";

  function normTheme(t) { return t === "dark" ? "dark" : "light"; }
  function normDensity(d) { return d === "compact" ? "compact" : "comfortable"; }

  function apply(theme, density) {
    var root = document.documentElement;
    root.setAttribute("data-theme", normTheme(theme));
    root.setAttribute("data-density", normDensity(density));
  }

  function current() {
    var root = document.documentElement;
    return {
      theme: normTheme(root.getAttribute("data-theme")),
      density: normDensity(root.getAttribute("data-density")),
    };
  }

  function persistLocal(theme, density) {
    try {
      localStorage.setItem(LS_THEME, normTheme(theme));
      localStorage.setItem(LS_DENSITY, normDensity(density));
    } catch (e) {}
  }

  function persistBackend(theme, density) {
    try {
      var api = window.pywebview && window.pywebview.api;
      if (api && typeof api.save_settings === "function") {
        api.save_settings({ theme: normTheme(theme), density: normDensity(density) });
      }
    } catch (e) {}
  }

  function set(theme, density) {
    var cur = current();
    var t = theme != null ? theme : cur.theme;
    var d = density != null ? density : cur.density;
    apply(t, d);
    persistLocal(t, d);
    persistBackend(t, d);
    // Re-render anything that listens (e.g. canvas) on theme change.
    try {
      window.dispatchEvent(new CustomEvent("m2k-theme", { detail: { theme: normTheme(t), density: normDensity(d) } }));
    } catch (e) {}
    return { theme: normTheme(t), density: normDensity(d) };
  }

  // 1) Immediate apply from localStorage (no flash before backend is ready).
  var bootTheme = "light", bootDensity = "comfortable";
  try {
    bootTheme = localStorage.getItem(LS_THEME) || "light";
    bootDensity = localStorage.getItem(LS_DENSITY) || "comfortable";
  } catch (e) {}
  apply(bootTheme, bootDensity);

  // 2) Reconcile with backend settings once pywebview is ready.
  function reconcile() {
    try {
      var api = window.pywebview && window.pywebview.api;
      if (!api || typeof api.get_settings !== "function") return;
      var p = api.get_settings();
      if (p && typeof p.then === "function") {
        p.then(function (st) {
          if (!st) return;
          var t = st.theme, d = st.density;
          if (t || d) {
            var cur = current();
            set(t || cur.theme, d || cur.density);
          }
        }).catch(function () {});
      }
    } catch (e) {}
  }
  if (window.pywebview && window.pywebview.api) {
    reconcile();
  } else {
    window.addEventListener("pywebviewready", reconcile);
    // Fallback: some builds fire DOMContentLoaded before the bridge is ready.
    document.addEventListener("DOMContentLoaded", function () { setTimeout(reconcile, 0); });
  }

  window.uiTheme = {
    set: set,
    setTheme: function (t) { return set(t, null); },
    setDensity: function (d) { return set(null, d); },
    toggle: function () { var c = current(); return set(c.theme === "dark" ? "light" : "dark", null); },
    current: current,
  };
})();
