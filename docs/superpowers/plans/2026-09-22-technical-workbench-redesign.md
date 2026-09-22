# Macro2k Technical Workbench Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign Hub, Designer, Runner, and DevScope as a coherent technical workbench while preserving every business workflow and tested geometry contract.

**Architecture:** Retain four independent WebView applications and their Python lifecycles. Strengthen the existing shared token/base/panel layer, then migrate each surface incrementally behind semantic and selector contract tests. Treat Hub layout, Runner narrow navigation, and Designer node geometry/snap as hard regression boundaries.

**Tech Stack:** Vanilla HTML, CSS, JavaScript, Python/pywebview, Node test runner, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-technical-workbench-redesign-design.md`

## Global Constraints

- Keep the vanilla stack and add no asset, font, framework, or runtime dependency.
- Preserve business-critical IDs, inline handlers, API calls, selectors, and independent backend lifecycles.
- Technical-workbench visual language: neutral, flat, compact, one accent, divider-led hierarchy.
- No gradients, glass, glow, decorative shadow, hover lift, or decorative status color.
- Shadows are allowed only for menus, dialogs, popovers, toasts, and maximized panels.
- Designer geometry remains: grid `16px`, regular node `144 × 64px`, Start/End `48 × 48px`, terminal single-drag `8px`, regular/multi-drag `16px`, `Alt` free.
- Hub keeps five columns at wide viewports, reflows to one, keeps cover-as-Run, visible Run/Edit/Build/Delete, and measured-column keyboard navigation.
- Runner narrow navigation contains Activities, Log, and Settings with ARIA tab semantics.
- Accessibility, reduced motion, light/dark focus, and non-color status cues are contracts.
- Do not modify `.claude/worktrees/*`.

## Review Focus

- A Runner settings tab opened and closed repeatedly must reuse the existing settings nodes and preserve their values/listeners rather than cloning duplicate IDs.
- A narrow Runner switched from Activity details to Settings and back must expose exactly one main view and keep roving tab focus correct.
- A Hub with long names, absent artwork, or a one-column layout must keep all card actions visible and arrow navigation predictable.
- Designer visual changes must not alter node dimensions, snap increments, port centering, group drag, or free movement with Alt.
- DevScope with no device, a disconnected device, or a resized stage must keep capture and selection controls operable without page-level overflow.

---

### Task 1: Document and Lock Cross-App Contracts

**Files:**
- Create: `tests/test_workbench_ui_contracts.py`
- Modify: `tests/test_runner_ui_structure.py`
- Test: `tests/test_hub_grid.cjs`
- Test: `tests/test_designer_geometry.cjs`

**Interfaces:**
- Consumes: Existing HTML IDs, inline handlers, CSS hooks, and current contract suites.
- Produces: Static structure checks that later markup/CSS tasks must satisfy.

- [ ] **Step 1: Add failing shell and accessibility tests**

Add tests that parse each app document and assert shared stylesheet ordering, one main application region, accessible names for icon-only buttons, Runner's three mobile tabs, no nested interactive elements, and the presence of theme/density hooks. Keep an explicit allow-list only where an app constructs controls dynamically.

- [ ] **Step 2: Run the focused tests and confirm the intended failures**

Run:

```bash
python -m pytest tests/test_workbench_ui_contracts.py tests/test_runner_ui_structure.py -q
```

Expected: failures identify the missing Runner Settings view and any real semantic contract gaps; existing unrelated assertions pass.

- [ ] **Step 3: Apply the smallest semantic markup fixes**

Add missing landmarks, labels, ARIA state, and shell classes without changing IDs or handlers. Do not perform visual redesign in this task.

- [ ] **Step 4: Run all hard regression contracts**

Run each command independently:

```bash
python -m pytest tests/test_workbench_ui_contracts.py tests/test_runner_ui_structure.py -q
node --test tests/test_hub_grid.cjs
node --test tests/test_designer_geometry.cjs tests/test_grid_alignment.cjs tests/test_click_connect.cjs
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_workbench_ui_contracts.py tests/test_runner_ui_structure.py apps/web/*/index.html
git commit -m "test: lock technical workbench UI contracts"
```

### Task 2: Restore Runner's Three-View Narrow Navigation

**Files:**
- Modify: `apps/web/runner/index.html`
- Modify: `apps/web/runner/js/runner.js`
- Modify: `apps/web/runner/css/runner.css`
- Modify: `tests/test_runner_ui_structure.py`

**Interfaces:**
- Consumes: `#runner-settings-src`, `#settings-pop`, `mountRunnerSettings()`, `switchMobileView(view, syncPanel)`, and `wireTabNav()`.
- Produces: A `settings` mobile view that moves one settings container between its desktop popover host and narrow in-workspace host without duplicate IDs.

- [ ] **Step 1: Extend the failing test beyond tab labels**

Assert that the Settings tab controls a dedicated settings panel, that `switchMobileView` accepts `settings`, and that the implementation moves/reuses settings content rather than cloning it a second time.

- [ ] **Step 2: Run the Runner contract and observe RED**

```bash
python -m pytest tests/test_runner_ui_structure.py -q
```

Expected: the Settings navigation assertions fail while the other Runner assertions pass.

- [ ] **Step 3: Implement the mobile Settings view**

Add the Settings tab and an empty settings host in `index.html`. Refactor `mountRunnerSettings()` to create one mounted settings root and move it to the narrow host when `settings` is active, or back to `#settings-pop` on desktop/popover use. Extend `switchMobileView()` and narrow CSS so exactly one of Activities, Log, Settings, or the internal Activity detail view is visible.

- [ ] **Step 4: Verify Runner behavior contracts**

```bash
python -m pytest tests/test_runner_ui_structure.py -q
```

Expected: all Runner structure tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/runner/index.html apps/web/runner/js/runner.js apps/web/runner/css/runner.css tests/test_runner_ui_structure.py
git commit -m "fix: restore runner mobile settings view"
```

### Task 3: Consolidate the Shared Workbench Foundation

**Files:**
- Modify: `apps/web/shared/tokens.css`
- Modify: `apps/web/shared/base.css`
- Modify: `apps/web/shared/panel.css`
- Modify: `apps/web/shared/theme.js`
- Modify: `tests/test_workbench_ui_contracts.py`

**Interfaces:**
- Consumes: Existing `data-theme`, `data-density`, `.btn`, `.card`, `.pnl`, `.rail`, `.ctlbar`, dialog, toast, tabs, and form primitives.
- Produces: Stable workbench shell, bar, divider, state, control, overlay, and responsive primitives used by all four apps.

- [ ] **Step 1: Add failing token and primitive tests**

Test for a three-layer token vocabulary, square workbench component metrics, visible `:focus-visible`, overlay-only shadows, reduced-motion handling, and shared shell/status classes. Tests must reject gradients and decorative card shadows in shared CSS.

- [ ] **Step 2: Run the tests and observe RED**

```bash
python -m pytest tests/test_workbench_ui_contracts.py -q
```

Expected: new primitive assertions fail on missing vocabulary, not on parser errors.

- [ ] **Step 3: Implement the minimal shared foundation**

Normalize token names and metrics, add shell/header/status primitives, tighten radii and flat borders, and remove redundant transitions. Preserve aliases required by existing app CSS. Keep overlays elevated and all docked content flat.

- [ ] **Step 4: Verify shared and app contracts**

```bash
python -m pytest tests/test_workbench_ui_contracts.py tests/test_runner_ui_structure.py -q
node --test tests/test_hub_grid.cjs
node --test tests/test_designer_geometry.cjs tests/test_grid_alignment.cjs tests/test_click_connect.cjs
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/shared tests/test_workbench_ui_contracts.py
git commit -m "style: establish shared technical workbench foundation"
```

### Task 4: Redesign Hub as the Project Switcher

**Files:**
- Modify: `apps/web/hub/index.html`
- Modify: `apps/web/hub/css/hub.css`
- Modify: `apps/web/hub/js/hub.js`
- Modify: `tests/test_hub_grid.cjs`
- Modify: `tests/test_workbench_ui_contracts.py`

**Interfaces:**
- Consumes: Shared shell/control primitives, `trackCount()`, `gridColumns()`, `cardHtml()`, delegated `data-act` handling.
- Produces: Technical project-switcher presentation with unchanged project actions and navigation behavior.

- [ ] **Step 1: Add failing Hub workbench tests**

Assert technical project language, semantic toolbar/main/status regions, flat project tiles, persistent actions, one primary New action, visible metadata, and no hover-gated controls. Include long-name and missing-art markup cases.

- [ ] **Step 2: Run Hub tests and observe RED**

```bash
node --test tests/test_hub_grid.cjs
python -m pytest tests/test_workbench_ui_contracts.py -q
```

Expected: only the new workbench assertions fail.

- [ ] **Step 3: Implement the Hub redesign**

Refine header, project copy, metadata hierarchy, shelf spacing, footer/status strip, empty state, build panel, and modal styling. Preserve the five-column CSS contract, cover Run button, visible footer actions, IDs, `data-act`, and keyboard geometry helpers.

- [ ] **Step 4: Verify Hub contracts**

```bash
node --test tests/test_hub_grid.cjs
python -m pytest tests/test_workbench_ui_contracts.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/hub tests/test_hub_grid.cjs tests/test_workbench_ui_contracts.py
git commit -m "style: redesign hub project switcher"
```

### Task 5: Redesign the Designer Workbench Shell

**Files:**
- Modify: `apps/web/wf/index.html`
- Modify: `apps/web/wf/css/base.css`
- Modify: `apps/web/wf/css/wf.css`
- Modify: Designer CSS files referenced by `apps/web/wf/index.html` only when necessary
- Modify: `tests/test_designer_geometry.cjs`
- Modify: `tests/test_workbench_ui_contracts.py`

**Interfaces:**
- Consumes: Existing Designer IDs/handlers, panel.js behavior, canvas/node DOM, shared workbench foundation.
- Produces: A unified docked Designer shell while leaving node and canvas geometry unchanged.

- [ ] **Step 1: Add failing Designer shell tests**

Assert semantic toolbar/workspace/status areas, panel header consistency, accessible icon controls, flat docked panels, and unchanged geometry custom properties.

- [ ] **Step 2: Run Designer contracts and observe RED only for shell assertions**

```bash
node --test tests/test_designer_geometry.cjs tests/test_grid_alignment.cjs tests/test_click_connect.cjs
python -m pytest tests/test_workbench_ui_contracts.py -q
```

Expected: geometry and interaction tests remain green; new shell tests fail.

- [ ] **Step 3: Implement the Designer shell redesign**

Align toolbar, palette, canvas chrome, inspector, dock, preview, log, and status regions to the shared panel grammar. Reduce card nesting and decorative radius/shadow. Do not modify node dimensions, canvas coordinate calculations, port placement, drag code, or snap code.

- [ ] **Step 4: Verify all Designer regression gates**

```bash
node --test tests/test_designer_geometry.cjs tests/test_grid_alignment.cjs tests/test_click_connect.cjs
python -m pytest tests/test_workbench_ui_contracts.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/wf tests/test_designer_geometry.cjs tests/test_workbench_ui_contracts.py
git commit -m "style: unify designer workbench shell"
```

### Task 6: Redesign Runner as an Operator Console

**Files:**
- Modify: `apps/web/runner/index.html`
- Modify: `apps/web/runner/css/runner.css`
- Modify: `apps/web/runner/js/runner.js` only for ARIA/state accuracy
- Modify: `tests/test_runner_ui_structure.py`
- Modify: `tests/test_workbench_ui_contracts.py`

**Interfaces:**
- Consumes: Task 2 mobile view controller and Task 3 shared foundation.
- Produces: Operator-first run hierarchy, persistent run controls, scannable queue/log/settings, and stable desktop/narrow layouts.

- [ ] **Step 1: Add failing Runner visual-contract tests**

Assert a persistent run-control region, textual statuses, one primary action, dark log console in both themes, flat split regions, overlay-only popover shadow, and three narrow views with one visible at a time.

- [ ] **Step 2: Run Runner tests and observe RED**

```bash
python -m pytest tests/test_runner_ui_structure.py tests/test_workbench_ui_contracts.py -q
```

Expected: new hierarchy/style assertions fail; mobile Settings remains green.

- [ ] **Step 3: Implement the Runner redesign**

Refine header/run status, queue rows, activity settings, log toolbar, preview, device footer, settings disclosure, and narrow tabs. Preserve every settings control ID, inline handler, Start/Pause/Stop behavior, log API, and preview API.

- [ ] **Step 4: Verify Runner contracts**

```bash
python -m pytest tests/test_runner_ui_structure.py tests/test_workbench_ui_contracts.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/runner tests/test_runner_ui_structure.py tests/test_workbench_ui_contracts.py
git commit -m "style: redesign runner operator console"
```

### Task 7: Integrate DevScope with the Shared Inspection System

**Files:**
- Modify: `apps/web/scope/index.html`
- Modify: `apps/web/scope/css/style.css`
- Modify: `apps/web/scope/js/app.js` or current Scope script only for ARIA/state accuracy
- Modify: `tests/test_workbench_ui_contracts.py`
- Create or Modify: focused DevScope UI contract test under `tests/`

**Interfaces:**
- Consumes: Shared tokens/base/panel styles and existing DevScope IDs/inline handlers.
- Produces: Inspection-stage layout using shared controls without changing capture, OCR, match, selection, or input behavior.

- [ ] **Step 1: Add failing DevScope structure tests**

Assert shared stylesheet loading order, one inspection stage, task-grouped Capture/Select/Match/OCR/Input controls, labelled controls, status text, and preservation of all IDs referenced by Scope JavaScript.

- [ ] **Step 2: Run the focused tests and observe RED**

```bash
python -m pytest tests/test_workbench_ui_contracts.py tests/test_scope_ui.py -q
```

Expected: shared-foundation and semantic grouping assertions fail; ID-preservation checks pass.

- [ ] **Step 3: Implement DevScope integration**

Load shared CSS before Scope CSS. Remove duplicate reset/button/input/focus rules where shared rules are equivalent, then style the device image as the primary stage and controls as compact task groups. Keep app-specific capture geometry, overlays, coordinate transforms, and handlers untouched.

- [ ] **Step 4: Verify DevScope and cross-app contracts**

```bash
python -m pytest tests/test_workbench_ui_contracts.py tests/test_scope_ui.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/web/scope tests/test_workbench_ui_contracts.py tests/test_scope_ui.py
git commit -m "style: redesign devscope inspection workspace"
```

### Task 8: Responsive, Accessibility, and Regression Closure

**Files:**
- Modify: only files implicated by a failing check
- Modify: `tests/test_workbench_ui_contracts.py`
- Modify: focused app tests as needed

**Interfaces:**
- Consumes: All prior tasks.
- Produces: A verified suite at target viewports with keyboard, theme, density, reduced-motion, and geometry guarantees.

- [ ] **Step 1: Add tests for uncovered review-focus cases**

Add static/dynamic tests for Runner settings node reuse, roving tabs after internal Activity view, Hub long names/no art, forbidden Designer geometry changes, and DevScope no-device status/overflow structure.

- [ ] **Step 2: Run focused suites and observe RED for each newly covered defect**

Run the smallest suite owning each defect. Do not edit production code until its test fails for the expected reason.

- [ ] **Step 3: Fix only verified defects**

Apply minimal corrections. Do not use this pass for untested visual polish.

- [ ] **Step 4: Perform manual UI checks**

At `1440×900`, `1280×720`, `1024×768`, and `800×600`, verify all four apps in light/dark themes, keyboard-only navigation, visible focus, reduced motion, 125–200% zoom, no page-level horizontal overflow, and no nested interactive controls.

- [ ] **Step 5: Run final automated verification**

Run commands independently and retain each result:

```bash
node --test tests/*.cjs
python -m pytest tests/test_runner_ui_structure.py tests/test_workbench_ui_contracts.py tests/test_scope_ui.py -q
python -m pytest -q
python -m py_compile apps/workflow_hub.py apps/workflow_designer.py apps/workflow_runner.py apps/devscope.py src/workflow/engine.py
git diff --check
```

Expected: JavaScript and focused Python suites pass; full Python suite passes except only independently reproduced baseline failures documented in the spec; compilation and diff checks pass.

- [ ] **Step 6: Commit**

```bash
git add apps/web tests
git commit -m "test: close workbench responsive and accessibility regressions"
```
