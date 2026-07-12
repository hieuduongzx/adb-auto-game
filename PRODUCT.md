# Product

## Register

product

## Users

One developer (Vietnamese-speaking) building and running ADB game-automation
workflows on Windows against Android emulators/devices. Tools run side by side
with an emulator window, often for hours; the runner window is small (~440px
wide) and portrait.

## Product Purpose

An internal tool suite — **Workflow2k Designer** (node-graph editor),
**Workflow2k Runner** (load a JSON flow and run it), and **DevScope** (device
inspector). The runner's job: load a flow, toggle activities, press Start, and
monitor progress/log at a glance while it runs unattended.

## Brand Personality

Compact, calm, utilitarian. IBM Plex Sans/Mono, light theme, dense but tidy.
The tool disappears into the task; state (running / paused / connected) is
always readable at a glance from across the desk.

## Anti-references

- Dark "gamer" RGB aesthetics, neon accents, heavy chrome.
- Marketing-style hero layouts; this is an operator panel, not a landing page.
- Oversized touch-first controls — this is a mouse-driven desktop tool.

## Design Principles

1. **One vocabulary across apps** — the runner, designer, and DevScope share
   tokens, controls, and component shapes (see `apps/web/wf/css/base.css`).
2. **Density without clutter** — small window, many rows; every pixel of
   chrome must earn its place.
3. **State first** — run status, per-activity status, and device connection
   are visible without interaction.
4. **English labels throughout** (unified July 2026 — previously mixed
   Vietnamese/English), mono for data (serials, timers, counts).

## Accessibility & Inclusion

Desktop WebView2, light scheme. Keep text ≥4.5:1 contrast, visible focus
rings, `prefers-reduced-motion` fallbacks. Single-user internal tool; WCAG AA
as a working floor, no formal audit required.
