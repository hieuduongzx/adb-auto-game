/* Workflow2k Hub — list / run / edit / create workflows. */

// ── Tiny helpers ─────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview && window.pywebview.api;

function escHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// ── Toast ────────────────────────────────────────────────────────────────────
const TOAST_ICO = {
  success: '<polyline points="4 12.5 9.5 18 20 6"/>',
  error:   '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  warning: '<path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.3 3.9 2.5 18a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  info:    '<circle cx="12" cy="12" r="9"/><line x1="12" y1="10.5" x2="12" y2="16"/><circle cx="12" cy="7.6" r="0.7"/>',
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
    `<svg viewBox="0 0 24 24">${TOAST_ICO[level]}</svg>` +
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

/** Collect create-dialog fields. Returns ``{name, controller, capture}`` or null. */
function readNewWorkflowForm(box) {
  const name = (box.querySelector("#hub-name-input").value || "").trim() || "My Workflow";
  const ctrlBtn = box.querySelector('.choice-seg[data-field="controller"] .choice.on');
  const capBtn = box.querySelector('.choice-seg[data-field="capture"] .choice.on');
  const controller = (ctrlBtn && ctrlBtn.dataset.value === "win32") ? "win32" : "adb";
  // Capture only applies to ADB projects; still persist a default for win32.
  const capture = (controller === "adb" && capBtn && capBtn.dataset.value === "adb")
    ? "adb" : "scrcpy";
  return { name, controller, capture };
}

function wireChoiceSeg(box) {
  box.querySelectorAll(".choice-seg").forEach((seg) => {
    seg.addEventListener("click", (e) => {
      const btn = e.target.closest(".choice");
      if (!btn || btn.disabled || seg.classList.contains("disabled")) return;
      seg.querySelectorAll(".choice").forEach((c) => c.classList.remove("on"));
      btn.classList.add("on");
      if (seg.dataset.field === "controller") syncCaptureForController(box);
    });
  });
  syncCaptureForController(box);
}

function syncCaptureForController(box) {
  const ctrlBtn = box.querySelector('.choice-seg[data-field="controller"] .choice.on');
  const win32 = ctrlBtn && ctrlBtn.dataset.value === "win32";
  const capSeg = box.querySelector('.choice-seg[data-field="capture"]');
  const capHint = box.querySelector("#hub-capture-hint");
  if (!capSeg) return;
  capSeg.classList.toggle("disabled", !!win32);
  capSeg.querySelectorAll(".choice").forEach((c) => { c.disabled = !!win32; });
  if (capHint) {
    capHint.textContent = win32
      ? "Win32 captures the target PC window directly — ADB capture source is unused."
      : "How the device screen is grabbed during preview and runs.";
  }
}

/** New-workflow dialog → ``{name, controller, capture}`` or null if cancelled. */
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
      `<div class="ui-modal-hd">New workflow</div>` +
      `<div class="ui-modal-bd">` +
        `<div class="form-field">` +
          `<label for="hub-name-input">Workflow name</label>` +
          `<input id="hub-name-input" type="text" spellcheck="false" autocomplete="off" value="My Workflow">` +
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
        `<div class="form-field">` +
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
          `<p class="ui-modal-hint" id="hub-capture-hint">How the device screen is grabbed during preview and runs.</p>` +
        `</div>` +
        `<p class="ui-modal-hint">Creates workflows/&lt;Name&gt;/workflow.json and opens the Designer.</p>` +
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
let WORKFLOWS = [];
let FILTER = "";

// ── Render ───────────────────────────────────────────────────────────────────
function filtered() {
  const q = FILTER.trim().toLowerCase();
  if (!q) return WORKFLOWS.slice();
  return WORKFLOWS.filter((w) => {
    const hay = [w.name, w.folder, w.file, w.controller, w.capture].join(" ").toLowerCase();
    return hay.includes(q);
  });
}

function render() {
  const rows = filtered();
  const body = $("wf-body");
  const empty = $("empty");
  const count = $("count");

  count.textContent = WORKFLOWS.length
    ? (rows.length === WORKFLOWS.length
        ? `${WORKFLOWS.length} workflow${WORKFLOWS.length === 1 ? "" : "s"}`
        : `${rows.length} of ${WORKFLOWS.length}`)
    : "0 workflows";

  if (!WORKFLOWS.length || !rows.length) {
    body.innerHTML = "";
    empty.hidden = false;
    if (WORKFLOWS.length && !rows.length) {
      empty.querySelector(".empty-title").textContent = "No matches";
      empty.querySelector(".empty-msg").textContent = "Try a different search term.";
      $("btn-empty-new").hidden = true;
    } else {
      empty.querySelector(".empty-title").textContent = "No workflows yet";
      empty.querySelector(".empty-msg").textContent = "Create one to start building automation flows.";
      $("btn-empty-new").hidden = false;
    }
    return;
  }
  empty.hidden = true;

  body.innerHTML = rows.map((w) => {
    const ctrl = (w.controller || "adb").toLowerCase() === "win32" ? "win32" : "adb";
    const cap = (w.capture || "scrcpy").toLowerCase() === "adb" ? "adb" : "scrcpy";
    const capLabel = ctrl === "win32" ? "window" : cap;
    return `<tr data-path="${escHtml(w.path)}">
      <td>
        <div class="wf-name" title="${escHtml(w.name)}">${escHtml(w.name)}</div>
        <div class="wf-file" title="${escHtml(w.relPath || w.file)}">${escHtml(w.relPath || w.file)}</div>
      </td>
      <td class="wf-acts">${w.activityCount ?? "—"}</td>
      <td>
        <span class="wf-ctrl ${ctrl}">${ctrl}</span>
        <div class="wf-cap" title="Capture source">${escHtml(capLabel)}</div>
      </td>
      <td class="wf-mod" title="${escHtml(w.modifiedIso || "")}">${escHtml(w.modified || "—")}</td>
      <td>
        <div class="row-actions">
          <button class="btn sm ok" data-act="run" title="Open Runner GUI">
            <svg viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></svg>
            Run
          </button>
          <button class="btn sm" data-act="edit" title="Open in Designer">
            <svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
            Edit
          </button>
          <button class="btn sm err ico" data-act="delete" title="Delete workflow" aria-label="Delete">
            <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
          </button>
        </div>
      </td>
    </tr>`;
  }).join("");
}

// ── Actions ──────────────────────────────────────────────────────────────────
async function loadList() {
  const a = api();
  if (!a) return;
  try {
    const res = await a.list_workflows();
    WORKFLOWS = (res && res.workflows) || [];
    const pathEl = $("footer-path");
    if (pathEl && res && res.dir) {
      pathEl.textContent = res.dir;
      pathEl.title = res.dir;
    }
    render();
  } catch (e) {
    toast("Failed to list workflows", "error");
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
  const label = name || folder || "this workflow";
  return new Promise((resolve) => {
    if (_modal) modalClose(undefined);
    const wrap = document.createElement("div");
    wrap.className = "ui-modal-wrap";
    const box = document.createElement("div");
    box.className = "ui-modal";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-modal", "true");
    box.innerHTML =
      `<div class="ui-modal-hd">Delete workflow?</div>` +
      `<div class="ui-modal-bd">` +
        `<p class="ui-modal-msg">Permanently delete <b>${escHtml(label)}</b>?` +
        (folder ? ` This removes the whole <span class="mono">workflows/${escHtml(folder)}/</span> folder (JSON + templates).` : "") +
        `</p>` +
        `<p class="ui-modal-hint">This cannot be undone.</p>` +
      `</div>` +
      `<div class="ui-modal-ft">` +
        `<button type="button" class="btn" data-v="cancel">Cancel</button>` +
        `<button type="button" class="btn err" data-v="ok">Delete</button>` +
      `</div>`;
    wrap.appendChild(box);
    const finish = (val) => {
      document.removeEventListener("keydown", onKey, true);
      wrap.remove();
      _modal = null;
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
    _modal = { wrap, resolve: () => {}, onKey, prevFocus: document.activeElement };
    setTimeout(() => {
      try { box.querySelector('[data-v="cancel"]').focus(); } catch {}
    }, 20);
  });
}

async function deleteWorkflow(path) {
  const meta = WORKFLOWS.find((w) => w.path === path) || {};
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
    toast("Deleted «" + (meta.name || res.folder || "workflow") + "»", "success");
    await loadList();
  } catch {
    toast("Delete failed", "error");
  }
}

async function createWorkflow() {
  const opts = await promptNewWorkflow();
  if (opts == null) return;
  const a = api();
  if (!a) return;
  try {
    const res = await a.create_workflow(opts.name, opts.controller, opts.capture);
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

// ── Events ───────────────────────────────────────────────────────────────────
function wire() {
  $("btn-refresh").onclick = () => loadList();
  $("btn-new").onclick = () => createWorkflow();
  $("btn-empty-new").onclick = () => createWorkflow();
  $("search").addEventListener("input", (e) => {
    FILTER = e.target.value || "";
    render();
  });
  $("wf-body").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const tr = btn.closest("tr[data-path]");
    if (!tr) return;
    const path = tr.getAttribute("data-path");
    if (!path) return;
    if (btn.dataset.act === "run") runWorkflow(path);
    else if (btn.dataset.act === "edit") editWorkflow(path);
    else if (btn.dataset.act === "delete") deleteWorkflow(path);
  });
  // Double-click a row → Edit (operator muscle memory).
  $("wf-body").addEventListener("dblclick", (e) => {
    if (e.target.closest("button")) return;
    const tr = e.target.closest("tr[data-path]");
    if (!tr) return;
    editWorkflow(tr.getAttribute("data-path"));
  });
}

// ── Boot ─────────────────────────────────────────────────────────────────────
async function init() {
  wire();
  let tries = 0;
  while (!(window.pywebview && window.pywebview.api) && tries < 50) {
    await new Promise((r) => setTimeout(r, 100));
    tries++;
  }
  if (!window.pywebview || !window.pywebview.api) {
    toast("pywebview unavailable", "error");
    return;
  }
  await loadList();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
