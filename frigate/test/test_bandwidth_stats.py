"""Tests for the ETW per-process bandwidth collector.

The kernel logger session only exists on Windows, so the native
calls cannot be exercised here. What *can* be checked everywhere is
the part that silently breaks: the ctypes structure layouts, the
event payload parsing, the rate math, and the graceful degradation
when the elevated session cannot be started.
"""

import ctypes
import socket
import struct
import unittest
from collections import namedtuple
from unittest.mock import MagicMock, patch

from frigate.util import bandwidth as bw
from frigate.util.platform import IS_WINDOWS

SnicAddress = namedtuple("SnicAddress", ["family", "address"])


class TestBandwidthStructures(unittest.TestCase):
    """The structures have to match the Windows SDK layout byte for byte."""

    def test_wnode_header_layout(self):
        self.assertEqual(ctypes.sizeof(bw._WNODE_HEADER), 48)
        self.assertEqual(bw._WNODE_HEADER.BufferSize.offset, 0)
        self.assertEqual(bw._WNODE_HEADER.Guid.offset, 24)
        self.assertEqual(bw._WNODE_HEADER.Flags.offset, 44)

    def test_event_trace_properties_layout(self):
        self.assertEqual(ctypes.sizeof(bw._EVENT_TRACE_PROPERTIES), 120)
        self.assertEqual(bw._EVENT_TRACE_PROPERTIES.EnableFlags.offset, 72)
        self.assertEqual(bw._EVENT_TRACE_PROPERTIES.LogFileMode.offset, 64)
        self.assertEqual(bw._EVENT_TRACE_PROPERTIES.LoggerNameOffset.offset, 116)

    def test_event_header_layout(self):
        self.assertEqual(ctypes.sizeof(bw._EVENT_HEADER), 80)
        self.assertEqual(bw._EVENT_HEADER.EventDescriptor.offset, 40)
        # Classic MOF events carry their event type in Opcode, not Id.
        header = bw._EVENT_HEADER()
        header.EventDescriptor.Opcode = bw.SEND_IPV4
        self.assertEqual(header.EventDescriptor.Opcode, bw.SEND_IPV4)

    def test_event_record_layout(self):
        self.assertEqual(ctypes.sizeof(bw._EVENT_RECORD), 112)
        self.assertEqual(bw._EVENT_RECORD.ExtendedDataCount.offset, 84)
        self.assertEqual(bw._EVENT_RECORD.UserDataLength.offset, 86)
        self.assertEqual(bw._EVENT_RECORD.ExtendedData.offset, 88)
        self.assertEqual(bw._EVENT_RECORD.UserData.offset, 96)
        self.assertEqual(bw._EVENT_RECORD.UserContext.offset, 104)

    def test_event_trace_logfile_layout(self):
        self.assertEqual(ctypes.sizeof(bw._EVENT_TRACE_HEADER), 48)
        self.assertEqual(ctypes.sizeof(bw._EVENT_TRACE), 88)
        self.assertEqual(ctypes.sizeof(bw._TIME_ZONE_INFORMATION), 172)
        self.assertEqual(ctypes.sizeof(bw._TRACE_LOGFILE_HEADER), 280)
        self.assertEqual(ctypes.sizeof(bw._EVENT_TRACE_LOGFILEW), 448)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.LogFileName.offset, 0)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.LoggerName.offset, 8)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.ProcessingMode.offset, 28)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.CurrentEvent.offset, 32)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.LogfileHeader.offset, 120)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.BufferCallback.offset, 400)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.EventRecordCallback.offset, 424)
        self.assertEqual(bw._EVENT_TRACE_LOGFILEW.Context.offset, 440)

    def test_guid_parsing(self):
        guid = bw._guid_from_string(bw.SYSTEM_TRACE_CONTROL_GUID)
        self.assertEqual(guid.Data1, 0x9E814AAD)
        self.assertEqual(guid.Data2, 0x3204)
        self.assertEqual(guid.Data3, 0x11D2)
        self.assertEqual(
            bytes(guid.Data4),
            bytes([0x9A, 0x82, 0x00, 0x60, 0x08, 0xA8, 0x69, 0x39]),
        )


class TestEventConsumption(unittest.TestCase):
    def setUp(self):
        self.monitor = bw.NetworkBandwidthMonitor()

    def _payload(self, pid: int, size: int) -> int:
        self._keepalive = ctypes.create_string_buffer(struct.pack("<II", pid, size))
        return ctypes.addressof(self._keepalive)

    def test_transfer_event_accumulates_pid_and_size(self):
        address = self._payload(4242, 1500)
        self.monitor._consume_event(bw.SEND_IPV4, address, 8)
        self.monitor._consume_event(bw.RECEIVE_IPV4, address, 8)
        self.assertEqual(self.monitor._totals, {4242: 3000})

    def test_ipv6_transfer_event_accumulates(self):
        address = self._payload(7, 900)
        self.monitor._consume_event(bw.RECEIVE_IPV6, address, 8)
        self.assertEqual(self.monitor._totals, {7: 900})

    def test_record_callback_reads_classic_opcode_and_payload(self):
        record = bw._EVENT_RECORD()
        record.EventHeader.EventDescriptor.Id = 0
        record.EventHeader.EventDescriptor.Opcode = bw.SEND_IPV4
        record.UserData = self._payload(4242, 1500)
        record.UserDataLength = 8

        self.monitor._on_record(ctypes.pointer(record))

        self.assertEqual(self.monitor._totals, {4242: 1500})

    def test_record_callback_does_not_treat_id_as_classic_event_type(self):
        record = bw._EVENT_RECORD()
        record.EventHeader.EventDescriptor.Id = bw.SEND_IPV4
        record.EventHeader.EventDescriptor.Opcode = 0
        record.UserData = self._payload(4242, 1500)
        record.UserDataLength = 8

        self.monitor._on_record(ctypes.pointer(record))

        self.assertEqual(self.monitor._totals, {})

    def test_non_transfer_event_is_ignored(self):
        address = self._payload(4242, 1500)
        for event_type in (12, 13, 14, 15, 16, 17, 18):
            self.monitor._consume_event(event_type, address, 8)
        self.assertEqual(self.monitor._totals, {})

    def test_short_payload_is_ignored(self):
        self.monitor._consume_event(bw.SEND_IPV4, self._payload(1, 2), 4)
        self.assertEqual(self.monitor._totals, {})

    def test_null_user_data_is_ignored(self):
        self.monitor._consume_event(bw.SEND_IPV4, None, 8)
        self.assertEqual(self.monitor._totals, {})


class TestAddressFiltering(unittest.TestCase):
    def setUp(self):
        self.monitor = bw.NetworkBandwidthMonitor()

    def _ipv4_payload(self, daddr: bytes, saddr: bytes) -> int:
        payload = struct.pack("<II", 100, 50) + daddr + saddr + b"\x00" * 8
        self._keepalive = ctypes.create_string_buffer(payload)
        return ctypes.addressof(self._keepalive)

    def test_no_filter_counts_every_address(self):
        self.assertIsNone(self.monitor._address_filter)
        address = self._ipv4_payload(b"\x0a\x00\x00\x01", b"\xc0\xa8\x01\x01")
        self.monitor._consume_event(bw.SEND_IPV4, address, 24)
        self.assertEqual(self.monitor._totals, {100: 50})

    def test_matching_destination_address_is_counted(self):
        self.monitor.set_address_filter(frozenset([b"\x0a\x00\x00\x01"]))
        address = self._ipv4_payload(b"\x0a\x00\x00\x01", b"\xc0\xa8\x01\x01")
        self.assertTrue(self.monitor._address_matches(bw.SEND_IPV4, address, 24))

    def test_matching_source_address_is_counted(self):
        self.monitor.set_address_filter(frozenset([b"\xc0\xa8\x01\x01"]))
        address = self._ipv4_payload(b"\x0a\x00\x00\x01", b"\xc0\xa8\x01\x01")
        self.assertTrue(self.monitor._address_matches(bw.SEND_IPV4, address, 24))

    def test_unrelated_address_is_dropped(self):
        self.monitor.set_address_filter(frozenset([b"\x7f\x00\x00\x01"]))
        address = self._ipv4_payload(b"\x0a\x00\x00\x01", b"\xc0\xa8\x01\x01")
        self.assertFalse(self.monitor._address_matches(bw.SEND_IPV4, address, 24))

    def test_ipv6_addresses_are_compared(self):
        v6 = bytes(range(16))
        self.monitor.set_address_filter(frozenset([v6]))
        payload = struct.pack("<II", 100, 50) + v6 + (b"\x00" * 16) + b"\x00" * 8
        self._keepalive = ctypes.create_string_buffer(payload)
        self.assertTrue(
            self.monitor._address_matches(
                bw.SEND_IPV6, ctypes.addressof(self._keepalive), 48
            )
        )


class TestSampling(unittest.TestCase):
    def setUp(self):
        self.monitor = bw.NetworkBandwidthMonitor()

    def test_first_call_establishes_a_baseline(self):
        self.monitor._totals = {1: 1000}
        with patch.object(bw.time, "monotonic", return_value=100.0):
            self.assertEqual(self.monitor.sample(), {})

    def test_rate_is_kilobytes_per_second(self):
        self.monitor._totals = {1: 10240}
        with patch.object(bw.time, "monotonic", return_value=100.0):
            self.monitor.sample()

        self.monitor._totals = {1: 10240 + 20480}
        with patch.object(bw.time, "monotonic", return_value=110.0):
            result = self.monitor.sample()

        self.assertEqual(result, {"1": {"bandwidth": 2.0}})

    def test_inactive_process_is_not_reported(self):
        self.monitor._totals = {1: 10240, 2: 4096}
        with patch.object(bw.time, "monotonic", return_value=100.0):
            self.monitor.sample()

        with patch.object(bw.time, "monotonic", return_value=110.0):
            result = self.monitor.sample()

        self.assertEqual(result, {})

    def test_retain_forgets_untracked_processes(self):
        self.monitor._totals = {1: 10240, 2: 4096, 3: 8192}
        self.monitor._last_totals = {1: 0, 2: 0, 3: 0}

        self.monitor.retain({"1", "3"})

        self.assertEqual(self.monitor._totals, {1: 10240, 3: 8192})
        self.assertEqual(self.monitor._last_totals, {1: 0, 3: 0})


class TestStartupDegradation(unittest.TestCase):
    def test_a_failed_session_reports_nothing(self):
        monitor = bw.NetworkBandwidthMonitor()
        with patch.object(bw, "_EtwFunctions", side_effect=OSError("denied")):
            self.assertFalse(monitor.start())
        self.assertFalse(monitor.is_running)
        self.assertEqual(monitor.sample(), {})

    def test_a_failed_session_is_not_retried(self):
        monitor = bw.NetworkBandwidthMonitor()
        with patch.object(bw, "_EtwFunctions", side_effect=OSError("denied")):
            self.assertFalse(monitor.start())
        with patch.object(bw, "_EtwFunctions", side_effect=AssertionError("retried")):
            self.assertFalse(monitor.start())


class TestInterfaceAddresses(unittest.TestCase):
    def test_empty_prefix_list_samples_every_interface(self):
        self.assertIsNone(bw.packed_interface_addresses([]))

    def test_matching_interfaces_are_packed(self):
        fake = {
            "Ethernet": [SnicAddress(socket.AF_INET, "10.0.0.5")],
            "Wi-Fi": [SnicAddress(socket.AF_INET, "192.168.1.10")],
        }
        with patch("psutil.net_if_addrs", return_value=fake):
            result = bw.packed_interface_addresses(["Ethernet"])
        self.assertIn(socket.inet_pton(socket.AF_INET, "10.0.0.5"), result)
        self.assertNotIn(socket.inet_pton(socket.AF_INET, "192.168.1.10"), result)

    def test_prefix_matching_is_case_insensitive(self):
        fake = {
            "ethernet 2": [SnicAddress(socket.AF_INET, "10.0.0.6")],
        }
        with patch("psutil.net_if_addrs", return_value=fake):
            result = bw.packed_interface_addresses(["ETHERNET"])
        self.assertIn(socket.inet_pton(socket.AF_INET, "10.0.0.6"), result)


@unittest.skipUnless(IS_WINDOWS, "services.py imports Windows-only media deps")
class TestGetBandwidthStats(unittest.TestCase):
    """The services-layer filter that keeps the stat to camera traffic."""

    def _config(self, enabled: bool):
        config = MagicMock()
        config.telemetry.stats.network_bandwidth = enabled
        config.telemetry.network_interfaces = []
        return config

    def test_only_camera_pipeline_processes_are_reported(self):
        from frigate.util import services

        monitor = bw.NetworkBandwidthMonitor()
        processes = [
            {
                "pid": 100,
                "name": "ffmpeg.exe",
                "cmdline": ["ffmpeg", "-i", "rtsp://cam"],
            },
            {"pid": 200, "name": "go2rtc.exe", "cmdline": ["go2rtc"]},
            {"pid": 300, "name": "chrome.exe", "cmdline": ["chrome"]},
        ]
        samples = {
            "100": {"bandwidth": 1.0},
            "200": {"bandwidth": 1.0},
            "300": {"bandwidth": 1.0},
        }

        with (
            patch.object(
                services, "get_network_bandwidth_monitor", return_value=monitor
            ),
            patch.object(services.psutil, "process_iter", return_value=processes),
            patch.object(monitor, "start", return_value=True),
            patch.object(monitor, "sample", return_value=samples),
        ):
            result = services.get_bandwidth_stats(self._config(True))

        self.assertEqual(set(result), {"100", "200"})

    def test_disabled_stats_are_empty(self):
        from frigate.util import services

        with patch.object(services, "get_network_bandwidth_monitor") as get_monitor:
            self.assertEqual(services.get_bandwidth_stats(self._config(False)), {})
        get_monitor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
