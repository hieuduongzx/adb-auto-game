/* Macro2k Hub — game library: every workflow project as a cover card. */

// ── Tiny helpers ─────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview && window.pywebview.api;

function escHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ── Toast ────────────────────────────────────────────────────────────────────
// Level -> the shared icon of the same name. The four glyphs used to be drawn
// here by hand (a fat polyline check, a 9px info circle) and disagreed with the
// Designer's own hand-drawn copies; both now read the shared set.
const TOAST_ICO = {
  success: "check",
  error:   "x",
  warning: "triangle-alert",
  info:    "info",
};
function toast(msg, level) {
  level = TOAST_ICO[level] ? level : "info";
  let host = $("ui-toasts");
  if (!host) {
    host = document.createElement("div");
    host.id = "ui-toasts";
    host.setAttribute("role", "status");
    host.setAttribute("aria-live", "polite");
    document.body.appendChild(host);
  }
  const t = document.createElement("div");
  t.className = "ui-toast ui-" + level;
  t.innerHTML =
    uiIco(TOAST_ICO[level], "uico-2") +
    `<span class="ui-toast-msg">${escHtml(msg)}</span>`;
  t.title = "Click to dismiss";
  host.appendChild(t);
  while (host.children.length > 4) host.removeChild(host.firstChild);
  let gone = false;
  const dismiss = () => {
    if (gone) return;
    gone = true;
    t.classList.add("out");
    t.addEventListener("animationend", () => t.remove(), { once: true });
    setTimeout(() => t.remove(), 300);
  };
  t.onclick = dismiss;
  setTimeout(dismiss, level === "error" ? 5200 : 2800);
}

// ── Modal ────────────────────────────────────────────────────────────────────
let _modal = null;
function modalClose(result) {
  if (!_modal) return;
  const m = _modal;
  _modal = null;
  document.removeEventListener("keydown", m.onKey, true);
  m.wrap.remove();
  if (m.prevFocus && m.prevFocus.focus) try { m.prevFocus.focus(); } catch {}
  m.resolve(result);
}
function modal(spec) {
  return new Promise((resolve) => {
    if (_modal) modalClose(undefined);
    const wrap = document.createElement("div");
    wrap.className = "ui-modal-wrap";
    const box = document.createElement("div");
    box.className = "ui-modal";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    if (spec.title) {
      const hd = document.createElement("div");
      hd.className = "ui-modal-hd";
      hd.textContent = spec.title;
      box.appendChild(hd);
    }
    const bd = document.createElement("div");
    bd.className = "ui-modal-bd";
    if (typeof spec.body === "function") spec.body(bd);
    else if (spec.body != null) bd.innerHTML = spec.body;
    box.appendChild(bd);
    const ft = document.createElement("div");
    ft.className = "ui-modal-ft";
    let primary = null;
    (spec.buttons || [{ label: "OK", value: true, kind: "accent" }]).forEach((b) => {
      const btn = document.createElement("button");
      btn.className = "btn" + (b.kind ? " " + b.kind : "");
      btn.textContent = b.label;
      btn.onclick = () => modalClose(b.value);
      if (b.kind === "accent" || b.autofocus) primary = btn;
      ft.appendChild(btn);
    });
    box.appendChild(ft);
    wrap.appendChild(box);
    wrap.addEventListener("mousedown", (e) => {
      if (e.target === wrap) modalClose(undefined);
    });
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); modalClose(undefined); }
      else if (e.key === "Enter" && primary && document.activeElement &&
               document.activeElement.tagName !== "BUTTON") {
        e.preventDefault();
        primary.click();
      }
    };
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    _modal = { wrap, resolve, onKey, prevFocus: document.activeElement };
    const focusEl = box.querySelector("input,button");
    if (focusEl) setTimeout(() => focusEl.focus(), 20);
  });
}

// ── New game dialog ──────────────────────────────────────────────────────────
/** Every Win32 input transport the engine accepts (src/core/win32/automation.py
    `_INPUT_MODES`) — keep in step with the Designer's Project settings. */
const WIN_INPUT_MODES = [
  "background", "background_sync", "background_cursor", "background_window",
  "anchored_touch", "unity_bridge", "foreground",
];

/** Collect create-dialog fields. Returns project backend settings or null. */
function readNewWorkflowForm(box) {
  const name = (box.querySelector("#hub-name-input").value || "").trim() || "My Game";
  const ctrlBtn = box.querySelector('.choice-seg[data-field="controller"] .choice.on');
  const capBtn = box.querySelector('.choice-seg[data-field="capture"] .choice.on');
  const inputBtn = box.querySelector('.choice-seg[data-field="inputMode"] .choice.on');
  const controller = (ctrlBtn && ctrlBtn.dataset.value === "win32") ? "win32" : "adb";
  // Capture only applies to ADB; input mode only applies to Win32.
  const capture = (controller === "adb" && capBtn && capBtn.dataset.value === "adb")
    ? "adb" : "scrcpy";
  const allowedModes = new Set(WIN_INPUT_MODES);
  const inputMode = inputBtn && allowedModes.has(inputBtn.dataset.value)
    ? inputBtn.dataset.value : "background";
  return { name, controller, capture, inputMode };
}

function wireChoiceSeg(box) {
  box.querySelectorAll(".choice-seg").forEach((seg) => {
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest(".choice");
      if (!btn || btn.disabled || seg.classList.contains("disabled")) return;
      seg.querySelectorAll(".choice").forEach((c) => c.classList.remove("on"));
      btn.classList.add("on");
      if (seg.dataset.field === "controller") syncBackendFields(box);
    });
  });
  syncBackendFields(box);
}

function syncBackendFields(box) {
  const ctrlBtn = box.querySelector('.choice-seg[data-field="controller"] .choice.on');
  const win32 = ctrlBtn && ctrlBtn.dataset.value === "win32";
  const capField = box.querySelector("#hub-capture-field");
  const inputField = box.querySelector("#hub-input-field");
  // Use explicit display instead of the HTML hidden attribute. WebView2 can
  // retain the attribute's UA `display:none` after dynamic modal updates.
  if (capField) capField.style.display = win32 ? "none" : "";
  if (inputField) inputField.style.display = win32 ? "" : "none";
}

/** New-game dialog → backend settings or null if cancelled. */
function promptNewWorkflow() {
  return new Promise((resolve) => {
    if (_modal) modalClose(undefined);
    const wrap = document.createElement("div");
    wrap.className = "ui-modal-wrap";
    const box = document.createElement("div");
    box.className = "ui-modal ui-modal-wide";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.innerHTML =
      `<div class="ui-modal-hd">New game</div>` +
      `<div class="ui-modal-bd">` +
        `<div class="form-field">` +
          `<label for="hub-name-input">Game name</label>` +
          `<input id="hub-name-input" type="text" spellcheck="false" autocomplete="off" value="My Game">` +
        `</div>` +
        `<div class="form-field">` +
          `<span class="form-lbl">Controller</span>` +
          `<div class="choice-seg" data-field="controller" role="group" aria-label="Controller">` +
            `<button type="button" class="choice on" data-value="adb">` +
              `<span class="choice-title">ADB</span>` +
              `<span class="choice-sub">Device / emulator</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="win32">` +
              `<span class="choice-title">Win32</span>` +
              `<span class="choice-sub">PC window</span>` +
            `</button>` +
          `</div>` +
        `</div>` +
        `<div class="form-field" id="hub-capture-field">` +
          `<span class="form-lbl">Capture source</span>` +
          `<div class="choice-seg" data-field="capture" role="group" aria-label="Capture source">` +
            `<button type="button" class="choice on" data-value="scrcpy">` +
              `<span class="choice-title">scrcpy</span>` +
              `<span class="choice-sub">Fast stream</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="adb">` +
              `<span class="choice-title">ADB</span>` +
              `<span class="choice-sub">screencap</span>` +
            `</button>` +
          `</div>` +
          `<p class="ui-modal-hint">How the device screen is grabbed during preview and runs.</p>` +
        `</div>` +
        `<div class="form-field" id="hub-input-field" style="display:none">` +
          `<span class="form-lbl">Win32 input mode</span>` +
          `<div class="choice-seg choice-seg-4" data-field="inputMode" role="group" aria-label="Win32 input mode">` +
            `<button type="button" class="choice on" data-value="background">` +
              `<span class="choice-title">Background</span>` +
              `<span class="choice-sub">PostMessage</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="background_sync">` +
              `<span class="choice-title">BG sync</span>` +
              `<span class="choice-sub">SendMessage</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="background_cursor">` +
              `<span class="choice-title">Cursor</span>` +
              `<span class="choice-sub">Unity / Unreal</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="background_window">` +
              `<span class="choice-title">Window</span>` +
              `<span class="choice-sub">No cursor move</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="anchored_touch">` +
              `<span class="choice-title">Anchored</span>` +
              `<span class="choice-sub">WM_POINTER</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="unity_bridge">` +
              `<span class="choice-title">Bridge</span>` +
              `<span class="choice-sub">In-game plugin</span>` +
            `</button>` +
            `<button type="button" class="choice" data-value="foreground">` +
              `<span class="choice-title">Foreground</span>` +
              `<span class="choice-sub">Real mouse</span>` +
            `</button>` +
          `</div>` +
          `<p class="ui-modal-hint">How clicks and swipes are delivered to the PC window.</p>` +
        `</div>` +
        `<p class="ui-modal-hint">Creates <span class="mono">workflows/&lt;Name&gt;/workflow.json</span> and opens the Designer. ` +
          `Put the cover art at <span class="mono">workflows/&lt;Name&gt;/assets/cover.png</span> (3:4) ` +
          `and the icon at <span class="mono">assets/icon.png</span> (square).</p>` +
      `</div>` +
      `<div class="ui-modal-ft">` +
        `<button type="button" class="btn" data-v="cancel">Cancel</button>` +
        `<button type="button" class="btn accent" data-v="ok">Create</button>` +
      `</div>`;
    wrap.appendChild(box);
    wireChoiceSeg(box);

    const finish = (val) => {
      document.removeEventListener("keydown", onKey, true);
      wrap.remove();
      _modal = null;
      resolve(val);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); finish(null); }
      else if (e.key === "Enter") {
        // Don't submit when focusing a choice button (space/enter toggles).
        if (e.target && e.target.closest && e.target.closest(".choice")) return;
        e.preventDefault();
        finish(readNewWorkflowForm(box));
      }
    };
    box.querySelector('[data-v="cancel"]').onclick = () => finish(null);
    box.querySelector('[data-v="ok"]').onclick = () => finish(readNewWorkflowForm(box));
    wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) finish(null); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    _modal = { wrap, resolve: () => {}, onKey, prevFocus: document.activeElement };
    const inp = box.querySelector("#hub-name-input");
    setTimeout(() => { try { inp.focus(); inp.select(); } catch {} }, 20);
  });
}

// ── State ────────────────────────────────────────────────────────────────────
let GAMES = [];
let FILTER = "";
let BUILD = null;   // {path, name, version, state: running|cancelling|done|failed|cancelled, progress, stage, …}
/** The shelf's widest layout — five covers across (hub.css `--cols`). It is the
    ceiling and the value used before the grid has been laid out; it is never
    the arrow-key step, because the grid reflows on a narrow window. */
const GRID_COLS = 5;

// ── Grid geometry ────────────────────────────────────────────────────────────
/** How many tracks a computed `grid-template-columns` describes. Chromium
    reports used values ("185px 185px …"); a `repeat(3, 185px)` form is counted
    from its repeat count instead. Unreadable values (a grid that is not laid
    out reports "none") fall back to `fallback`. */
function trackCount(value, fallback) {
  const css = String(value == null ? "" : value).trim();
  if (!css || css === "none") return fallback;
  const rep = /^repeat\(\s*(\d+)/i.exec(css);
  if (rep) return Number(rep[1]) || fallback;
  const n = css.split(/\s+/).filter(Boolean).length;
  return n > 0 ? n : fallback;
}

/** Columns the shelf is actually laying out, so arrows move by whole rows at
    every reflow step rather than by a constant that only suits a wide window. */
function gridColumns() {
  const grid = $("grid");
  let css = "";
  try { css = grid ? getComputedStyle(grid).gridTemplateColumns : ""; } catch { css = ""; }
  return Math.max(1, trackCount(css, GRID_COLS));
}

// ── Cover art ────────────────────────────────────────────────────────────────
// The Hub used to keep its own paths here, including a hand-drawn box for Build.
// Every icon now comes from the shared set (shared/icons.js) — one geometry, one
// weight, so the Hub reads the same as the Designer.
const svg = (name, cls) => uiIco(name, cls);

// Hues for cover slots without art: the accent family plus a few calm
// neighbours, picked per game so the same game always gets the same tint.
const TONES = [214, 158, 256, 32, 346, 190];
function toneFor(key) {
  let h = 0;
  for (const ch of String(key || "")) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return TONES[h % TONES.length];
}
/** "BrownDust2" → "BD", "Cherry_Tale" → "CT", "Nikke" → "NI". */
function initialsFor(name) {
  const words = String(name || "")
    .replace(/([a-z])([A-Z0-9])/g, "$1 $2")
    .split(/[\s_\-.]+/)
    .filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}
/** The game's small icon: assets/icon.*, else the cover, else its initials. */
function iconHtmlFor(g, cls) {
  const src = g.icon || g.cover;
  if (src) return `<img class="${cls}" src="${escHtml(src)}" alt="" decoding="async" draggable="false">`;
  return `<span class="${cls} icon-mono" aria-hidden="true">${escHtml(initialsFor(g.name))}</span>`;
}
function emptyArtHtml(name) {
  return `<span class="game-art-empty" aria-hidden="true">` +
    `<span class="art-initials">${escHtml(initialsFor(name))}</span>` +
    `<span class="art-hint">assets/cover.png</span></span>`;
}

// ── Render ───────────────────────────────────────────────────────────────────
function filtered() {
  const q = FILTER.trim().toLowerCase();
  if (!q) return GAMES.slice();
  return GAMES.filter((g) => [g.name, g.folder, g.controller].join(" ").toLowerCase().includes(q));
}

/** One card. The cover is its own button — clicking the art runs the game — and
    the footer under it carries the same Run as a labelled control beside the
    Edit / Build / Delete tools, so nothing on a card depends on hovering to be
    found. Neither button nests inside the other: the delegated click handler
    reads `data-act` from whichever one was hit. */
function cardHtml(g, i) {
  const name = escHtml(g.name);
  const ctrl = g.controller === "win32" ? "win32" : "adb";
  const acts = Number(g.activityCount) || 0;
  const art = g.cover
    ? `<img class="game-img" src="${escHtml(g.cover)}" alt="" decoding="async" draggable="false">`
    : emptyArtHtml(g.name);
  const building = !!(BUILD && BUILD.state === "running" && BUILD.path === g.path);
  return `<article class="game${building ? " is-building" : ""}" role="listitem" data-path="${escHtml(g.path)}" style="--i:${i};--tone:${toneFor(g.folder || g.name)}">` +
    `<button class="game-cover" type="button" data-act="run" title="Run ${name}" aria-label="Run ${name}">` +
      art +
      `<span class="game-building" title="Show build progress"><span class="build-dot"></span>Building <span class="chip-pct">${building ? (BUILD.progress || 0) : 0}%</span></span>` +
    `</button>` +
    `<div class="game-info">` +
      iconHtmlFor(g, "game-icon") +
      `<span class="game-name" title="${name}">${name}</span>` +
      `<span class="game-meta">` +
        `<span class="ctrl-tag ${ctrl}">${ctrl === "win32" ? "Win32" : "ADB"}</span>` +
        `<span class="game-acts">${acts} ${acts === 1 ? "activity" : "activities"}</span>` +
      `</span>` +
    `</div>` +
    `<div class="game-foot">` +
      `<button class="game-run" type="button" data-act="run" title="Run ${name}" aria-label="Run ${name}">${svg("play", "uico-2 uico-fill")}Run</button>` +
      `<span class="game-tools">` +
        `<button class="game-tool" type="button" data-act="edit" title="Edit in Designer (E)" aria-label="Edit ${name}">${svg("pencil", "uico-2")}</button>` +
        `<button class="game-tool" type="button" data-act="build" title="Build a standalone Runner .exe (B)" aria-label="Build Runner exe for ${name}">${svg("package", "uico-2")}</button>` +
        `<button class="game-tool danger" type="button" data-act="delete" title="Delete (Del)" aria-label="Delete ${name}">${svg("trash-2", "uico-2")}</button>` +
      `</span>` +
    `</div>` +
  `</article>`;
}

/** Two rows of placeholder cards. The boxes stand in for the footer's Run and
    tools as well as the cover and the name lines, so a row keeps its height
    when the real cards land in it. */
function renderSkeleton() {
  const grid = $("grid");
  grid.innerHTML = Array.from({ length: gridColumns() * 2 }, (_, i) =>
    `<div class="game skeleton" aria-hidden="true" style="--i:${i}">` +
      `<span class="game-cover"></span>` +
      `<span class="game-info"><span class="sk-line"></span><span class="sk-line short"></span></span>` +
      `<span class="game-foot">` +
        `<span class="sk-line run"></span>` +
        `<span class="sk-dots"><span class="sk-dot"></span><span class="sk-dot"></span><span class="sk-dot"></span></span>` +
      `</span>` +
    `</div>`).join("");
  grid.setAttribute("aria-busy", "true");
}

function render(opts) {
  const intro = !!(opts && opts.intro);
  const grid = $("grid");
  const empty = $("empty");
  const items = filtered();

  $("count").textContent = GAMES.length
    ? (items.length === GAMES.length
        ? `${GAMES.length} ${GAMES.length === 1 ? "game" : "games"}`
        : `${items.length} of ${GAMES.length}`)
    : "0 games";

  // Keep keyboard focus on the same game across a re-render (refresh, delete).
  const active = document.activeElement;
  const focusedPath = active && active.closest && active.closest(".game")
    ? active.closest(".game").dataset.path : "";

  grid.setAttribute("aria-busy", "false");
  if (!items.length) {
    grid.innerHTML = "";
    empty.hidden = false;
    const searching = GAMES.length > 0;
    empty.querySelector(".empty-title").textContent = searching ? "No matches" : "No games yet";
    empty.querySelector(".empty-msg").textContent = searching
      ? `Nothing in the library matches “${FILTER.trim()}”.`
      : "Create a game project to start building its workflow.";
    // Empty library → the way out is a new game; no matches → the way out is
    // dropping the search (Esc in the field does the same).
    $("btn-empty-new").hidden = searching;
    $("btn-empty-clear").hidden = !searching;
    return;
  }
  empty.hidden = true;

  grid.classList.toggle("intro", intro);
  grid.innerHTML = items.map(cardHtml).join("");
  if (intro) setTimeout(() => grid.classList.remove("intro"), 1000);

  if (focusedPath) {
    const card = [...grid.querySelectorAll(".game")].find((c) => c.dataset.path === focusedPath);
    if (card) card.querySelector(".game-cover").focus({ preventScroll: true });
  }
}

// ── Actions ──────────────────────────────────────────────────────────────────
async function loadList(opts) {
  const a = api();
  if (!a) return;
  try {
    const res = await a.list_workflows();
    GAMES = (res && res.workflows) || [];
    const pathEl = $("footer-path");
    if (pathEl && res && res.dir) {
      pathEl.textContent = res.dir;
      pathEl.title = res.dir;
    }
    render(opts);
  } catch (e) {
    $("grid").innerHTML = "";
    $("grid").setAttribute("aria-busy", "false");
    toast("Could not read the game library", "error");
  }
}

async function runWorkflow(path) {
  const a = api();
  if (!a) return;
  try {
    const ok = await a.run_workflow(path);
    if (ok) toast("Runner opened", "success");
    else toast("Could not open Runner", "error");
  } catch {
    toast("Could not open Runner", "error");
  }
}

async function editWorkflow(path) {
  const a = api();
  if (!a) return;
  try {
    const ok = await a.edit_workflow(path);
    if (ok) toast("Designer opened", "success");
    else toast("Could not open Designer", "error");
  } catch {
    toast("Could not open Designer", "error");
  }
}

function confirmDelete(name, folder) {
  const label = name || folder || "this game";
  return new Promise((resolve) => {
    if (_modal) modalClose(undefined);
    const wrap = document.createElement("div");
    wrap.className = "ui-modal-wrap";
    const box = document.createElement("div");
    box.className = "ui-modal";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.innerHTML =
      `<div class="ui-modal-hd">Delete game?</div>` +
      `<div class="ui-modal-bd">` +
        `<p class="ui-modal-msg">Permanently delete <b>${escHtml(label)}</b>?` +
        (folder ? ` This removes the whole <span class="mono">workflows/${escHtml(folder)}/</span> folder (workflow, templates and cover).` : "") +
        `</p>` +
        `<p class="ui-modal-hint">This cannot be undone.</p>` +
      `</div>` +
      `<div class="ui-modal-ft">` +
        `<button type="button" class="btn" data-v="cancel">Cancel</button>` +
        `<button type="button" class="btn err" data-v="ok">Delete</button>` +
      `</div>`;
    wrap.appendChild(box);
    const prevFocus = document.activeElement;
    const finish = (val) => {
      document.removeEventListener("keydown", onKey, true);
      wrap.remove();
      _modal = null;
      if (!val && prevFocus && prevFocus.focus) try { prevFocus.focus(); } catch {}
      resolve(val);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.preventDefault(); finish(false); }
    };
    box.querySelector('[data-v="cancel"]').onclick = () => finish(false);
    box.querySelector('[data-v="ok"]').onclick = () => finish(true);
    wrap.addEventListener("mousedown", (e) => { if (e.target === wrap) finish(false); });
    document.addEventListener("keydown", onKey, true);
    document.body.appendChild(wrap);
    _modal = { wrap, resolve: () => {}, onKey, prevFocus };
    setTimeout(() => {
      try { box.querySelector('[data-v="cancel"]').focus(); } catch {}
    }, 20);
  });
}

async function deleteWorkflow(path) {
  const meta = GAMES.find((g) => g.path === path) || {};
  const ok = await confirmDelete(meta.name, meta.folder);
  if (!ok) return;
  const a = api();
  if (!a) return;
  try {
    const res = await a.delete_workflow(path);
    if (!res || !res.ok) {
      toast((res && res.error) || "Delete failed", "error");
      return;
    }
    toast("Deleted «" + (meta.name || res.folder || "game") + "»", "success");
    await loadList();
  } catch {
    toast("Delete failed", "error");
  }
}

// ── Build a standalone Runner .exe ──────────────────────────────────────────
/** Build dialog → {version, publish, repo}, or null if cancelled. */
function promptBuild(info) {
  let form = null;
  const vendor = (info.vendor || []).length ? info.vendor.join(", ") : "none";
  // workflows/<Name>/vendor/ ships beside the exe as requirements\ for the game folder.
  const reqs = info.requirements || [];
  const reqText = reqs.length
    ? `${reqs.length} file${reqs.length === 1 ? "" : "s"} from vendor\\ → requirements\\ (players copy them into the game folder)`
    : "none";
  const published = info.published ? `v${info.published}` : "nothing yet";
  return modal({
    title: "Build Runner .exe",
    body: (bd) => {
      bd.innerHTML =
        `<p class="ui-modal-msg">Package <b>${escHtml(info.name)}</b> as a standalone Runner with its own version and self-update.</p>` +
        `<div class="form-field build-field">` +
          `<label for="build-version">Version</label>` +
          `<input id="build-version" type="text" spellcheck="false" autocomplete="off" value="${escHtml(info.version)}">` +
        `</div>` +
        `<label class="build-check${info.canPublish ? "" : " disabled"}">` +
          `<input type="checkbox" id="build-publish"${info.canPublish ? "" : " disabled"}>` +
          `<span><b>Publish as an update</b><small>${escHtml(info.canPublish
            ? "Uploads a GitHub Release; installed Runners of this game offer it on their next launch."
            : info.publishNote)}</small></span>` +
        `</label>` +
        `<div class="form-field build-field build-repo" hidden>` +
          `<label for="build-repo">Update repository</label>` +
          `<input id="build-repo" type="text" spellcheck="false" autocomplete="off" value="${escHtml(info.repo)}" placeholder="owner/name">` +
        `</div>` +
        `<dl class="build-facts">` +
          `<dt>Icon</dt><dd class="build-icon">` +
            (info.iconPreview ? `<img src="${info.iconPreview}" alt="">` : "") +
            `<span>${escHtml(info.iconSource || "Macro2k icon")}</span></dd>` +
          `<dt>Output</dt><dd class="mono" title="${escHtml(info.folder)}">${escHtml(info.folder)}\\${escHtml(info.exeName)}</dd>` +
          `<dt>Vendor</dt><dd class="mono">${escHtml(vendor)}</dd>` +
          `<dt>Game files</dt><dd>${escHtml(reqText)}</dd>` +
          `<dt>Published</dt><dd class="mono">${escHtml(published)} <span class="build-tag">${escHtml(info.tagPrefix)}*</span></dd>` +
        `</dl>` +
        (info.exists ? `<p class="ui-modal-hint">The previous build in that folder is replaced.</p>` : "");
      const publish = bd.querySelector("#build-publish");
      const repoField = bd.querySelector(".build-repo");
      publish.addEventListener("change", () => { repoField.hidden = !publish.checked; });
      form = { version: bd.querySelector("#build-version"), publish, repo: bd.querySelector("#build-repo") };
    },
    buttons: [{ label: "Cancel", value: false }, { label: "Build", value: true, kind: "accent" }],
  }).then((ok) => (ok ? {
    version: (form.version.value || "").trim() || info.version,
    publish: !!form.publish.checked,
    repo: (form.repo.value || "").trim() || info.repo,
  } : null));
}

async function buildWorkflow(path) {
  if (BUILD && (BUILD.state === "running" || BUILD.state === "cancelling")) {
    if (BUILD.path === path) openBuildPanel();
    else toast(`Already building ${BUILD.name}`, "warning");
    return;
  }
  const a = api();
  if (!a) return;
  let info = null;
  try { info = await a.build_info(path); } catch {}
  if (!info || !info.ok) {
    toast((info && info.error) || "Build is not available", "error");
    return;
  }
  const choice = await promptBuild(info);
  if (choice == null) return;
  let res = null;
  try { res = await a.build_runner(path, choice.version, choice.publish, choice.repo); } catch {}
  if (!res || !res.ok) {
    toast((res && res.error) || "Build did not start", "error");
    return;
  }
  applyBuild(res, { reset: true });
  openBuildPanel();
}

// ── Build panel ──────────────────────────────────────────────────────────────
const BP = { open: false, timer: null };
const buildActive = () => !!(BUILD && (BUILD.state === "running" || BUILD.state === "cancelling"));

function applyBuild(state, opts) {
  const prev = BUILD;
  if (!state || !state.path) {
    BUILD = null;
    renderBuildPanel();
    return;
  }
  const lines = state.lines || state.log || [];
  const fresh = (opts && opts.reset) || !prev || prev.path !== state.path || prev.startedAt !== state.startedAt;
  BUILD = Object.assign({}, state);
  delete BUILD.lines;
  delete BUILD.log;
  if (fresh) $("bp-log").innerHTML = "";
  appendBuildLines(lines);

  const wasActive = prev && (prev.state === "running" || prev.state === "cancelling") && prev.startedAt === BUILD.startedAt;
  if (wasActive && BUILD.state === "done") toast((BUILD.releaseUrl ? `Published ${BUILD.name} v${BUILD.version}` : `Built ${BUILD.name} v${BUILD.version}`)
    + (BUILD.requirements ? " — ships requirements\\ for the game folder" : ""), "success");
  else if (wasActive && BUILD.state === "failed") toast(`Build failed: ${BUILD.error || BUILD.name}`, "error");
  else if (wasActive && BUILD.state === "cancelled") toast(`Build cancelled: ${BUILD.name}`, "info");

  document.querySelectorAll(".game").forEach((card) => {
    const on = buildActive() && card.dataset.path === BUILD.path;
    card.classList.toggle("is-building", on);
    const pct = card.querySelector(".chip-pct");
    if (on && pct) pct.textContent = `${BUILD.progress || 0}%`;
  });
  renderBuildPanel();
}

function appendBuildLines(lines) {
  if (!lines || !lines.length) return;
  const log = $("bp-log");
  const follow = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  const frag = document.createDocumentFragment();
  for (const raw of lines) {
    const line = String(raw);
    const div = document.createElement("div");
    let cls = "bp-line";
    let text = line;
    if (line.startsWith(">> ")) { cls += " major"; text = line.slice(3); }
    if (/\b(ERROR|Traceback|FAILED)\b|Error:/.test(line)) cls += " err";
    else if (/\bWARNING\b/.test(line)) cls += " warn";
    div.className = cls;
    div.textContent = text;
    frag.appendChild(div);
  }
  log.appendChild(frag);
  while (log.childElementCount > 4000) log.removeChild(log.firstChild);
  if (follow) log.scrollTop = log.scrollHeight;
}

function fmtDuration(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function renderBuildPanel() {
  const panel = $("build-panel");
  if (!BUILD) {
    if (BP.open) hideBuildPanel();
    return;
  }
  const s = BUILD.state;
  const labels = { running: "Building", cancelling: "Cancelling", done: BUILD.releaseUrl ? "Published" : "Built", failed: "Failed", cancelled: "Cancelled" };
  panel.dataset.state = s;
  $("bp-title").textContent = `Build ${BUILD.name}`;
  $("bp-sub").textContent = `v${BUILD.version}` + (BUILD.publish ? ` · publish to ${BUILD.repo}` : "") + ` · ${BUILD.folder || ""}`;
  $("bp-sub").title = BUILD.folder || "";
  const badge = $("bp-badge");
  badge.className = "bp-badge " + s;
  badge.textContent = labels[s] || s;
  const pct = s === "done" ? 100 : Math.max(0, Math.min(100, BUILD.progress || 0));
  $("bp-fill").style.transform = `scaleX(${pct / 100})`;
  $("bp-track").setAttribute("aria-valuenow", String(pct));
  $("bp-pct").textContent = `${pct}%`;
  $("bp-stage").textContent = s === "failed" ? (BUILD.error || "Failed")
    : (s === "done" && BUILD.requirements) ? `${BUILD.stage || labels[s]} · players must copy requirements\\ into the game folder (REQUIREMENTS.txt)`
    : (BUILD.stage || labels[s] || "");
  tickBuildTime();

  const foot = $("bp-foot");
  let html = "";
  if (s === "running") html += `<button class="btn err" type="button" data-bp="cancel">Cancel build</button>`;
  if (s === "cancelling") html += `<button class="btn err" type="button" disabled>Cancelling…</button>`;
  html += `<span class="bp-sp"></span>`;
  if (s === "done") {
    html += `<button class="btn" type="button" data-bp="folder">Open folder</button>`;
    if (BUILD.requirements) html += `<button class="btn" type="button" data-bp="req">Open requirements</button>`;
    if (BUILD.releaseUrl) html += `<button class="btn" type="button" data-bp="release">View release</button>`;
  }
  html += buildActive()
    ? `<button class="btn" type="button" data-bp="hide">Hide</button>`
    : `<button class="btn accent" type="button" data-bp="close">Close</button>`;
  foot.innerHTML = html;

  clearInterval(BP.timer);
  BP.timer = buildActive() ? setInterval(tickBuildTime, 500) : null;
}

function tickBuildTime() {
  if (!BUILD || !BUILD.startedAt) return;
  const end = BUILD.endedAt || Date.now() / 1000;
  $("bp-time").textContent = fmtDuration(end - BUILD.startedAt);
}

function openBuildPanel() {
  if (!BUILD) return;
  const panel = $("build-panel");
  renderBuildPanel();
  panel.hidden = false;
  BP.open = true;
  document.body.classList.add("bp-open");
  requestAnimationFrame(() => panel.classList.add("in"));
  const log = $("bp-log");
  log.scrollTop = log.scrollHeight;
}

function hideBuildPanel() {
  const panel = $("build-panel");
  BP.open = false;
  document.body.classList.remove("bp-open");
  panel.classList.remove("in");
  setTimeout(() => { if (!BP.open) panel.hidden = true; }, 220);
}

async function onBuildPanelAction(action) {
  const a = api();
  if (!BUILD || !a) return;
  if (action === "hide") hideBuildPanel();
  else if (action === "close") { hideBuildPanel(); if (!buildActive()) BUILD = null; }
  else if (action === "cancel") {
    const ok = await modal({
      title: "Cancel this build?",
      body: `<p class="ui-modal-msg">Stop building <b>${escHtml(BUILD.name)}</b>. Nothing is published and the previous build folder may be left incomplete.</p>`,
      buttons: [{ label: "Keep building", value: false }, { label: "Cancel build", value: true, kind: "err" }],
    });
    if (ok) { try { await a.cancel_build(); } catch {} }
  }
  else if (action === "folder") { const ok = await a.open_folder(BUILD.folder); if (!ok) toast("Build folder not found", "error"); }
  else if (action === "req") { const ok = await a.open_folder(BUILD.requirements); if (!ok) toast("Requirements folder not found", "error"); }
  else if (action === "release") a.open_url(BUILD.releaseUrl);
}

window.__buildEvent = (state) => applyBuild(state);

async function createWorkflow() {
  const opts = await promptNewWorkflow();
  if (opts == null) return;
  const a = api();
  if (!a) return;
  try {
    const res = await a.create_workflow(opts.name, opts.controller, opts.capture, opts.inputMode);
    if (!res || !res.ok) {
      toast((res && res.error) || "Create failed", "error");
      return;
    }
    toast("Created «" + (res.name || opts.name) + "»", "success");
    await loadList();
    if (res.path) await editWorkflow(res.path);
  } catch {
    toast("Create failed", "error");
  }
}

// ── Keyboard — the shelf is a grid, so arrows move like one ─────────────────
function onGridKey(e) {
  const card = e.target.closest(".game");
  if (!card || card.classList.contains("skeleton")) return;
  if (e.ctrlKey || e.altKey || e.metaKey) return;
  const path = card.dataset.path;
  if (e.key === "e" || e.key === "E") { e.preventDefault(); editWorkflow(path); return; }
  if (e.key === "b" || e.key === "B") { e.preventDefault(); buildWorkflow(path); return; }
  if (e.key === "Delete") { e.preventDefault(); deleteWorkflow(path); return; }

  const cols = gridColumns();
  const covers = [...$("grid").querySelectorAll(".game-cover")];
  const index = covers.indexOf(card.querySelector(".game-cover"));
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }[e.key];
  let next;
  if (step !== undefined) next = index + step;
  else if (e.key === "Home") next = 0;
  else if (e.key === "End") next = covers.length - 1;
  else return;
  e.preventDefault();
  // Up from the first row leaves the shelf for the search box above it.
  if (e.key === "ArrowUp" && index < cols) { $("search").focus(); return; }
  next = Math.max(0, Math.min(covers.length - 1, next));
  covers[next].focus({ preventScroll: true });
  covers[next].scrollIntoView({ block: "nearest", behavior: "smooth" });
}

// ── Events ───────────────────────────────────────────────────────────────────
function wire() {
  // Theme toggle — drives the shared controller in web/shared/theme.js, which
  // persists through the backend so the Designer and Runner match.
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.onclick = () => { if (window.uiTheme) window.uiTheme.toggle(); };
  });
  $("btn-refresh").onclick = () => loadList();
  $("btn-new").onclick = () => createWorkflow();
  $("btn-empty-new").onclick = () => createWorkflow();

  const search = $("search");
  search.addEventListener("input", (e) => {
    FILTER = e.target.value || "";
    render();
  });
  search.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && search.value) { e.preventDefault(); search.value = ""; FILTER = ""; render(); }
    else if (e.key === "ArrowDown" || e.key === "Enter") {
      const first = $("grid").querySelector(".game-cover");
      if (first) { e.preventDefault(); first.focus(); }
    }
  });
  // "Clear search" in the no-match empty state — same as Esc in the field,
  // then focus it so typing a new term needs no click.
  $("btn-empty-clear").onclick = () => {
    search.value = "";
    FILTER = "";
    render();
    search.focus();
  };
  document.addEventListener("keydown", (e) => {
    if (_modal || e.defaultPrevented) return;
    const typing = e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA");
    if ((e.ctrlKey && e.key.toLowerCase() === "f") || (e.key === "/" && !typing)) {
      e.preventDefault();
      search.focus();
      search.select();
    }
  });

  const grid = $("grid");
  grid.addEventListener("click", (e) => {
    // The "Building n%" chip sits on the cover but reopens the build panel.
    const chipCard = e.target.closest(".game-building") && e.target.closest(".game.is-building");
    if (chipCard) { openBuildPanel(); return; }
    const btn = e.target.closest("button[data-act]");
    const card = btn && btn.closest(".game");
    if (!card || card.classList.contains("skeleton")) return;
    const path = card.dataset.path;
    if (btn.dataset.act === "run") runWorkflow(path);
    else if (btn.dataset.act === "edit") editWorkflow(path);
    else if (btn.dataset.act === "build") buildWorkflow(path);
    else if (btn.dataset.act === "delete") deleteWorkflow(path);
  });
  $("build-panel").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-bp]");
    if (btn && !btn.disabled) onBuildPanelAction(btn.dataset.bp);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && BP.open && !_modal) { e.preventDefault(); hideBuildPanel(); }
  });
  grid.addEventListener("keydown", onGridKey);
  // A cover that fails to decode falls back to the blank slot. Image errors do
  // not bubble, hence the capture phase.
  grid.addEventListener("error", (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement)) return;
    const card = img.closest(".game");
    const meta = GAMES.find((g) => card && g.path === card.dataset.path);
    const name = meta ? meta.name : "";
    if (img.classList.contains("game-icon")) {
      img.insertAdjacentHTML("afterend", `<span class="game-icon icon-mono" aria-hidden="true">${escHtml(initialsFor(name))}</span>`);
    } else if (img.classList.contains("game-img")) {
      img.insertAdjacentHTML("afterend", emptyArtHtml(name));
    } else {
      return;
    }
    img.remove();
  }, true);
}

// ── Auto-update (Velopack) ────────────────────────────────────────────────────
// Background check on boot + a click-to-install pill in the header. `manual`
// true surfaces "up to date" / error toasts; false stays silent unless there's
// actually an update to offer.
async function checkForUpdates(manual) {
  const btn = $("app-update");
  let res;
  try { res = await api().update_check(); } catch { return; }
  if (!res) return;
  if (res.available) {
    if (btn) {
      btn.hidden = false;
      btn.disabled = false;
      btn.textContent = "Update to v" + res.version;
      btn.onclick = () => applyUpdate(res.version);
    }
    toast("Update available: v" + res.version, "info");
  } else {
    if (btn) btn.hidden = true;
    if (manual) {
      if (res.error) toast("Update check failed: " + res.error, "error");
      else if (!res.supported) toast("Auto-update only works in the installed build", "info");
      else toast("You're on the latest version (v" + res.current + ")", "success");
    }
  }
}

// Full-screen progress overlay shown while an update downloads + installs.
function showUpdateOverlay(version) {
  hideUpdateOverlay();
  const wrap = document.createElement("div");
  wrap.id = "update-overlay";
  wrap.innerHTML =
    '<div class="upd-card">' +
      '<div class="upd-title">Updating Macro2k</div>' +
      '<div class="upd-sub" id="upd-sub">Downloading v' + escHtml(version) + '…</div>' +
      '<div class="upd-track"><div class="upd-fill" id="upd-fill"></div></div>' +
      '<div class="upd-pct" id="upd-pct">0%</div>' +
    '</div>';
  document.body.appendChild(wrap);
}
function hideUpdateOverlay() { const o = $("update-overlay"); if (o) o.remove(); }

// Called from Python (via evaluate_js) as bytes download: pct 0..100, or -1 for
// indeterminate (server didn't send a length).
window.__updateProgress = function (pct) {
  const wrap = $("update-overlay");
  if (!wrap) return;
  const fill = $("upd-fill"), pctEl = $("upd-pct"), sub = $("upd-sub");
  if (pct < 0) {                        // indeterminate — animate the track
    wrap.classList.add("indet");
    if (pctEl) pctEl.textContent = "";
    return;
  }
  wrap.classList.remove("indet");
  const p = Math.max(0, Math.min(100, Math.round(pct)));
  if (fill) fill.style.transform = `scaleX(${p / 100})`;
  if (pctEl) pctEl.textContent = p + "%";
  if (p >= 100 && sub) sub.textContent = "Installing… the app will restart";
};

async function applyUpdate(version) {
  const ok = await modal({
    title: "Update Macro2k?",
    body: `Download and install <b>v${escHtml(version)}</b>, then restart the app.`,
    buttons: [{ label: "Later", value: false }, { label: "Update now", value: true, kind: "accent" }],
  });
  if (!ok) return;
  const btn = $("app-update");
  if (btn) { btn.disabled = true; btn.textContent = "Updating…"; }
  showUpdateOverlay(version);
  try {
    // On success the app installs the new version and restarts, so this call
    // never resolves; we only get here when there's nothing to do or it failed.
    const res = await api().update_apply();
    hideUpdateOverlay();
    if (res && res.error) {
      toast("Update failed: " + res.error, "error");
      if (btn) { btn.disabled = false; btn.textContent = "Update to v" + version; }
    }
  } catch {
    hideUpdateOverlay();
    toast("Update failed", "error");
    if (btn) { btn.disabled = false; btn.textContent = "Update to v" + version; }
  }
}

// ── Boot ─────────────────────────────────────────────────────────────────────
async function init() {
  wire();
  renderSkeleton();
  let tries = 0;
  while (!(window.pywebview && window.pywebview.api) && tries < 50) {
    await new Promise((r) => setTimeout(r, 100));
    tries++;
  }
  if (!window.pywebview || !window.pywebview.api) {
    toast("pywebview unavailable", "error");
    return;
  }
  try {
    const ver = await api().app_version();
    const vEl = $("app-version");
    if (vEl && ver) vEl.textContent = "v" + ver;
  } catch {}
  checkForUpdates(false);   // background check on boot (never blocks the UI)
  let restored = null;
  try { restored = await api().build_state(); } catch {}
  if (restored && restored.path) applyBuild(restored, { reset: true });
  await loadList({ intro: true });
  if (buildActive()) openBuildPanel();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
