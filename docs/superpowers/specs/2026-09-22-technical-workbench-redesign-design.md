# Macro2k Technical Workbench Redesign

**Date:** 2026-09-22  
**Status:** Approved  
**Scope:** `apps/web/shared`, Hub, Workflow Designer, Runner, and DevScope

## 1. Objective

Turn the four Macro2k WebView surfaces into one coherent technical workbench without changing workflow execution, device control, capture, OCR, project storage, or backend lifecycle behavior.

The result should feel like a desktop instrument: neutral, square, compact, information-dense, and fast to scan. Hub remains the entry point and project switcher. Designer is the primary workbench. Runner and DevScope remain independent tool windows because their execution, capture, and device lifecycles are separate.

## 2. Product Architecture

### Hub — project switcher

Hub is the suite entry point. It must make projects easy to find and launch while preserving the proven card contract:

- A wide viewport uses a five-column shelf and progressively reflows to one column.
- The cover remains a standalone Run button.
- Run, Edit, Build, and Delete remain visible at rest and are never nested inside the cover button.
- Arrow-key movement uses the number of columns actually laid out.
- Search, refresh, settings, theme, creation, build progress, empty states, and keyboard shortcuts remain available.

The visual treatment may become more technical and information-led, but project recognition through cover/icon imagery remains useful and is retained.

### Designer — primary workbench

Designer remains the central authoring environment. Palette, canvas, inspector, library, preview, activity dock, and logs read as docked work areas rather than unrelated cards. Existing business IDs, inline handlers, panel behavior, node rendering, and canvas interactions remain intact.

Geometry is a hard regression boundary:

- `WF_GRID` remains `16`.
- Regular nodes remain `144 × 64px` (`9 × 4` cells).
- Start and End remain `48 × 48px` (`3 × 3` cells).
- A single Start or End node may snap in `8px` increments.
- Regular nodes and multi-selection movement snap in `16px` increments.
- `Alt + drag` remains free movement.
- Smart Align must not place regular nodes on half cells.

### Runner — operator console

Runner prioritizes run state, the Start/Pause/Stop controls, activity queue, activity settings, log, and preview. At narrow widths it exposes one primary view at a time through an accessible tablist with exactly:

1. Activities
2. Log
3. Settings

The tab implementation must maintain `role="tablist"`, `role="tab"`, one `aria-selected="true"`, roving `tabindex`, arrow/Home/End keyboard navigation, and corresponding `data-mobile-view` values. Settings uses the existing settings controls and IDs; controls must not be duplicated in the DOM.

### DevScope — inspection instrument

DevScope keeps the device/capture image as its main stage. Capture, Select, Match, OCR, and Input controls are grouped by task and use the shared workbench vocabulary. All existing IDs, inline handlers, capture state, device state, region selection, matching, OCR, and input behavior remain unchanged.

## 3. Visual System

### Direction

- Technical workbench, not consumer dashboard.
- Flat surfaces separated by one-pixel rules.
- Square or lightly rounded geometry; no decorative capsules.
- One blue accent for selection, focus, and primary action.
- Semantic success, warning, and error colors only for meaningful state.
- No gradients, glass, glow, decorative shadow, or hover lift.
- Shadows are reserved for true overlays: menus, popovers, dialogs, toasts, and maximized panels.
- Typography, alignment, whitespace, and surface contrast establish hierarchy.

Baseline: **ENERGY 2 / RHYTHM 2 / MOTION 1**.

### Token architecture

`apps/web/shared/tokens.css` is the primitive and semantic source of truth.

- Primitive layer: color values, type families and scale, spacing, shape, elevation, z-index, easing.
- Semantic layer: background, panel, surface, border, ink, muted, accent, success, warning, error, and console colors.
- Component metrics: shell/header/footer heights, panel header, rail, control bar, and form label widths.

App styles may define domain-specific tokens, but must consume shared semantic tokens instead of recreating reset, focus, form, button, dialog, tab, or panel primitives.

### Typography

Use only bundled/system fonts already declared by the shared layer:

- IBM Plex Sans / Segoe UI / system UI for interface copy.
- IBM Plex Mono / Cascadia Code / Consolas for paths, identifiers, logs, coordinates, and numeric telemetry.

Use the shared type ladder. Do not introduce arbitrary display sizes. Labels are concise; uppercase is reserved for small operational labels and state indicators.

### Components

- One filled primary action per context.
- Secondary actions are bordered, text, or icon controls.
- Icon-only controls require an accessible name.
- Panels use one header grammar: title, count/state, tools, maximize/collapse when applicable.
- Divider-led grouping is preferred over card nesting.
- Empty states state what is missing and provide one clear exit.
- Status always includes text or an accessible label; color is supplementary.

## 4. Layout and Responsive Behavior

The suite is desktop-first. Responsive behavior keeps tools operable in small windows; it does not imitate a mobile consumer app.

Validation viewports:

- `1440 × 900`
- `1280 × 720`
- `1024 × 768`
- `800 × 600`

Requirements:

- No page-level horizontal overflow.
- Primary controls remain visible or move into an explicit alternate view.
- Dense two-column areas become docked/alternate views rather than long stacked pages.
- Touch/coarse-pointer rules increase targets without hiding controls.
- Hub retains its tested 5→4→3→2→1 reflow.
- Runner uses its three-view mobile tab contract at the narrow breakpoint.
- Designer preserves usable canvas area and existing geometry at every breakpoint.

## 5. Accessibility

Accessibility is a product contract:

- Every interactive control is keyboard reachable.
- `:focus-visible` is obvious in light and dark themes.
- Dialogs and popovers expose their state and restore focus when closed where applicable.
- Tabs use ARIA tab semantics and keyboard navigation.
- Icon controls have `aria-label` or equivalent accessible text.
- Form controls have associated labels; errors and save states are programmatically announced.
- Status is never communicated by color alone.
- Text and controls remain usable at 125–200% zoom.
- `prefers-reduced-motion` reduces transitions and animations to effectively instant.
- Interactive elements must not be nested.

## 6. Motion

Motion is functional and restrained:

- Opacity and transform only for short entrances/exits.
- Typical duration `100–180ms`.
- No large layout animation or decorative looping motion.
- Existing progress/spinner motion may remain where it communicates active work.

## 7. Engineering Boundaries

- Keep the vanilla HTML/CSS/JavaScript stack.
- Add no font, asset, framework, or runtime dependency.
- Do not merge the four Python backends into one process.
- Preserve all business-critical IDs, inline handlers, API calls, and selector hooks.
- Extract only shared primitives used by multiple surfaces; do not create a component framework.
- DevScope may begin loading shared CSS, but app-specific rules must prevent behavior or geometry regressions.
- Functional changes use test-driven development.
- Existing Designer geometry/snap tests, Hub layout/navigation tests, and Runner structure tests are mandatory regression gates.
- The dirty gitlinks under `.claude/worktrees/*` are out of scope and must not be modified.

## 8. Verification Gates

Each implementation batch must run its focused contract tests. Final verification includes:

- `python -m pytest tests/test_runner_ui_structure.py -q`
- `node --test tests/test_hub_grid.cjs`
- `node --test tests/test_designer_geometry.cjs tests/test_grid_alignment.cjs tests/test_click_connect.cjs`
- All JavaScript tests.
- Relevant Python tests, then the full Python suite when practical.
- Python compilation checks for changed Python files.
- `git diff --check`.
- Manual viewport and keyboard checks for all four surfaces.

Two pre-existing Python failures may remain only if independently reproduced and unchanged:

- `test_hub_launcher_prefers_project_virtualenv`
- `test_bridge_online_is_reported_and_marks_warned`
