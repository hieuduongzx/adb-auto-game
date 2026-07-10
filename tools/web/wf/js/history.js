// ── Undo / Redo ─────────────────────────────────────────────────────────────
// Full-graph snapshot history using the existing wfCleanGraph / wfHydrateGraph
// round-trip. Every user action that mutates the data model pushes a snapshot
// BEFORE the mutation occurs, so undo restores the exact prior state.
//
// Debounced push (wfPushUndoDebounced) is used for text fields and other
// rapid-fire changes (inspector params) to avoid flooding the stack on every
// keystroke — it snapshots on the FIRST call and re-arm after 500 ms of quiet.

const _UNDO_MAX = 50;
let _undoStack = [];
let _redoStack = [];

// Deep-clone the entire workflow state (all activities, functions, globals,
// speedhack) plus the current selection. This makes undo work across edit-target
// switches — e.g. undo after deleting an activity restores it fully.
function wfTakeSnapshot() {
  return {
    editKind: WF.edit.kind,
    editId: WF.edit.id,
    // Every graph in every activity + function, cleaned.
    activities: (WF.activities || []).map(a => ({
      id: a.id,
      name: a.name,
      type: a.type,
      enabled: a.enabled,
      maxRetries: a.maxRetries,
      pollInterval: a.pollInterval,
      vars: JSON.parse(JSON.stringify(a.vars || [])),
      graph: typeof wfCleanGraph === "function" ? wfCleanGraph(a.graph) : { nodes: [], edges: [], groups: [] },
    })),
    functions: (WF.functions || []).map(f => ({
      id: f.id,
      name: f.name,
      graph: typeof wfCleanGraph === "function" ? wfCleanGraph(f.graph) : { nodes: [], edges: [], groups: [] },
    })),
    globals: JSON.parse(JSON.stringify(WF.globals || [])),
    speedhack: JSON.parse(JSON.stringify(WF.speedhack || { enabled: false, speed: 2.0, package: "" })),
    sel: (WF.sel || []).slice(),
    selectedNode: WF.selectedNode,
  };
}

// Push a snapshot onto the undo stack (to be called BEFORE the mutation).
// Clears the redo stack (new action after undo invalidates redo history).
function wfPushUndo() {
  const snap = wfTakeSnapshot();
  _undoStack.push(snap);
  if (_undoStack.length > _UNDO_MAX) _undoStack.shift();
  _redoStack = [];
  if (typeof wfMarkDirty === "function") wfMarkDirty();   // a mutation is imminent → unsaved
}

// Debounced version for rapid-fire changes (inspector fields).
// On first call it snapshots immediately; subsequent calls within 500 ms are
// no-ops. After 500 ms of quiet the flag resets so the next change snapshots
// again (capturing the accumulated mutations).
let _undoDebounceTimer = null;
let _undoDebounceArmed = false;
function wfPushUndoDebounced() {
  if (!_undoDebounceArmed) {
    _undoDebounceArmed = true;
    wfPushUndo();
  }
  if (_undoDebounceTimer) clearTimeout(_undoDebounceTimer);
  _undoDebounceTimer = setTimeout(() => {
    _undoDebounceArmed = false;
    _undoDebounceTimer = null;
  }, 500);
}

// Restore a snapshot into the live WF state, then rebuild the UI.
function wfRestoreSnapshot(snap) {
  if (!snap) return;

  // Restore top-level fields.
  if (snap.globals !== undefined) WF.globals = snap.globals;
  if (snap.speedhack !== undefined) WF.speedhack = snap.speedhack;

  // Restore activities.
  WF.activities = (snap.activities || []).map(a => ({
    id: a.id,
    name: a.name,
    type: a.type,
    enabled: a.enabled,
    maxRetries: a.maxRetries,
    pollInterval: a.pollInterval,
    vars: a.vars || [],
    graph: typeof wfHydrateGraph === "function" ? wfHydrateGraph(a.graph) : { nodes: [], edges: [], groups: [] },
  }));

  // Restore functions.
  WF.functions = (snap.functions || []).map(f => ({
    id: f.id,
    name: f.name,
    graph: typeof wfHydrateGraph === "function" ? wfHydrateGraph(f.graph) : { nodes: [], edges: [], groups: [] },
  }));

  // Restore edit target — resolve to the right activity/function.
  if (snap.editKind === "function") {
    const fn = WF.functions.find(f => f.id === snap.editId);
    WF.edit = { kind: "function", id: fn ? fn.id : (WF.functions[0] ? WF.functions[0].id : null) };
    if (!WF.edit.id) WF.edit = { kind: "activity", id: WF.activities[0] ? WF.activities[0].id : null };
  } else {
    const act = WF.activities.find(a => a.id === snap.editId);
    WF.edit = { kind: "activity", id: act ? act.id : (WF.activities[0] ? WF.activities[0].id : null) };
  }

  // Restore selection.
  WF.sel = (snap.sel || []).slice();
  WF.selectedNode = snap.selectedNode || null;

  // Rebuild everything.
  if (typeof wfSyncSpeedUI === "function") wfSyncSpeedUI();
  if (typeof wfRenderAll === "function") wfRenderAll();
}

function wfUndo() {
  if (!_undoStack.length) { setStatus("Nothing to undo"); return; }
  // Push current state onto redo stack before restoring.
  _redoStack.push(wfTakeSnapshot());
  const snap = _undoStack.pop();
  wfRestoreSnapshot(snap);
  if (typeof wfMarkDirty === "function") wfMarkDirty();
  setStatus("Undone");
}

function wfRedo() {
  if (!_redoStack.length) { setStatus("Nothing to redo"); return; }
  // Push current state onto undo stack before restoring.
  _undoStack.push(wfTakeSnapshot());
  const snap = _redoStack.pop();
  wfRestoreSnapshot(snap);
  if (typeof wfMarkDirty === "function") wfMarkDirty();
  setStatus("Redone");
}
