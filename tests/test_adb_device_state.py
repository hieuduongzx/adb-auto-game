import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.adb.controller import ADBController, TimedAdbClient  # noqa: E402
from src.core.adb.scanner import DeviceScanner  # noqa: E402


class _Device:
    def __init__(self, serial, shell_result="ok"):
        self.serial = serial
        self.shell_result = shell_result
        self.shell_calls = []

    def shell(self, command, timeout=None):
        self.shell_calls.append((command, timeout))
        return self.shell_result


class TestAdbDeviceStates(unittest.TestCase):
    def test_parse_devices_output_preserves_transport_state(self):
        output = """List of devices attached
127.0.0.1:5555\tdevice product:x model:Online transport_id:1
127.0.0.1:5557\toffline transport_id:2
usb-1\tunauthorized usb:1-2

"""

        self.assertEqual(
            DeviceScanner.parse_device_states(output),
            {
                "127.0.0.1:5555": "device",
                "127.0.0.1:5557": "offline",
                "usb-1": "unauthorized",
            },
        )

    def test_quick_refresh_ignores_offline_device(self):
        controller = ADBController()
        offline = _Device("127.0.0.1:5555")
        controller.client = types.SimpleNamespace(devices=lambda: [offline])
        controller.scanner.get_device_states = mock.Mock(
            return_value={offline.serial: "offline"}
        )
        controller.device_id = offline.serial

        self.assertFalse(controller.quick_refresh())
        self.assertIsNone(controller.device)
        self.assertEqual(controller.device_id, offline.serial)
        self.assertEqual(offline.shell_calls, [])

    def test_list_devices_ignores_non_ready_transports(self):
        controller = ADBController()
        online = _Device("127.0.0.1:5555", shell_result="Online")
        offline = _Device("127.0.0.1:5557", shell_result="Offline")
        controller.client = types.SimpleNamespace(devices=lambda: [online, offline])
        controller.scanner.get_device_states = mock.Mock(return_value={
            online.serial: "device",
            offline.serial: "offline",
        })

        devices = controller.list_devices()

        self.assertEqual([item["serial"] for item in devices], [online.serial])
        self.assertFalse(any(call for call in offline.shell_calls))

    def test_quick_refresh_does_not_switch_selected_device(self):
        controller = ADBController()
        other = _Device("127.0.0.1:5557")
        controller.client = types.SimpleNamespace(devices=lambda: [other])
        controller.scanner.get_device_states = mock.Mock(
            return_value={other.serial: "device"}
        )
        controller.device_id = "127.0.0.1:5555"

        self.assertFalse(controller.quick_refresh())
        self.assertIsNone(controller.device)
        self.assertEqual(controller.device_id, "127.0.0.1:5555")

    def test_failed_selection_clears_previous_device(self):
        controller = ADBController()
        previous = _Device("127.0.0.1:5555")
        controller.device = previous
        controller.device_id = previous.serial
        controller.client = types.SimpleNamespace(devices=lambda: [previous])
        controller.scanner.get_device_states = mock.Mock(
            return_value={previous.serial: "device"}
        )

        self.assertFalse(controller.select_device("127.0.0.1:5557"))
        self.assertIsNone(controller.device)
        self.assertEqual(controller.device_id, "127.0.0.1:5557")

    def test_unauthorized_device_is_not_listed(self):
        controller = ADBController()
        unauthorized = _Device("usb-1")
        controller.client = types.SimpleNamespace(devices=lambda: [unauthorized])
        controller.scanner.get_device_states = mock.Mock(
            return_value={unauthorized.serial: "unauthorized"}
        )

        self.assertEqual(controller.list_devices(), [])
        self.assertEqual(unauthorized.shell_calls, [])

    def test_quick_refresh_health_check_has_timeout(self):
        controller = ADBController()
        online = _Device("127.0.0.1:5555")
        controller.client = types.SimpleNamespace(devices=lambda: [online])
        controller.scanner.get_device_states = mock.Mock(
            return_value={online.serial: "device"}
        )
        controller.device_id = online.serial

        self.assertTrue(controller.quick_refresh())
        self.assertEqual(online.shell_calls, [("echo ok", 2.0)])

    def test_light_status_does_not_query_foreground_app(self):
        controller = ADBController()
        online = _Device("127.0.0.1:5555", shell_result="Online")
        controller.device = online
        controller.device_id = online.serial

        status = controller.get_status_summary(include_app=False)

        self.assertTrue(status["connected"])
        self.assertIsNone(status["app_package"])
        self.assertEqual(
            online.shell_calls,
            [("getprop ro.product.model", 3.0)],
        )


class TestAdbConnectVerification(unittest.TestCase):
    def test_state_query_uses_configured_adb_server(self):
        scanner = DeviceScanner(host="10.0.0.2", port=15037)
        result = types.SimpleNamespace(returncode=0, stdout="", stderr="")

        with mock.patch(
            "src.core.adb.scanner.subprocess.run", return_value=result
        ) as run:
            scanner.get_device_states()

        command = run.call_args.args[0]
        self.assertEqual(
            command,
            [scanner.adb_path, "-H", "10.0.0.2", "-P", "15037", "devices", "-l"],
        )

    def test_connect_rejects_transport_that_stays_offline(self):
        scanner = DeviceScanner()
        scanner._is_port_open = mock.Mock(return_value=True)
        scanner.get_device_states = mock.Mock(
            return_value={"127.0.0.1:5555": "offline"}
        )
        result = types.SimpleNamespace(
            returncode=0, stdout="connected to 127.0.0.1:5555", stderr=""
        )

        with mock.patch("src.core.adb.scanner.subprocess.run", return_value=result), \
                mock.patch("src.core.adb.scanner.time.sleep"):
            self.assertIsNone(scanner._try_connect_to_host("127.0.0.1:5555"))

    def test_connect_accepts_transport_after_it_becomes_ready(self):
        scanner = DeviceScanner()
        scanner._is_port_open = mock.Mock(return_value=True)
        scanner.get_device_states = mock.Mock(side_effect=[
            {"127.0.0.1:5555": "offline"},
            {"127.0.0.1:5555": "device"},
        ])
        result = types.SimpleNamespace(
            returncode=0, stdout="connected to 127.0.0.1:5555", stderr=""
        )

        with mock.patch("src.core.adb.scanner.subprocess.run", return_value=result), \
                mock.patch("src.core.adb.scanner.time.sleep"):
            self.assertEqual(
                scanner._try_connect_to_host("127.0.0.1:5555"),
                "127.0.0.1:5555",
            )


class TestUniqueDevices(unittest.TestCase):
    """One picker row per emulator, stable while aliases come and go."""

    @staticmethod
    def _alias(serial, android_id="abc123", model="MuMu"):
        return _Device(serial, shell_result=f"{model}\n{android_id}\n")

    def test_aliases_collapse_to_loopback_serial(self):
        scanner = DeviceScanner()
        devices = [self._alias("emulator-5554"), self._alias("127.0.0.1:5555")]

        self.assertEqual(scanner.unique_devices(devices),
                         [{"serial": "127.0.0.1:5555", "name": "MuMu"}])

    def test_preferred_serial_represents_its_group(self):
        # A scan adding 127.0.0.1:16384 (sorts before :5555) must not swap
        # the row the user picked.
        scanner = DeviceScanner()
        devices = [self._alias("127.0.0.1:5555"), self._alias("127.0.0.1:16384")]

        self.assertEqual(scanner.unique_devices(devices)[0]["serial"], "127.0.0.1:16384")
        self.assertEqual(
            scanner.unique_devices(devices, prefer=("127.0.0.1:5555", None)),
            [{"serial": "127.0.0.1:5555", "name": "MuMu"}],
        )

    def test_different_emulators_stay_separate(self):
        scanner = DeviceScanner()
        devices = [self._alias("127.0.0.1:5555", "aaa"),
                   self._alias("127.0.0.1:5557", "bbb")]

        self.assertEqual(len(scanner.unique_devices(devices)), 2)

    def test_fingerprints_are_cached_while_listed(self):
        scanner = DeviceScanner()
        dev = self._alias("127.0.0.1:5555")

        scanner.unique_devices([dev])
        scanner.unique_devices([dev])

        self.assertEqual(len(dev.shell_calls), 1)

    def test_cache_drops_serial_that_left(self):
        # The port can come back as a different instance — re-fingerprint it.
        scanner = DeviceScanner()
        first = self._alias("127.0.0.1:5555", "aaa")
        scanner.unique_devices([first])
        scanner.unique_devices([])
        again = self._alias("127.0.0.1:5555", "bbb")

        scanner.unique_devices([again])

        self.assertEqual(len(again.shell_calls), 1)
        self.assertEqual(scanner._fp_cache["127.0.0.1:5555"], ("MuMu", "bbb"))


class TestQuietScan(unittest.TestCase):
    def test_background_scan_logs_only_new_devices(self):
        scanner = DeviceScanner()
        scanner._try_connect_to_host = lambda host: host
        ports = ["127.0.0.1:5555", "127.0.0.1:5557"]

        with mock.patch("src.core.adb.scanner.log_success") as log:
            scanner.scan_ports(ports, quiet=True)
            self.assertEqual(log.call_count, 2)
            scanner.scan_ports(ports, quiet=True)
            self.assertEqual(log.call_count, 2)
            scanner.scan_ports(ports)            # manual scan reports all
            self.assertEqual(log.call_count, 4)


class TestReleaseScrcpySources(unittest.TestCase):
    def test_keeps_only_wanted_serials(self):
        from src.core.adb.auto import scrcpy_capture as cap

        stopped = []

        class _Src:
            def __init__(self, serial):
                self.serial = serial

            def stop(self):
                stopped.append(self.serial)

        with mock.patch.dict(cap._SOURCES, clear=True):
            for serial in ("a", "b", "c"):
                cap._SOURCES[serial] = _Src(serial)

            cap.release_scrcpy_sources({"b", None})

            self.assertEqual(sorted(stopped), ["a", "c"])
            self.assertEqual(list(cap._SOURCES), ["b"])


class TestTimedAdbClient(unittest.TestCase):
    def test_host_connection_uses_default_timeout(self):
        client = TimedAdbClient(timeout=3.0)
        sentinel = object()

        with mock.patch(
            "ppadb.client.Client.create_connection", return_value=sentinel
        ) as create_connection:
            self.assertIs(client.create_connection(), sentinel)

        create_connection.assert_called_once_with(timeout=3.0)


if __name__ == "__main__":
    unittest.main()
