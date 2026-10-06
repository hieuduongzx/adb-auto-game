"""Runner regressions with no window, ADB connection, or real workflow writes."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from apps.workflow_runner import WorkflowRunnerAPI


def runner(tmp_path, controller="adb"):
    api = WorkflowRunnerAPI.__new__(WorkflowRunnerAPI)
    api.flow = {"name": "Audit", "controller": controller, "activities": [{
        "id": "a", "name": "A", "enabled": True, "pollInterval": 1,
        "maxRetries": 1, "vars": [{"name": "n", "type": "number", "value": 1}],
        "graph": {"nodes": [{"id": "path", "type": "win_launch",
                             "params": {"pathSrc": "custom", "path": "old.exe"}}]},
    }, {"id": "b", "name": "B"}], "win32": {"path": "old.exe"},
        "emulator": {"kind": "ldplayer", "path": "old", "index": 0}}
    api._runner_config = {"keep": {"value": 1}}
    api._runner_config_path = str(tmp_path / "config.json")
    api._runner_config_lock = threading.RLock()
    api._run_request_lock = threading.Lock()
    api._capture_request_lock = threading.Lock()
    api._run_active = False
    api._act_status = {}
    api._run_id = 0
    api._run_scope = None
    api._run_started_at = 0
    api._run_counts = {"completed": 0, "failed": 0, "stopped": 0}
    api._stop_intent = False
    api._run_failed = False
    api._outcome = None
    api._flow_game_path = "old.exe"
    api.flow_path = None
    api._flow_emulator = dict(api.flow["emulator"])
    api._window = None
    api._closing = False
    api._push = Mock()
    api._requirements_payload = Mock(return_value=None)
    api._select_run_device = Mock()
    api._push_bridge_status = Mock()
    api._blocked_by_launch_paths = Mock(return_value=False)
    api.engine = Mock()
    api.engine.is_running.return_value = False
    api.engine.is_paused.return_value = False
    api.engine.background_stopping.return_value = False
    api.engine.speedhack_info.return_value = {"enabled": False, "speed": 2}
    return api


@pytest.mark.parametrize("setter,controller", [
    (lambda a: a.toggle_activity("a", False), "adb"),
    (lambda a: a.set_interval("a", 2), "adb"),
    (lambda a: a.set_activity_retries("a", 3), "adb"),
    (lambda a: a.set_activity_var("a", "n", 2), "adb"),
    (lambda a: a.set_node_runtime_param("path", "path", "new.exe"), "win32"),
    (lambda a: a.set_game_path("new.exe"), "win32"),
    (lambda a: a.set_emulator("mumu", "new", 2), "adb"),
    (lambda a: a.reorder_activities(["b", "a"]), "adb"),
    (lambda a: a.set_capture_backend("adb"), "adb"),
    (lambda a: a.set_speedhack(True, 3), "adb"),
    (lambda a: a.set_speed_scale(3), "adb"),
])
def test_failed_save_is_reported_and_does_not_change_live_values(tmp_path, setter, controller):
    api = runner(tmp_path, controller)
    flow, config = copy.deepcopy(api.flow), copy.deepcopy(api._runner_config)
    api._save_runner_config = Mock(return_value=False)
    result = setter(api)
    assert (result.get("ok") if isinstance(result, dict) else result) is False
    assert api.flow == flow
    assert api._runner_config == config
    api.engine.set_win32_path.assert_not_called()
    api.engine.set_emulator_config.assert_not_called()
    api.engine.configure_speedhack.assert_not_called()
    api.engine.set_speed_scale.assert_not_called()


def test_reorder_deduplicates_ids_and_preserves_missing_activities(tmp_path):
    api = runner(tmp_path)
    assert api.reorder_activities(["b", "b", "unknown"])
    assert [a["id"] for a in api.flow["activities"]] == ["b", "a"]
    assert api._runner_config["order"] == ["b", "a"]


@pytest.mark.parametrize("method", ["start", "run_activity"])
def test_live_run_refuses_new_requests_before_resetting_rows(tmp_path, method):
    api = runner(tmp_path)
    api._run_active = True  # Engine running=False, but on_stop is still unwinding.
    api._act_status = {"a": "completed"}
    assert not getattr(api, method)(*([] if method == "start" else ["a"]))
    api._blocked_by_launch_paths.assert_not_called()
    api.engine.start.assert_not_called()
    api.engine.start_activity.assert_not_called()
    api._push.assert_not_called()
    assert api._act_status == {"a": "completed"}


def test_concurrent_run_requests_do_not_start_two_workers(tmp_path):
    api = runner(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def start(**kwargs):
        entered.set()
        assert release.wait(3)
        return True

    api.engine.start.side_effect = start
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(api.start)
        try:
            assert entered.wait(3)
            second = pool.submit(api.run_activity, "a")
            assert second.result(timeout=1) is False
        finally:
            release.set()
        assert first.result(timeout=3) is True
    api.engine.start_activity.assert_not_called()


def test_preflight_ignores_disconnected_nodes_and_unreachable_calls(tmp_path):
    api = runner(tmp_path, "win32")
    graph = api.flow["activities"][0]["graph"]
    graph["nodes"] += [{"id": "s", "type": "start"}, {"id": "e", "type": "end"},
                       {"id": "c", "type": "call", "params": {"fn": "f"}}]
    graph["edges"] = [{"from": "s", "to": "e", "fromPort": "out"},
                      {"from": "e", "to": "path", "fromPort": "out"}]
    api.flow["functions"] = [{"id": "f", "graph": {"nodes": [
        {"id": "fs", "type": "start"}, {"id": "fp", "type": "win_launch", "params": {}}
    ], "edges": [{"from": "fs", "to": "fp"}]}}]
    assert api._launch_preflight(["a"]) == []
    assert len(api._graph_nodes(["a"])) == 6  # Broad settings scan still includes orphan nodes.
    graph["edges"] = [{"from": "s", "to": "c"}]
    assert api._launch_preflight(["a"])


def test_reachable_scan_handles_deep_calls_without_python_recursion(tmp_path):
    api = runner(tmp_path, "win32")
    def graph(i):
        return {"nodes": [{"id": f"s{i}", "type": "start"},
                          {"id": f"c{i}", "type": "call", "params": {"fn": f"f{i+1}"}}],
                "edges": [{"from": f"s{i}", "to": f"c{i}"}]}
    api.flow["activities"][0]["graph"] = graph(0)
    api.flow["functions"] = [{"id": f"f{i}", "graph": graph(i)} for i in range(1, 1100)]
    assert len(api._graph_nodes(["a"], reachable_only=True)) == 2200


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_nonfinite_runtime_numbers_are_rejected(tmp_path, value):
    api = runner(tmp_path)
    assert api.set_interval("a", value) is False
    assert api.set_activity_retries("a", value)["ok"] is False
    assert api.set_emulator("mumu", "new", value)["ok"] is False
    assert api.set_speed_scale(value)["ok"] is False


def test_state_snapshot_keeps_activity_status_and_solo_scope(tmp_path):
    api = runner(tmp_path)
    api._act_status = {"a": "failed"}
    api._run_scope = ["a"]
    api._run_started_at = 123
    assert api._activities_payload()[0]["status"] == "failed"
    assert api._running_payload()["runScope"] == ["a"]
    assert api._running_payload()["startedAt"] == 123


def test_capture_requests_are_bounded_and_retry_after_worker_finishes(tmp_path):
    api = runner(tmp_path)
    api._window = Mock()
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    def capture():
        entered.set()
        assert release.wait(3)
    api._capture_once = Mock(side_effect=capture)
    assert api.capture()
    try:
        assert entered.wait(3)
        assert all(api.capture() is False for _ in range(20))
        assert api._capture_once.call_count == 1
    finally:
        release.set()
    # Acquiring the lock waits for the wrapper's finally, without a sleep/poll.
    assert api._capture_request_lock.acquire(timeout=3)
    api._capture_request_lock.release()
    api._capture_once.side_effect = done.set
    assert api.capture()
    assert done.wait(3)


def test_failed_atomic_replace_preserves_existing_config_and_cleans_temp(tmp_path, monkeypatch):
    api = runner(tmp_path)
    path = tmp_path / "config.json"
    path.write_text('{"old":true}', encoding="utf-8")
    before = copy.deepcopy(api._runner_config)
    def failed_replace(*_args):
        raise OSError("simulated write failure")
    monkeypatch.setattr("apps.workflow_runner.os.replace", failed_replace)
    assert api.set_interval("a", 2) is False
    assert path.read_text(encoding="utf-8") == '{"old":true}'
    assert list(tmp_path.glob("*.tmp")) == []
    assert api._runner_config == before
    assert api.flow["activities"][0]["pollInterval"] == 1


def test_runner_refuses_enabling_background_until_previous_worker_returns(tmp_path):
    api = runner(tmp_path)
    act = api.flow["activities"][0]
    act.update(type="background", enabled=False)
    api.engine.is_running.return_value = True
    api.engine.background_stopping.return_value = True
    before = copy.deepcopy(api._runner_config)
    assert api.toggle_activity("a", True) is False
    assert act["enabled"] is False
    assert api._runner_config == before
    api.engine.start_background.assert_not_called()
