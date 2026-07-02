# Product

## Register

product

## Users

Developers and QA engineers building automation workflows for Android devices — primarily game botting and mobile app testing. Users range from scripters who want a visual node-graph instead of raw Python to test engineers who need repeatable, debuggable automation pipelines. They spend hours in the tool and value precision, speed, and clear feedback over decoration.

## Product Purpose

Workflow2k is a visual workflow designer and runner for Android automation. Users compose node graphs (tap, swipe, template-match, OCR, conditional branches, loops) that execute against real devices via ADB and scrcpy. The tool eliminates the friction of writing automation scripts by hand, making Android automation visual, debuggable, and composable.

## Brand Personality

Precise, efficient, capable. The tool feels like a sharp instrument — no fluff, no hand-holding, but never cold or hostile. It respects the user's time and intelligence. Visual language is clean, restrained, and information-dense without being overwhelming.

## Anti-references

- **Design-tool aesthetic** (Linear, Raycast, Figma): no pastel palettes, no frosted glass, no soft-focus blur. This is not a design tool.
- **Dashboard/data-monitoring UIs** (Grafana, Retool): no dark-mode-by-default, no wall-of-metrics, no chart-heavy dashboards.
- **Playful/consumer apps** (Duolingo, Notion): no illustrations, no gamification, no whimsy.
- **Unix hacker tools**: not raw, not hostile, not terminal-first — visual and approachable.

## Design Principles

1. **Show the graph.** The node-graph is the center of the product. Every design decision should make the graph more readable: wires, ports, run trails, validation badges all exist to make state visible at a glance.
2. **One action, one click.** Frequent operations (run, save, validate, inspect) are reachable without menu diving. The toolbar is always visible; the inspector updates instantly on selection.
3. **State is obvious.** Running nodes pulse amber. Completed trails are green. Failures are red. Validation warnings are amber badges. No hidden state — the canvas tells the full story.
4. **Dense but calm.** Information lives where it's needed (toolbar, canvas, inspector, log). Visual weight is proportional to importance. Spacing and hierarchy prevent overload without adding emptiness.
5. **Keyboard first, mouse friendly.** Power users navigate with shortcuts; everything remains discoverable via mouse. No hidden gestures.

## Accessibility & Inclusion

- Standard defaults: keyboard-navigable, reduced-motion support already built in
- No specific WCAG level required, but maintain current contrast ratios and focus indicators
- The app is single-user desktop software; color alone is not the sole indicator for critical state (text labels back up run status, validation badges, and port colors)
