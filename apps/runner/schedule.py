"""Scheduled starts: the Runner presses Start by itself at set times of day."""
from __future__ import annotations

import datetime
import re
import threading
import time
from typing import List, Optional

from src.utils import LOG_KIND_RUN, log_info, log_warning

# A scheduled time fires if the Runner notices it within this window — the
# watcher wakes every few seconds, and a PC busy for a moment must not skip a day.
FIRE_WINDOW_S = 120
_POLL_S = 5.0
_TIME_RE = re.compile(r"^\s*([01]?\d|2[0-3])[:.h]([0-5]\d)\s*$")


def parse_times(raw) -> Optional[List[str]]:
    """``"5:05, 17:05"`` → ``["05:05", "17:05"]`` (sorted, unique).

    Accepts a list or a comma/space separated string; ``None`` when any entry
    is not a valid ``HH:MM`` — the caller refuses the whole edit then.
    """
    items = raw if isinstance(raw, list) else re.split(r"[,;\s]+", str(raw or ""))
    out = set()
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        m = _TIME_RE.match(item)
        if not m:
            return None
        out.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    return sorted(out)


def next_start(times: List[str], now: Optional[datetime.datetime] = None) -> Optional[float]:
    """Epoch seconds of the next of *times* (``HH:MM``) after *now*."""
    if not times:
        return None
    now = now or datetime.datetime.now()
    best = None
    for t in times:
        hh, mm = (int(x) for x in t.split(":"))
        cand = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if cand <= now:
            cand += datetime.timedelta(days=1)
        if best is None or cand < best:
            best = cand
    return best.timestamp() if best else None


def due_time(times: List[str], now: datetime.datetime, fired: set) -> Optional[str]:
    """The scheduled time that is due at *now* and has not fired today, if any."""
    for t in times:
        hh, mm = (int(x) for x in t.split(":"))
        at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        key = f"{now.date().isoformat()} {t}"
        if key in fired:
            continue
        if 0 <= (now - at).total_seconds() < FIRE_WINDOW_S:
            return t
    return None


class ScheduleMixin:
    """Start the full run at the times in Settings → Schedule, every day."""

    def _schedule_cfg(self) -> dict:
        raw = (self._runner_config or {}).get("schedule")
        raw = raw if isinstance(raw, dict) else {}
        times = parse_times(raw.get("times") or []) or []
        return {"enabled": bool(raw.get("enabled")) and bool(times), "times": times}

    def _schedule_payload(self) -> dict:
        cfg = self._schedule_cfg()
        nxt = next_start(cfg["times"]) if cfg["enabled"] else None
        return {**cfg, "next": nxt}

    def get_schedule(self) -> dict:
        return self._schedule_payload()

    def set_schedule(self, enabled, times) -> dict:
        """Turn scheduled starts on/off and set their times (``"05:05, 17:05"``).
        Returns ``{ok, error, schedule}``; saved in this workflow's Runner config."""
        parsed = parse_times(times)
        if parsed is None:
            return {"ok": False, "error": "Use 24-hour times like 05:05, 17:30",
                    "schedule": self._schedule_payload()}
        want = bool(enabled) and bool(parsed)
        with self._runner_config_lock:
            ok = self._persist_runner_config({("schedule",): {"enabled": want, "times": parsed}})
        if ok:
            self._schedule_fired = set()
            if want:
                log_info(f"⏰ Scheduled start every day at {', '.join(parsed)}", kind=LOG_KIND_RUN)
        payload = self._schedule_payload()
        self._push("schedule_state", payload)
        error = "" if ok else "Couldn't save the schedule"
        if ok and bool(enabled) and not parsed:
            error = "Add at least one time"
        return {"ok": ok, "error": error, "schedule": payload}

    def _start_schedule_watch(self) -> None:
        self._schedule_fired = set()
        threading.Thread(target=self._schedule_watch, daemon=True).start()

    def _schedule_watch(self) -> None:
        while not getattr(self, "_closing", False):
            time.sleep(_POLL_S)
            try:
                self._schedule_tick(datetime.datetime.now())
            except Exception as exc:  # the watcher must outlive one bad tick
                log_warning(f"Scheduled start check failed: {exc}")

    def _schedule_tick(self, now: datetime.datetime) -> bool:
        """Fire a due scheduled start. Returns True when a run was started."""
        cfg = self._schedule_cfg()
        if not cfg["enabled"] or not self.flow:
            return False
        fired = getattr(self, "_schedule_fired", None)
        if fired is None:
            fired = self._schedule_fired = set()
        due = due_time(cfg["times"], now, fired)
        if not due:
            return False
        fired.add(f"{now.date().isoformat()} {due}")
        if self._run_live():
            log_warning(f"⏰ {due}: a run is still going — today's scheduled start is skipped",
                        kind=LOG_KIND_RUN)
            self._push("schedule_state", self._schedule_payload())
            return False
        log_info(f"⏰ Scheduled start ({due})", kind=LOG_KIND_RUN)
        started = bool(self.start())
        self._push("schedule_state", self._schedule_payload())
        return started
