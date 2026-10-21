"""Tests for native Windows hardware-stat collection."""

import unittest
from unittest.mock import patch, MagicMock

from frigate.stats.hardware import (
    _hwaccel_hardware,
    _poll_nvidia,
    _poll_intel_gpu,
    _poll_amd_gpu,
    _present_gpu,
    _wmi_service,
    _gpu_vendor_indices,
    _query_wmi_gpu_engines,
    _query_wmi_gpu_memory,
)


class TestHardwareStats(unittest.TestCase):
    def test_hwaccel_hardware_detects_nvidia_and_intel(self) -> None:
        self.assertEqual(_hwaccel_hardware("preset-windows-nvenc"), "nvidia")
        self.assertEqual(_hwaccel_hardware("-hwaccel cuda"), "nvidia")
        self.assertEqual(_hwaccel_hardware("windows-qsv"), "intel")
        self.assertIsNone(_hwaccel_hardware("preset-windows-d3d11va"))
        self.assertIsNone(_hwaccel_hardware(""))

    def test_present_gpu_returns_vendor_set(self) -> None:
        with patch(
            "frigate.stats.hardware._present_hardware",
            return_value={"cpu", "onnx:nvidia"},
        ):
            self.assertEqual(_present_gpu(), {"nvidia"})

        with patch(
            "frigate.stats.hardware._present_hardware",
            return_value={"cpu", "openvino:GPU.0"},
        ):
            self.assertEqual(_present_gpu(), {"intel"})

        with patch(
            "frigate.stats.hardware._present_hardware",
            return_value={"cpu", "onnx:directml:0"},
        ):
            self.assertIn("amd", _present_gpu())

        with patch(
            "frigate.stats.hardware._present_hardware",
            return_value={"cpu"},
        ):
            self.assertEqual(_present_gpu(), set())

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
        with patch("frigate.stats.hardware.get_nvidia_gpu_stats", return_value=raw):
            result = _poll_nvidia(None)  # type: ignore[arg-type]

        self.assertTrue(result.ok)
        self.assertEqual(result.gpu["NVIDIA GeForce"]["gpu"], "12.35%")
        self.assertEqual(result.gpu["NVIDIA GeForce"]["mem"], "23.46%")
        self.assertEqual(result.gpu["NVIDIA GeForce"]["temp"], "55")

    def test_empty_nvml_result_enters_cooldown(self) -> None:
        with patch("frigate.stats.hardware.get_nvidia_gpu_stats", return_value={}):
            result = _poll_nvidia(None)  # type: ignore[arg-type]

        self.assertFalse(result.ok)
        self.assertIn("nvidia-gpu", result.gpu)

    def test_wmi_service_unavailable_returns_none(self) -> None:
        with patch("win32com.client.GetObject", side_effect=Exception("no WMI")):
            self.assertIsNone(_wmi_service())

    def test_gpu_vendor_indices_mapping(self) -> None:
        mock_wmi = MagicMock()
        mock_controller = MagicMock()
        mock_controller.Name = "NVIDIA GeForce RTX 3060"
        mock_controller.VideoProcessor = "NVIDIA"
        mock_wmi.ExecQuery.return_value = [mock_controller]

        indices = _gpu_vendor_indices(mock_wmi)
        self.assertIn("nvidia", indices)
        self.assertEqual(indices["nvidia"], [0])

    def test_wmi_engine_query_filters_by_vendor(self) -> None:
        mock_wmi = MagicMock()
        mock_entry = MagicMock()
        mock_entry.Name = "GPU 0: 3D"
        mock_entry.UtilizationPercentage = 42.5
        mock_wmi.ExecQuery.return_value = [mock_entry]

        vendor_indices = {"nvidia": [0], "intel": [], "amd": []}
        engines = _query_wmi_gpu_engines(mock_wmi, vendor_indices)
        self.assertEqual(engines.get(0, {}).get("3D"), 42.5)

    def test_wmi_memory_query_filters_by_vendor(self) -> None:
        mock_wmi = MagicMock()
        mock_entry = MagicMock()
        mock_entry.Name = "GPU 0: Dedicated GPU Memory"
        mock_entry.DedicatedUsagePercentage = 55.0
        mock_wmi.ExecQuery.return_value = [mock_entry]

        vendor_indices = {"nvidia": [0], "intel": [], "amd": []}
        memories = _query_wmi_gpu_memory(mock_wmi, vendor_indices)
        self.assertEqual(memories.get(0), 55.0)

    def test_intel_poller_returns_empty_when_no_intel_adapter(self) -> None:
        with patch("frigate.stats.hardware._wmi_service", return_value=None):
            result = _poll_intel_gpu(None)  # type: ignore[arg-type]
        self.assertFalse(result.ok)

    def test_amd_poller_returns_empty_when_no_amd_adapter(self) -> None:
        with patch("frigate.stats.hardware._wmi_service", return_value=None):
            result = _poll_amd_gpu(None)  # type: ignore[arg-type]
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()