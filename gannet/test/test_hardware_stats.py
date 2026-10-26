"""Tests for native Windows hardware-stat collection."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gannet.stats.hardware import (
    HardwareStats,
    WindowsGpuAdapter,
    _hwaccel_hardware,
    _poll_amd_gpu,
    _poll_intel_gpu,
    _poll_nvidia,
    _poll_wmi_gpu_stats,
    _present_gpu,
    _query_wmi_gpu_engines,
    _query_wmi_gpu_memory,
    _windows_gpu_adapters,
    _wmi_service,
)

INTEL_LUID = 0x0000000100001234
AMD_LUID = 0x0000000200005678
INTEL_ADAPTER = WindowsGpuAdapter(
    luid=INTEL_LUID,
    name="Intel(R) UHD Graphics 770",
    vendor="intel",
    dedicated_memory=1_000_000_000,
)
AMD_ADAPTER = WindowsGpuAdapter(
    luid=AMD_LUID,
    name="AMD Radeon RX 6600",
    vendor="amd",
    dedicated_memory=8_000_000_000,
)


def _engine_name(
    luid: int,
    pid: int = 100,
    phys: int = 0,
    eng: int = 0,
    engine_type: str = "3D",
) -> str:
    high = (luid >> 32) & 0xFFFFFFFF
    low = luid & 0xFFFFFFFF
    return (
        f"pid_{pid}_luid_0x{high:08x}_0x{low:08x}_"
        f"phys_{phys}_eng_{eng}_engtype_{engine_type}"
    )


def _memory_name(luid: int, phys: int = 0) -> str:
    high = (luid >> 32) & 0xFFFFFFFF
    low = luid & 0xFFFFFFFF
    return f"luid_0x{high:08x}_0x{low:08x}_phys_{phys}"


def _counter(name: str, **attributes) -> MagicMock:
    entry = MagicMock()
    entry.Name = name
    for key, value in attributes.items():
        setattr(entry, key, value)
    return entry


class TestHardwareStats(unittest.TestCase):
    def test_hwaccel_hardware_detects_vendor_specific_families(self) -> None:
        for args, vendor in (
            ("preset-windows-nvenc", "nvidia"),
            ("-hwaccel cuda", "nvidia"),
            ("-c:v h264_nvenc", "nvidia"),
            ("windows-qsv", "intel"),
            ("-hwaccel qsv -c:v h264_qsv", "intel"),
            ("preset-windows-amf", "amd"),
            ("-c:v hevc_amf", "amd"),
        ):
            with self.subTest(args=args):
                self.assertEqual(_hwaccel_hardware(args), vendor)

        self.assertIsNone(_hwaccel_hardware("preset-windows-d3d11va"))
        self.assertIsNone(_hwaccel_hardware(""))

    def _present_hardware(self, hardware: set[str], adapters: set[str]) -> set[str]:
        with (
            patch(
                "gannet.stats.hardware._present_hardware",
                return_value=hardware,
            ),
            patch(
                "gannet.stats.hardware.get_display_adapter_vendors",
                return_value=adapters,
            ),
        ):
            return _present_gpu()

    def test_present_gpu_returns_vendor_set(self) -> None:
        self.assertEqual(
            self._present_hardware({"cpu", "onnx:nvidia"}, set()), {"nvidia"}
        )
        self.assertEqual(
            self._present_hardware({"cpu", "openvino:GPU.0"}, set()), {"intel"}
        )
        self.assertEqual(
            self._present_hardware(
                {"cpu", "onnx:windowsml:MIGraphXExecutionProvider"}, set()
            ),
            {"amd"},
        )
        self.assertEqual(self._present_hardware({"cpu"}, set()), set())

    def test_directml_uses_actual_adapter_vendors(self) -> None:
        self.assertEqual(
            self._present_hardware({"onnx:directml:0"}, {"intel"}), {"intel"}
        )
        self.assertEqual(self._present_hardware({"onnx:directml:0"}, {"amd"}), {"amd"})

    def test_nvidia_stats_are_normalized(self) -> None:
        raw = {
            0: {
                "name": "NVIDIA GeForce",
                "gpu": "12.345",
                "mem": "23.456",
                "enc": "1",
                "dec": "2",
                "temp": "55",
            }
        }
        with patch("gannet.stats.hardware.get_nvidia_gpu_stats", return_value=raw):
            result = _poll_nvidia(None)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(result.gpu["NVIDIA GeForce"]["gpu"], "12.35%")
        self.assertEqual(result.gpu["NVIDIA GeForce"]["mem"], "23.46%")
        self.assertEqual(result.gpu["NVIDIA GeForce"]["temp"], "55")

    def test_empty_nvml_result_enters_cooldown(self) -> None:
        with patch("gannet.stats.hardware.get_nvidia_gpu_stats", return_value={}):
            result = _poll_nvidia(None)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertIn("nvidia-gpu", result.gpu)

    def test_wmi_service_unavailable_returns_none(self) -> None:
        with patch("win32com.client.GetObject", side_effect=Exception("no WMI")):
            self.assertIsNone(_wmi_service())

    def test_directx_registry_adapters_are_keyed_by_luid(self) -> None:
        values = {
            "AdapterLuid": INTEL_LUID,
            "Description": INTEL_ADAPTER.name,
            "VendorId": 0x8086,
            "DedicatedVideoMemory": 750_000_000,
            "DedicatedSystemMemory": 250_000_000,
        }
        fake_winreg = MagicMock()
        root = MagicMock()
        key = MagicMock()
        root.__enter__.return_value = root
        key.__enter__.return_value = key
        fake_winreg.OpenKey.side_effect = (root, key)
        fake_winreg.QueryInfoKey.return_value = (1, 0, 0)
        fake_winreg.EnumKey.return_value = "{test-adapter}"
        fake_winreg.QueryValueEx.side_effect = lambda _key, name: (values[name], 0)

        with patch.dict(sys.modules, {"winreg": fake_winreg}):
            adapters = _windows_gpu_adapters()

        self.assertEqual(adapters, {INTEL_LUID: INTEL_ADAPTER})

    def test_wmi_engine_query_aggregates_real_instance_names(self) -> None:
        mock_wmi = MagicMock()
        mock_wmi.ExecQuery.return_value = [
            _counter(_engine_name(INTEL_LUID, pid=100), UtilizationPercentage=30),
            _counter(_engine_name(INTEL_LUID, pid=200), UtilizationPercentage="20"),
            _counter(
                _engine_name(INTEL_LUID, pid=300, eng=1),
                UtilizationPercentage=40,
            ),
            _counter(
                _engine_name(INTEL_LUID, pid=400, eng=2, engine_type="VideoDecode"),
                UtilizationPercentage=25,
            ),
            _counter(_engine_name(AMD_LUID), UtilizationPercentage=90),
            _counter("GPU 0: 3D", UtilizationPercentage=100),
        ]

        engines = _query_wmi_gpu_engines(mock_wmi, {INTEL_LUID: INTEL_ADAPTER})

        self.assertEqual(
            engines,
            {INTEL_LUID: {"3d": 50.0, "videodecode": 25.0}},
        )
        query = mock_wmi.ExecQuery.call_args.args[0]
        self.assertIn("GpuPerformanceCounters_GpuEngine", query)
        self.assertIn("UtilizationPercentage", query)

    def test_wmi_engine_query_ignores_invalid_samples(self) -> None:
        mock_wmi = MagicMock()
        mock_wmi.ExecQuery.return_value = [
            _counter(_engine_name(INTEL_LUID), UtilizationPercentage=float("nan")),
            _counter(_engine_name(INTEL_LUID), UtilizationPercentage=-1),
            _counter(_engine_name(INTEL_LUID), UtilizationPercentage="invalid"),
            _counter(_engine_name(INTEL_LUID), UtilizationPercentage=10),
        ]

        engines = _query_wmi_gpu_engines(mock_wmi, {INTEL_LUID: INTEL_ADAPTER})

        self.assertEqual(engines, {INTEL_LUID: {"3d": 10.0}})

    def test_wmi_memory_query_reads_adapter_dedicated_bytes(self) -> None:
        mock_wmi = MagicMock()
        mock_wmi.ExecQuery.return_value = [
            _counter(_memory_name(INTEL_LUID), DedicatedUsage="250000000"),
            _counter(_memory_name(AMD_LUID), DedicatedUsage=4_000_000_000),
            _counter("GPU 0: Dedicated GPU Memory", DedicatedUsage=1),
        ]

        usage = _query_wmi_gpu_memory(mock_wmi, {INTEL_LUID: INTEL_ADAPTER})

        self.assertEqual(usage, {INTEL_LUID: 250_000_000.0})
        query = mock_wmi.ExecQuery.call_args.args[0]
        self.assertIn("GpuPerformanceCounters_GpuAdapterMemory", query)
        self.assertIn("DedicatedUsage", query)
        self.assertNotIn("DedicatedUsagePercentage", query)

    def test_wmi_poller_normalizes_counter_values(self) -> None:
        mock_wmi = MagicMock()

        def exec_query(query: str):
            if "GpuAdapterMemory" in query:
                return [_counter(_memory_name(INTEL_LUID), DedicatedUsage=250_000_000)]
            return [
                _counter(_engine_name(INTEL_LUID, pid=100), UtilizationPercentage=30),
                _counter(_engine_name(INTEL_LUID, pid=200), UtilizationPercentage=20),
                _counter(
                    _engine_name(INTEL_LUID, eng=1, engine_type="Compute"),
                    UtilizationPercentage=15,
                ),
                _counter(
                    _engine_name(INTEL_LUID, eng=2, engine_type="VideoDecode"),
                    UtilizationPercentage=5,
                ),
                _counter(
                    _engine_name(INTEL_LUID, eng=3, engine_type="VideoEncode"),
                    UtilizationPercentage=10,
                ),
            ]

        mock_wmi.ExecQuery.side_effect = exec_query
        with (
            patch("gannet.stats.hardware._wmi_service", return_value=mock_wmi),
            patch(
                "gannet.stats.hardware._windows_gpu_adapters",
                return_value={INTEL_LUID: INTEL_ADAPTER},
            ),
        ):
            result = _poll_wmi_gpu_stats(None, "intel")  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        stats = result.gpu[INTEL_ADAPTER.name]
        self.assertEqual(stats["vendor"], "intel")
        self.assertEqual(stats["gpu"], "50.0%")
        self.assertEqual(stats["mem"], "25.0%")
        self.assertEqual(stats["compute"], "65.0%")
        self.assertEqual(stats["dec"], "5.0%")
        self.assertEqual(stats["enc"], "10.0%")

    def test_wmi_poller_does_not_overwrite_identical_adapter_names(self) -> None:
        second_luid = INTEL_LUID + 1
        second_adapter = WindowsGpuAdapter(
            luid=second_luid,
            name=INTEL_ADAPTER.name,
            vendor="intel",
            dedicated_memory=1_000_000_000,
        )
        adapters = {INTEL_LUID: INTEL_ADAPTER, second_luid: second_adapter}
        mock_wmi = MagicMock()
        mock_wmi.ExecQuery.side_effect = lambda query: (
            [
                _counter(_memory_name(INTEL_LUID), DedicatedUsage=100_000_000),
                _counter(_memory_name(second_luid), DedicatedUsage=200_000_000),
            ]
            if "GpuAdapterMemory" in query
            else []
        )

        with (
            patch("gannet.stats.hardware._wmi_service", return_value=mock_wmi),
            patch(
                "gannet.stats.hardware._windows_gpu_adapters", return_value=adapters
            ),
        ):
            result = _poll_wmi_gpu_stats(None, "intel")  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(len(result.gpu), 2)
        self.assertEqual(
            {entry["mem"] for entry in result.gpu.values()}, {"10.0%", "20.0%"}
        )

    def test_wmi_poller_reports_query_failure(self) -> None:
        mock_wmi = MagicMock()
        mock_wmi.ExecQuery.side_effect = Exception("counters unavailable")
        with (
            patch("gannet.stats.hardware._wmi_service", return_value=mock_wmi),
            patch(
                "gannet.stats.hardware._windows_gpu_adapters",
                return_value={INTEL_LUID: INTEL_ADAPTER},
            ),
        ):
            result = _poll_wmi_gpu_stats(None, "intel")  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertEqual(result.gpu, {})

    def test_intel_poller_returns_empty_when_wmi_is_unavailable(self) -> None:
        with patch("gannet.stats.hardware._wmi_service", return_value=None):
            result = _poll_intel_gpu(None)  # type: ignore[arg-type]
        self.assertFalse(result.ok)

    def test_amd_poller_returns_empty_when_wmi_is_unavailable(self) -> None:
        with patch("gannet.stats.hardware._wmi_service", return_value=None):
            result = _poll_amd_gpu(None)  # type: ignore[arg-type]
        self.assertFalse(result.ok)

    def test_vendor_neutral_hwaccel_enables_present_gpu_pollers(self) -> None:
        stats = HardwareStats.__new__(HardwareStats)
        stats.config = SimpleNamespace(
            cameras={
                "front": SimpleNamespace(
                    ffmpeg=SimpleNamespace(
                        hwaccel_args="preset-windows-d3d11va", inputs=[]
                    )
                )
            }
        )

        with patch(
            "gannet.stats.hardware._present_gpu", return_value={"intel", "amd"}
        ):
            self.assertEqual(stats._scan_ffmpeg(), {"intel", "amd"})

    def test_amf_hwaccel_enables_amd_poller(self) -> None:
        stats = HardwareStats.__new__(HardwareStats)
        stats.config = SimpleNamespace(
            cameras={
                "front": SimpleNamespace(
                    ffmpeg=SimpleNamespace(hwaccel_args="preset-windows-amf", inputs=[])
                )
            }
        )

        self.assertEqual(stats._scan_ffmpeg(), {"amd"})


if __name__ == "__main__":
    unittest.main()
