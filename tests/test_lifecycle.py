"""Tests for the cross-process ADB lease lifecycle."""
import json
import os
import tempfile
import unittest

from src.core.adb import lifecycle


class TestAdbLease(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="m2k_leases_")

    def _acquire(self, tag, pid=None):
        if pid is None:
            return lifecycle.acquire_adb_lease(tag, lease_dir=self.dir)
        # Simulate a foreign process by writing its lease file directly.
        path = os.path.join(
            self.dir, lifecycle._lease_filename(tag, pid))
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pid": pid, "tag": tag, "started": 0}, fh)
        return path

    def test_acquire_creates_lease_for_own_pid(self):
        path = self._acquire("devscope")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as fh:
            info = json.load(fh)
        self.assertEqual(info["pid"], os.getpid())

    def test_release_removes_own_lease_only(self):
        self._acquire("runner")
        self._acquire("designer", pid=os.getpid() + 424242)
        lifecycle.release_adb_lease("runner", lease_dir=self.dir)
        remaining = [n for n in os.listdir(self.dir) if n.endswith(".json")]
        self.assertEqual(len(remaining), 1)
        self.assertIn(str(os.getpid() + 424242), remaining[0])

    def test_live_leases_prunes_dead_pids(self):
        dead_pid = self._dead_pid()
        self.assertIsNotNone(dead_pid, "no dead PID available for the test")
        self._acquire("ghost", pid=dead_pid)
        live = lifecycle.live_leases(lease_dir=self.dir)
        self.assertEqual(live, [])
        self.assertEqual([n for n in os.listdir(self.dir)
                          if n.endswith(".json")], [])

    def test_release_and_kill_if_last_reports_siblings(self):
        from unittest.mock import patch
        dead_pid = self._dead_pid()
        self._acquire("runner")   # our own lease
        if dead_pid is not None:
            self._acquire("stale", pid=dead_pid)   # pruned, not a sibling
        # A live "sibling" lease: reuse our own PID under another tag.
        self._acquire("designer", pid=os.getpid())
        with patch("src.core.adb.scanner.kill_adb_server") as killer:
            killed = lifecycle.release_adb_and_kill_if_last(
                "runner", lease_dir=self.dir)
            self.assertFalse(killed,
                             "must not kill while a sibling lease lives")
            killer.assert_not_called()
        # After the sibling goes away too, we are the last one.
        lifecycle.release_adb_lease("designer", lease_dir=self.dir,
                                    pid=os.getpid())
        with patch("src.core.adb.scanner.kill_adb_server") as killer:
            killed = lifecycle.release_adb_and_kill_if_last(
                "runner", lease_dir=self.dir)
            self.assertTrue(killed)
            killer.assert_called_once()

    @staticmethod
    def _dead_pid():
        """Find a PID that is (almost certainly) not alive right now."""
        import subprocess
        import sys
        code = ("import os, sys;"
                "print(os.getpid());"
                "sys.stdout.flush();"
                "sys.stdin.readline()")
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            pid = int(proc.stdout.readline().strip())
        except Exception:
            proc.kill()
            return None
        proc.stdin.write("bye\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
        return pid


if __name__ == "__main__":
    unittest.main()
