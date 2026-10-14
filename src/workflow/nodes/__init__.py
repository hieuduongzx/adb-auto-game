"""Node handlers, grouped by family and mixed into :class:`WorkflowEngine`.

Each module holds one mixin. The mixins share the engine's state (``self.auto``,
``self._vars``, ``self._stop`` …) and call each other's helpers through ``self``,
so they are only meaningful combined in ``src.workflow.engine.WorkflowEngine``.
"""
from src.workflow.nodes.actions import ActionNodes
from src.workflow.nodes.conditions import ConditionNodes
from src.workflow.nodes.emulator import EmulatorNodes
from src.workflow.nodes.speedhack import SpeedhackSupport
from src.workflow.nodes.vision import VisionHelpers
from src.workflow.nodes.win32 import Win32Nodes

__all__ = ["ActionNodes", "ConditionNodes", "EmulatorNodes", "SpeedhackSupport",
           "VisionHelpers", "Win32Nodes"]
