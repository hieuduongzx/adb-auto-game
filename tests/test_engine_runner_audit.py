"""Lifecycle failures that previously gave Runner a misleading result."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

import pytest

from src.workflow import engine as E


def engine():
    with patch.object(E, "ADBGameAutomation"):
        result = E.WorkflowEngine()
    result._ensure_ready = Mock(return_value=True)
    return result


def test_background_iteration_clears_failure_from_previous_iteration():
    eng = engine()
    statuses, contexts = [], []
    stop = threading.Event()
    act = {"id": "bg", "vars": [], "pollInterval": 0.05, "graph": {}}

    def graph(_graph):
        contexts.append((eng._branch_failed, eng._reached_end, eng._try_chain_mode))
        if len(contexts) == 1:
            eng._branch_failed = True
            eng._try_chain_mode = True
        else:
            eng._reached_end = True
        return not eng._branch_failed

    eng._run_graph = graph
    def complete(_act, ok):
        statuses.append(ok)
        if len(statuses) == 2:
            stop.set()
    eng.callbacks["on_activity_complete"].append(complete)
    eng._bg_loop(act, stop)
    assert contexts == [(False, False, False), (False, False, False)]
    assert statuses == [False, True]


def test_background_dead_end_is_not_reported_as_success():
    eng = engine()
    statuses, stop = [], threading.Event()
    act = {"id": "bg", "vars": [], "pollInterval": 0.05, "graph": {}}

    def graph(_graph):
        return True  # Walker returned without reaching End.

    eng._run_graph = graph
    def complete(_act, ok):
        statuses.append(ok)
        stop.set()
    eng.callbacks["on_activity_complete"].append(complete)
    eng._bg_loop(act, stop)
    assert statuses == [False]


def test_activity_exception_emits_failed_completion_for_runner():
    eng = engine()
    act = {"id": "a", "name": "A"}
    statuses = []
    eng._run_activity_attempts = Mock(side_effect=ValueError("bad runtime parameter"))
    eng.callbacks["on_activity_complete"].append(lambda item, ok: statuses.append((item, ok)))
    assert eng._run_activity(act) is False
    assert statuses == [(act, False)]


@pytest.mark.parametrize("first", ["start", "start_activity", "start_graph"])
def test_engine_serializes_all_start_entrypoints_during_slow_readiness(first):
    eng = engine()
    eng.flow = {"activities": [{"id": "a", "vars": [], "graph": {}}]}
    entered, release, finish = threading.Event(), threading.Event(), threading.Event()
    def ready():
        entered.set()
        assert release.wait(3)
        return True
    eng._ensure_ready.side_effect = ready
    eng._start_speedhack = Mock()
    eng.start_all_background = Mock()
    eng._run_sequence = lambda: finish.wait(3)
    eng._run_single_activity = lambda _act: finish.wait(3)
    eng._run_graph_from_node = lambda *_args: finish.wait(3)
    requests = {"start": lambda: eng.start(), "start_activity": lambda: eng.start_activity("a"),
                "start_graph": lambda: eng.start_graph({}, "s")}
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(requests[first])
            try:
                assert entered.wait(3)
                assert all(call() is False for call in requests.values())
            finally:
                release.set()
            assert pending.result(timeout=3) is True
        assert eng._ensure_ready.call_count == 1
    finally:
        release.set()
        finish.set()
        if eng._seq_thread:
            eng._seq_thread.join(timeout=3)


def test_failed_readiness_releases_engine_start_reservation():
    eng = engine()
    eng._ensure_ready.return_value = False
    assert eng.start() is False
    assert eng._run_start_lock.locked() is False


def test_disabling_background_stops_after_current_action_and_prevents_worker_overlap():
    eng = engine()
    entered, release, continued = threading.Event(), threading.Event(), threading.Event()
    graph = {"nodes": [{"id": "s", "type": "start"}, {"id": "block", "type": "tap"},
                       {"id": "after", "type": "tap"}, {"id": "e", "type": "end"}],
             "edges": [{"from": a, "to": b} for a, b in [("s", "block"), ("block", "after"), ("after", "e")]]}
    act = {"id": "bg", "vars": [], "graph": graph, "pollInterval": 0.05}
    def tap(node, _params):
        if node["id"] == "block":
            entered.set()
            assert release.wait(3)
        else:
            continued.set()
        return True
    eng._actions["tap"] = tap
    eng._run_action_with_retry = lambda node, params, handler: handler(node, params)
    eng.running = True
    eng.start_background(act)
    worker = eng._bg_threads["bg"]
    try:
        assert entered.wait(3)
        eng.stop_background("bg")
        assert eng.background_stopping("bg") is True
        assert eng.start_background(act) is False
        assert eng.running is True  # Wait for the outstanding action to return.
    finally:
        release.set()
        worker.join(timeout=3)
        eng._stop.set()
    assert not worker.is_alive()
    assert not continued.is_set()
    assert not eng.background_stopping("bg")
    assert eng.running is False


def test_disabling_paused_background_does_not_resume_or_execute_its_graph():
    eng = engine()
    act = {"id": "bg", "vars": [], "pollInterval": 0.05, "graph": {}}
    eng._run_graph = Mock()
    eng.running = True
    eng.pause()
    assert eng.start_background(act)
    worker = eng._bg_threads["bg"]
    try:
        eng.stop_background("bg")
        worker.join(timeout=3)
        assert not worker.is_alive()
        eng._run_graph.assert_not_called()
        assert eng.is_paused()
        assert eng.running is False
    finally:
        eng._stop.set()
        eng._pause.set()
        worker.join(timeout=3)
