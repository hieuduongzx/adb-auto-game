"""Read-only inventory and graph audit; never rewrites workflow JSON.

python tools/audit_workflows.py --output out/workflow-audit.json
"""
import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def registry():
    tree = ast.parse((ROOT / "src/workflow/engine.py").read_text(encoding="utf-8"))
    declaration = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                       and isinstance(n.target, ast.Name) and n.target.id == "NODE_TYPES")
    return ast.literal_eval(declaration.value)


def audit_graph(owner, specs):
    graph = owner.get("graph") or {}
    nodes, edges = graph.get("nodes") or [], graph.get("edges") or []
    by_id = {n.get("id"): n for n in nodes}
    ports, outgoing = defaultdict(list), defaultdict(list)
    for edge in edges:
        ports[(edge.get("from"), edge.get("fromPort", "out"))].append(edge.get("to"))
    for (source, _port), targets in ports.items():
        outgoing[source].append(targets[0])
    start = next((n for n in by_id.values() if n.get("type") == "start"), None)
    reachable, pending = set(), [start.get("id")] if start else []
    while pending:
        nid = pending.pop()
        if nid in reachable or nid not in by_id:
            continue
        reachable.add(nid)
        if by_id[nid].get("type") not in ("end", "stop"):
            pending.extend(outgoing.get(nid, []))
    def describe(node):
        return {"id": node.get("id"), "type": node.get("type"), "note": node.get("note", "")}
    duplicate_ids = [nid for nid, n in Counter(n.get("id") for n in nodes).items() if n > 1]
    return {
        "id": owner.get("id"), "name": owner.get("name"), "nodes": len(nodes), "edges": len(edges),
        "types": dict(Counter(n.get("type") for n in nodes)), "no_start": start is None,
        "multiple_starts": sum(n.get("type") == "start" for n in nodes) > 1,
        "duplicate_ids": duplicate_ids,
        "unknown_types": [describe(n) for n in nodes if n.get("type") not in specs],
        "dangling_edges": [e for e in edges if e.get("from") not in by_id or e.get("to") not in by_id],
        "multiple_wires_per_output": [{"node": nid, "port": p, "targets": ts}
                                      for (nid, p), ts in ports.items() if len(ts) > 1],
        "reachable_count": len(reachable),
        "unreachable": [describe(n) for n in nodes if n.get("id") not in reachable and n.get("type") != "note"],
        "annotations": sum(n.get("type") == "note" for n in nodes),
        "empty_logs": [describe(n) for n in nodes if n.get("type") == "log"
                       and not str((n.get("params") or {}).get("message") or "").strip()],
        "reachable_calls": [str((by_id[nid].get("params") or {}).get("fn") or "")
                            for nid in reachable if by_id[nid].get("type") == "call"],
    }


def audit_file(path, specs):
    flow = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(flow, dict) or "activities" not in flow:
        return None
    activities = [audit_graph(a, specs) for a in flow.get("activities") or []]
    functions = [audit_graph(f, specs) for f in flow.get("functions") or []]
    by_id = {str(f.get("id")): f for f in functions}
    used, pending, missing = set(), [fn for a in activities for fn in a["reachable_calls"]], set()
    while pending:
        fn = pending.pop()
        if fn in used:
            continue
        if fn not in by_id:
            missing.add(fn)
            continue
        used.add(fn)
        pending.extend(by_id[fn]["reachable_calls"])
    types = Counter()
    for g in activities + functions:
        types.update(g["types"])
    return {"path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
            "name": flow.get("name"), "controller": flow.get("controller", "adb"),
            "nodes": sum(g["nodes"] for g in activities + functions), "types": dict(types),
            "activities": activities, "functions": functions,
            "unused_functions": [{"id": f["id"], "name": f["name"], "nodes": f["nodes"]}
                                 for f in functions if str(f["id"]) not in used],
            "missing_reachable_functions": sorted(missing)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    specs = registry()
    paths = args.paths or sorted(p for p in (ROOT / "workflows").rglob("*.json")
                                if "_run" not in p.relative_to(ROOT / "workflows").parts)
    reports, errors = [], []
    for path in paths:
        try:
            result = audit_file(path.resolve(), specs)
            if result:
                reports.append(result)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    counts = Counter()
    for report in reports:
        counts.update(report["types"])
    result = {"registry_types": len(specs), "files": reports, "errors": errors,
              "total_nodes": sum(r["nodes"] for r in reports), "usage": dict(counts.most_common()),
              "unused_types_in_this_corpus": sorted(set(specs) - set(counts))}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, ensure_ascii=False, indent=2))
    for report in reports:
        graphs = report["activities"] + report["functions"]
        print(f"{report['path']}: {report['nodes']} nodes, "
              f"{sum(len(g['unreachable']) for g in graphs)} unreachable, "
              f"{len(report['unused_functions'])} unused functions")


if __name__ == "__main__":
    main()
