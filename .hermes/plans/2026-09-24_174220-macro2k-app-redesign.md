# Macro2k app redesign implementation plan

> **For Hermes:** Use this plan as the execution contract. Keep the existing vanilla HTML/CSS/JavaScript and Python WebView backends; do not migrate frameworks.

**Goal:** Redesign Hub, Designer, Runner, and DevScope as one coherent technical workbench while preserving workflow execution, device control, file formats, business IDs, keyboard contracts, and existing window boundaries.

**Architecture:** Treat `apps/web/shared/tokens.css`, `base.css`, `panel.css`, `icons.css`, and `theme.js` as the visual foundation. Each surface keeps its existing HTML/JS behavior and receives incremental layout and state improvements. Backend changes are out of scope unless a UI contract exposes a verified defect.

**Tech Stack:** Vanilla HTML/CSS/JavaScript, PyWebView/WebView2, Python workflow engine, existing Node and Python tests.

---

## Current baseline

- Current redesign work is pushed to `main` at commit `af227369557f3b375e94efe68d1bf776ddbd117a`.
- The redesign foundation already exists in `apps/web/shared/` and current Hub/Designer/Runner/DevScope shells.
- The committed workflow fix adds the missing false edge in `workflows/Cherry_Tale/Cherry_Tale.json` and preserves the startup loop when the window is already at target size.
- JavaScript suite and focused Python UI/engine tests pass. Full Python suite currently has two unrelated/pre-existing failures: launcher virtualenv assertion and Win32 bridge logging assertion.
- `.claude/worktrees/*` dirty gitlinks are local agent state and remain out of scope.

## Product direction

- Product language remains English; use IBM Plex Sans for UI and IBM Plex Mono for identifiers, logs, coordinates, and telemetry.
- Use a light technical workbench as the default: flat panels, one-pixel rules, square/lightly rounded controls, one blue accent, and semantic state colors only.
- Make state readable at a glance: connection, run state, dirty state, active project, selected node, activity status, and errors must have text or accessible labels, not color alone.
- Do not introduce a new framework, visual dependency, font dependency, or component system.
- Do not add gradients, glass, decorative shadows, RGB/gamer styling, consumer-dashboard cards, or marketing hero sections.

---

## Phase 0: establish the shared contract

### Task 0.1: Inventory selectors and runtime contracts

**Files:**
- Inspect: `apps/web/hub/index.html`, `apps/web/hub/js/hub.js`, `apps/web/runner/index.html`, `apps/web/runner/js/runner.js`
- Inspect: `apps/web/wf/index.html`, `apps/web/wf/js/*.js`, `apps/web/scope/index.html`, `apps/web/scope/js/*.js`
- Inspect: `apps/workflow_hub.py`, `apps/workflow_designer.py`, `apps/workflow_runner.py`, `apps/devscope.py`

Record every ID used by `querySelector`, `getElementById`, inline handlers, PyWebView callbacks, and tests. Mark each as immutable before editing HTML. Do not rename selectors to make the redesign cleaner.

### Task 0.2: Define shared tokens and primitives

**Files:**
- Modify: `apps/web/shared/tokens.css`
- Modify: `apps/web/shared/base.css`
- Modify: `apps/web/shared/panel.css`
- Modify: `apps/web/shared/theme.js`
- Test: `tests/test_workbench_ui_contracts.py`

Add or consolidate tokens for semantic surfaces, borders, ink/muted text, accent/focus, success/warning/error, spacing, control heights, panel headers, z-index, and reduced motion. Make all four surfaces consume these tokens. Keep existing light/dark theme keys and keyboard behavior intact.

Verify:

```bash
python -m pytest tests/test_workbench_ui_contracts.py -q
```

### Task 0.3: Add shared accessibility primitives

**Files:**
- Modify: `apps/web/shared/base.css`
- Modify: `apps/web/shared/panel.css`
- Test: `tests/test_workbench_ui_contracts.py`

Standardize `:focus-visible`, disabled states, button/select/input sizing, `prefers-reduced-motion`, dialog/popover elevation, and status text. Confirm icon-only controls have `aria-label` or equivalent title plus accessible name.

---

## Phase 1: Hub redesign

### Task 1.1: Make the project shelf scan-first

**Files:**
- Modify: `apps/web/hub/index.html`
- Modify: `apps/web/hub/css/hub.css`
- Test: `tests/test_hub_grid.cjs`

Preserve the five-to-one-column responsive grid and visible Run/Edit/Build/Delete actions. Improve hierarchy so each project card exposes: project identity, controller/device type, last-known state, workflow count, and primary Run action. Keep the cover as imagery only; do not nest interactive controls inside it.

### Task 1.2: Improve Hub empty, loading, search, and error states

**Files:**
- Modify: `apps/web/hub/index.html`
- Modify: `apps/web/hub/js/hub.js`
- Modify: `apps/web/hub/css/hub.css`
- Test: `tests/test_hub_grid.cjs`

Implement composed states for loading, no projects, no search matches, refresh failure, build-in-progress, and build failure. Keep keyboard shortcuts `/`, Enter, E, B, Delete, and arrow movement. Never use `window.alert()` for routine state feedback.

### Task 1.3: Add Hub project triage affordances

**Files:**
- Modify: `apps/web/hub/index.html`
- Modify: `apps/web/hub/js/hub.js`
- Modify: `apps/web/hub/css/hub.css`

Add sorting/filter affordances only if they use existing project metadata and do not hide core actions. Recommended first slice: recent activity, controller type, and build status. Keep search fast and preserve a clear-search escape path.

Verify at `1440x900`, `1280x720`, `1024x768`, `800x600`; check no horizontal overflow and arrow navigation follows the actual column count.

---

## Phase 2: Designer redesign

### Task 2.1: Clarify the Designer three-zone workbench

**Files:**
- Modify: `apps/web/wf/index.html`
- Modify: `apps/web/wf/css/base.css`
- Modify: `apps/web/wf/css/wf.css`
- Test: `tests/test_designer_geometry.cjs`, `tests/test_workbench_ui_contracts.py`

Keep the toolbar, node palette, canvas, inspector, library, preview, variables, and activity/log docks. Improve visual zoning with panel headers, explicit active view, selected-node state, dirty-save state, and a stable canvas center. Preserve all existing IDs and inline handlers.

### Task 2.2: Preserve graph geometry while improving node hierarchy

**Files:**
- Modify: `apps/web/wf/css/wf.css`
- Inspect/modify only if necessary: `apps/web/wf/js/render.js`, `layout.js`, `selection.js`
- Test: `tests/test_designer_geometry.cjs`, `tests/test_grid_alignment.cjs`, `tests/test_click_connect.cjs`

Hard boundaries:

- `WF_GRID = 16`.
- Regular nodes remain `144x64px`; Start/End remain `48x48px`.
- Regular and multi-selection movement stays on 16px snaps.
- Single Start/End movement stays on 8px snaps.
- Alt-drag remains free movement.
- Smart Align never creates half-cell positions.

Only change rendering hierarchy, badges, state indicators, and spacing after geometry tests remain green.

### Task 2.3: Make Inspector editing predictable

**Files:**
- Modify: `apps/web/wf/index.html`
- Modify: `apps/web/wf/js/inspector.js`
- Modify: `apps/web/wf/css/wf.css`
- Test: existing Designer inspector tests plus a new focused contract test if a behavior changes

Group fields by intent: identity, timing, target/capture, branching, and advanced options. Keep inline validation, save status, reset/undo behavior, and selected-node synchronization. Errors must appear beside the relevant field and be announced through the existing status region.

### Task 2.4: Improve canvas navigation and alternate views

**Files:**
- Modify: `apps/web/wf/js/keyboard.js`
- Modify: `apps/web/wf/js/ui.js`
- Modify: `apps/web/wf/css/wf.css`
- Test: `tests/test_tab_toggle.cjs`, `tests/test_designer_geometry.cjs`

Make Canvas/Preview/Library switching explicit. Preserve F, Shift+F, Ctrl/Cmd+F, Tab, Space, and modifier behavior. Ensure F clears Preview overlays without fitting Canvas, and F in Library is a no-op. Keep command palette and shortcuts discoverable.

---

## Phase 3: Runner redesign

### Task 3.1: Make run state the visual anchor

**Files:**
- Modify: `apps/web/runner/index.html`
- Modify: `apps/web/runner/css/runner.css`
- Modify: `apps/web/runner/js/runner.js`
- Test: `tests/test_runner_ui_structure.py`, `tests/test_runner_source_label.cjs`

Keep one clear primary Start/Stop action, Pause/Resume, workflow identity, controller label/version, elapsed time, and connection state in the header. Preserve the short `Window` / `Android` source labels and append version consistently.

### Task 3.2: Reduce activity-monitoring noise

**Files:**
- Modify: `apps/web/runner/index.html`
- Modify: `apps/web/runner/css/runner.css`
- Modify: `apps/web/runner/js/runner.js`

Make the activity queue the first scan target, with explicit enabled/disabled/running/succeeded/failed/paused states. Keep sequence/background separation, select-all/clear, per-activity settings, log search/filter/export, and preview behavior. Use mono typography for timers and counts.

### Task 3.3: Finish narrow Runner behavior

**Files:**
- Modify: `apps/web/runner/css/runner.css`
- Modify: `apps/web/runner/index.html`
- Test: `tests/test_runner_ui_structure.py`, `tests/test_tab_toggle.cjs`

Preserve exactly three mobile views: Activities, Log, Settings. Keep ARIA tablist/tab/tabpanel semantics, one selected tab, roving tabindex, arrow/Home/End navigation, and no duplicate settings controls in the DOM. Validate at 440px portrait width and 800px desktop width.

---

## Phase 4: DevScope redesign

### Task 4.1: Group controls by inspection task

**Files:**
- Modify: `apps/web/scope/index.html`
- Modify: `apps/web/scope/css/style.css`
- Inspect/modify only if necessary: `apps/web/scope/js/*.js`
- Test: `tests/test_scope_ui.py`

Preserve the device/capture image as the main stage. Group controls into Capture, Select, Match, OCR, and Input sections. Keep all existing IDs, inline handlers, capture state, region selection, OCR, matching, and input behavior.

### Task 4.2: Make device and capture state unambiguous

**Files:**
- Modify: `apps/web/scope/index.html`
- Modify: `apps/web/scope/css/style.css`
- Modify: `apps/web/scope/js/state.js`
- Test: `tests/test_scope_ui.py`

Expose device connection, capture source, image age, selected region, and operation result with text and accessible status. Distinguish stale capture from disconnected device and operation failure.

---

## Phase 5: cross-surface validation and cleanup

### Task 5.1: Add contract tests for state and accessibility

**Files:**
- Create only focused test files when an existing test cannot express the contract.
- Modify: `tests/test_workbench_ui_contracts.py` and surface-specific tests.

Cover: unique IDs, interactive nesting, accessible names, focus-visible hooks, active navigation, empty/error/loading states, responsive overflow, and status text. Do not snapshot entire HTML documents; assert durable contracts.

### Task 5.2: Manual desktop QA matrix

Run each surface at:

- `1440x900`
- `1280x720`
- `1024x768`
- `800x600`
- Runner portrait around `440px` wide

Check keyboard-only operation, reduced motion, light/dark theme, long project/workflow names, empty/error/loading states, and no horizontal page overflow.

### Task 5.3: Final verification and release checklist

Run:

```bash
python -m pytest tests/test_workbench_ui_contracts.py tests/test_hub_ui.py tests/test_scope_ui.py tests/test_runner_ui_structure.py -q
node --test tests/test_hub_grid.cjs tests/test_designer_geometry.cjs tests/test_grid_alignment.cjs tests/test_click_connect.cjs tests/test_tab_toggle.cjs
node --test tests/*.cjs
python -m compileall -q src apps tests
git diff --check
```

Record pre-existing failures separately; do not weaken tests to make the redesign pass. Verify `git status` excludes `.claude/worktrees/*` from staged changes.

---

## Risks and decisions

- **Risk: visual changes break selectors.** Mitigation: inventory IDs first and use contract tests before layout edits.
- **Risk: Designer styling changes graph geometry.** Mitigation: treat geometry/snap tests as a hard gate after each batch.
- **Risk: narrow windows become unusable.** Mitigation: validate the explicit desktop viewport matrix and Runner’s three-view mobile contract.
- **Risk: scope expands into backend refactoring.** Mitigation: keep Python backend boundaries and workflow file formats unchanged.
- **Open decision:** whether Hub filtering belongs in the first redesign release or waits until project metadata is stable. Default: ship search and status clarity first; add filters only when they reduce operator time.
- **Open decision:** whether DevScope should load all shared primitives or only tokens/base styles. Default: load shared tokens/base/panel primitives and override scope-specific canvas rules locally.

## Definition of done

- Hub, Designer, Runner, and DevScope look like one technical workbench.
- All existing core workflows and window/device behavior remain intact.
- Existing geometry, keyboard, tab, and project-grid contracts pass.
- No new runtime dependency is introduced.
- All four surfaces pass the viewport, keyboard, theme, accessibility, and state QA matrix.
- Final staged diff contains only intended app/test/workflow changes; agent worktree gitlinks remain untouched.
