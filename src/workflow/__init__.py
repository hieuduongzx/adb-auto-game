"""JSON-driven workflow engine for ADB auto-game.

A *workflow* is a plain JSON document describing automation as a list of
**activities**, each holding a stack of **blocks** (tap, swipe, wait,
tap_image, …). Activities run in one of two modes, mirroring
``src/game_core/base_game.py``:

* ``sequence``   — run once, in order, as part of the main run.
* ``background`` — loop in their own thread, polling every ``pollInterval``
  seconds; can be toggled on/off while sequence activities run.

The same JSON is produced by the Workflow tab in ``tools/dev_helper.py`` and
consumed by the standalone runner GUI (``src/gui/workflow_runner_gui.py``).
"""
from .engine import WorkflowEngine, NODE_TYPES

__all__ = ["WorkflowEngine", "NODE_TYPES"]
