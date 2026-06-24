"""Activity collection + bookkeeping (no execution).

Owns the activity list, id->Activity map, run order, and current pointer.
Execution/callbacks stay on BaseGameAutomation (coupled to the game instance).
"""
from typing import Dict, List, Optional

from src.game_core.activity import Activity


class ActivityManager:
    """Holds and manages a game's activities (no execution, no I/O)."""

    def __init__(self) -> None:
        self.activities: List[Activity] = []
        self.activity_map: Dict[str, Activity] = {}
        self.activity_order: List[str] = []
        self.current_activity: Optional[Activity] = None

    def set_activities(self, activities: List[Activity]) -> None:
        """Install the activity list.

        Seeds each activity's ``custom_values`` from its declared
        ``custom_settings`` defaults (for freshly added settings), rebuilds the
        id map, and computes the sequential run order (enabled, non-background).
        """
        for act in activities:
            for spec in act.custom_settings:
                key = spec.get("key")
                if key is None or key in act.custom_values:
                    continue
                act.custom_values[key] = spec.get("default")
        self.activities = activities
        self.activity_map = {act.id: act for act in activities}
        self.activity_order = [
            act.id for act in activities if act.enabled and not act.background
        ]

    def get(self, activity_id: str) -> Optional[Activity]:
        """Return the activity with ``activity_id`` or ``None``."""
        return self.activity_map.get(activity_id)

    def enable_in_order(self, activity_id: str, enabled: bool) -> None:
        """Add/remove a sequential activity from the run order."""
        if enabled and activity_id not in self.activity_order:
            self.activity_order.append(activity_id)
        elif not enabled and activity_id in self.activity_order:
            self.activity_order.remove(activity_id)

    def set_order(self, order: List[str]) -> bool:
        """Replace the run order. Returns ``False`` if any id is unknown."""
        invalid = [aid for aid in order if aid not in self.activity_map]
        if invalid:
            return False
        self.activity_order = order
        return True

    def reset_all(self) -> None:
        """Reset every activity's runtime state to pending."""
        for activity in self.activities:
            activity.reset()
