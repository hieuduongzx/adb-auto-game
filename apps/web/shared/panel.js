/* Macro2k shared panel controller — the behaviour half of panel.css.

   Load after shared/theme.js on every surface:
     <script src="../shared/panel.js"></script>

   Markup contract — a panel opts in with one attribute:

     <section class="pnl" data-pnl="log" data-pnl-title="Log">
       <div class="pnl-hd">
         <button class="pnl-title"><span>Log</span><span class="pnl-count"></span></button>
         <div class="pnl-tools">…panel-specific tools go here…</div>
       </div>
       <div class="pnl-body">…</div>
     </section>

   This file appends the two universal tools (maximize, collapse) to the END of
   .pnl-tools, so every panel in the suite ends with the same pair in the same
   order no matter what app-specific buttons come before them. Opt out per
   panel with data-pnl-tools="max" | "collapse" | "none".

   Maximize moves the panel node onto the nearest [data-pnl-stage] ancestor and
   leaves a placeholder behind, so a panel can escape an overflow:hidden column
   without any z-index fight. Escape restores it.

   Collapsed state is remembered per panel id in localStorage. Every change
   fires a `m2k-pnl` CustomEvent on window ({ id, el, state }) so a surface with
   a canvas can re-measure. */
(function () {
  "use strict";

  var LS = "m2k-pnl:";
  var ICON = {
    max: '<svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>',
    min: '<svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="M8 3v3a2 2 0 0 1-2 2H3"/><path d="M21 8h-3a2 2 0 0 1-2-2V3"/><path d="M3 16h3a2 2 0 0 1 2 2v3"/><path d="M16 21v-3a2 2 0 0 1 2-2h3"/></svg>',
    chev: '<svg class="uico" aria-hidden="true" viewBox="0 0 24 24"><path d="m18 15-6-6-6 6"/></svg>',
  };

  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function idOf(el) { return el.getAttribute("data-pnl") || ""; }

  function load(id) {
    if (!id) return null;
    try { return localStorage.getItem(LS + id); } catch (e) { return null; }
  }
  function save(id, v) {
    if (!id) return;
    try { v ? localStorage.setItem(LS + id, v) : localStorage.removeItem(LS + id); } catch (e) {}
  }

  function emit(el, state) {
    try {
      window.dispatchEvent(new CustomEvent("m2k-pnl", {
        detail: { id: idOf(el), el: el, state: state },
      }));
    } catch (e) {}
    // Panels commonly sit next to a canvas that sizes itself from its box.
    try { window.dispatchEvent(new Event("resize")); } catch (e) {}
  }

  function title(el) {
    var t = el.getAttribute("data-pnl-title");
    if (t) return t;
    var node = el.querySelector(".pnl-title > span");
    return node ? node.textContent.trim() : "panel";
  }

  /* ── collapse ─────────────────────────────────────────────────────────── */

  function isCollapsed(el) { return el.classList.contains("is-collapsed"); }

  function setCollapsed(el, on, quiet) {
    if (el.classList.contains("is-max")) return;   // maximized panels never collapse
    el.classList.toggle("is-collapsed", !!on);
    var btn = el.querySelector('.pnl-tool[data-pnl-act="collapse"]');
    if (btn) {
      btn.setAttribute("aria-expanded", on ? "false" : "true");
      btn.title = (on ? "Expand " : "Collapse ") + title(el);
    }
    var ttl = el.querySelector("button.pnl-title");
    if (ttl) ttl.setAttribute("aria-expanded", on ? "false" : "true");
    if (!quiet) { save(idOf(el), on ? "collapsed" : ""); emit(el, on ? "collapsed" : "open"); }
  }

  function toggleCollapse(el) { setCollapsed(el, !isCollapsed(el)); }

  /* ── maximize ─────────────────────────────────────────────────────────── */

  var maxed = null;          // the panel currently owning its stage
  var slot = null;           // placeholder marking where it came from
  var stageEl = null;

  function stageFor(el) {
    // A panel docked outside the workspace (a bottom log drawer, say) names the
    // stage it wants to take over instead of inheriting its own container.
    var sel = el.getAttribute("data-pnl-stage-sel");
    if (sel) { var named = document.querySelector(sel); if (named) return named; }
    var n = el.parentElement;
    while (n && n !== document.body) {
      if (n.hasAttribute && n.hasAttribute("data-pnl-stage")) return n;
      n = n.parentElement;
    }
    return document.getElementById("app") || document.body;
  }

  function syncMaxBtn(el) {
    var btn = el && el.querySelector('.pnl-tool[data-pnl-act="max"]');
    if (!btn) return;
    var on = el.classList.contains("is-max");
    btn.innerHTML = on ? ICON.min : ICON.max;
    btn.classList.toggle("on", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.title = (on ? "Restore " : "Maximize ") + title(el) + (on ? " (Esc)" : "");
  }

  function restore() {
    if (!maxed) return;
    var el = maxed, was = el;
    el.classList.remove("is-max");
    if (slot && slot.parentNode) { slot.parentNode.replaceChild(el, slot); }
    if (stageEl) stageEl.classList.remove("has-max");
    maxed = null; slot = null; stageEl = null;
    syncMaxBtn(el);
    emit(was, "restored");
  }

  function maximize(el) {
    if (maxed === el) { restore(); return; }
    if (maxed) restore();
    setCollapsed(el, false, true);
    stageEl = stageFor(el);
    slot = document.createComment("pnl:" + idOf(el));
    el.parentNode.insertBefore(slot, el);
    stageEl.appendChild(el);
    stageEl.classList.add("has-max");
    el.classList.add("is-max");
    maxed = el;
    syncMaxBtn(el);
    emit(el, "maximized");
  }

  function toggleMax(el) { (maxed === el) ? restore() : maximize(el); }

  /* ── wiring ───────────────────────────────────────────────────────────── */

  function tool(act, html, label) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "pnl-tool";
    b.setAttribute("data-pnl-act", act);
    b.title = label;
    b.setAttribute("aria-label", label);
    b.innerHTML = html;
    return b;
  }

  function wire(el) {
    if (el.__pnlWired) return;
    el.__pnlWired = true;

    var want = (el.getAttribute("data-pnl-tools") || "max collapse").toLowerCase();
    var wantMax = want.indexOf("max") >= 0;
    var wantCol = want.indexOf("collapse") >= 0;

    var hd = el.querySelector(".pnl-hd");
    if (!hd) return;
    var tools = hd.querySelector(".pnl-tools");
    if (!tools) { tools = document.createElement("div"); tools.className = "pnl-tools"; hd.appendChild(tools); }

    if (wantMax && !tools.querySelector('[data-pnl-act="max"]')) {
      tools.appendChild(tool("max", ICON.max, "Maximize " + title(el)));
    }
    if (wantCol && !tools.querySelector('[data-pnl-act="collapse"]')) {
      var c = tool("collapse", ICON.chev, "Collapse " + title(el));
      c.setAttribute("aria-expanded", "true");
      var body = el.querySelector(".pnl-body");
      if (body) {
        if (!body.id) body.id = "pnl-body-" + (idOf(el) || Math.random().toString(36).slice(2, 8));
        c.setAttribute("aria-controls", body.id);
      }
      tools.appendChild(c);
    }

    // The title doubles as the collapse target — a 100px hit area beats a 14px one.
    var ttl = hd.querySelector("button.pnl-title");
    if (ttl && wantCol) {
      ttl.setAttribute("aria-expanded", "true");
      ttl.addEventListener("click", function (ev) { ev.preventDefault(); toggleCollapse(el); });
    }

    tools.addEventListener("click", function (ev) {
      var b = ev.target.closest ? ev.target.closest("[data-pnl-act]") : null;
      if (!b || !tools.contains(b)) return;
      var act = b.getAttribute("data-pnl-act");
      if (act === "max") { ev.preventDefault(); toggleMax(el); }
      else if (act === "collapse") { ev.preventDefault(); toggleCollapse(el); }
    });

    syncMaxBtn(el);
    if (wantCol && load(idOf(el)) === "collapsed") setCollapsed(el, true, true);
  }

  function init(root) {
    $$(".pnl[data-pnl]", root || document).forEach(wire);
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && maxed) {
      var tag = (ev.target && ev.target.tagName) || "";
      // Let a focused field swallow Escape first (clearing a search, closing a menu).
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      ev.preventDefault();
      restore();
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { init(); });
  } else {
    init();
  }

  window.uiPanel = {
    init: init,
    wire: wire,
    collapse: function (id) { var el = find(id); if (el) setCollapsed(el, true); },
    expand: function (id) { var el = find(id); if (el) setCollapsed(el, false); },
    toggle: function (id) { var el = find(id); if (el) toggleCollapse(el); },
    maximize: function (id) { var el = find(id); if (el) maximize(el); },
    restore: restore,
    isMaximized: function (id) { return !!maxed && (!id || idOf(maxed) === id); },
  };

  function find(id) {
    return typeof id === "string" ? document.querySelector('.pnl[data-pnl="' + id + '"]') : id;
  }
})();
