"""Pin Activity serialization + settings-merge semantics."""
import unittest

from tests import _bootstrap  # noqa: F401  (sys.path side effect)
from src.game_core.activity import Activity, ActivityStatus


class TestActivitySettings(unittest.TestCase):
    def test_to_settings_dict_minimal(self):
        act = Activity(id="daily", name="Daily")
        data = act.to_settings_dict()
        self.assertEqual(data["id"], "daily")
        self.assertTrue(data["enabled"])
        self.assertEqual(data["poll_interval"], 1.0)
        # No custom values -> no "custom" key.
        self.assertNotIn("custom", data)

    def test_to_settings_dict_includes_custom(self):
        act = Activity(id="speed", name="Speed", custom_values={"scale": 2.0})
        data = act.to_settings_dict()
        self.assertEqual(data["custom"], {"scale": 2.0})

    def test_from_settings_dict_without_defaults(self):
        data = {"id": "farm", "enabled": False, "poll_interval": 2.5}
        act = Activity.from_settings_dict(data)
        self.assertIsNotNone(act)
        self.assertEqual(act.id, "farm")
        self.assertFalse(act.enabled)
        self.assertEqual(act.poll_interval, 2.5)

    def test_from_settings_dict_merges_into_defaults(self):
        default = Activity(
            id="speed", name="Speedhack", enabled=True, poll_interval=1.0,
            custom_settings=[{"key": "scale", "default": 1.0}],
            custom_values={"scale": 1.0},
        )
        data = {"id": "speed", "enabled": False, "poll_interval": 0.5,
                "custom": {"scale": 3.0}}
        merged = Activity.from_settings_dict(data, defaults=default)
        # Same object is mutated and returned (preserves name/description/etc).
        self.assertIs(merged, default)
        self.assertFalse(merged.enabled)
        self.assertEqual(merged.poll_interval, 0.5)
        self.assertEqual(merged.custom_values["scale"], 3.0)
        self.assertEqual(merged.name, "Speedhack")

    def test_from_settings_dict_rejects_missing_id(self):
        self.assertIsNone(Activity.from_settings_dict({}))
        self.assertIsNone(Activity.from_settings_dict({"enabled": True}))

    def test_round_trip_preserves_enabled_and_interval(self):
        act = Activity(id="x", name="X", enabled=False, poll_interval=4.0,
                       custom_values={"k": "v"})
        restored = Activity.from_settings_dict(act.to_settings_dict())
        self.assertEqual(restored.enabled, act.enabled)
        self.assertEqual(restored.poll_interval, act.poll_interval)

    def test_reset_clears_runtime_state(self):
        act = Activity(id="x", name="X")
        act.status = ActivityStatus.FAILED
        act.progress = 80.0
        act.error_message = "boom"
        act.reset()
        self.assertEqual(act.status, ActivityStatus.PENDING)
        self.assertEqual(act.progress, 0.0)
        self.assertIsNone(act.error_message)


if __name__ == "__main__":
    unittest.main()
