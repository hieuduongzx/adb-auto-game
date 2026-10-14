"""The Hub's Recent runs strip reads every game's Runner history."""
import time

from apps import workflow_hub
from src import run_history


def test_merges_games_newest_first_and_counts_today(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_hub, "data_root", lambda: str(tmp_path))
    root = tmp_path / "data" / "runner"
    now = time.time()
    run_history.append(str(root / "GirlWars_0123abcd" / "history.jsonl"),
                       {"workflow": "Girl Wars", "end": now - 60, "outcome": "completed", "seconds": 5})
    run_history.append(str(root / "GirlWars_0123abcd" / "history.jsonl"),
                       {"workflow": "Girl Wars", "end": now - 3 * 86400, "outcome": "failed"})
    # A record written before the name was stored: recovered from its folder.
    run_history.append(str(root / "Brown_Dust_89abcdef" / "history.jsonl"),
                       {"end": now - 30, "outcome": "failed", "reason": "1 of 2 failed"})
    (root / "empty_00000000").mkdir(parents=True)

    api = workflow_hub.WorkflowHubAPI.__new__(workflow_hub.WorkflowHubAPI)
    out = api.recent_runs(10)
    assert [r["workflow"] for r in out["runs"]] == ["Brown Dust", "Girl Wars", "Girl Wars"]
    assert out["runs"][0]["reason"] == "1 of 2 failed"
    assert out["today"] == {"runs": 2, "completed": 1, "failed": 1, "stopped": 0}
    assert len(api.recent_runs(1)["runs"]) == 1


def test_no_runner_folder_is_an_empty_strip(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_hub, "data_root", lambda: str(tmp_path))
    api = workflow_hub.WorkflowHubAPI.__new__(workflow_hub.WorkflowHubAPI)
    assert api.recent_runs()["runs"] == []
