"""The Library tab: listing, rename, duplicates and template bundling."""
from __future__ import annotations

import json
import os
import shutil
from typing import Dict, List, Optional

from src.core.adb import device_info
from src.utils import (
    log_info,
    log_warning,
)
from designer.common import (
    _PROJECT_ROOT,
    _TEMPLATES_DIRNAME,
    _sanitize_name,
)
from designer.templates import (
    _norm_tpl,
    build_template_index,
    group_duplicate_items,
    iter_owners,
    iter_template_refs,
)


class LibraryMixin:
    """The Library tab: listing, rename, duplicates and template bundling."""

    # ── Asset library ─────────────────────────────────────────────────────────

    def list_assets(self) -> list:
        return device_info.list_image_assets(self._scope_out())

    def get_asset_thumbnail(self, path: str) -> str:
        return device_info.asset_thumbnail(self._scope_out(), path)

    def delete_asset(self, path: str) -> bool:
        return device_info.delete_asset(self._scope_out(), path)

    # ── Library tab (templates of the open workflow) ───────────────────────────
    #
    # The Library is an audit surface: which template files does this workflow
    # actually use, which are dead weight, and which nodes point at a file that
    # is not there. It takes the flow from the page rather than from disk so an
    # unsaved reference shows up immediately — an orphan you just created by
    # deleting a node should not need a save to become visible.

    def _library_dir(self, flow_json: str = "") -> str:
        """Folder the Library browses: the open workflow's ``templates/``.

        Cached per call to :meth:`list_templates` so the file actions that
        follow (thumbnail, delete, rename) act on the same folder the listing
        described, even if the user opens another workflow in between.
        """
        dest = self._workflow_templates_dir(flow_json)
        if not dest:
            # No workflow context at all — fall back to the preview crop folder
            # so the tab still shows something rather than an empty error.
            dest = self._scope_out()
        self._library_out_dir = dest
        return dest

    def list_templates(self, flow_json: str = "") -> dict:
        """Every template in the open workflow's folder, with its node usages.

        One round-trip returns the whole grid: file size and dimensions are read
        here rather than per-card, because 269 thumbnails is already 269 calls.
        """
        out_dir = self._library_dir(flow_json)
        try:
            flow = json.loads(flow_json) if flow_json else {}
        except Exception:
            flow = {}
        items = device_info.list_image_assets(out_dir, with_dims=True)
        return {"dir": out_dir.replace("\\", "/"),
                **build_template_index(flow, items)}

    def template_thumbnail(self, path: str) -> str:
        out_dir = getattr(self, "_library_out_dir", "") or self._scope_out()
        return device_info.asset_thumbnail(out_dir, path)

    def template_delete(self, path: str) -> dict:
        """Soft-delete one template file (moves it to ``_trash/``)."""
        out_dir = getattr(self, "_library_out_dir", "") or self._scope_out()
        name = os.path.basename((path or "").replace("\\", "/"))
        if not device_info.delete_asset(out_dir, path):
            return {"ok": False, "error": f"Could not delete '{name}'"}
        log_info(f"Moved '{name}' to {device_info.TRASH_DIR}/")
        return {"ok": True, "name": name}

    def template_restore(self, path: str) -> dict:
        """Undo a soft delete: move the file back out of ``_trash/``."""
        out_dir = getattr(self, "_library_out_dir", "") or self._scope_out()
        name = os.path.basename((path or "").replace("\\", "/"))
        if not device_info.restore_asset(out_dir, path):
            return {"ok": False, "error": f"Could not restore '{name}'"}
        log_info(f"Restored '{name}'")
        return {"ok": True, "name": name}

    def list_trash(self) -> list:
        """Files sitting in ``_trash/``, newest first."""
        out_dir = getattr(self, "_library_out_dir", "") or self._scope_out()
        trash = os.path.join(out_dir, device_info.TRASH_DIR)
        return device_info.list_image_assets(trash, with_dims=True)

    # ── Template rename (with reference rewrite) ───────────────────────────────

    def rename_template(self, flow_json: str, path: str, new_name: str) -> dict:
        """Rename a template file and every node reference to it.

        Returns ``{"ok", "flow", "old", "new", "nodes"}`` — ``flow`` is the
        rewritten flow JSON for the page to adopt, so one Ctrl+Z on the canvas
        undoes both the rename and the rewrite (the page pushes its undo
        snapshot before applying it).
        """
        out_dir = self._library_dir(flow_json)
        # asset_path, not confined_path: the page may pass the absolute listing
        # path or just the file name the rename field holds.
        src = device_info.asset_path(out_dir, path)
        if not src:
            return {"ok": False, "error": "Original file not found"}
        clean = _sanitize_name(os.path.splitext(str(new_name or ""))[0])
        if not clean:
            return {"ok": False, "error": "Invalid new name"}
        ext = os.path.splitext(src)[1]
        old_base = os.path.basename(src)
        new_base = clean + ext
        if new_base == old_base:
            return {"ok": True, "flow": flow_json, "old": old_base, "new": new_base,
                    "nodes": 0}

        dest = os.path.join(out_dir, new_base)
        if os.path.exists(dest):
            return {"ok": False, "error": f"A file named '{new_base}' already exists in this folder"}

        try:
            flow = json.loads(flow_json) if flow_json else {}
        except Exception:
            return {"ok": False, "error": "Could not read workflow JSON"}
        if not isinstance(flow, dict):
            return {"ok": False, "error": "Invalid workflow JSON"}

        # Rewrite first, then move: if the JSON turns out to be unwritable the
        # file is still where every existing reference expects it.
        tdir = (flow.get("templatesDir") or _TEMPLATES_DIRNAME).strip().strip("/\\") \
            or _TEMPLATES_DIRNAME
        touched = 0
        old_key = old_base.lower()
        rel = f"{tdir}/{new_base}"
        for node, _kind, _owner, pk, idx, raw in iter_template_refs(flow):
            if _norm_tpl(raw) != old_key:
                continue
            if idx is None:
                node["params"][pk] = rel
            elif isinstance(node["params"][pk][idx], dict):
                node["params"][pk][idx]["template"] = rel
            else:
                node["params"][pk][idx] = rel
            touched += 1

        try:
            os.replace(src, dest)
        except OSError as exc:
            return {"ok": False, "error": f"Could not rename file: {exc}"}

        log_info(f"Renamed '{old_base}' → '{new_base}' ({touched} node(s) updated)")
        return {"ok": True, "flow": json.dumps(flow, ensure_ascii=False),
                "old": old_base, "new": new_base, "nodes": touched}

    # ── Duplicate detection ────────────────────────────────────────────────────

    def find_duplicate_templates(self, threshold: int = 4) -> dict:
        """Group templates that are near-identical crops of the same button.

        Everything happens Python-side in one call — the browser would have to
        fetch every image to compare them, which at 269 templates is 269
        round-trips to answer a question the backend can answer from the files.

        ``threshold`` is passed straight to :func:`group_duplicate_items`.
        """
        out_dir = getattr(self, "_library_out_dir", "") or self._scope_out()
        items = device_info.list_image_assets(out_dir, with_dims=True)
        if len(items) < 2:
            return {"groups": [], "scanned": len(items)}
        return group_duplicate_items(out_dir, items, threshold)

    # ── Template bundling (portable game folder) ───────────────────────────────

    @staticmethod
    def _iter_graphs(flow: dict):
        """Yield every node-graph in a flow (each activity + each function)."""
        for _kind, _owner, g in iter_owners(flow):
            yield g

    def _resolve_existing(self, raw: str, save_dir: str) -> Optional[str]:
        """Absolute path of an existing template, or ``None`` if not found.

        Tries the save folder (already-bundled / in-place save), the currently
        open flow's folder, then the project's usual asset roots.
        """
        raw = (raw or "").strip().replace("\\", "/")
        if not raw:
            return None
        if os.path.isabs(raw):
            return raw if os.path.isfile(raw) else None
        anchors: List[str] = []
        if save_dir:
            anchors.append(save_dir)
        if self._wf_path:
            anchors.append(os.path.dirname(self._wf_path))
        anchors += [_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "out"), os.getcwd()]
        for a in anchors:
            cand = os.path.join(a, raw)
            if os.path.isfile(cand):
                return cand
        return None

    def _materialize_templates(self, flow: dict, save_dir: str) -> int:
        """Copy every template used by ``flow`` into ``save_dir/templates`` and
        rewrite each node's path to the relative ``templates/<file>`` form.

        Returns the number of distinct images bundled. Mutates ``flow`` in place.
        """
        tdir_name = (flow.get("templatesDir") or _TEMPLATES_DIRNAME).strip().strip("/\\")
        tdir_name = tdir_name or _TEMPLATES_DIRNAME
        flow["templatesDir"] = tdir_name
        dest_dir = os.path.join(save_dir, tdir_name)

        copied: Dict[str, str] = {}   # normalized source abs path -> "templates/<file>"
        taken: set = set()            # lower-cased basenames already claimed

        def relocate(raw: str) -> str:
            src = self._resolve_existing(raw, save_dir)
            if not src:
                return raw  # leave unknown/empty paths untouched
            key = os.path.normcase(os.path.abspath(src))
            if key in copied:
                return copied[key]
            stem, ext = os.path.splitext(os.path.basename(src))
            name, n = f"{stem}{ext}", 1
            while name.lower() in taken:   # different source, same basename
                name = f"{stem}_{n}{ext}"
                n += 1
            taken.add(name.lower())
            dest = os.path.join(dest_dir, name)
            if os.path.normcase(os.path.abspath(dest)) != key:
                os.makedirs(dest_dir, exist_ok=True)
                shutil.copy2(src, dest)
            rel = f"{tdir_name}/{name}"
            copied[key] = rel
            return rel

        for node, _kind, _owner, pk, idx, raw in iter_template_refs(flow):
            if idx is None:
                node["params"][pk] = relocate(raw)
            else:
                node["params"][pk][idx] = relocate(raw)
        return len(copied)

    # Top-level keys other tools write into the workflow JSON and the Designer
    # page never loads — the Hub build's runnerUpdate (update repo, last built
    # version). Without carrying them over, every save forgot the chosen repo.
    _EXTERNAL_FLOW_KEYS = ("runnerUpdate",)

    @classmethod
    def _keep_external_keys(cls, flow: dict, path: str) -> None:
        """Copy :attr:`_EXTERNAL_FLOW_KEYS` from the file on disk into ``flow``."""
        if not isinstance(flow, dict) or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                old = json.load(fh) or {}
        except Exception:
            return
        if not isinstance(old, dict):
            return
        for key in cls._EXTERNAL_FLOW_KEYS:
            if key not in flow and key in old:
                flow[key] = old[key]

    def _write_flow(self, flow_json: str, path: str) -> None:
        """Write a flow to ``path``, bundling its templates into a sibling folder.

        Falls back to writing the raw JSON unchanged if it can't be parsed or
        the images can't be copied, so a save never silently fails.
        """
        text = flow_json
        try:
            flow = json.loads(flow_json)
            self._keep_external_keys(flow, path)
            n = self._materialize_templates(flow, os.path.dirname(os.path.abspath(path)))
            text = json.dumps(flow, ensure_ascii=False, indent=2)
            if n:
                log_info(f"Bundled {n} template images into ./{_TEMPLATES_DIRNAME}/")
        except Exception as exc:
            log_warning(f"Couldn't bundle template images: {exc} — saving the original JSON")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
