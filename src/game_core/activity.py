"""Activity model objects shared by game automations."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ActivityStatus(Enum):
    """Status of an activity."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Activity:
    """Represents an automation activity/task.

    There are two execution modes:

    * **Sequential** (default): the activity runs once, in order, as part of
      the main automation loop in ``BaseGameAutomation.process_game_actions``.
    * **Background** (``background=True``): the activity loops in its own
      thread, polling every ``poll_interval`` seconds, and can be toggled on
      and off at runtime via ``BaseGameAutomation.set_activity_enabled`` while
      the main loop is running.

    ``custom_settings`` lets a subclass declare extra per-activity UI widgets
    (sliders, spin boxes) beyond the built-in ``poll_interval``.
    """

    id: str
    name: str
    description: str = ""
    enabled: bool = True
    status: ActivityStatus = ActivityStatus.PENDING
    error_message: Optional[str] = None
    execution_count: int = 0
    max_retries: int = 3
    background: bool = False
    poll_interval: float = 1.0
    custom_settings: List[Dict[str, Any]] = field(default_factory=list)
    custom_values: Dict[str, Any] = field(default_factory=dict)

    def to_settings_dict(self) -> Dict[str, Any]:
        """Export only user-tweakable settings for persistence."""
        data: Dict[str, Any] = {
            "id": self.id,
            "enabled": self.enabled,
            "poll_interval": self.poll_interval,
        }
        if self.custom_values:
            data["custom"] = dict(self.custom_values)
        return data

    @classmethod
    def from_settings_dict(
        cls,
        data: Dict[str, Any],
        defaults: Optional["Activity"] = None,
    ) -> Optional["Activity"]:
        """Build an activity with persisted settings applied."""
        if not data or not data.get("id"):
            return None
        if defaults is None:
            return cls(
                id=data["id"],
                name=data.get("name", ""),
                description=data.get("description", ""),
                enabled=bool(data.get("enabled", True)),
                max_retries=int(data.get("max_retries", 3)),
                background=bool(data.get("background", False)),
                poll_interval=float(data.get("poll_interval", 1.0)),
            )

        defaults.enabled = bool(data.get("enabled", defaults.enabled))
        defaults.poll_interval = float(data.get("poll_interval", defaults.poll_interval))
        persisted_custom = data.get("custom", {})
        if isinstance(persisted_custom, dict):
            for key, value in persisted_custom.items():
                defaults.custom_values[key] = value
        return defaults

    def reset(self):
        """Reset runtime state before a retry or fresh run."""
        self.status = ActivityStatus.PENDING
        self.error_message = None
