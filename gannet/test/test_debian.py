# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Debian platform, secret storage, privilege boundary, and process regressions."""

import base64
import importlib
import io
import json
import os
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gannet.util import platform
from gannet.util.wireguard_debian import HELPER, DebianWireGuardManager

KEY = base64.b64encode(b"x" * 32).decode()
CONFIG = f"[Interface]\nPrivateKey={KEY}\nAddress=10.20.0.2/32\n[Peer]\nPublicKey={KEY}\nAllowedIPs=192.168.50.0/24\nEndpoint=vpn.example.com:51820\n"
TUNNEL_ID = "0123456789abcdef"
bootstrap_debian = importlib.import_module("bootstrap_debian")


@patch.object(platform, "IS_WINDOWS", False)
class TestDebianPlatform(unittest.TestCase):
    def test_native_executable_and_shell_roundtrip(self):
        self.assertEqual(platform.executable_name("ffmpeg"), "ffmpeg")
        args = ["/opt/tools with spaces/ffmpeg", "a'b", 'a"b', "$HOME;echo bad", ""]
        command = " ".join(platform.quote_ffmpeg_arg(arg) for arg in args)
        self.assertEqual(platform.split_ffmpeg_command(command), args)

    def test_concat_preserves_native_backslashes(self):
        self.assertEqual(
            platform.ffmpeg_concat_file_line(r"/media/cam\archive.mp4"),
            r"file '/media/cam\archive.mp4'",
        )

    def test_xdg_default_and_environment_override(self):
        with patch.dict(
            os.environ,
            {"XDG_DATA_HOME": "/data", "GANNET_BASE_DIR": "", "FRIGATE_BASE_DIR": ""},
        ):
            self.assertEqual(platform.get_base_dir(), os.path.abspath("/data/gannet"))
        with patch.dict(os.environ, {"GANNET_BASE_DIR": "/var/lib/gannet"}):
            self.assertEqual(
                platform.get_base_dir(), os.path.abspath("/var/lib/gannet")
            )

    def test_supported_host_and_rejection(self):
        with (
            patch.object(platform.sys, "platform", "linux"),
            patch.object(platform.sys, "version_info", (3, 12, 0)),
            patch.object(platform.platform, "machine", return_value="x86_64"),
            patch.object(
                platform.platform,
                "freedesktop_os_release",
                return_value={"ID": "debian", "VERSION_ID": "13"},
            ) as release,
        ):
            platform.require_supported_platform()
            for unsupported in (
                {"ID": "debian", "VERSION_ID": "12"},
                {"ID": "ubuntu", "VERSION_ID": "26.04"},
            ):
                release.return_value = unsupported
                with self.assertRaises(platform.UnsupportedPlatformError):
                    platform.require_supported_platform()
            release.return_value = {"ID": "debian", "VERSION_ID": "13"}
            with (
                patch.object(platform.platform, "machine", return_value="aarch64"),
                self.assertRaises(platform.UnsupportedPlatformError),
            ):
                platform.require_supported_platform()
            with (
                patch.object(platform.sys, "version_info", (3, 13, 0)),
                self.assertRaises(platform.UnsupportedPlatformError),
            ):
                platform.require_supported_platform()

    def test_sigterm_stops_service(self):
        event = Mock()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(signal, "signal") as install,
        ):
            platform.install_signal_handlers(event)
        callbacks = dict(call.args for call in install.call_args_list)
        callbacks[signal.SIGTERM](signal.SIGTERM, None)
        event.set.assert_called_once()

    def test_spawn_and_windows_watchers_remain_portable(self):
        self.assertEqual(platform.get_mp_start_method(), "spawn")
        self.assertFalse(platform.install_service_stop_watcher(Mock()))

    def test_priority_uses_posix_nice_not_windows_classes(self):
        with patch("psutil.Process") as process:
            platform.set_process_priority(5)
        process.return_value.nice.assert_called_once_with(5)

    def test_ffmpeg_native_directory_resolution(self):
        from gannet.util.config import resolve_ffmpeg_path

        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "ffmpeg"
            binary.touch()
            with (
                patch("gannet.util.config.IS_WINDOWS", False),
                patch("gannet.util.config.EXECUTABLE_SUFFIX", ""),
            ):
                self.assertEqual(resolve_ffmpeg_path(directory), str(binary))

    def test_no_windows_hardware_auto_selection(self):
        from gannet.util import hwaccel, services

        with patch.object(hwaccel, "IS_WINDOWS", False):
            with (
                patch.object(hwaccel, "linux_render_node", return_value=None),
                patch.object(
                    hwaccel, "get_display_adapter_vendors", return_value=set()
                ),
            ):
                self.assertEqual(hwaccel.hwaccel_options("onnx:CPU"), ("", []))
        with (
            patch.object(hwaccel, "windows_hwaccel_preset") as windows,
            patch.object(services, "get_go2rtc_hardware_sources", return_value=[]),
        ):
            self.assertEqual(services.auto_detect_hwaccel(), "")
            windows.assert_not_called()

    def test_presets_reject_windows_devices_but_accept_native_raw_args(self):
        from gannet.ffmpeg_presets import PRESETS_HW_ACCEL_DECODE, validate_ffmpeg_args

        with patch("gannet.ffmpeg_presets.IS_WINDOWS", False):
            validate_ffmpeg_args(
                ["-threads", "2"], "ffmpeg.hwaccel_args", PRESETS_HW_ACCEL_DECODE
            )
            with self.assertRaises(ValueError):
                validate_ffmpeg_args(
                    "preset-windows-d3d11va",
                    "ffmpeg.hwaccel_args",
                    PRESETS_HW_ACCEL_DECODE,
                )
            with self.assertRaises(ValueError):
                validate_ffmpeg_args(
                    ["-hwaccel", "d3d11va"],
                    "ffmpeg.hwaccel_args",
                    PRESETS_HW_ACCEL_DECODE,
                )

    def test_go2rtc_has_no_windows_creationflags(self):
        from gannet.util.go2rtc_process import Go2rtcProcess

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("gannet.util.go2rtc_process.IS_WINDOWS", False),
            patch(
                "gannet.util.go2rtc_process.find_go2rtc", return_value="/usr/bin/go2rtc"
            ),
            patch(
                "gannet.util.go2rtc_process.prepare_homekit_config",
                return_value="/etc/gannet/homekit.yml",
            ),
            patch(
                "gannet.util.go2rtc_process.get_service_log_path",
                return_value=str(Path(directory) / "go2rtc.log"),
            ),
            patch("gannet.util.go2rtc_process.sp.Popen") as popen,
        ):
            process = Go2rtcProcess("/etc/gannet/go2rtc.yml")
            self.assertTrue(process.start())
            self.assertNotIn("creationflags", popen.call_args.kwargs)
            process.stop()

    def test_config_ui_does_not_offer_windows_decoders(self):
        from gannet.api.app import ffmpeg_presets
        from gannet.ffmpeg_presets import LINUX_DECODE_PRESETS

        self.assertEqual(
            json.loads(ffmpeg_presets().body)["hwaccel_args"], LINUX_DECODE_PRESETS
        )

    def test_backend_dispatch(self):
        from gannet.util.wireguard import WireGuardManager

        with patch("gannet.util.wireguard.IS_WINDOWS", False):
            self.assertIsInstance(WireGuardManager(), DebianWireGuardManager)


@patch.object(platform, "IS_WINDOWS", False)
class TestDebianAcceleration(unittest.TestCase):
    def test_pci_adapters_use_driver_vendor_not_windows_api(self):
        with tempfile.TemporaryDirectory() as directory:
            device = Path(directory) / "0000:03:00.0"
            device.mkdir()
            for name, value in {
                "class": "0x030200",
                "vendor": "0x10de",
                "device": "0x1234",
            }.items():
                (device / name).write_text(value)
            with patch.object(platform.Path, "glob", return_value=[device]):
                self.assertEqual(
                    platform.linux_display_adapters(), ["NVIDIA 0x1234 (0000:03:00.0)"]
                )

    def test_render_node_requires_access_and_matching_vendor(self):
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / "renderD129"
            (node / "device").mkdir(parents=True)
            (node / "device/vendor").write_text("0x8086")
            with (
                patch.object(platform.Path, "glob", return_value=[node]),
                patch.object(os, "access", return_value=True) as access,
            ):
                self.assertEqual(
                    platform.linux_render_node("intel"), "/dev/dri/renderD129"
                )
                self.assertIsNone(platform.linux_render_node("amd"))
                access.return_value = False
                self.assertIsNone(platform.linux_render_node("intel"))

    def test_no_gpu_gives_cpu_and_intel_offers_qsv_and_vaapi(self):
        from gannet.util import hwaccel

        with (
            patch.object(hwaccel, "IS_WINDOWS", False),
            patch.object(
                hwaccel, "get_display_adapter_vendors", return_value={"intel"}
            ),
            patch.object(
                hwaccel, "linux_render_node", return_value="/dev/dri/renderD129"
            ),
        ):
            key, families = hwaccel.hwaccel_options(codecs={"h264"})
            self.assertEqual(key, "intel-qsv")
            self.assertEqual(
                [family.key for family in families], ["intel-qsv", "vaapi"]
            )
            self.assertEqual(hwaccel.hwaccel_options(codecs={"av1"})[0], "vaapi")
            self.assertEqual(hwaccel.hwaccel_options()[0], "vaapi")

    def test_auto_requires_successful_probe_not_just_compiled_support(self):
        from gannet.util.hwaccel import linux_hwaccel_preset

        self.assertEqual(linux_hwaccel_preset([]), "")
        self.assertEqual(
            linux_hwaccel_preset(
                [{"name": "ERROR", "url": "ffmpeg:camera#hardware=cuda"}]
            ),
            "",
        )
        self.assertEqual(
            linux_hwaccel_preset(
                [{"name": "OK", "url": "ffmpeg:camera#hardware=cuda"}]
            ),
            "preset-nvidia",
        )

    def test_linux_preset_validation_and_hardware_download_filters(self):
        from gannet import ffmpeg_presets as presets

        with (
            patch.object(presets, "IS_WINDOWS", False),
            patch.object(
                presets, "linux_render_node", return_value="/dev/dri/renderD129"
            ),
        ):
            for name in presets.LINUX_DECODE_PRESETS:
                presets.validate_ffmpeg_args(
                    name, "ffmpeg.hwaccel_args", presets.PRESETS_HW_ACCEL_DECODE
                )
                args = presets.parse_preset_hardware_acceleration_decode(
                    name, 5, 640, 360, 0
                )
                self.assertNotIn("d3d11va", args)
                if "qsv" in name or "vaapi" in name:
                    self.assertIn("/dev/dri/renderD129", args)
                scale = presets.parse_preset_hardware_acceleration_scale(
                    name, ["-f", "rawvideo"], 5, 640, 360
                )
                self.assertIn("hwdownload", " ".join(scale))
            presets.validate_ffmpeg_args(
                "preset-vaapi",
                "record.export.hwaccel_args",
                presets.PRESETS_HW_ACCEL_ENCODE_TIMELAPSE,
            )
            with (
                patch.object(presets, "IS_WINDOWS", True),
                self.assertRaises(ValueError),
            ):
                presets.validate_ffmpeg_args(
                    "preset-vaapi",
                    "ffmpeg.hwaccel_args",
                    presets.PRESETS_HW_ACCEL_DECODE,
                )

    def test_vaapi_export_keeps_speed_scale_and_quoted_paths(self):
        from gannet import ffmpeg_presets as presets

        with (
            patch.object(presets, "IS_WINDOWS", False),
            patch.object(
                presets, "linux_render_node", return_value="/dev/dri/renderD129"
            ),
        ):
            command = presets.parse_preset_hardware_acceleration_encode(
                "/opt/tools/ffmpeg",
                "preset-vaapi",
                "-i '/media/camera one.mp4' -vf setpts=PTS/4",
                "-vf scale=640:360 -an '/media/export one.mp4'",
                presets.EncodeTypeEnum.timelapse,
            )
            tokens = platform.split_ffmpeg_command(command)
            self.assertEqual(tokens.count("-vf"), 1)
            self.assertIn("setpts=PTS/4,scale=640:360,format=nv12,hwupload", tokens)
            self.assertIn("h264_vaapi", tokens)
            self.assertEqual(tokens[-1], "/media/export one.mp4")

    def test_vaapi_complex_graph_uses_software_without_losing_graph(self):
        from gannet import ffmpeg_presets as presets

        with patch.object(presets, "IS_WINDOWS", False):
            command = presets.parse_preset_hardware_acceleration_encode(
                "ffmpeg",
                "preset-vaapi",
                "-i input.mp4",
                "-filter_complex scale=640:360 output.mp4",
                presets.EncodeTypeEnum.timelapse,
            )
        self.assertIn("libx264", command)
        self.assertIn("-filter_complex scale=640:360", command)

    def test_linux_driver_gauges_unknown_is_not_zero(self):
        from gannet.stats.hardware import _poll_linux_gpu

        with tempfile.TemporaryDirectory() as directory:
            card = Path(directory) / "card0"
            device = card / "device"
            device.mkdir(parents=True)
            for name, value in {
                "vendor": "0x1002",
                "gpu_busy_percent": "25",
                "mem_info_vram_used": "100",
                "mem_info_vram_total": "400",
            }.items():
                (device / name).write_text(value)
            with patch("gannet.stats.hardware.Path.glob", return_value=[card]):
                stats = _poll_linux_gpu("amd").gpu["amd-card0"]
                self.assertEqual(stats["gpu"], "25.00%")
                self.assertEqual(stats["mem"], "25.00%")
                (device / "gpu_busy_percent").unlink()
                self.assertEqual(_poll_linux_gpu("amd").gpu["amd-card0"]["gpu"], "")

    def test_service_device_permissions_and_exclusive_cuda_runtime(self):
        installer = (
            Path(__file__).resolve().parents[2] / "scripts/install_debian.sh"
        ).read_text()
        self.assertIn("for group in render video", installer)
        self.assertIn("usermod -aG", installer)
        self.assertLess(
            installer.index("pip uninstall --python"),
            installer.index("'onnxruntime-gpu[cuda,cudnn]"),
        )


class TestDebianWireGuardClient(unittest.TestCase):
    def test_create_sends_keys_only_over_stdin(self):
        result = subprocess.CompletedProcess(
            [], 0, '{"result":{"id":"0123456789abcdef"}}'
        )
        with patch(
            "gannet.util.wireguard_debian.subprocess.run", return_value=result
        ) as run:
            record = DebianWireGuardManager().create("Cabin", CONFIG)
        self.assertEqual(record["id"], TUNNEL_ID)
        self.assertEqual(
            run.call_args.args[0], ["/usr/bin/sudo", "-n", HELPER, "create"]
        )
        self.assertNotIn(KEY, " ".join(run.call_args.args[0]))
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["config"], CONFIG)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_missing_helper_is_actionable_and_never_leaks_output(self):
        with (
            patch(
                "gannet.util.wireguard_debian.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, [], stderr=KEY),
            ),
            self.assertRaises(RuntimeError) as failure,
        ):
            DebianWireGuardManager().start(TUNNEL_ID)
        self.assertNotIn(KEY, str(failure.exception))
        self.assertIn("helper", str(failure.exception))

    def test_invalid_id_never_runs_helper(self):
        for value in ("../../etc/shadow", "x;reboot", "0123456789abcdef.service"):
            with (
                patch("gannet.util.wireguard_debian.subprocess.run") as run,
                self.assertRaises(ValueError),
            ):
                DebianWireGuardManager().stop(value)
            run.assert_not_called()

    def test_privileged_mode_requires_root(self):
        with (
            patch("os.geteuid", return_value=1001, create=True),
            self.assertRaises(RuntimeError),
        ):
            DebianWireGuardManager(privileged=True)


@unittest.skipUnless(os.name == "posix", "Debian filesystem permission semantics")
class TestDebianWireGuardStore(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        with patch("os.geteuid", return_value=0):
            self.manager = DebianWireGuardManager(
                privileged=True, directory=Path(self.temporary.name) / "gannet"
            )
        self.command = patch.object(
            self.manager,
            "_systemctl",
            return_value=subprocess.CompletedProcess([], 3, "inactive\n"),
        )
        self.run = self.command.start()
        self.addCleanup(self.command.stop)

    def test_secrets_are_root_only_and_metadata_only_is_returned(self):
        record = self.manager.create("Cabin", CONFIG)
        tunnel_id = record["id"]
        self.assertEqual(len(tunnel_id), 16)
        self.assertLess(len(self.manager.interface(tunnel_id)), 16)
        self.assertEqual(self.manager._config(tunnel_id).stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            self.manager._metadata(tunnel_id).stat().st_mode & 0o777, 0o600
        )
        self.assertEqual(self.manager.directory.stat().st_mode & 0o777, 0o700)
        self.assertIn(KEY, self.manager._config(tunnel_id).read_text())
        self.assertNotIn(KEY, json.dumps(self.manager.list()))
        self.assertNotIn(KEY, json.dumps(self.manager.get(tunnel_id)))

    def test_lifecycle_calls_only_generated_service(self):
        tunnel_id = self.manager.create("Cabin", CONFIG)["id"]
        self.manager.start(tunnel_id)
        self.run.assert_called_with("start", tunnel_id)
        self.manager.stop(tunnel_id)
        self.run.assert_called_with("stop", tunnel_id)
        self.manager.delete(tunnel_id)
        self.assertFalse(self.manager._config(tunnel_id).exists())
        self.assertEqual(self.manager.list(), [])

    def test_duplicate_names_and_routes_are_rejected(self):
        self.manager.create("Cabin", CONFIG)
        for name, config in (("cabin", CONFIG), ("Other", CONFIG)):
            with self.assertRaises(ValueError):
                self.manager.create(name, config)

    def test_hooks_never_reach_systemd(self):
        with self.assertRaises(ValueError):
            self.manager.create(
                "Unsafe", CONFIG.replace("[Peer]", "PostUp=touch /tmp/unsafe\n[Peer]")
            )
        self.run.assert_not_called()
        tunnel_id = self.manager.create("Cabin", CONFIG)["id"]
        self.manager._config(tunnel_id).write_text(
            CONFIG.replace("[Peer]", "PostUp=touch /tmp/unsafe\n[Peer]")
        )
        with self.assertRaises(ValueError):
            self.manager.start(tunnel_id)
        self.run.assert_not_called()

    def test_private_write_refuses_symlinks(self):
        target = Path(self.temporary.name) / "target"
        target.write_text("unchanged")
        link = Path(self.temporary.name) / "link"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            self.manager._write_private(link, "secret")
        self.assertEqual(target.read_text(), "unchanged")


class TestDebianAssets(unittest.TestCase):
    def test_download_digest_checked_before_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "go2rtc"
            target.write_bytes(b"original")
            with (
                patch.object(
                    bootstrap_debian, "urlopen", return_value=io.BytesIO(b"tampered")
                ),
                self.assertRaises(ValueError),
            ):
                bootstrap_debian.verified_download(
                    "https://example.invalid/asset", target, "0" * 64
                )
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).glob(".download-*")), [])

    def test_systemd_runs_unprivileged_and_keeps_shutdown_containment(self):
        unit = (
            Path(__file__).resolve().parents[2] / "scripts/gannet.service"
        ).read_text()
        for setting in (
            "User=gannet",
            "KillMode=mixed",
            "KillSignal=SIGTERM",
            "Restart=always",
            "ProtectSystem=strict",
        ):
            self.assertIn(setting, unit)
        self.assertNotIn("User=root", unit)


if __name__ == "__main__":
    unittest.main()
