"""Paths and helpers shared by the Designer's API mixins (apps/designer/*)."""
from __future__ import annotations

import os

from src.utils import (
    bundle_dir,
    data_root,
    is_frozen,
    sanitize_name,
    ts_stamp,
)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))

# In a frozen build, writable resources (data/) live under data_root() — next to
# the app when writable, else %LOCALAPPDATA% (read-only Program Files install).
if is_frozen():
    _PROJECT_ROOT = data_root()

# Bundled HTML: ``apps/web`` from source, ``<_MEIPASS>/web`` when frozen.
_WEB_DIR = (os.path.join(bundle_dir(), "web") if is_frozen()
            else os.path.join(os.path.dirname(os.path.dirname(__file__)), "web"))
# Default home for saved workflows. Each workflow lives in its own subfolder
# ``workflows/<name>/<name>.json`` (with its ``templates/`` bundle alongside),
# next to the .exe in a frozen build or in the repo root from source.
_WORKFLOWS_DIR = os.path.join(_PROJECT_ROOT, "workflows")
# Transient flow written for the "Run GUI" handoff to the runner.
_RUN_TMP_DIR = os.path.join(_WORKFLOWS_DIR, "_run")
# Convention: a saved workflow.json is paired with a sibling assets folder of
# this name, so the pair (json + folder) is a self-contained, movable bundle —
# the unit we later package into an .exe. Image nodes reference their templates
# relative to the json as ``<_TEMPLATES_DIRNAME>/<file>``.
_TEMPLATES_DIRNAME = "templates"
# Node params whose value is a template image path (kept in sync with the
# ``t:"tpl"`` fields in workflow_designer.html — all use the key "template").
_TEMPLATE_PARAM_KEYS = ("template",)
# Node params whose value is a *list* of template paths (``t:"tpls"`` fields —
# the "…_any" multi-image OR nodes; key "templates").
_TEMPLATE_LIST_PARAM_KEYS = ("templates", "images")
# How long Start game waits for a freshly-booted emulator's ADB before giving
# up (a cold LDPlayer/MuMu boot can take a minute or more).
_START_GAME_ADB_WAIT = 180.0


def _sanitize_name(raw: str) -> str:
    return sanitize_name(raw)


def _ts() -> str:
    return ts_stamp()
