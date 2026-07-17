/* Macro2k Hub — list / run / edit / create workflows. */

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

/** Collect create-dialog fields. Returns project backend settings or null. */
function readNewWorkflowForm(box) {
  const name = (box.querySelector("#hub-name-input").value || "").trim() || "My Workflow";
  const ctrlBtn = box.querySelector('.choice-seg[data-field="controller"] .choice.on');
  const capBtn = box.querySelector('.choice-seg[data-field="capture"] .choice.on');
  const inputBtn = box.querySelector('.choice-seg[data-field="inputMode"] .choice.on');
  const controller = (ctrlBtn && ctrlBtn.dataset.value === "win32") ? "win32" : "adb";
  // Capture only applies to ADB; input mode only applies to Win32.
  const capture = (controller === "adb" && capBtn && capBtn.dataset.value === "adb")
    ? "adb" : "scrcpy";
  const allowedModes = new Set(["background", "background_sync", "background_cursor", "foreground"]);
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

/** New-workflow dialog → backend settings or null if cancelled. */
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
            `<button type="button" class="choice" data-value="foreground">` +
              `<span class="choice-title">Foreground</span>` +
              `<span class="choice-sub">Real mouse</span>` +
            `</button>` +
          `</div>` +
          `<p class="ui-modal-hint">How clicks and swipes are delivered to the PC window.</p>` +
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
let WORKFLOWS_LOADED = false;
let AC_STATE = { running:false, count:0, cycles:0, activePointId:"", startedAt:0, elapsed:0, status:"Ready", error:"", hotkeys:false };
let AC_CONFIG = { profileName:"Untitled sequence", selectedPointId:"point-1", points:[], intervalMs:250, startDelaySec:0, infinite:true, count:100 };
let AC_CURRENT_FILE = "";
let AC_PROFILES = [];
let AC_DIR = "autoclicks";
let AC_DIRTY = false;
let _acConfigureTimer = null;
let _acElapsedTimer = null;

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

// ── Tool navigation ─────────────────────────────────────────────────────────
async function openTool(name) {
  document.querySelectorAll(".tool-view").forEach((view) => view.classList.toggle("active", view.id === (name === "workflow" ? "workflow-app" : name === "autoclick" ? "autoclick-app" : "tool-home")));
  try { await api().autoclick_set_view_active(name === "autoclick"); } catch {}
  if (name === "workflow" && !WORKFLOWS_LOADED) {
    await loadList();
    WORKFLOWS_LOADED = true;
  }
  if (name === "autoclick") {
    renderAutoClick();
    setTimeout(() => { const run=$("ac-run"); if(run) run.focus(); }, 20);
  }
}

function segValue(field) {
  const on = document.querySelector(`.seg-control[data-ac-field="${field}"] .seg.on`);
  return on ? on.dataset.value : "";
}
function setSegValue(field, value) {
  const box = document.querySelector(`.seg-control[data-ac-field="${field}"]`);
  if (!box) return;
  box.querySelectorAll(".seg").forEach((button) => {
    const selected = button.dataset.value === String(value);
    button.classList.toggle("on", selected);
    button.setAttribute("aria-checked", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
}
function newPoint(index) {
  return { id:`point-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,6)}`, label:`Point ${index + 1}`,
    enabled:true, targetMode:"fixed", x:0, y:0, button:"left", clickType:"single" };
}
function selectedPoint() {
  const pts = AC_CONFIG.points || [];
  return pts.find((p) => p.id === AC_CONFIG.selectedPointId) || null;
}
function pointSummary(point) {
  const pos = point.targetMode === "cursor" ? "Cursor" : `${point.x}, ${point.y}`;
  const btn = point.button === "right" ? "R" : point.button === "middle" ? "M" : "L";
  return { pos, click: `${btn} · ${point.clickType === "double" ? "2×" : "1×"}` };
}
// AC_CONFIG.points is the source of truth (edited via the list + detail panel);
// only the always-present name / schedule fields are read from the DOM here.
function readAutoClickConfig() {
  const points = (AC_CONFIG.points || []).map((point, index) => ({
    id:point.id, label:(point.label || `Point ${index + 1}`).trim() || `Point ${index + 1}`,
    enabled:!!point.enabled,
    targetMode:point.targetMode === "cursor" ? "cursor" : "fixed",
    x:parseInt(point.x, 10) || 0, y:parseInt(point.y, 10) || 0,
    button:["left", "right", "middle"].includes(point.button) ? point.button : "left",
    clickType:point.clickType === "double" ? "double" : "single",
  }));
  return { profileName:($("ac-profile-name").value||"Untitled sequence").trim(), selectedPointId:AC_CONFIG.selectedPointId,
    points, intervalMs:Math.max(10,parseInt($("ac-interval").value,10)||250),
    startDelaySec:Math.max(0,parseInt($("ac-delay").value,10)||0),
    infinite:segValue("countMode")!=="finite", count:Math.max(1,parseInt($("ac-limit").value,10)||100) };
}
function renderPoints() {
  const host=$("ac-points"); host.innerHTML="";
  const points=AC_CONFIG.points||[];
  points.forEach((point,index) => {
    const row=document.createElement("div");
    row.className="point-row"+(point.id===AC_CONFIG.selectedPointId?" selected":"")+(point.id===AC_STATE.activePointId?" active":"")+(point.enabled?"":" off");
    row.dataset.id=point.id;
    const s=pointSummary(point);
    row.innerHTML=`<span class="point-order"><b>${index+1}</b><span class="point-move"><button type="button" data-point-act="up" ${index===0?"disabled":""} title="Move up" aria-label="Move point up">⌃</button><button type="button" data-point-act="down" ${index===points.length-1?"disabled":""} title="Move down" aria-label="Move point down">⌄</button></span></span>
      <label class="point-enable" title="${point.enabled?"Enabled — click to disable":"Disabled — click to enable"}"><input type="checkbox" data-point-act="toggle" ${point.enabled?"checked":""} aria-label="Enable point"><span></span></label>
      <span class="point-title">${escHtml(point.label)}</span>
      <span class="point-sum"><span class="point-pos">${escHtml(s.pos)}</span><span class="point-click">${s.click}</span></span>
      <button class="point-delete" type="button" data-point-act="delete" title="Delete point" aria-label="Delete point"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M8 10v8M12 10v8M16 10v8M6 7l1 14h10l1-14"/></svg></button>`;
    host.appendChild(row);
  });
  $("ac-points-empty").hidden=!!points.length;
  const enabled=points.filter(p=>p.enabled).length;
  $("ac-point-summary").textContent=`${points.length} point${points.length===1?"":"s"} · ${enabled} enabled`;
  renderPointEditor();
}
function renderPointEditor() {
  const host=$("ac-point-editor"); if(!host)return;
  const points=AC_CONFIG.points||[];
  const point=points.find(p=>p.id===AC_CONFIG.selectedPointId)||points[0];
  if(!point){ host.hidden=true; host.innerHTML=""; return; }
  host.hidden=false;
  const index=points.indexOf(point), cursor=point.targetMode==="cursor";
  host.innerHTML=`<div class="pe-head"><span class="pe-badge">${index+1}</span><span class="pe-title">Point settings</span></div>
    <label class="pe-name"><span>Name</span><input data-pe="label" maxlength="80" value="${escHtml(point.label)}" spellcheck="false"></label>
    <div class="pe-mode"><span class="pe-lbl">Position</span>
      <div class="seg-control pe-seg" data-pe-seg="targetMode" role="radiogroup" aria-label="Position mode">
        <button type="button" class="seg${cursor?"":" on"}" data-value="fixed" role="radio" aria-checked="${!cursor}">Fixed point</button><button type="button" class="seg${cursor?" on":""}" data-value="cursor" role="radio" aria-checked="${cursor}">At cursor</button>
      </div>
    </div>
    ${cursor
      ? `<p class="pe-hint">Clicks wherever the cursor is when this point runs.</p>`
      : `<div class="pe-row pe-xy">
          <label><span>X</span><input type="number" data-pe="x" value="${point.x}"></label>
          <label><span>Y</span><input type="number" data-pe="y" value="${point.y}"></label>
          <button class="pe-capture" type="button" data-pe-act="capture" title="Capture cursor position"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>Capture<kbd>F7</kbd></button>
        </div>`}
    <div class="pe-row pe-click">
      <label><span>Mouse button</span><select data-pe="button"><option value="left" ${point.button==="left"?"selected":""}>Left</option><option value="right" ${point.button==="right"?"selected":""}>Right</option><option value="middle" ${point.button==="middle"?"selected":""}>Middle</option></select></label>
      <label><span>Action</span><select data-pe="clickType"><option value="single" ${point.clickType!=="double"?"selected":""}>Single click</option><option value="double" ${point.clickType==="double"?"selected":""}>Double click</option></select></label>
    </div>`;
}
function updatePointRow(point) {
  const row=document.querySelector(`.point-row[data-id="${CSS.escape(point.id)}"]`);
  if(!row)return;
  const s=pointSummary(point);
  const title=row.querySelector(".point-title"); if(title)title.textContent=point.label||`Point`;
  const pos=row.querySelector(".point-pos"); if(pos)pos.textContent=s.pos;
  const click=row.querySelector(".point-click"); if(click)click.textContent=s.click;
}
function applyAutoClickConfig(config, clean=false) {
  if(!config)return;
  AC_CONFIG={...AC_CONFIG,...config,points:Array.isArray(config.points)?config.points:[]};
  $("ac-profile-name").value=AC_CONFIG.profileName||"Untitled sequence";
  $("ac-interval").value=AC_CONFIG.intervalMs; $("ac-delay").value=AC_CONFIG.startDelaySec; $("ac-limit").value=AC_CONFIG.count;
  setSegValue("countMode",AC_CONFIG.infinite?"infinite":"finite");
  renderPoints(); syncAutoClickFields();
  if(clean)setAutoClickDirty(false);
}
function setAutoClickDirty(dirty=true){ AC_DIRTY=dirty; const el=$("ac-dirty"); el.hidden=!dirty; }
function syncAutoClickFields(){ $("ac-limit").disabled=AC_STATE.running||segValue("countMode")!=="finite"; }
function queueAutoClickConfigure(){
  if(AC_STATE.running)return;
  AC_CONFIG=readAutoClickConfig(); setAutoClickDirty(true);
  clearTimeout(_acConfigureTimer);
  _acConfigureTimer=setTimeout(async()=>{ try{await api().autoclick_configure(AC_CONFIG);}catch{} },180);
}
function formatElapsed(seconds){ seconds=Math.max(0,Math.floor(seconds||0)); const h=Math.floor(seconds/3600),m=Math.floor((seconds%3600)/60),s=seconds%60; return h?`${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`:`${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`; }
function renderAutoClick(){
  const running=!!AC_STATE.running, status=AC_STATE.error?"Error":(AC_STATE.status||(running?"Clicking":"Ready"));
  $("ac-status").textContent=status; $("ac-count").textContent=String(AC_STATE.count||0); $("ac-cycles").textContent=String(AC_STATE.cycles||0);
  const enabled=(AC_CONFIG.points||[]).filter(p=>p.enabled).length;
  $("ac-status-detail").textContent=AC_STATE.error?AC_STATE.error:running?`Running ${enabled} point${enabled===1?"":"s"} in sequence.`:status==="Completed"?`Completed ${AC_STATE.cycles||0} cycles.`:`${enabled} enabled point${enabled===1?"":"s"} ready.`;
  const header=$("ac-header-state"); header.className="run-state "+(AC_STATE.error?"error":running?"running":"ready"); header.querySelector("span:last-child").textContent=running?"Running":AC_STATE.error?"Error":"Ready";
  const run=$("ac-run"); run.classList.toggle("running",running);
  run.querySelector(".run-icon").innerHTML=running?'<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="1.5"/></svg>':'<svg viewBox="0 0 24 24"><polygon points="7 4 20 12 7 20 7 4"/></svg>';
  run.querySelector("b").textContent=running?"Stop Auto Click":"Start Sequence";
  run.querySelector("small").textContent=running?"Stops after the current action":"Runs enabled points from top to bottom";
  $("ac-form").querySelectorAll("input,select,.seg,button").forEach(el=>{el.disabled=running;});
  $("ac-profile-name").disabled=running; $("ac-profile-select").disabled=running; $("ac-new").disabled=running; $("ac-save").disabled=running;
  if(!running){const rows=[...document.querySelectorAll(".point-row")];if(rows.length){const up=rows[0].querySelector('[data-point-act="up"]'),down=rows[rows.length-1].querySelector('[data-point-act="down"]');if(up)up.disabled=true;if(down)down.disabled=true;}}
  syncAutoClickFields();
  document.querySelectorAll(".point-row").forEach(row=>row.classList.toggle("active",running&&row.dataset.id===AC_STATE.activePointId));
  const home=$("home-clicker-state"); home.textContent=running?`Running · ${AC_STATE.count||0} actions`:`${enabled} points · F6 run · F8 add`; home.classList.toggle("running",running);
  if(!_acElapsedTimer)_acElapsedTimer=setInterval(()=>{const elapsed=AC_STATE.running&&AC_STATE.startedAt?Date.now()/1000-AC_STATE.startedAt:(AC_STATE.elapsed||0); const out=$("ac-elapsed");if(out)out.textContent=formatElapsed(elapsed);},250);
}
async function refreshAutoClickProfiles(selectFile=""){
  try{const res=await api().autoclick_list_profiles(); if(!res||!res.ok)return; AC_PROFILES=res.profiles||[]; AC_DIR=res.dir||"autoclicks"; $("ac-file-path").textContent=AC_DIR;
    const select=$("ac-profile-select"); select.innerHTML='<option value="">Open a saved sequence…</option>'+AC_PROFILES.map(p=>`<option value="${escHtml(p.filename)}" ${p.filename===(selectFile||AC_CURRENT_FILE)?"selected":""}>${escHtml(p.name)}${p.invalid?" · invalid":` · ${p.points} points`}</option>`).join("");
  }catch{}
}
async function confirmDiscard(){ if(!AC_DIRTY)return true; return await modal({title:"Discard unsaved changes?",body:"Your current sequence has changes that have not been saved.",buttons:[{label:"Keep editing",value:false},{label:"Discard",value:true,kind:"err"}]}); }
async function newAutoClickSequence(){
  if(!await confirmDiscard())return;
  AC_CURRENT_FILE=""; AC_STATE={...AC_STATE,count:0,cycles:0,status:"Ready",error:"",elapsed:0,startedAt:0};
  const point=newPoint(0); applyAutoClickConfig({profileName:"Untitled sequence",selectedPointId:point.id,points:[point],intervalMs:250,startDelaySec:0,infinite:true,count:100},true);
  $("ac-profile-select").value=""; renderAutoClick(); $("ac-profile-name").select();
}
async function saveAutoClickSequence(){
  AC_CONFIG=readAutoClickConfig(); const name=AC_CONFIG.profileName; if(!name){toast("Enter a sequence name.","error");$("ac-profile-name").focus();return;}
  let res=await api().autoclick_save_profile(name,AC_CONFIG,AC_CURRENT_FILE,!!AC_CURRENT_FILE);
  if(res&&res.exists){const overwrite=await modal({title:"Replace saved sequence?",body:`<b>${escHtml(res.filename)}</b> already exists in autoclicks/.`,buttons:[{label:"Cancel",value:false},{label:"Replace",value:true,kind:"err"}]}); if(overwrite)res=await api().autoclick_save_profile(name,AC_CONFIG,res.filename,true);}
  if(!res||!res.ok){toast((res&&res.error)||"Could not save sequence.","error");return;}
  AC_CURRENT_FILE=res.filename; applyAutoClickConfig(res.config,true); await refreshAutoClickProfiles(AC_CURRENT_FILE); toast(`Saved ${res.filename}`,"success");
}
async function loadAutoClickSequence(filename){
  if(!filename)return; if(!await confirmDiscard()){ $("ac-profile-select").value=AC_CURRENT_FILE; return; }
  const res=await api().autoclick_load_profile(filename); if(!res||!res.ok){toast((res&&res.error)||"Could not load sequence.","error");return;}
  AC_CURRENT_FILE=res.filename; AC_STATE={...AC_STATE,count:0,cycles:0,status:"Ready",error:"",elapsed:0,startedAt:0}; applyAutoClickConfig(res.config,true); renderAutoClick(); toast(`Opened ${res.filename}`,"success");
}
async function toggleAutoClick(){
  const a=api();if(!a)return;const run=$("ac-run");run.disabled=true;
  try{let res;if(AC_STATE.running)res=await a.autoclick_stop();else{if(!$("ac-form").reportValidity())return;AC_CONFIG=readAutoClickConfig();if(!AC_CONFIG.points.some(p=>p.enabled)){toast("Add or enable at least one click point.","error");return;}res=await a.autoclick_start(AC_CONFIG);} if(!res||res.ok===false)toast((res&&res.error)||"Auto Click could not start.","error");else{AC_STATE={...AC_STATE,...res};if(res.config)applyAutoClickConfig(res.config);renderAutoClick();}}
  catch(error){toast("Auto Click could not update. "+String(error&&error.message||error),"error");}finally{run.disabled=false;}
}
async function captureAutoClickPosition(pointId=AC_CONFIG.selectedPointId){
  try{clearTimeout(_acConfigureTimer);AC_CONFIG=readAutoClickConfig();await api().autoclick_configure(AC_CONFIG);const res=await api().autoclick_capture_position(pointId);if(!res||!res.ok){toast((res&&res.error)||"Could not read cursor position.","error");return;}const point=AC_CONFIG.points.find(p=>p.id===res.pointId);if(point){point.x=res.x;point.y=res.y;}renderPoints();setAutoClickDirty(true);toast(`Captured (${res.x}, ${res.y})`,"success");}catch{toast("Could not read cursor position.","error");}
}
async function addAutoClickPointAtCursor(){
  try{clearTimeout(_acConfigureTimer);AC_CONFIG=readAutoClickConfig();await api().autoclick_configure(AC_CONFIG);const res=await api().autoclick_add_point_at_cursor();if(!res||!res.ok)toast((res&&res.error)||"Could not add cursor position.","error");}
  catch{toast("Could not add cursor position.","error");}
}
function acceptAddedPoint(point){
  if(!point||AC_CONFIG.points.some(p=>p.id===point.id))return;
  AC_CONFIG.points.push(point);AC_CONFIG.selectedPointId=point.id;renderPoints();setAutoClickDirty(true);queueAutoClickConfigure();renderAutoClick();
  const row=document.querySelector(`.point-row[data-id="${point.id}"]`);if(row)row.scrollIntoView({block:"nearest",behavior:"smooth"});
  toast(`Added ${point.label} at (${point.x}, ${point.y})`,"success");
}
function updateHotkeyState(ok){AC_STATE.hotkeys=!!ok;const note=$("ac-hotkey-note");if(!note)return;note.className="hotkey-note "+(ok?"ok":"bad");note.innerHTML=`<span class="hotkey-dot"></span>${ok?"F6 Start/Stop · F7 Update selected point · F8 Add point":"Global hotkeys unavailable — use the on-screen controls"}`;}
window.__autoClickEvent=(event,data)=>{data=data||{};if(event==="position"){const point=AC_CONFIG.points.find(p=>p.id===data.pointId);if(point){point.x=data.x;point.y=data.y;renderPoints();setAutoClickDirty(true);}}else if(event==="point-added"){acceptAddedPoint(data.point);}else if(event==="tick"){AC_STATE={...AC_STATE,count:data.count||0,cycles:data.cycles||0,activePointId:data.pointId||""};}else if(event==="hotkeys")updateHotkeyState(!!data.ok);else if(event==="state"){AC_STATE={...AC_STATE,...data};if(data.config)applyAutoClickConfig(data.config);}if($("ac-status"))renderAutoClick();};

// ── Events ───────────────────────────────────────────────────────────────────
function wire() {
  document.querySelectorAll("[data-open-tool]").forEach((button) => { button.onclick = () => openTool(button.dataset.openTool); });
  document.querySelectorAll("[data-back-home]").forEach((button) => { button.onclick = () => openTool("home"); });
  $("btn-refresh").onclick = () => loadList();
  $("btn-new").onclick = () => createWorkflow();
  $("btn-empty-new").onclick = () => createWorkflow();
  $("search").addEventListener("input", (e) => {
    FILTER = e.target.value || "";
    render();
  });
  $("ac-form").addEventListener("submit", (e) => e.preventDefault());
  $("ac-run").onclick = toggleAutoClick;
  $("ac-new").onclick = newAutoClickSequence;
  $("ac-save").onclick = saveAutoClickSequence;
  $("ac-folder").onclick = () => api().autoclick_open_folder();
  $("ac-profile-select").onchange = (e) => loadAutoClickSequence(e.target.value);
  $("ac-profile-name").addEventListener("input", queueAutoClickConfigure);
  $("ac-form").addEventListener("input", queueAutoClickConfigure);
  $("ac-form").addEventListener("change", queueAutoClickConfigure);
  $("ac-add-point").onclick = addAutoClickPointAtCursor;
  // Point list — select a row, reorder, or delete (enable toggle handled on change).
  $("ac-points").addEventListener("click", (e) => {
    const row=e.target.closest(".point-row");if(!row||AC_STATE.running)return;
    if(e.target.closest(".point-enable"))return; // checkbox → handled by 'change'
    const id=row.dataset.id, index=AC_CONFIG.points.findIndex(p=>p.id===id);
    if(index<0)return;
    const act=(e.target.closest("[data-point-act]")||{}).dataset?.pointAct;
    if(act==="delete"){
      AC_CONFIG.points.splice(index,1);
      AC_CONFIG.selectedPointId=AC_CONFIG.points[Math.min(index,AC_CONFIG.points.length-1)]?.id||"";
    } else if(act==="up"&&index>0){
      [AC_CONFIG.points[index-1],AC_CONFIG.points[index]]=[AC_CONFIG.points[index],AC_CONFIG.points[index-1]];AC_CONFIG.selectedPointId=id;
    } else if(act==="down"&&index<AC_CONFIG.points.length-1){
      [AC_CONFIG.points[index+1],AC_CONFIG.points[index]]=[AC_CONFIG.points[index],AC_CONFIG.points[index+1]];AC_CONFIG.selectedPointId=id;
    } else {
      AC_CONFIG.selectedPointId=id; // plain select
    }
    renderPoints();setAutoClickDirty(true);queueAutoClickConfigure();
  });
  $("ac-points").addEventListener("change", (e) => {
    if(e.target.dataset.pointAct!=="toggle"||AC_STATE.running)return;
    const row=e.target.closest(".point-row");if(!row)return;
    const point=AC_CONFIG.points.find(p=>p.id===row.dataset.id);if(!point)return;
    point.enabled=e.target.checked;renderPoints();setAutoClickDirty(true);queueAutoClickConfigure();renderAutoClick();
  });
  // Point detail editor — edits the selected point in place.
  $("ac-point-editor").addEventListener("input", (e) => {
    const point=selectedPoint();if(!point||AC_STATE.running)return;
    const key=e.target.dataset.pe;if(!key)return;
    if(key==="label")point.label=e.target.value;
    else if(key==="x")point.x=parseInt(e.target.value,10)||0;
    else if(key==="y")point.y=parseInt(e.target.value,10)||0;
    updatePointRow(point);setAutoClickDirty(true);queueAutoClickConfigure();
  });
  $("ac-point-editor").addEventListener("change", (e) => {
    const point=selectedPoint();if(!point||AC_STATE.running)return;
    const key=e.target.dataset.pe;
    if(key==="button")point.button=e.target.value;
    else if(key==="clickType")point.clickType=e.target.value;
    else return;
    updatePointRow(point);setAutoClickDirty(true);queueAutoClickConfigure();
  });
  $("ac-point-editor").addEventListener("click", async (e) => {
    if(AC_STATE.running)return;
    const point=selectedPoint();if(!point)return;
    const seg=e.target.closest(".pe-seg .seg");
    if(seg){point.targetMode=seg.dataset.value==="cursor"?"cursor":"fixed";renderPointEditor();updatePointRow(point);setAutoClickDirty(true);queueAutoClickConfigure();return;}
    if(e.target.closest('[data-pe-act="capture"]'))await captureAutoClickPosition(point.id);
  });
  document.addEventListener("keydown", (e) => {if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"&&$("autoclick-app").classList.contains("active")){e.preventDefault();saveAutoClickSequence();}});
  document.querySelectorAll(".seg-control").forEach((box) => {
    box.addEventListener("click", (e) => {
      const button=e.target.closest(".seg"); if(!button||button.disabled) return;
      setSegValue(box.dataset.acField,button.dataset.value); syncAutoClickFields(); queueAutoClickConfigure();
    });
    box.addEventListener("keydown", (e) => {
      if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key)) return;
      const buttons=[...box.querySelectorAll(".seg:not(:disabled)")]; if(!buttons.length) return;
      const current=Math.max(0,buttons.findIndex(b=>b.classList.contains("on")));
      const delta=(e.key==="ArrowLeft"||e.key==="ArrowUp")?-1:1;
      const next=buttons[(current+delta+buttons.length)%buttons.length];
      e.preventDefault(); next.click(); next.focus();
    });
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

// ── Auto-update (Velopack) ────────────────────────────────────────────────────
// Background check on boot + a click-to-install pill in the footer. `manual`
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
  try {
    const state=await api().autoclick_state();
    if(state){ AC_STATE={...AC_STATE,...state}; AC_DIR=state.profilesDir||AC_DIR; applyAutoClickConfig(state.config,true); updateHotkeyState(!!state.hotkeys); renderAutoClick(); }
    await refreshAutoClickProfiles();
  } catch { updateHotkeyState(false); }
  await openTool("home");
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
