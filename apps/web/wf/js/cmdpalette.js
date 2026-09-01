// ── Command palette (Ctrl+K / Ctrl+P) ─────────────────────────────────────────
// One searchable surface for every command that used to be buried in the header
// toolbar, the ▾ menus, or keyboard-only shortcuts. Reuses the finder card's
// visual language (see wf.css ".wf-cmd" — same card, docked top-centre).
//
// Commands are built fresh on each open so enable/disable state reflects the
// live app (running, selection, edit target…). Each entry: {t:title, s:hint,
// k:shortcut-label, run:fn, when:optional-bool}.
let wfCmdEl = null, wfCmdHits = [], wfCmdSel = 0;

function wfCmdCatalog() {
  const running = (typeof wfRunning !== "undefined") && wfRunning;
  const hasSel = (WF.sel || []).length > 0;
  const g = (typeof wfGraph === "function") ? wfGraph() : null;
  const cmds = [
    { t: "Run / Stop test", s: "toggle the test run", k: "", run: () => wfToggleRun() },
    { t: "Test selected block", s: "run the selected block, overlay on Preview", k: "Ctrl+Enter", run: () => wfRunSingleNode(), when: hasSel },
    { t: "Validate workflow", s: "find broken wires, missing templates", k: "", run: () => wfValidateShow() },
    { t: "Run from selected block", s: "start the run at the selected block", k: "", run: () => (typeof wfRunFromSelected === "function") && wfRunFromSelected(), when: hasSel },
    { t: "Open Runner GUI", s: "launch the standalone runner on this flow", k: "", run: () => (typeof wfRunGui === "function") && wfRunGui() },
    { t: "Build EXE", s: "package this workflow as a standalone exe", k: "", run: () => (typeof wfBuildExe === "function") && wfBuildExe() },
    { t: "New workflow", s: "create an empty workflow", k: "", run: () => wfNew() },
    { t: "Open / Import workflow", s: "load a workflow from JSON", k: "", run: () => wfImport() },
    { t: "Save", s: "save to the current file", k: "Ctrl+S", run: () => wfSave() },
    { t: "Save as / Export", s: "save to a new JSON file", k: "", run: () => wfExport() },
    { t: "Project settings", s: "package, ADB/Win32 target, OCR engine", k: "", run: () => wfOpenProjectSettings() },
    { t: "Undo", s: "undo the last edit", k: "Ctrl+Z", run: () => wfUndo(), when: !running },
    { t: "Redo", s: "redo the last undone edit", k: "Ctrl+Y", run: () => wfRedo(), when: !running },
    { t: "Find block", s: "jump to a node by name / image / note", k: "Ctrl+F", run: () => wfFindShow() },
    { t: "Fit view", s: "zoom the graph to fit", k: "F", run: () => wfFit() },
    { t: "Zoom to 100%", s: "reset graph zoom", k: "Ctrl+0", run: () => (typeof wfZoomReset === "function") && wfZoomReset() },
    { t: "Toggle Preview / Edit", s: "switch canvas ↔ device mirror", k: "Tab", run: () => wfSwitchView((typeof wfPvActive !== "undefined" && wfPvActive) ? "canvas" : "preview") },
    { t: "Add activity", s: "create a new sequence activity", k: "", run: () => (typeof wfActAddCurrent === "function") && wfActAddCurrent() },
    { t: "Add function", s: "create a reusable function", k: "", run: () => (typeof wfAddFunction === "function") && wfAddFunction() },
    { t: "Toggle snap to grid", s: "20px grid snap when dragging blocks", k: "", run: () => (typeof wfToggleSnap === "function") && wfToggleSnap() },
    { t: "Toggle align guides", s: "smart alignment guides while dragging", k: "", run: () => (typeof wfToggleAlign === "function") && wfToggleAlign() },
    { t: "Toggle minimap", s: "bird's-eye graph overview", k: "", run: () => (typeof wfToggleMinimap === "function") && wfToggleMinimap() },
    { t: "Toggle image preview on nodes", s: "show template thumbnails on blocks", k: "", run: () => (typeof wfTogglePreview === "function") && wfTogglePreview() },
    { t: "Toggle dark theme", s: "switch light ↔ dark", k: "", run: () => (window.uiTheme && window.uiTheme.toggle()) },
    { t: "Toggle compact density", s: "tighter spacing + smaller rows", k: "", run: () => { const c = window.uiTheme && window.uiTheme.current(); window.uiTheme && window.uiTheme.setDensity(c && c.density === "compact" ? "comfortable" : "compact"); } },
    { t: "Select all blocks", s: "select every block in the open graph", k: "Ctrl+A", run: () => { const gg = wfGraph(); if (gg) { WF.sel = gg.nodes.map(n => n.id); WF.selectedNode = null; wfMarkSel(); wfRenderInspector(); } }, when: !!g },
    { t: "Delete selected", s: "remove the selected blocks", k: "Del", run: () => wfDeleteSelected(), when: hasSel && !running },
    { t: "Duplicate selected", s: "copy the selected blocks", k: "Ctrl+D", run: () => wfDuplicate(), when: hasSel && !running },
    { t: "Keyboard & mouse shortcuts", s: "open the shortcuts sheet", k: "F1", run: () => uiShowShortcuts() },
  ];
  return cmds.filter(c => c.when === undefined || c.when);
}

function wfCmdClose() {
  if (wfCmdEl) { wfCmdEl.remove(); wfCmdEl = null; wfCmdHits = []; wfCmdSel = 0; }
}
function wfCmdRun(it) {
  wfCmdClose();
  if (!it) return;
  try { it.run(); } catch (e) { try { setStatus("Command failed: " + e); } catch (_) {} }
}
function wfCmdRender(listEl, q) {
  const all = wfCmdCatalog();
  const terms = (q || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  wfCmdHits = terms.length
    ? all.filter(c => terms.every(t => (c.t + " " + (c.s || "")).toLowerCase().includes(t)))
    : all;
  wfCmdSel = Math.min(wfCmdSel, Math.max(0, wfCmdHits.length - 1));
  listEl.innerHTML = "";
  if (!wfCmdHits.length) {
    const e = document.createElement("div"); e.className = "wf-find-empty";
    e.textContent = "No commands match.";
    listEl.appendChild(e); return;
  }
  wfCmdHits.slice(0, 30).forEach((it, i) => {
    const row = document.createElement("button"); row.type = "button";
    row.className = "wf-find-item" + (i === wfCmdSel ? " sel" : "");
    row.innerHTML =
      `<span class="t">${escHtml(it.t)}</span>` +
      (it.s ? `<span class="s">${escHtml(it.s)}</span>` : "") +
      (it.k ? `<span class="w">${escHtml(it.k)}</span>` : "");
    row.addEventListener("mousedown", e => e.preventDefault());
    row.addEventListener("click", () => wfCmdRun(it));
    listEl.appendChild(row);
  });
}
function wfCmdShow() {
  if (wfCmdEl) { const inp = wfCmdEl.querySelector("input"); if (inp) { inp.focus(); inp.select(); } return; }
  const host = $("wf-canvas") || document.body;
  const box = document.createElement("div"); box.className = "wf-find wf-cmd"; wfCmdEl = box;
  box.innerHTML =
    `<div class="wf-find-bar">
       <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>
       <input type="text" placeholder="Type a command… (run, save, undo, theme, minimap)" spellcheck="false" autocomplete="off">
       <span class="k">Esc</span>
     </div>
     <div class="wf-find-list"></div>`;
  host.appendChild(box);
  const inp = box.querySelector("input"), list = box.querySelector(".wf-find-list");
  const move = d => { if (!wfCmdHits.length) return; wfCmdSel = (wfCmdSel + d + Math.min(30, wfCmdHits.length)) % Math.min(30, wfCmdHits.length); wfCmdRender(list, inp.value); };
  inp.addEventListener("input", () => { wfCmdSel = 0; wfCmdRender(list, inp.value); });
  inp.addEventListener("keydown", e => {
    e.stopPropagation();
    if (e.key === "Escape") { wfCmdClose(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
    else if (e.key === "Enter") { e.preventDefault(); wfCmdRun(wfCmdHits[wfCmdSel]); }
  });
  box.addEventListener("mousedown", e => e.stopPropagation());
  inp.addEventListener("blur", () => { setTimeout(() => { if (wfCmdEl && !wfCmdEl.contains(document.activeElement)) wfCmdClose(); }, 120); });
  wfCmdRender(list, "");
  inp.focus();
}
