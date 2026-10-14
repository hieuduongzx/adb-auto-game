"""The Runner's Python API, split by area and mixed into WorkflowRunnerAPI.

Each module holds one mixin; they share the API's state (``self.engine``,
``self.flow``, ``self._window`` …) and call each other through ``self``, so
they only make sense combined in ``apps/workflow_runner.py``. Imports are
absolute (``runner.*``) because the apps run with ``apps/`` on ``sys.path``
— from source, from tests and in the frozen builds alike.
"""
