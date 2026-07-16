"""JSON-driven workflow engine for ADB auto-game.

A *workflow* is a plain JSON document describing automation as a list of
**activities**, each holding a **node graph** (tap, swipe, wait, if_image, …).
Activities run in one of two modes:

* ``sequence``   — run the graph once, in order, as part of the main run.
* ``background`` — loop the graph in its own thread every ``pollInterval`` s;
  can be toggled on/off while sequence activities run.

Produced by Macro2k Designer (``apps/workflow_designer.py``) and consumed
by the Runner (``apps/workflow_runner.py``).
"""
from .engine import WorkflowEngine, NODE_TYPES

__all__ = ["WorkflowEngine", "NODE_TYPES"]
