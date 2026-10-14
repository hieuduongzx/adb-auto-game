"""Scheduled starts: parse times, find the next one, fire each once a day."""
import datetime
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps"))

from runner import schedule as SC  # noqa: E402
from runner.schedule import ScheduleMixin  # noqa: E402


def test_times_parse_sorted_unique_and_refuse_garbage():
    assert SC.parse_times("17:05, 5:05 ; 05.05 17h05") == ["05:05", "17:05"]
    assert SC.parse_times(["23:59", "0:00"]) == ["00:00", "23:59"]
    assert SC.parse_times("") == []
    assert SC.parse_times("25:00") is None
    assert SC.parse_times("5pm") is None


def test_next_start_rolls_over_to_tomorrow():
    now = datetime.datetime(2026, 10, 15, 18, 0)
    nxt = datetime.datetime.fromtimestamp(SC.next_start(["05:05", "17:05"], now))
    assert nxt == datetime.datetime(2026, 10, 16, 5, 5)
    nxt = datetime.datetime.fromtimestamp(SC.next_start(["05:05", "19:30"], now))
    assert nxt == datetime.datetime(2026, 10, 15, 19, 30)
    assert SC.next_start([], now) is None


class _Runner(ScheduleMixin):
    def __init__(self, cfg):
        self._runner_config = {"schedule": cfg}
        self._runner_config_lock = threading.RLock()
        self.flow = {"name": "G"}
        self._push = Mock()
        self.start = Mock(return_value=True)
        self._live = False

    def _run_live(self):
        return self._live

    def _persist_runner_config(self, changes, remove=()):
        for path, value in changes.items():
            self._runner_config[path[0]] = value
        return True


def test_a_due_time_fires_once_per_day_inside_its_window():
    r = _Runner({"enabled": True, "times": ["05:05"]})
    day = datetime.datetime(2026, 10, 15, 5, 5, 30)
    assert r._schedule_tick(day) is True
    assert r._schedule_tick(day + datetime.timedelta(seconds=20)) is False   # same day: once
    assert r._schedule_tick(datetime.datetime(2026, 10, 15, 5, 8)) is False   # outside window
    assert r._schedule_tick(datetime.datetime(2026, 10, 16, 5, 5, 10)) is True  # next day again
    assert r.start.call_count == 2


def test_a_live_run_skips_the_slot_and_disabled_never_fires():
    r = _Runner({"enabled": True, "times": ["05:05"]})
    r._live = True
    assert r._schedule_tick(datetime.datetime(2026, 10, 15, 5, 5)) is False
    r._live = False
    assert r._schedule_tick(datetime.datetime(2026, 10, 15, 5, 6)) is False   # that slot is spent
    r.start.assert_not_called()
    off = _Runner({"enabled": False, "times": ["05:05"]})
    assert off._schedule_tick(datetime.datetime(2026, 10, 15, 5, 5)) is False


def test_set_schedule_validates_and_reports_next_start():
    r = _Runner({})
    bad = r.set_schedule(True, "7pm")
    assert bad["ok"] is False and "24-hour" in bad["error"]
    good = r.set_schedule(True, "17:05, 05:05")
    assert good["ok"] and good["schedule"]["times"] == ["05:05", "17:05"] and good["schedule"]["next"]
    empty = r.set_schedule(True, "")
    assert empty["schedule"]["enabled"] is False and empty["error"] == "Add at least one time"
