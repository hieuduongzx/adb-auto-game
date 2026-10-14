"""Which nodes use which template — one walk shared by the bundler and the Library."""
from __future__ import annotations

import os
from typing import Any, Dict, List

from src.workflow import NODE_TYPES

from designer.common import _TEMPLATE_LIST_PARAM_KEYS, _TEMPLATE_PARAM_KEYS


# ── Template references ───────────────────────────────────────────────────────
#
# One definition of "this node uses this template", shared by the bundler that
# copies the files on save and the Library that audits them. Two walks that
# drifted apart would mean the Library could call a file unused that the save
# then bundles — so the bundler writes through _iter_template_refs too.

def iter_owners(flow: dict):
    """Yield ``(kind, owner, graph)`` for every graph in a flow.

    ``kind`` is ``"activity"`` or ``"function"`` and ``owner`` is the dict
    itself, so a caller that needs to say *where* a node lives does not have to
    re-walk the flow to find out.
    """
    if not isinstance(flow, dict):
        return
    for act in flow.get("activities") or []:
        g = act.get("graph") if isinstance(act, dict) else None
        if isinstance(g, dict):
            yield "activity", act, g
    for fn in flow.get("functions") or []:
        g = fn.get("graph") if isinstance(fn, dict) else None
        if isinstance(g, dict):
            yield "function", fn, g


def iter_template_refs(flow: dict):
    """Yield ``(node, kind, owner, param_key, index, raw)`` per reference.

    ``index`` is the position inside a list param (the "…_any" OR nodes), or
    ``None`` for the scalar ``template`` field.
    """
    for kind, owner, graph in iter_owners(flow):
        for node in graph.get("nodes") or []:
            params = node.get("params") if isinstance(node, dict) else None
            if not isinstance(params, dict):
                continue
            for pk in _TEMPLATE_PARAM_KEYS:
                if params.get(pk):
                    yield node, kind, owner, pk, None, params[pk]
            for pk in _TEMPLATE_LIST_PARAM_KEYS:
                vals = params.get(pk)
                if isinstance(vals, list):
                    for i, v in enumerate(vals):
                        raw = v.get("template") if isinstance(v, dict) else v
                        if raw:
                            yield node, kind, owner, pk, i, raw


def _norm_tpl(raw: Any) -> str:
    """Normalised key for matching a stored template path to a file on disk.

    A stored value is ``templates/<file>`` once bundled, but is whatever the user
    picked before that (an absolute path, ``out/<file>``…). Both sides collapse
    to the bare basename, which is what the bundler guarantees is unique inside
    one workflow's folder.
    """
    return os.path.basename(str(raw or "").replace("\\", "/")).strip().lower()


def build_template_index(flow: dict, items: List[dict]) -> dict:
    """Pair the files found on disk with the nodes that reference them.

    *items* is what ``list_image_assets`` returned. Pure — no I/O — so the
    Library's counts can be tested against a fixture instead of a device.
    """
    used: Dict[str, List[dict]] = {}
    refs = 0
    for node, kind, owner, _pk, _idx, raw in iter_template_refs(flow):
        refs += 1
        ntype = node.get("type") or ""
        used.setdefault(_norm_tpl(raw), []).append({
            "activity": owner.get("name") or owner.get("id") or "?",
            "ownerId": owner.get("id") or "",
            "ownerKind": kind,          # "activity" | "function"
            "nodeId": node.get("id") or "",
            "nodeType": ntype,
            "nodeLabel": NODE_TYPES.get(ntype, {}).get("label") or ntype or "?",
            "raw": str(raw),
        })

    on_disk: Dict[str, dict] = {}
    templates = []
    orphan = 0
    for it in items:
        key = os.path.basename(it["name"]).lower()
        on_disk[key] = it
        usages = used.get(key, [])
        if not usages:
            orphan += 1
        templates.append({**it, "used": usages, "usedCount": len(usages)})

    # A reference whose file is not in the folder: those nodes will fail at run
    # time, and nothing else in the tool says so before you press Run.
    missing = [{**e, "name": os.path.basename(e["raw"]) or e["raw"]}
               for key, entries in used.items() if key and key not in on_disk
               for e in entries]

    return {
        "templates": templates,
        "missing": missing,
        "counts": {
            "total": len(templates),
            "used": len(templates) - orphan,
            "orphan": orphan,
            "missing": len(missing),
            "refs": refs,
        },
    }


def group_duplicate_items(out_dir: str, items: List[dict],
                          threshold: int = 4) -> dict:
    """Group near-identical images by perceptual hash.

    *threshold* is the maximum Hamming distance for two files to count as the
    same crop — 4 keeps different buttons apart while catching a re-crop that
    shifted by a pixel or two. Files are bucketed by dimensions first, because
    two crops of the same button are rarely taken at the same size by accident,
    which turns an O(n²) comparison into a handful of plausible pairs.
    """
    from src.core.imghash import dhash, hamming

    hashed = []
    for it in items:
        h = dhash(os.path.join(out_dir, it["name"].replace("/", os.sep)))
        if h is not None:
            hashed.append((it, h))

    by_size: Dict[tuple, List[tuple]] = {}
    for it, h in hashed:
        by_size.setdefault((it.get("w"), it.get("h")), []).append((it, h))

    seen: set = set()
    groups: List[dict] = []
    for bucket in by_size.values():
        if len(bucket) < 2:
            continue
        for i, (a, ha) in enumerate(bucket):
            if a["name"] in seen:
                continue
            group = [a]
            for b, hb in bucket[i + 1:]:
                if b["name"] in seen:
                    continue
                if hamming(ha, hb) <= threshold:
                    group.append(b)
                    seen.add(b["name"])
            if len(group) > 1:
                seen.add(a["name"])
                # Largest first: the biggest file is the one most likely to be
                # the original crop rather than one of its shrunken copies.
                group.sort(key=lambda x: x.get("size") or 0, reverse=True)
                groups.append({
                    "w": a.get("w"), "h": a.get("h"),
                    "files": [{"name": f["name"], "path": f["path"],
                               "size": f["size"]} for f in group],
                })
    groups.sort(key=lambda g: len(g["files"]), reverse=True)
    return {"groups": groups, "scanned": len(hashed)}
