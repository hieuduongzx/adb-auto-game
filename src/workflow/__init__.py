"""JSON-driven workflow engine for ADB auto-game.

A *workflow* is a plain JSON document describing automation as a list of
**activities**, each holding a **node graph** (tap, swipe, wait, if_image, …).
Activities run in one of two modes:

* ``sequence``   — run the graph once, in order, as part of the main run.
* ``background`` — loop the graph in its own thread every ``pollInterval`` s;
  can be toggled on/off while sequence activities run.

Produced by Macro2k Designer (``apps/workflow_designer.py``) and consumed
by the Runner (``apps/workflow_runner.py``).

Layout:

* ``engine``      — :class:`WorkflowEngine`: loading, run lifecycle, graph walk.
* ``catalog``     — ``NODE_TYPES``, the node catalog the walk dispatches on.
* ``nodes/``      — node handlers by family, mixed into the engine
  (``actions``, ``conditions``, ``vision``, ``emulator``, ``win32``,
  ``speedhack``).
* ``logs``        — the engine's log helpers (step detail by default).
* ``local_vars``  — Designer-only variable overrides.
"""
from . import local_vars
from .engine import WorkflowEngine, NODE_TYPES

__all__ = ["WorkflowEngine", "NODE_TYPES", "local_vars"]
