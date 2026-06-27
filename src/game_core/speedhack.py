"""Reusable speedhack integration for game automations."""

from typing import Any, Optional

from src.game_core.activity import Activity
from src.game_core.frida_speedhack import FridaSpeedhackManager
from src.utils import log_info, log_success, log_warning


class SpeedhackMixin:
    """Mixin that adds a reusable Frida speedhack background activity.

    Usage:
        class MyGame(SpeedhackMixin, BaseGameAutomation):
            PACKAGE_NAME = "com.example.game"

            def __init__(self):
                super().__init__()
                self.setup_speedhack()

            def define_activities(self):
                return [self.speedhack_activity(), ...]
    """

    SPEEDHACK_ACTIVITY_ID = "speedhack"
    SPEEDHACK_MIN = 0.5
    SPEEDHACK_MAX = 5.0
    SPEEDHACK_DEFAULT = 1.0
    SPEEDHACK_POLL_INTERVAL = 999999.0

    def setup_speedhack(
        self,
        package: Optional[str] = None,
        time_scale: float = 1.0,
    ) -> None:
        """Initialize the shared Frida speedhack manager for this game."""
        package_name = package or getattr(self, "PACKAGE_NAME", None) or getattr(self, "package_name", None)
        if not package_name:
            raise ValueError("setup_speedhack() requires PACKAGE_NAME or package")
        self.speedhack = FridaSpeedhackManager(
            package=package_name,
            time_scale=time_scale,
        )
        # Allow the manager to read the selected ADB device dynamically.
        self.speedhack.adb_controller = getattr(self, "adb", None)
        self.speedhack_enabled = False

    def speedhack_activity(
        self,
        enabled: bool = False,
        min_speed: Optional[float] = None,
        max_speed: Optional[float] = None,
        default_speed: Optional[float] = None,
    ) -> Activity:
        """Return the standard Speedhack activity declaration."""
        min_value = self.SPEEDHACK_MIN if min_speed is None else min_speed
        max_value = self.SPEEDHACK_MAX if max_speed is None else max_speed
        default_value = self.SPEEDHACK_DEFAULT if default_speed is None else default_speed
        return Activity(
            id=self.SPEEDHACK_ACTIVITY_ID,
            name="Speedhack",
            description="Tăng tốc game bằng Frida (cần root + frida-inject). Tự động tắt khi dừng.",
            enabled=enabled,
            background=True,
            poll_interval=self.SPEEDHACK_POLL_INTERVAL,
            custom_settings=[
                {
                    "key": "speed",
                    "type": "slider",
                    "label": "Speed",
                    "min": min_value,
                    "max": max_value,
                    "step": 0.1,
                    "default": default_value,
                    "suffix": "x",
                },
            ],
        )

    @property
    def speedhack_scale(self) -> float:
        """Current speed multiplier, read from the persisted custom setting."""
        activity_map = getattr(self, "_activity_map", {})
        activity = activity_map.get(self.SPEEDHACK_ACTIVITY_ID)
        if activity:
            value = activity.custom_values.get("speed")
            if value is not None:
                return float(value)
        return self.SPEEDHACK_DEFAULT

    def apply_custom_setting(self, activity_id: str, key: str, value: Any) -> None:
        """Apply speed changes immediately while the speedhack is active."""
        super().apply_custom_setting(activity_id, key, value)
        if activity_id != self.SPEEDHACK_ACTIVITY_ID:
            return
        if key == "speed":
            if getattr(self, "speedhack_enabled", False) and self.speedhack.available:
                log_info(f"[speedhack] applying new scale {value}")
                self.speedhack.set_scale(float(value))

    def set_activity_enabled(self, activity_id: str, enabled: bool):
        """Reset the speedhack when its background task is disabled."""
        super().set_activity_enabled(activity_id, enabled)
        if activity_id != self.SPEEDHACK_ACTIVITY_ID:
            return
        if enabled:
            self.speedhack_enabled = True
        else:
            self.speedhack_enabled = False
            self._disable_speedhack()

    def handle_activity_speedhack(self) -> bool:
        """Background one-shot: inject once, skip if already active."""
        if self.speedhack.active:
            return True
        self.speedhack_enabled = True
        return self._apply_speedhack()

    def _apply_speedhack(self) -> bool:
        if not getattr(self, "speedhack_enabled", False):
            return False
        if not self.speedhack.available:
            log_warning("[speedhack] frida-inject binary not found in vendor/frida/")
            return False
        ok = self.speedhack.set_scale(self.speedhack_scale)
        if ok:
            log_success(f"[speedhack] enabled at {self.speedhack_scale}x")
        else:
            log_warning("[speedhack] could not set time scale")
        return ok

    def _disable_speedhack(self) -> None:
        speedhack = getattr(self, "speedhack", None)
        if speedhack is None:
            return
        try:
            if speedhack.active:
                speedhack.set_scale(1.0)
            speedhack.detach()
        except Exception as exc:
            log_warning(f"[speedhack] error while disabling: {exc}")
        finally:
            log_info("[speedhack] disabled / restored normal speed")

    def stop(self) -> None:
        self._disable_speedhack()
        super().stop()
