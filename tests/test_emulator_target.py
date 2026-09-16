"""Tests for the emulator nodes' "selected device" targeting.

The half of that feature which decides anything is Windows plumbing
(``EnumWindows``, ``netstat``) that can't run here — no emulator installed — so
the decisions themselves live in pure functions over plain data, and those are
what this file pins down. The engine methods run against a stub engine whose
two probes are monkeypatched.

Stdlib only (``unittest``), matching the run command in the README:

    python -m unittest discover -s tests -v
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.workflow import engine as E  # noqa: E402
from src.workflow.engine import WorkflowEngine  # noqa: E402


def rec(hwnd, pid, family_exe="dnplayer.exe", under=r"C:\LDPlayer\LDPlayer9",
        area=1000, title="LDPlayer"):
    """One ``_enum_player_windows`` record, shaped the way the real one is."""
    exe = f"{under}\\{family_exe}" if under else family_exe
    return {"hwnd": hwnd, "pid": pid, "title": title, "exe_path": exe, "area": area}


class _StubEngine(WorkflowEngine):
    """The engine's targeting state without a controller or a workflow file.

    ``WorkflowEngine.__init__`` builds an ``ADBGameAutomation`` (OCR backend and
    all) that these paths never touch: ``selected`` targeting reads only the
    selected serial, the bound ADB device, and the shared emulator setting, so
    the stub supplies exactly those three and nothing else.
    """

    def __init__(self, device_id=""):
        self.selected_serial = ""
        self._emu_cfg = {}
        self.auto = types.SimpleNamespace(
            adb=types.SimpleNamespace(device_id=device_id))


class TestSplitSerial(unittest.TestCase):
    def test_loopback_and_lan(self):
        self.assertEqual(E._split_emulator_serial("127.0.0.1:16384"), ("127.0.0.1", 16384))
        self.assertEqual(E._split_emulator_serial("192.168.1.7:5555"), ("192.168.1.7", 5555))

    def test_emulator_console_form_maps_to_the_adb_port(self):
        # adb's console port is one below the ADB port (5554 console / 5555 adb),
        # which is the pairing LDPlayer answers on.
        self.assertEqual(E._split_emulator_serial("emulator-5554"), ("", 5555))
        self.assertEqual(E._split_emulator_serial("EMULATOR-5554"), ("", 5555))

    def test_no_port_forms(self):
        for serial in ("", "   ", None, "R58M12ABC", "127.0.0.1:notaport"):
            with self.subTest(serial=serial):
                self.assertIsNone(E._split_emulator_serial(serial)[1])

    def test_zero_port_is_not_a_port(self):
        self.assertIsNone(E._split_emulator_serial("127.0.0.1:0")[1])


class TestPortCandidates(unittest.TestCase):
    def test_round_trips_every_family(self):
        for kind, spec in E.EMULATOR_CONSOLES.items():
            with self.subTest(kind=kind):
                for index in (0, 1, 3):
                    port = spec["port0"] + index * spec["step"]
                    self.assertIn((kind, index), E._emulator_port_candidates(port))

    def test_ldplayer_and_bluestacks_share_seven_ports(self):
        # 5555 + 2a == 5555 + 10b only when a is a multiple of 5, so the two
        # families meet on exactly seven ports — the reason a serial alone can't
        # name a family, and why the resolver needs the running-process evidence.
        shared = sorted(p for p in range(5555, 5620)
                        if len({k for k, _ in E._emulator_port_candidates(p)}) > 1)
        self.assertEqual(shared, [5555, 5565, 5575, 5585, 5595, 5605, 5615])

    def test_single_owner_ports(self):
        for port, kind in ((16384, "mumu"), (62001, "nox"), (21503, "memu")):
            with self.subTest(port=port):
                self.assertEqual(E._emulator_port_candidates(port), [(kind, 0)])

    def test_rejects_ports_no_family_owns(self):
        # 7555 is MuMu's alias for the same device as 16384 — it must not become
        # a second candidate; 5037 is the ADB server itself.
        for port in (0, -1, 5037, 7555, 999999):
            with self.subTest(port=port):
                self.assertEqual(E._emulator_port_candidates(port), [])

    def test_index_stops_at_the_32_instance_range(self):
        port0 = E.EMULATOR_CONSOLES["nox"]["port0"]
        self.assertIn(("nox", 31), E._emulator_port_candidates(port0 + 31))
        self.assertNotIn(("nox", 32), E._emulator_port_candidates(port0 + 32))


class TestFamilyFromExe(unittest.TestCase):
    def test_player_exes(self):
        for exe, kind in ((r"C:\LDPlayer\LDPlayer9\dnplayer.exe", "ldplayer"),
                          (r"C:\BlueStacks_nxt\HD-Player.exe", "bluestacks"),
                          (r"C:\Program Files\Netease\MuMuPlayer.exe", "mumu")):
            with self.subTest(exe=exe):
                self.assertEqual(E._emulator_family_from_exe(exe), kind)

    def test_console_and_unrelated_exes_are_not_players(self):
        # ldconsole drives LDPlayer but owns no window — resizing it is meaningless.
        self.assertIsNone(E._emulator_family_from_exe(r"C:\LDPlayer\LDPlayer9\ldconsole.exe"))
        self.assertIsNone(E._emulator_family_from_exe(r"C:\Windows\System32\adb.exe"))
        self.assertIsNone(E._emulator_family_from_exe(""))


class TestPickPlayerWindow(unittest.TestCase):
    def test_no_window_of_the_family(self):
        self.assertEqual(E._pick_player_window({}, "ldplayer"), (None, "none"))

    def test_single_window_needs_no_evidence(self):
        recs = {"ldplayer": [rec(11, 100)]}
        self.assertEqual(E._pick_player_window(recs, "ldplayer"), (11, "single"))

    def test_pid_hint_beats_a_larger_sibling(self):
        # The regression this feature exists for: two LDPlayers open and the
        # selected one is the small window. Size must not get a vote.
        recs = {"ldplayer": [rec(11, 100, area=99999), rec(22, 200, area=100)]}
        self.assertEqual(
            E._pick_player_window(recs, "ldplayer", pid_hints=[200]), (22, "pid"))

    def test_pid_hint_that_matches_nothing_falls_through(self):
        recs = {"ldplayer": [rec(11, 100, area=99999), rec(22, 200, area=100)]}
        self.assertEqual(
            E._pick_player_window(recs, "ldplayer", pid_hints=[999]), (11, "largest"))

    def test_strict_refuses_rather_than_resizing_a_sibling(self):
        # The guard the whole "report it, don't guess" rule rests on.
        recs = {"ldplayer": [rec(11, 100, area=99999), rec(22, 200, area=100)]}
        self.assertEqual(
            E._pick_player_window(recs, "ldplayer", strict=True), (None, "ambiguous"))

    def test_strict_still_accepts_an_exact_answer(self):
        recs = {"ldplayer": [rec(11, 100, area=9), rec(22, 200, area=99999)]}
        self.assertEqual(
            E._pick_player_window(recs, "ldplayer", pid_hints=[100], strict=True), (11, "pid"))
        self.assertEqual(
            E._pick_player_window({"ldplayer": [rec(11, 100)]}, "ldplayer",
                                  strict=True), (11, "single"))

    def test_install_dir_outranks_size(self):
        recs = {"ldplayer": [
            rec(11, 100, under=r"D:\Other\LDPlayer9", area=99999),
            rec(22, 200, under=r"C:\LDPlayer\LDPlayer9", area=100),
        ]}
        self.assertEqual(
            E._pick_player_window(recs, "ldplayer", r"C:\LDPlayer\LDPlayer9"), (22, "largest"))

    def test_find_emulator_window_is_unchanged_for_legacy_callers(self):
        recs = {"ldplayer": [rec(11, 100, area=5), rec(22, 200, area=9)]}
        with mock.patch.object(E, "_enum_player_windows", return_value=recs):
            self.assertEqual(E._find_emulator_window("ldplayer"), 22)
            self.assertIsNone(E._find_emulator_window("mumu"))


class TestResolveSelectedEmulator(unittest.TestCase):
    """The resolution ladder, with both Windows probes stubbed out."""

    def setUp(self):
        self.eng = _StubEngine()

    def _resolve(self, serial, running=None, verb="Resize"):
        with mock.patch.object(E, "_enum_player_windows", return_value=running or {}):
            self.eng.set_selected_device(serial)
            return self.eng._resolve_selected_emulator({"emulator": "selected"}, verb)

    def test_no_device_selected(self):
        self.assertIsNone(self._resolve("", running={}))
        self.assertIsNone(self._resolve(None, running={}))

    def test_serial_without_a_usable_port(self):
        self.assertIsNone(self._resolve("R58M12ABC"))

    def test_unowned_port(self):
        self.assertIsNone(self._resolve("127.0.0.1:5037"))

    def test_unambiguous_port_resolves_without_window_evidence(self):
        kind, index, _, instance = self._resolve("127.0.0.1:16384")
        self.assertEqual((kind, index, instance), ("mumu", 0, ""))

    def test_shared_port_uses_the_running_family(self):
        running = {"ldplayer": [rec(11, 100)]}
        kind, index, path, _ = self._resolve("127.0.0.1:5555", running=running)
        self.assertEqual((kind, index), ("ldplayer", 0))
        # The running instance's own folder beats whatever the project setting says.
        self.assertEqual(path, r"C:\LDPlayer\LDPlayer9")

    def test_shared_port_with_both_families_running_is_refused(self):
        # Two families that could each own 5555, both open: not evidence.
        running = {"ldplayer": [rec(11, 100)], "bluestacks": [rec(22, 200)]}
        self.assertIsNone(self._resolve("127.0.0.1:5555", running=running))

    def test_shared_port_with_nothing_running_is_refused(self):
        self.assertIsNone(self._resolve("127.0.0.1:5555", running={}))

    def test_index_comes_from_the_port_not_the_formula_default(self):
        kind, index, _, _ = self._resolve("127.0.0.1:5565", running={"ldplayer": [rec(1, 1)]})
        self.assertEqual((kind, index), ("ldplayer", 5))

    def test_lan_serial_still_resolves(self):
        # LDPlayer binds 0.0.0.0:5555, so its reachable serial is often a LAN IP.
        kind, index, _, _ = self._resolve("192.168.1.7:5557", running={"ldplayer": [rec(1, 1)]})
        self.assertEqual((kind, index), ("ldplayer", 1))


class TestPcTargetRouting(unittest.TestCase):
    """``_emulator_pc_target`` sends "selected" down the new path and nothing else."""

    def setUp(self):
        self.eng = _StubEngine()

    def test_selected_routes_to_the_resolver(self):
        self.eng.set_selected_device("127.0.0.1:16384")
        with mock.patch.object(E, "_enum_player_windows", return_value={}):
            self.assertEqual(self.eng._emulator_pc_target({"emulator": "selected"}, "Resize")[:2],
                             ("mumu", 0))

    def test_a_plain_family_never_reads_the_selected_serial(self):
        # "last" with nothing saved refuses — the point is that the selected
        # serial is not consulted at all on the explicit paths.
        self.eng.set_selected_device("127.0.0.1:16384")
        with mock.patch.object(WorkflowEngine, "_load_emulator_state", return_value=None):
            self.assertIsNone(self.eng._emulator_pc_target({"emulator": "last"}, "Resize"))

    def test_an_unknown_family_is_still_refused(self):
        self.assertIsNone(self.eng._emulator_pc_target({"emulator": "khong_co_hang"}, "Resize"))


class TestSelectedInstanceHints(unittest.TestCase):
    def setUp(self):
        self.eng = _StubEngine()

    def test_family_nodes_keep_the_historical_rule(self):
        self.eng.set_selected_device("127.0.0.1:16384")
        for kind in ("mumu", "last"):
            with self.subTest(kind=kind):
                self.assertEqual(self.eng._selected_instance_hints({"emulator": kind}),
                                 (None, None, False))

    def test_selected_node_is_strict_and_asks_for_the_ports_owner(self):
        self.eng.set_selected_device("127.0.0.1:16384")
        with mock.patch.object(E, "_tcp_listener_pids", return_value=[4242]) as tp:
            self.assertEqual(self.eng._selected_instance_hints({"emulator": "selected"}),
                             (16384, [4242], True))
            tp.assert_called_once_with(16384)

    def test_selected_with_no_device_still_strict(self):
        # No serial → no port → no hints, but the node still refuses a guess.
        self.eng.set_selected_device("")
        self.assertEqual(self.eng._selected_instance_hints({"emulator": "selected"}),
                         (None, [], True))

    def test_falls_back_to_the_bound_adb_device(self):
        eng = _StubEngine(device_id="127.0.0.1:62001")
        with mock.patch.object(E, "_tcp_listener_pids", return_value=[7]) as tp:
            port, pids, strict = eng._selected_instance_hints({"emulator": "selected"})
        self.assertEqual((port, pids, strict), (62001, [7], True))
        tp.assert_called_once_with(62001)


class TestTcpListenerPids(unittest.TestCase):
    NETSTAT = """\
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:5555           0.0.0.0:0              LISTENING       100
  TCP    127.0.0.1:16384        0.0.0.0:0              LISTENING       244
  TCP    127.0.0.1:5555         0.0.0.0:0              LISTENING       300
  TCP    127.0.0.1:5555         127.0.0.1:52104        ESTABLISHED     300
  TCP    [::]:5555              [::]:0                 LISTENING       100
"""

    def _pids(self, port, stdout=NETSTAT):
        done = mock.Mock(stdout=stdout, returncode=0)
        with mock.patch("subprocess.run", return_value=done):
            return E._tcp_listener_pids(port)

    def test_matches_every_bind_of_the_port(self):
        # LDPlayer binds 0.0.0.0 and MuMu binds 127.0.0.1 — both are the port.
        self.assertEqual(self._pids(5555), [100, 300])

    def test_ignores_established_sockets_and_other_ports(self):
        self.assertEqual(self._pids(16384), [244])
        self.assertEqual(self._pids(9999), [])

    def test_failure_is_an_empty_list(self):
        with mock.patch("subprocess.run", side_effect=OSError("no netstat")):
            self.assertEqual(E._tcp_listener_pids(5555), [])

    def test_unparseable_output_is_an_empty_list(self):
        self.assertEqual(self._pids(5555, stdout=""), [])
        self.assertEqual(self._pids(5555, stdout="garbage\nTCP nonsense\n"), [])


if __name__ == "__main__":
    unittest.main()
