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
    api._round = None
    api._flow_game_path = "old.exe"
    api.flow_path = None
    api._flow_emulator = dict(api.flow["emulator"])
    api._window = None
    api._closing = False
    api._push = Mock()
    api._start_hotkeys = Mock()       # never grab the real keyboard in tests
    api._stop_hotkeys = Mock()
    # Nor write the real data folder or pop real notifications: history,
    # failure shots and run notifications all stay inside tmp_path.
    api._history_path = lambda: str(tmp_path / "history.jsonl")
    api._failure_dir = lambda: str(tmp_path / "failures")
    api._notify_outcome = Mock()
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


def _real_rounds(api):
    """Give the mocked engine the real configure_rounds bookkeeping."""
    from src.workflow.engine import WorkflowEngine

    def configure(count=1, rest=0):
        return WorkflowEngine.configure_rounds(api.engine, count, rest)
    api.engine.configure_rounds.side_effect = configure
    api.engine.rounds, api.engine.round_rest = 1, 0.0


def test_rounds_are_saved_per_workflow_and_restored(tmp_path):
    import json
    api = runner(tmp_path)
    _real_rounds(api)
    assert api.set_rounds(3, 600) == {"ok": True, "count": 3, "rest": 600.0}
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["rounds"] == {"count": 3, "rest": 600.0}
    api.engine.rounds, api.engine.round_rest = 1, 0.0
    api._runner_config = saved
    api._apply_runner_config()
    assert (api.engine.rounds, api.engine.round_rest) == (3, 600.0)


def test_rounds_cannot_change_under_a_live_run(tmp_path):
    api = runner(tmp_path)
    _real_rounds(api)
    api._run_active = True
    assert api.set_rounds(0, 0)["ok"] is False
    assert api.engine.rounds == 1


def test_new_round_resets_rows_and_outcome_names_the_rounds(tmp_path):
    api = runner(tmp_path)
    api.engine._fatal = ""
    api.engine._stop = threading.Event()
    api._on_engine_start()
    api._on_round({"round": 1, "total": 3, "phase": "running", "restUntil": 0})
    api._on_activity_complete({"id": "a"}, True)
    api._push.reset_mock()
    api._on_round({"round": 2, "total": 3, "phase": "running", "restUntil": 0})
    assert ("activity_update", {"id": "a", "status": "pending"}) in [c.args for c in api._push.call_args_list]
    assert api._running_payload()["round"]["round"] == 2
    api._on_activity_complete({"id": "a"}, True)
    api._on_engine_stop()
    assert api._outcome["kind"] == "completed"
    assert api._outcome["reason"].startswith("2 rounds · ")
    assert api._running_payload()["round"] is None


def test_finished_run_appends_one_history_record(tmp_path, monkeypatch):
    from src import run_history
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(run_history, "history_path", lambda *a: str(path))
    api = runner(tmp_path)
    api.engine._fatal = ""
    api.engine._stop = threading.Event()
    api._on_engine_start()
    api._on_activity_start({"id": "a", "name": "A"})
    api._on_activity_complete({"id": "a", "name": "A"}, False)
    api._on_engine_stop()
    api._on_engine_stop()            # stop() and the sequence thread both emit on_stop
    records = run_history.load(str(path))
    assert len(records) == 1
    rec = records[0]
    assert rec["outcome"] == "failed" and rec["scope"] == ""
    assert rec["activities"] == [{"id": "a", "name": "A", "completed": 0, "failed": 1,
                                  "stopped": 0, "seconds": rec["activities"][0]["seconds"]}]
    assert ("history_added", rec) in [c.args for c in api._push.call_args_list]
    assert api.get_history() == records


def _notify_runner(tmp_path, monkeypatch, cfg):
    sent = []
    monkeypatch.setattr("src.notify.desktop", lambda t, m: sent.append(("desktop", t, m)))
    monkeypatch.setattr("src.notify.discord_async", lambda url, t, m, kind, fields: sent.append(("discord", t, kind, fields)))
    api = runner(tmp_path)
    api._notify_outcome = WorkflowRunnerAPI._notify_outcome.__get__(api)   # the real one here
    api.get_notify = lambda: dict(cfg)
    api._run_started_at = 0
    api._round = None
    api._run_acts = {"a": {"id": "a", "name": "A", "completed": 0, "failed": 1, "stopped": 0, "seconds": 3}}
    return api, sent


def test_failed_run_notifies_desktop_and_discord(tmp_path, monkeypatch):
    api, sent = _notify_runner(tmp_path, monkeypatch, {"when": "failed", "desktop": True,
                                                       "discord": "https://discord.com/api/webhooks/1/x"})
    api._notify_outcome({"kind": "failed", "label": "Failed", "reason": "1 of 1 activities failed",
                         "counts": {"completed": 0, "failed": 1}})
    assert [s[0] for s in sent] == ["desktop", "discord"]
    assert sent[0][1] == "Audit — Failed"
    assert sent[1][2] == "failed" and sent[1][3]["Failed"] == "A"


def test_completed_run_is_quiet_on_failures_only_and_solo_runs_never_notify(tmp_path, monkeypatch):
    api, sent = _notify_runner(tmp_path, monkeypatch, {"when": "failed", "desktop": True, "discord": ""})
    api._notify_outcome({"kind": "completed", "label": "Completed", "reason": "", "counts": {}})
    assert sent == []
    api.get_notify = lambda: {"when": "all", "desktop": True, "discord": ""}
    api._run_scope = ["a"]
    api._notify_outcome({"kind": "failed", "label": "Failed", "reason": "", "counts": {}})
    assert sent == []


def test_set_notify_refuses_a_non_discord_webhook(tmp_path, monkeypatch):
    saved = {}
    monkeypatch.setattr("runner.outcome.load_ui_settings", lambda: dict(saved))
    monkeypatch.setattr("runner.outcome.save_ui_settings", lambda patch: saved.update(patch) or True)
    api = runner(tmp_path)
    assert api.set_notify({"discord": "https://evil.example/hook"})["ok"] is False
    assert "runNotify" not in saved
    r = api.set_notify({"when": "all", "discord": "https://discord.com/api/webhooks/1/x"})
    assert r["ok"] and saved["runNotify"]["when"] == "all"
    assert api.get_notify()["discord"] == "https://discord.com/api/webhooks/1/x"


def test_time_limit_is_a_runner_override_saved_and_reapplied(tmp_path):
    import json
    api = runner(tmp_path)
    assert api.set_activity_time_limit("a", "15") == {"ok": True, "timeLimit": 15.0}
    assert api.flow["activities"][0]["timeLimit"] == 15.0
    assert api.set_activity_time_limit("a", "abc")["ok"] is False
    assert api.set_activity_time_limit("a", float("inf"))["ok"] is False
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["activities"]["a"]["timeLimit"] == 15.0
    api.flow["activities"][0]["timeLimit"] = 0
    api._runner_config = saved
    api._apply_runner_config()
    assert api.flow["activities"][0]["timeLimit"] == 15.0
    assert api._activities_payload()[0]["timeLimit"] == 15.0


def test_failed_activity_saves_a_screenshot_and_history_links_it(tmp_path, monkeypatch):
    import numpy as np
    from src import run_history
    monkeypatch.setattr(run_history, "runner_dir", lambda *a: str(tmp_path / "runner"))
    api = runner(tmp_path)
    api.engine._fatal = ""
    api.engine._stop = threading.Event()
    api.engine.auto.capture_screen.return_value = np.zeros((20, 30, 3), dtype=np.uint8)
    api._on_engine_start()
    api._on_activity_start({"id": "a", "name": "Claim VIP"})
    api._on_activity_crash({"id": "a", "name": "Claim VIP"}, None)
    api._on_activity_complete({"id": "a", "name": "Claim VIP"}, False)
    shot = api._run_acts["a"]["shot"]
    assert shot.endswith("_Claim_VIP.jpg") and (tmp_path / "failures").exists()
    import os
    assert os.path.isfile(shot)
    opened = []
    monkeypatch.setattr("runner.outcome.os.startfile", lambda p: opened.append(p), raising=False)
    assert api.open_failure_shot(shot)["ok"] is True and len(opened) == 1
    outside = tmp_path / "evil.jpg"
    outside.write_bytes(b"x")
    assert api.open_failure_shot(str(outside))["ok"] is False


def test_failure_shots_are_pruned_to_the_newest(tmp_path):
    import os
    api = runner(tmp_path)
    folder = tmp_path / "f"
    folder.mkdir()
    for i in range(45):
        p = folder / f"{i:03d}.jpg"
        p.write_bytes(b"x")
        os.utime(p, (1000 + i, 1000 + i))
    api._prune_failure_shots(str(folder))
    left = sorted(p.name for p in folder.iterdir())
    assert len(left) == api.FAILURE_SHOTS_KEEP and left[0] == "005.jpg"


def test_resume_from_starts_there_and_marks_earlier_activities_skipped(tmp_path):
    api = runner(tmp_path)
    api.flow["activities"] = [{"id": "x", "name": "X"}, {"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    api._resume_from = None
    api.engine.start.side_effect = lambda **kw: api._on_engine_start() or True
    assert api.resume_from("a") is True
    assert api.engine.start.call_args.kwargs == {"background": True, "start_from": "a"}
    pushed = [c.args[1] for c in api._push.call_args_list if c.args[0] == "activity_update"]
    assert pushed[:3] == [{"id": "x", "status": "skipped"}, {"id": "a", "status": "pending"},
                          {"id": "b", "status": "pending"}]
    assert api._resume_from is None                      # consumed by this run only


def test_resume_from_an_unknown_activity_is_a_plain_start(tmp_path):
    api = runner(tmp_path)
    api._resume_from = None
    api.engine.start.return_value = True
    assert api.resume_from("nope") is True
    assert api.engine.start.call_args.kwargs == {"background": True}
