---
name: Workflow2k
description: Visual workflow designer for Android automation — precise, efficient, graph-first.
colors:
  ink-primary: "#19222e"
  ink-secondary: "#41505f"
  dim: "#5a6573"
  muted: "#7c8795"
  bg: "#eef0f3"
  panel: "#ffffff"
  surface: "#f7f9fc"
  alt: "#f3f5f9"
  border: "#e4e7ec"
  border2: "#dde2e8"
  line: "#f1f3f6"
  accent: "#2f6fed"
  accent-bg: "#eef5ff"
  accent-bd: "#d6e4f5"
  ok: "#1f9254"
  ok-bg: "#e8f5ed"
  ok-bd: "#cfead9"
  warn: "#9c6c12"
  warn-bg: "#fdf6e9"
  err: "#bb3a33"
  err-bg: "#fcefee"
  err-bd: "#eecdca"
  run-ok: "#1f9d57"
  run-fail: "#d6483f"
  run-live: "#f97316"
  run-info: "#06b6d4"
  run-warn: "#eab308"
  branch-t: "#1f9d57"
  branch-t-bg: "#e8f5ed"
  branch-t-bd: "#9fd4b5"
  branch-f: "#e0792e"
  branch-f-bg: "#fff4e8"
  branch-f-bd: "#f3c29a"
  branch-loop: "#e0a64b"
  branch-loop-bg: "#fff7ea"
  branch-loop-line: "#d09030"
  cat-basic: "#6f9be8"
  cat-image: "#2fb0a3"
  cat-ocr: "#e0954b"
  cat-logic: "#9a78e6"
  group-red: "#cf6b6b"
  log-bg: "#fbfcfd"
  log-ink: "#41505f"
  log-muted: "#b3bbc4"
  cat-input: "#4338ca"
  cat-flow: "#b45309"
  cat-misc: "#4b5563"
  scrollbar-thumb: "#cbd5e1"
  scrollbar-thumb-hover: "#94a3b8"
  wire-default: "#8493a7"
  wire-stack: "#b8c6d4"
  port-default-bg: "#e0e5eb"
  port-default-bd: "#c5cdd6"
  port-connected-output: "#8597ab"
  node-default-hd-bg: "#f4eefe"
  node-default-hd-bd: "#ece3fb"
  node-default-title: "#7c3aed"
  run-header-bg: "#ffedd5"
  run-header-bd: "#fdba74"
  run-header-title: "#9a3412"
  speed-border-on: "#f1c84b"
  speed-bg-on: "#fdf6e9"
  speed-title-on: "#9c6c12"
  note-bg: "#fdf6e9"
  note-border: "#e7d5a4"
  note-color: "#7a5b12"
  note-sum-color: "#7a5b12"
  node-warn-bg: "#f3b51a"
  node-warn-text: "#3a2c05"
  node-warn-border: "#e6a417"
  preview-bg: "#121316"
  preview-thumb-bg: "#1a1d21"
  palette-basic-bg: "#eef5ff"
  palette-basic-color: "#2d64cc"
  palette-image-bg: "#ecfdf9"
  palette-image-color: "#0f766e"
  palette-ocr-bg: "#fff7ed"
  palette-ocr-color: "#c2610f"
  palette-logic-bg: "#f5f3ff"
  palette-logic-color: "#6d28d9"
  palette-misc-bg: "#f3f4f6"
  palette-misc-color: "#4b5563"
  fn-badge-bg: "#7c3aed"
  fn-row-bg: "#faf7ff"
  fn-row-bd: "#d8c8f7"
  fn-row-hover-bg: "#f3eefe"
  fn-row-hover-bd: "#c4b1f6"
  fn-row-sel-bg: "#ede8fc"
  fn-row-sel-bd: "#9a78e6"
  chip-grip-color: "#c4cbd4"
  chip-cat-basic-color: "#2d64cc"
  chip-cat-image-color: "#0f766e"
  chip-cat-ocr-color: "#c2610f"
  chip-cat-logic-color: "#6d28d9"
  chip-cat-flow-color: "#b45309"
  chip-cat-misc-color: "#4b5563"
  node-log-bg: "#eef6fb"
  node-log-color: "#2f6b8f"
typography:
  body:
    fontFamily: "IBM Plex Sans, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: "IBM Plex Sans, Segoe UI, system-ui, sans-serif"
    fontSize: "10.5px"
    fontWeight: 700
    letterSpacing: "0.05em"
    textTransform: uppercase
  mono:
    fontFamily: "IBM Plex Mono, Cascadia Code, Consolas, monospace"
    fontSize: "11.5px"
    fontWeight: 400
  display:
    fontFamily: "IBM Plex Sans, Segoe UI, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
  title:
    fontFamily: "IBM Plex Sans, Segoe UI, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
rounded:
  sm: "7px"
  md: "10px"
  lg: "14px"
  node: "7px"
spacing:
  s1: "4px"
  s2: "6px"
  s3: "8px"
  s4: "12px"
  s5: "16px"
  s6: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "8px"
    padding: "0 11px"
    height: "30px"
  button-primary-hover:
    backgroundColor: "#2559c7"
  button-success:
    backgroundColor: "{colors.ok}"
    textColor: "#ffffff"
    rounded: "8px"
    height: "30px"
  button-danger:
    backgroundColor: "{colors.err-bg}"
    textColor: "{colors.err}"
    rounded: "8px"
    height: "30px"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-primary}"
    rounded: "{rounded.sm}"
    padding: "5px 8px"
  card:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.md}"
  chip:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink-secondary}"
    rounded: "7px"
    padding: "7px 8px"
---

# Design System: Workflow2k

## 1. Overview

**Creative North Star: "The Calibrated Instrument"**

Workflow2k is a precision tool. Every visual element exists to serve the user's task — composing, debugging, and executing Android automation workflows. The design system treats the interface like a calibrated instrument: surfaces are clean and cool, accents are deliberate and restrained, and nothing decorative competes with the graph.

The palette is cool-neutral with a single stable blue accent. IBM Plex Sans carries the UI; IBM Plex Mono holds code, coordinates, and data. Components are tactile and confident — buttons feel like they commit action, nodes feel like they're part of a live circuit. The graph canvas is the center; everything else recedes until needed.

This system explicitly rejects the design-tool aesthetic: no pastels, no glassmorphism, no soft-focus blur. It's not a dashboard, not a consumer app, and not a terminal-first tool. It's a developer's instrument — precise, efficient, and capable.

**Key Characteristics:**
- Cool-neutral light palette with a single blue accent
- IBM Plex Sans for UI, IBM Plex Mono for code and data
- Tactile buttons and confident cards — nothing feels tentative
- The graph is the center; chrome recedes until needed
- Semantic color roles for run state (green trail, red failure, amber live)
- No decoration without function

## 2. Colors

The palette is a restrained cool-neutral system built around one primary accent. Colors are grouped by role: structural (ink, dim, muted), surfaces (bg, panel, surface, alt), semantic feedback (ok, warn, err), and run-trail (the graph's live state).

### Primary
- **Stable Blue** (#2f6fed): The sole accent. Used on primary buttons, focus rings, selected states, active tabs, links, and the entry-marker bar on the graph's default starting block. Rarity is its power — it should appear on ≤10% of any screen.

### Secondary
Not applicable. Workflow2k uses a single accent. The ok/err/warn colors are semantic, not decorative accents.

### Neutral
- **Ink** (#19222e): Body text on light surfaces. Used for primary content, node titles, input text. Always ≥4.5:1 against the panel background.
- **Ink Secondary** (#41505f): Secondary text. Labels, descriptions, helper text.
- **Dim** (#5a6573): Tertiary text. Field labels, toolbar button text, icon defaults.
- **Muted** (#7c8795): Quaternary text. Placeholders, hints, disabled states. Must still hit ≥3:1 against its background for UI text; ≥4.5:1 when used as placeholder in inputs.
- **Background** (#eef0f3): Page canvas. Cool grey with a barely-there blue cast. Never warm-tinted.
- **Panel** (#ffffff): Card and container surface. Pure white for maximum contrast against the bg.
- **Surface** (#f7f9fc): Subtle alternative surface. Log backgrounds, speed-hack cluster, search inputs.
- **Alt** (#f3f5f9): Hover backgrounds, tray backgrounds, tab tracks. Slightly warmer than Surface to create distinction.
- **Border** (#e4e7ec): Container borders. Cards, groups, trays.
- **Border Secondary** (#dde2e8): Input borders, tighter borders on interactive elements.
- **Line** (#f1f3f6): Hairline dividers. Sidebar section dividers, inspector block separators.

### Semantic
- **OK Green** (#1f9254): Success. Save buttons, connected device dot, success log lines.
- **Warn Amber** (#9c6c12): Warnings. Validation issues, timing indicators, speed-hack active state.
- **Error Red** (#bb3a33): Errors. Delete buttons, error log lines, validation failures.

### Run Trail (Graph State)
- **Run OK** (#1f9d57): Node executed successfully. Green border, green wire trail.
- **Run Fail** (#d6483f): Node action failed. Red border, red skipped-wire trail.
- **Run Live** (#f97316): Node currently executing. Amber pulse animation, the strongest visual signal on screen.
- **Run Info** (#06b6d4): Informational trail state.
- **Run Warn** (#eab308): Warning trail state.

### Branch Ports
- **Branch True** (#1f9d57): The true/yes output port on condition nodes. Green dot.
- **Branch False** (#e0792e): The false/no output port. Orange dot.
- **Branch Loop** (#e0a64b): The loop-back input port. Amber ring.

### Node Categories
- **Basic** (#6f9be8): Tap, swipe, key, wait nodes. Blue header tint.
- **Image** (#2fb0a3): Template match, screenshot nodes. Teal header tint.
- **OCR** (#e0954b): Read-text nodes. Orange header tint.
- **Logic** (#9a78e6): Condition, switch, loop nodes. Purple header tint.
- **Flow** (#b45309): Goto, call, parallel nodes. Amber header tint.
- **Misc** (#4b5563): Log, note nodes. Grey header tint.
- **Group Red** (#cf6b6b): Group frame accent only — no matching node category.

### Named Rules
**The One Accent Rule.** The Stable Blue is used on ≤10% of any given screen. Its rarity is the point — it draws the eye to the one thing that matters: the current action, the selected node, the focus ring. When everything is blue, nothing is.

**The Cool-Neutral Floor Rule.** The background is always cool-grey (#eef0f3), never warm (cream/sand/beige/parchment). Warmth is carried by the amber/orange semantic colors (run-live, warn, branch-false), not by the structural palette.

**The Semantic-Only Color Rule.** Ok green, warn amber, and error red appear only when they carry meaning (save succeeded, validation warning, action failed). They are never used as decorative flourishes. A button is green only when it commits; it's red only when it destroys.

## 3. Typography

**Body Font:** IBM Plex Sans (with Segoe UI, system-ui, sans-serif fallback)
**Mono Font:** IBM Plex Mono (with Cascadia Code, Consolas, monospace fallback)

**Character:** A single sans-serif family in multiple weights, paired with a matching monospace for code and data. The pairing is cohesive — Plex Sans and Plex Mono share proportions, x-height, and weight grades, so code inline with UI text feels intentional, not jarring. No serif, no display font; this is a tool, not a publication.

### Hierarchy
- **Display** (700, 13px, 1.25): Workflow name in the toolbar. The largest text on screen, always bold.
- **Title** (600, 12px, 1.25): Section headers, node titles, inspector identity. Semi-bold for presence without shouting.
- **Body** (400, 13px, 1.5): Primary UI text. Canvas hints, inspector content, button labels. Max line length 65-75ch on long prose.
- **Label** (700, 10.5px, 1.3, uppercase, +0.05em tracking): Section headers in sidebars, tray labels, inspector section titles, group headers. Uppercase with tracking — this is the system's only eyebrow convention, and it's earned because every label actually labels something.
- **Mono Body** (400, 11.5px, 1.5): Input text, log lines, coordinates, variable values, JSON. The system font for data.

### Named Rules
**The One Family Rule.** IBM Plex Sans and IBM Plex Mono. No third family. The proportional/monospace contrast is sufficient; adding a serif or display face dilutes the tool's precision.

**The No-Eyebrow Rule.** The uppercase label style is used only when the text actually labels a control or section. It never appears as a decorative kicker above content that doesn't need labeling. If you see "ABOUT" / "PROCESS" / "FEATURES" above every section, that's AI grammar — delete them.

## 4. Elevation

Workflow2k uses subtle, functional elevation. Surfaces are flat at rest; shadows appear only to reinforce hierarchy and interaction. The system has three shadow levels, each with a clear structural role.

### Shadow Vocabulary
- **Shadow Sm** (`0 1px 2px rgba(20,30,45,.06)`): Cards, toolbar, sidebar containers. Ambient layer — the minimum needed to separate a surface from the background.
- **Shadow Md** (`0 2px 8px rgba(20,30,45,.08)`): Nodes on the canvas, dropdown menus, corner-stack panels. Structural layer — clearly lifted from the canvas.
- **Shadow Lg** (`0 10px 30px rgba(20,30,45,.16)`): Context menus, layout menus, variable picker popovers. Modal layer — floating above everything.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest. Shadows appear only as a response to structure (cards need separation from bg, nodes need lift from canvas) or state (a context menu is floating). No decorative shadow — if the element isn't physically above something else, it doesn't cast a shadow.

**The Z-Index Scale Rule.** No arbitrary z-index values. The scale is: node (2), selection box (1), node hover (6), menu (50), toast (60). Every z-index in the CSS maps to one of these semantic layers.

## 5. Components

### Buttons
- **Shape:** Rounded rectangles (8px radius). The corner is soft enough to feel approachable, tight enough to feel precise.
- **Primary:** Stable Blue (#2f6fed) background, white text, no border. Used for save, run, and commit actions. 30px tall, 11px horizontal padding.
- **Primary Hover:** Darkens to #2559c7. Transition: 150ms background.
- **Success (.ok):** Green (#1f9254) background, white text. Run button, speed-hack enable. Has a subtle green box-shadow for presence.
- **Danger (.err):** Error-red background (#fcefee), red text (#bb3a33), red border (#eecdca). Delete, clear, destructive actions.
- **Default:** Panel background, dim text, border (#e4e7ec). Secondary actions, toolbar controls.
- **Icon-only (.ico):** Square (30px × 30px for standard, 26px × 26px for small). The icon SVG is 16px, centered. Label lives in the title attribute.
- **Focus:** 2px Stable Blue outline, 2px offset. Visible and consistent.
- **Motion:** 150ms transition on background, opacity, color, border-color. Cubic-bezier(0.16, 1, 0.3, 1) — the system's standard ease-out-quart curve.

### Trays (Segmented Controls)
- **Style:** Alt background (#f3f5f9), border (#e4e7ec), 10px radius. Contains icon buttons that lose their individual borders.
- **Internal buttons:** Transparent background, no border. Hover: panel background + border secondary.
- **Tray label:** 9.5px uppercase, muted, with a hairline separator before the action buttons.
- **Toolbar run tray:** Larger (36px) primary button with green shadow — the toolbar's focal point.

### Cards
- **Corner Style:** Medium radius (10px). Soft enough to feel like a surface, tight enough to stay precise.
- **Background:** White panel (#ffffff).
- **Border:** 1px border (#e4e7ec).
- **Shadow:** Shadow Sm (0 1px 2px rgba(20,30,45,.06)).
- **Internal Padding:** Varies by card role. Toolbar: 6px horizontal. Sidebar headers: 12px.

### Nodes (Graph Blocks)
- **Corner Style:** Tighter radius (7px) — rectangular, only lightly rounded, so nodes read as circuit elements, not friendly cards.
- **Background:** White panel (#ffffff).
- **Border:** 1px border secondary (#dde2e8). Category color lives in the header tint and icon, not the border.
- **Shadow:** Shadow Md (0 2px 8px rgba(20,30,45,.08)).
- **Header:** 20px tall, tinted per category. Light tinted background with matching border-bottom.
- **Title:** 10px bold, color matches category. Overflow ellipsis.
- **Body:** Mono summary line (10px, dim), 4-5px padding. Preview thumbnail: 26px square with checkerboard placeholder.
- **States:**
  - **Selected:** Blue border + 2px blue outer glow.
  - **Running:** Amber border + orange glow + pulse animation. The strongest signal on the canvas.
  - **Ran OK:** Green border + green shadow.
  - **Ran Fail:** Red border + red shadow.
  - **Ran Skip:** Red top-border, 50% opacity.
  - **Validation warning:** Amber "!" badge top-right, amber border.
- **Terminals (start/end):** 30px circles with filled accent disc and white glyph. No border in default state; state rings (selected, running, ran-*) apply as concentric halos.

### Inputs & Fields
- **Style:** Panel background, ink text, 1px border secondary (#dde2e8), 7px radius. Mono font (11.5px) with 5px/8px padding.
- **Placeholder:** Muted (#7c8795) — must still hit 4.5:1 against the panel background.
- **Focus:** Border shifts to Stable Blue + 3px blue outer glow (accent-bd color).
- **Select:** Custom chevron via inline SVG data-URI. Stripped native appearance. Sans font for consistency.

### Ports (Node Connection Dots)
- **Style:** 9px circles, 1.5px border, positioned at node edges (left for inputs, right for outputs).
- **Input (unconnected):** Grey fill (#e0e5eb), grey border (#c5cdd6).
- **Input (connected):** Accent-blue fill + border.
- **Output (unconnected):** Grey fill + border.
- **Output (connected):** Filled with the node's category accent color.
- **True/False ports:** Colored borders (green/orange) even when unconnected; fill lights up when wired.
- **Loop port:** Amber-ringed input for loop-back connections.
- **Hover:** Scales to 1.35×, border turns blue. Has an invisible 6px padded hit-area.
- **Run trail:** Taken port fills green; skipped port fills red.

### Sidebar (Node Palette)
- **Width:** 254px, resizable via drag handle.
- **Search:** Compact field with inline magnifier icon, clear button on right when active. Rounded, surface background.
- **Categories:** Pill headers with colored dot + count badge. Per-category background tint.
- **Chips:** Grab-handle cards with category-colored icon, bold title (12.5px, ink-secondary). Hover: blue border + blue tint background.

### Inspector (Right Panel)
- **Width:** 280px, resizable. Sticky identity header with icon + title + ID count badge.
- **Sections:** Flat blocks separated by hairline dividers. No nested cards — the divider is the separator.
- **Field rows:** Label (10.5px, dim, 58px min-width) + input/select. Compact and aligned.
- **JSON debug:** Expandable read-only textarea with copy button. 220px default height, resizable.

### Log Panel
- **Style:** Collapsible card at bottom. 100-155px height, collapses to 33px header-only.
- **Header:** Chevron + "LOG" label + count badge + clear button. Hover: alt background.
- **Body:** Log-background (#fbfcfd), mono lines with timestamp + tag + message.
- **Tags:** Color-coded: blue (info), green (success), amber (warning), red (error).

### Context Menu
- **Style:** Fixed-position floating panel. White, 8px radius, shadow-lg. 4px internal padding.
- **Items:** 12px ink text, 7px/10px padding, 5px radius. Hover: accent-blue background + blue text. Icon + text layout.

### Run Status Pill
- **Style:** Rounded pill (999px) in toolbar. Alt background, border, dim text at rest.
- **Running:** Amber background (#fff7ed), amber border (#fdba74), amber text (#c2610f). Dot pulses amber.

### Groups (Canvas Frames)
- **Style:** Dashed border, colored per category (or group-red). 10px radius. Body is pointer-events:none so nodes remain interactive.
- **Header:** Colored tab above the frame, white text, bold. Delete button inline.
- **Resize handle:** Bottom-right corner, 14px, nwse-resize cursor.

## 6. Do's and Don'ts

### Do:
- **Do** use the Stable Blue accent sparingly — it should appear on ≤10% of any screen. Primary buttons, selected states, focus rings only.
- **Do** use semantic colors (ok green, warn amber, err red) only when they carry meaning — never as decoration.
- **Do** keep the graph canvas as the visual center. The toolbar, sidebar, and inspector are chrome — they recede until needed.
- **Do** use the uppercase label style only when the text actually labels a control or section. Never as a decorative kicker.
- **Do** maintain 4.5:1 contrast for all body text against its background. Muted (#7c8795) is for placeholders and hints only.
- **Do** use the shadow scale by role: sm for cards, md for nodes/menus, lg for floating panels. Never arbitrary shadow values.
- **Do** keep the background cool-grey (#eef0f3). Warmth comes from semantic amber/orange, not from tinting the structural palette.
- **Do** use IBM Plex Sans for UI, IBM Plex Mono for code/data. No third family.

### Don't:
- **Don't** use the design-tool aesthetic: no pastels, no glassmorphism, no soft-focus blur, no frosted glass. This is not Linear, Raycast, or Figma.
- **Don't** make the interface dark-by-default or dashboard-like. No wall-of-metrics, no chart-heavy panels, no Grafana/Retool look.
- **Don't** add playful or consumer-app elements: no illustrations, no gamification, no whimsy. This is not Duolingo or Notion.
- **Don't** use border-left or border-right greater than 1px as a colored accent stripe on cards, list items, or callouts.
- **Don't** use gradient text (background-clip: text). Use a single solid color. Emphasis via weight or size.
- **Don't** use arbitrary z-index values. Map to the semantic scale: node (2), node-hover (6), menu (50), toast (60).
- **Don't** warm-tint the background. No cream, sand, beige, parchment, or ivory. The background is cool-grey, always.
- **Don't** animate without a reduced-motion fallback. Every animation must have `@media (prefers-reduced-motion: reduce)` alternative.
- **Don't** introduce a second accent color. The Stable Blue is the only accent. Semantic colors (green/amber/red) are functional, not decorative.
