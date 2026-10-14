"""The Designer's Python API, split by area and mixed into WorkflowDesignerAPI.

Each module holds one mixin; they share the API's state (``self._window``,
``self.controller``, ``self._engine`` …) and call each other through ``self``,
so they only make sense combined in ``apps/workflow_designer.py``. Imports are
absolute (``designer.*``) because the apps run with ``apps/`` on ``sys.path``
— from source, from tests and in the frozen build alike.
"""
