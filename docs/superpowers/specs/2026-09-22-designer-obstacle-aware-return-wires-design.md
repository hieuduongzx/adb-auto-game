# Designer obstacle-aware return wires

## Intent and scope

A backward connection in a dense workflow should take a nearby visible gap instead of diving beneath every node whose X-coordinate lies between its endpoints. The reported `sequence_y0b1` graph in `workflows/GirlWars/GirlWars.json` has long returns `nxxatqvh → nij39omx` and `n6t0kzpb → nt1m0dej`; the existing single-horizontal-lane router chooses roughly Y=1540 because unrelated nodes extend to Y=1512. Preserve graph data, endpoint ports, drag previews, wire interaction, semantic colours, link-mode behaviour for forward connections, and existing short return behaviour. Do not edit the workflow JSON.

## Routing approach

For a rendered backward edge, snapshot card rectangles and construct a sparse rectilinear visibility graph from obstacle boundaries plus endpoint escape points. Expand cards by a fixed clearance so the path and rounded corners do not touch cards. Exclude endpoint card interiors from the middle-route search; start/end stubs leave/enter on their correct sides. Connect adjacent visible coordinates along horizontal and vertical axes only when a segment does not intersect an expanded obstacle. Use a deterministic shortest-path search weighted by travelled distance, a modest bend cost, and a crossing/overlap penalty against already routed wires when practical. Stable edge sorting makes redraws reproducible. If the search cannot find a path within a bounded work budget, fall back to the current outer-lane route rather than losing the connection. Existing near-level short loop returns can continue using the outer lane when it is the clearest route; do not route through card boxes to shorten the drawing.

## Rendering and interactions

Pass route waypoints to the existing rounded orthogonal SVG path builder; the visible stroke, canvas-coloured underlay and transparent hit path share exactly the same `d`. Preserve the DOM order on hover (the recent pointerover reordering caused hover flicker). Keyboard focus and delete behaviour remain unchanged. Forward wires and temporary drag wires use their current shape modes. No workflow schema changes.

## Verification

Use actual node rectangles and long-edge IDs from the supplied `sequence_y0b1` as a regression fixture. Assert the computed routes do not intersect unrelated node rectangles, are much shorter than the old Y≈1540 detour, connect the exact ports, and are stable across redraws. Cover blocked corridors, close/level return, parallel edges, fallback, and hover. Run focused Node tests, the browser hover test, and the full available Node suite; report unrelated failures rather than hiding them.
