# Obstacle-Aware Return Wires Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route backwards designer wires through nearby open passages, rather than below every intervening node.

**Architecture:** Add a bounded deterministic orthogonal visibility-graph router for backward edges only. Keep existing fallback and forward-link rendering; integrate waypoint lists with the existing rounded path builder and unchanged SVG hit/halo paths.

**Tech Stack:** Vanilla JavaScript, SVG, Node `node:test`, Python Playwright.

**Spec:** `docs/superpowers/specs/2026-09-22-designer-obstacle-aware-return-wires-design.md`

## Global Constraints

- Do not modify `workflows/GirlWars/GirlWars.json` or workflow schema.
- Keep forward modes and temporary drag wire behavior unchanged.
- Hit path, halo, visible stroke share one path string.
- Stable routes and bounded work; fallback to existing outer lane when search fails.

## Review Focus

- A tall unrelated node anywhere between X endpoints must not force a long detour: Task 1 actual graph test.
- Close same-row return must remain outside cards: Task 1 existing test.
- Endpoint entry/exit cannot cut through cards: Task 1 geometry test.
- Reversed/imported edge order must not change route: Task 2 order test.
- Hovering overlapping wires must retain highlight: Task 2 browser hover regression.

---

### Task 1: Pure route search and graph regression

**Files:** Modify `apps/web/wf/js/wires.js`; modify `tests/test_wire_readability.cjs`.

**Interfaces:** Consumes endpoint port points `{x,y,edge,bottom}` and node rectangles `{left,right,top,bottom}`. Produces `wfFindReturnPoints(a,b,blocks,options?)` returning orthogonal waypoints from source port to destination port, or `null` if no valid path within budget.

- [ ] **Step 1: Write failing tests:** Read `workflows/GirlWars/GirlWars.json`, locate activity `sequence_y0b1`, derive rendered node rectangles using canonical geometry (144×64; terminal 48×48), and inspect both named long return edges. Assert waypoints start/end at their ports; each segment remains orthogonal; horizontal/vertical middle segments avoid all other card rectangles plus 10px; maximum Y stays substantially above 1540; route length is shorter than old external lane. Test adjacent/level returns, blocked corridor and deterministic repeated calls. Avoid relying on mutable workflow data: read-only.
- [ ] **Step 2: Verify red:** `node --test tests/test_wire_readability.cjs`; expected new route tests fail because `wfFindReturnPoints` does not exist.
- [ ] **Step 3: Implement minimal router:** Build candidate X/Y coordinates from expanded rectangle sides and endpoint escape stubs; connect axis-aligned adjacent visible candidates; Dijkstra/A* with Manhattan distance + turn penalty, capped candidates/expansions. Keep entry/exit horizontal outward from the port. If search is exhausted or geometry invalid return `null`. Reuse the existing outer-lane route as fallback.
- [ ] **Step 4: Verify green:** `node --test tests/test_wire_readability.cjs tests/test_designer_geometry.cjs`.
- [ ] **Step 5: Commit:** stage only `apps/web/wf/js/wires.js` and `tests/test_wire_readability.cjs`; `git commit -m "feat: find obstacle-aware return wire routes"`.

### Task 2: Integrate waypoints into rendered wires

**Files:** Modify `apps/web/wf/js/wires.js`; modify `tests/test_wire_readability.cjs`; inspect `tests/check_wire_hover.py`.

**Interfaces:** `wfFindReturnPoints` from Task 1. Produce `wfRoundedPointsPath(points)` SVG `d` using existing corner rounding; `wfWirePath(a,b)` consumes `a.routePoints` when present.

- [ ] **Step 1: Write failing tests:** assert route path uses the returned waypoints for both long edges; route is stable when edge input order is reversed; fallback if router returns `null`; forward spline and temporary path remain unchanged. Browser hover regression uses the rendered hit-path's shared `d`.
- [ ] **Step 2: Verify red:** `node --test tests/test_wire_readability.cjs` fails on missing waypoint integration.
- [ ] **Step 3: Wire integration:** snapshot node rectangles once per draw, sort edges by stable key, resolve only backward edges with `wfFindReturnPoints`, put route waypoints on a copied source endpoint, use rounded SVG path for these edges. Keep halo/hit/wire on the same `d`; never reorder SVG elements on pointerover.
- [ ] **Step 4: Verify:** `node --test tests/test_wire_readability.cjs tests/test_designer_geometry.cjs tests/test_wire_fanin.cjs tests/test_click_connect.cjs`; `uv run --no-project --with playwright python tests/check_wire_hover.py`; `uv run --no-project --with playwright python tests/check_node_execution_style.py`; `node --test tests/*.cjs` (report pre-existing failures by name); `git diff --check`.
- [ ] **Step 5: Commit and push:** stage scoped code/tests and plan; `git commit -m "fix: use obstacle-aware paths for return wires"`; `git push origin main` only after verification. Do not stage the user-modified workflow JSON or submodule/worktree entries.
