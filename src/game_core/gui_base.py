"""GUI adapter base class for automation frontends."""

from typing import Any, Dict

from src.game_core.activity import Activity


class GUIBase:
    """Base class for creating GUI interfaces."""

    def __init__(self, automation):
        self.automation = automation
        self._setup_callbacks()

    def _setup_callbacks(self):
        """Setup default callbacks to update GUI."""
        self.automation.register_callback("on_start", self.on_automation_start)
        self.automation.register_callback("on_stop", self.on_automation_stop)
        self.automation.register_callback("on_activity_start", self.on_activity_start)
        self.automation.register_callback("on_activity_complete", self.on_activity_complete)
        self.automation.register_callback("on_activity_failed", self.on_activity_failed)
        self.automation.register_callback("on_progress", self.on_progress_update)
        self.automation.register_callback("on_error", self.on_error)
        self.automation.register_callback("on_status_change", self.on_status_change)

    def on_automation_start(self):
        """Called when automation starts."""
        pass

    def on_automation_stop(self):
        """Called when automation stops."""
        pass

    def on_activity_start(self, activity: Activity):
        """Called when an activity starts."""
        pass

    def on_activity_complete(self, activity: Activity, success: bool):
        """Called when an activity completes."""
        pass

    def on_activity_failed(self, activity: Activity, error: Exception):
        """Called when an activity fails."""
        pass

    def on_progress_update(self, activity_id: str, progress: float):
        """Called when progress updates."""
        pass

    def on_error(self, error: Exception):
        """Called on error."""
        pass

    def on_status_change(self, status: Dict[str, Any]):
        """Called on status change."""
        pass

    def start(self):
        """Start the GUI - implement in subclass."""
        raise NotImplementedError("Subclasses must implement start()")

    def stop(self):
        """Stop the GUI."""
        self.automation.stop()
