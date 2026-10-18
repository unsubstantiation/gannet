"""Tests for the native Windows video hardware report behind ``/api/gpuinfo``."""

import subprocess as sp
import unittest
from unittest.mock import patch

from frigate.util import services

HWACCELS_OUTPUT = """Hardware acceleration methods:
cuda
dxva2
qsv
d3d11va
vulkan
"""


class TestFfmpegHwaccels(unittest.TestCase):
    def test_parses_ffmpeg_hwaccels_listing(self) -> None:
        completed = sp.CompletedProcess(
            args=["ffmpeg.exe"], returncode=0, stdout=HWACCELS_OUTPUT, stderr=""
        )
        with patch.object(services.sp, "run", return_value=completed) as run:
            hwaccels = services.get_ffmpeg_hwaccels(r"C:\Frigate\ffmpeg\ffmpeg.exe")

        self.assertEqual(hwaccels, ["cuda", "dxva2", "qsv", "d3d11va", "vulkan"])
        self.assertEqual(
            run.call_args.args[0],
            [r"C:\Frigate\ffmpeg\ffmpeg.exe", "-hide_banner", "-hwaccels"],
        )

    def test_missing_ffmpeg_reports_no_hwaccels(self) -> None:
        with patch.object(services.sp, "run", side_effect=FileNotFoundError):
            self.assertEqual(services.get_ffmpeg_hwaccels("missing.exe"), [])

    def test_hung_ffmpeg_reports_no_hwaccels(self) -> None:
        with patch.object(
            services.sp, "run", side_effect=sp.TimeoutExpired(cmd="ffmpeg", timeout=10)
        ):
            self.assertEqual(services.get_ffmpeg_hwaccels("ffmpeg.exe"), [])


class TestWindowsGpuInfo(unittest.TestCase):
    def _info(
        self,
        adapters: list[str],
        vendors: set[str],
        go2rtc_sources: list[dict[str, str]],
    ) -> dict:
        from frigate.util import hwaccel

        with (
            patch.object(hwaccel, "get_display_adapters", return_value=adapters),
            patch.object(hwaccel, "get_display_adapter_vendors", return_value=vendors),
            patch.object(hwaccel, "get_cpu_brand", return_value=""),
            patch("frigate.util.platform.get_display_adapters", return_value=adapters),
            patch(
                "frigate.util.platform.get_display_adapter_vendors",
                return_value=vendors,
            ),
            patch(
                "frigate.util.platform.get_cpu_brand",
                return_value="Intel(R) Core(TM) i5-13500",
            ),
            patch.object(
                services, "get_go2rtc_hardware_sources", return_value=go2rtc_sources
            ),
            patch.object(services, "get_ffmpeg_hwaccels", return_value=["d3d11va"]),
            patch.object(
                services,
                "get_nvidia_driver_info",
                return_value={0: {"name": "NVIDIA GeForce", "driver": "560.94"}},
            ),
        ):
            return services.get_windows_gpu_info("ffmpeg.exe")

    def test_intel_machine_reports_windows_presets(self) -> None:
        info = self._info(
            ["Intel(R) UHD Graphics 770"],
            {"intel"},
            [{"name": "OK", "url": "ffmpeg:...#hardware=qsv"}],
        )

        self.assertEqual(info["adapters"], ["Intel(R) UHD Graphics 770"])
        self.assertEqual(info["vendors"], ["intel"])
        self.assertEqual(info["cpu"], "Intel(R) Core(TM) i5-13500")
        self.assertEqual(info["ffmpeg_hwaccels"], ["d3d11va"])
        self.assertEqual(info["recommended"], "preset-windows-qsv")
        self.assertEqual(
            info["go2rtc_hardware"],
            [{"name": "OK", "url": "ffmpeg:...#hardware=qsv"}],
        )
        keys = [family["key"] for family in info["decoders"]]
        self.assertIn("windows-qsv", keys)
        self.assertIn("windows-d3d11va", keys)
        for family in info["decoders"]:
            for preset in family["presets"].values():
                self.assertTrue(preset.startswith("preset-windows-"))
        self.assertNotIn("nvidia", info)

    def test_nvidia_machine_includes_driver_info(self) -> None:
        info = self._info(["NVIDIA GeForce RTX 3060"], {"nvidia"}, [])

        self.assertEqual(info["recommended"], "preset-windows-nvenc")
        self.assertEqual(info["nvidia"][0]["driver"], "560.94")

    def test_machine_without_adapters_recommends_software(self) -> None:
        info = self._info([], set(), [])

        self.assertEqual(info["adapters"], [])
        self.assertEqual(info["decoders"], [])
        self.assertEqual(info["recommended"], "")

    def test_report_is_json_serializable(self) -> None:
        import json

        info = self._info(["AMD Radeon RX 6600"], {"amd"}, [])
        json.dumps(info)
        self.assertEqual(info["recommended"], "preset-windows-d3d11va")


if __name__ == "__main__":
    unittest.main()
