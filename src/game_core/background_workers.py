"""Background-activity worker threads for game automations.

Each background activity loops in its own daemon thread, calling
``handle_activity_<id>`` every ``poll_interval`` seconds. The manager owns the
threads and talks to the game only through three injected callables
(``handler_resolver``, ``is_paused``, ``ensure_ready``) so it never references
the game object directly.
"""
import threading
from typing import Callable, Dict, Iterable, Optional

from src.game_core.activity import Activity, ActivityStatus
from src.utils import log_error, log_info


class BackgroundWorkerManager:
    """Owns and supervises one worker thread per background activity."""

    def __init__(
        self,
        handler_resolver: Callable[[str], Optional[Callable]],
        is_paused: Callable[[], bool],
        ensure_ready: Callable[[], bool],
    ) -> None:
        self._resolve_handler = handler_resolver
        self._is_paused = is_paused
        self._ensure_ready = ensure_ready
        self._threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def _worker(self, activity: Activity, stop_event: threading.Event) -> None:
        """Worker loop: call the handler each tick until stopped.

        Handler exceptions are caught so one bad tick can't kill the thread.
        """
        handler = self._resolve_handler(activity.id)
        if handler is None:
            log_error(
                f"Background activity '{activity.id}' has no handler "
                f"(expected method 'handle_activity_{activity.id}'); aborting"
            )
            return
        log_info(f"[bg] Background activity started: {activity.name}")
        activity.status = ActivityStatus.RUNNING
        try:
            while not stop_event.is_set():
                # Honour pause: skip ticks while the main loop is paused.
                if not self._is_paused():
                    try:
                        handler()
                        activity.execution_count += 1
                    except Exception as e:
                        # Swallow errors so a bug in one tick does not kill
                        # the whole background loop.
                        log_error(f"[bg] Error in background '{activity.id}': {e}")
                # Sleep on the stop event so we wake immediately on disable.
                if stop_event.wait(timeout=max(0.05, activity.poll_interval)):
                    break
        finally:
            activity.status = ActivityStatus.PENDING
            log_info(f"[bg] Background activity stopped: {activity.name}")

    def start(self, activity: Activity) -> bool:
        """Start a worker thread for ``activity``.

        Idempotent: returns ``True`` if a worker is now running, ``False`` if
        the activity is not a background one. Ensures ADB + capture are alive
        first so the worker has frames to look at.
        """
        if not activity.background:
            return False
        # No-op when the main automation loop is already running.
        self._ensure_ready()
        with self._lock:
            existing = self._threads.get(activity.id)
            if existing is not None and existing.is_alive():
                return True
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._worker,
                args=(activity, stop_event),
                name=f"bg-{activity.id}",
                daemon=True,
            )
            self._stop_events[activity.id] = stop_event
            self._threads[activity.id] = thread
            thread.start()
        return True

    def stop(self, activity: Activity, join_timeout: float = 0.5) -> None:
        """Signal a single worker to stop and wait briefly for it."""
        with self._lock:
            stop_event = self._stop_events.pop(activity.id, None)
            thread = self._threads.pop(activity.id, None)
        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)

    def start_all(self, activities: Iterable[Activity]) -> None:
        """Start workers for every enabled background activity."""
        for activity in activities:
            if activity.background and activity.enabled:
                self.start(activity)

    def stop_all(self, join_timeout: float = 0.5) -> None:
        """Signal every worker to stop, then join once."""
        with self._lock:
            for stop_event in self._stop_events.values():
                stop_event.set()
            threads = list(self._threads.values())
            self._stop_events.clear()
            self._threads.clear()
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=join_timeout)

    def is_running(self, activity_id: str) -> bool:
        """Whether a given background activity currently has a live worker."""
        thread = self._threads.get(activity_id)
        return thread is not None and thread.is_alive()
