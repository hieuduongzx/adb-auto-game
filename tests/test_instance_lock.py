"""One Runner per workflow: the lock file and who holds it."""
import json
import os
import subprocess
import sys

from src import instance_lock as L


def test_acquire_release_and_stale_takeover(tmp_path):
    path = str(tmp_path / "runner.pid")
    assert L.acquire(path) is None                         # free → ours
    assert json.loads(open(path).read())["pid"] == os.getpid()
    assert L.holder(path) is None                          # our own lock never blocks us
    L.release(path)
    assert not os.path.exists(path)
    # A PID that has exited is stale: taken over silently.
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    with open(path, "w") as fh:
        json.dump({"pid": gone.pid}, fh)
    assert L.acquire(path) is None
    assert json.loads(open(path).read())["pid"] == os.getpid()


def test_a_live_other_process_holds_the_lock(tmp_path):
    path = str(tmp_path / "runner.pid")
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        with open(path, "w") as fh:
            json.dump({"pid": child.pid}, fh)
        assert L.pid_alive(child.pid)
        assert L.acquire(path) == child.pid
        L.release(path)                                    # not ours: left alone
        assert json.loads(open(path).read())["pid"] == child.pid
    finally:
        child.kill()
        child.wait()


def test_garbage_lock_is_ignored(tmp_path):
    path = tmp_path / "runner.pid"
    path.write_text("not json", encoding="utf-8")
    assert L.holder(str(path)) is None
    assert L.pid_alive(0) is False and L.pid_alive("x") is False


def test_runner_claim_focuses_the_open_runner_instead_of_opening_a_twin(tmp_path, monkeypatch):
    import subprocess
    from apps import workflow_runner as WR
    flow = tmp_path / "flow.json"
    flow.write_text('{"name": "Twin"}', encoding="utf-8")
    lock = tmp_path / "runner.pid"
    monkeypatch.setattr(WR.instance_lock, "lock_path", lambda name, path: str(lock))
    focused = []
    monkeypatch.setattr(WR.instance_lock, "focus_process_window", lambda pid: focused.append(pid) or True)
    assert WR._claim_workflow(str(flow)) == str(lock)       # first Runner takes it
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"])
    try:
        lock.write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
        assert WR._claim_workflow(str(flow)) is None         # second launch stands down
        assert focused == [child.pid]
    finally:
        child.kill()
        child.wait()
    assert WR._claim_workflow(None) == ""                    # nothing to claim
