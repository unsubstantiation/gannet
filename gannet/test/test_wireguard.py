# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Portable validation/API tests; service operations are mocked, not Windows proof."""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gannet.api.wireguard import router
from gannet.util.wireguard import (
    WireGuardManager,
    start_camera_tunnels,
    validate_config,
)

KEY = base64.b64encode(bytes(range(32))).decode()
CONFIG = f"""[Interface]
PrivateKey = {KEY}
Address = 10.200.0.2/32

[Peer]
PublicKey = {KEY}
AllowedIPs = 192.168.50.0/24
Endpoint = vpn.example.com:51820
PersistentKeepalive = 25
"""
TUNNEL_ID = "0123456789abcdef"


class TestWireGuardValidation(unittest.TestCase):
    def test_split_tunnel_and_comments(self):
        self.assertEqual(validate_config(CONFIG + "# comment\n"), ["192.168.50.0/24"])

    def test_ipv6_and_multiple_routes(self):
        config = CONFIG.replace("192.168.50.0/24", "192.168.50.0/24, fd00:50::/64")
        config = config.replace("vpn.example.com:51820", "[2001:db8::1]:51820")
        self.assertEqual(validate_config(config), ["192.168.50.0/24", "fd00:50::/64"])

    def test_forbidden_options(self):
        for option in (
            "PostUp = cmd.exe",
            "DNS = 1.1.1.1",
            "Table = off",
            "PreDown = anything",
        ):
            with self.subTest(option=option), self.assertRaises(ValueError):
                validate_config(CONFIG.replace("Address =", option + "\nAddress ="))

    def test_bad_configurations_are_rejected_without_echoing_secrets(self):
        for text in (
            "",
            CONFIG + "[Interface]\n",
            CONFIG.replace("[Interface]", "[Peer]"),
            CONFIG.replace(KEY, "PRIVATE-SECRET"),
            CONFIG.replace("192.168.50.0/24", "0.0.0.0/0"),
            CONFIG.replace("192.168.50.0/24", "::/0"),
            CONFIG.replace("192.168.50.0/24", "0.0.0.0/1,128.0.0.0/1"),
            CONFIG.replace("25", "65536"),
            CONFIG.replace(":51820", ":65536"),
            CONFIG.replace("Address =", "PrivateKey = duplicate\nAddress ="),
            CONFIG + "\x00",
            CONFIG + "#" * 65536,
        ):
            with self.subTest(), self.assertRaises(ValueError) as error:
                validate_config(text)
            self.assertNotIn("PRIVATE-SECRET", str(error.exception))
            self.assertNotIn(KEY, str(error.exception))

    def test_overlapping_peer_routes(self):
        with self.assertRaises(ValueError):
            validate_config(
                CONFIG + f"\n[Peer]\nPublicKey={KEY}\nAllowedIPs=192.168.50.42/32\n"
            )


class TestWireGuardStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = WireGuardManager(Path(self.temp.name))
        # Real encryption/ACL/service behavior must be tested on Windows.
        self.protect = Mock(return_value=b"encrypted blob")
        patcher = patch.dict(
            sys.modules, {"win32crypt": SimpleNamespace(CryptProtectData=self.protect)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(self.manager, "_prepare")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_encrypted_store_contains_no_plaintext_configuration(self):
        record = self.manager.create("Remote site", CONFIG)
        path = self.manager._path(record["id"], ".conf.dpapi")
        self.assertEqual(path.read_bytes(), b"encrypted blob")
        self.protect.assert_called_once_with(
            CONFIG.encode(), f"gannet_{record['id']}", None, None, None, 5
        )
        self.assertNotIn(KEY, json.dumps(self.manager.get(record["id"])))
        self.assertEqual(set(record), {"id", "name", "routes", "status"})
        self.assertEqual(len(list(Path(self.temp.name).glob("*.json"))), 1)
        self.assertFalse(list(Path(self.temp.name).glob("*.tmp")))

    def test_duplicate_names_and_cross_tunnel_routes_are_rejected(self):
        self.manager.create("Site", CONFIG)
        for name, config in (
            ("site", CONFIG.replace("192.168.50", "192.168.51")),
            ("Other", CONFIG),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.manager.create(name, config)

    def test_disjoint_tunnels_can_be_reused(self):
        self.manager.create("Site", CONFIG)
        self.manager.create("Other", CONFIG.replace("192.168.50", "192.168.51"))
        self.assertEqual(len(self.manager._records()), 2)

    def test_path_traversal_and_bad_ids_rejected(self):
        for value in ("../secret", "", "A" * 16, "0123456789abcdef/anything"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.manager.get(value)

    def test_start_installs_encrypted_file_and_waits_for_service(self):
        record = self.manager.create("Site", CONFIG)
        service = Mock()
        with (
            patch.object(self.manager, "_windows"),
            patch.object(self.manager, "_demand_start"),
            patch.object(self.manager, "status", return_value="not_installed"),
            patch.object(self.manager, "_command") as command,
            patch.dict(sys.modules, {"win32serviceutil": service}),
        ):
            self.manager.start(record["id"])
        command.assert_called_once_with(
            "/installtunnelservice",
            str(self.manager._path(record["id"], ".conf.dpapi")),
        )
        service.WaitForServiceStatus.assert_called_once_with(
            f"WireGuardTunnel$gannet_{record['id']}", 4, 30
        )

    def test_start_running_service_does_not_install_again(self):
        record = self.manager.create("Site", CONFIG)
        service = Mock()
        with (
            patch.object(self.manager, "_windows"),
            patch.object(self.manager, "_demand_start"),
            patch.object(self.manager, "status", return_value="running"),
            patch.object(self.manager, "_command") as command,
            patch.dict(sys.modules, {"win32serviceutil": service}),
        ):
            self.manager.start(record["id"])
        command.assert_not_called()
        service.StartService.assert_not_called()

    def test_uninstall_failure_preserves_saved_config(self):
        record = self.manager.create("Site", CONFIG)
        with (
            patch.object(self.manager, "_windows"),
            patch.object(self.manager, "_demand_start"),
            patch.object(self.manager, "status", return_value="running"),
            patch.object(self.manager, "_command", side_effect=RuntimeError("failed")),
            self.assertRaises(RuntimeError),
        ):
            self.manager.delete(record["id"])
        self.assertEqual(self.manager.get(record["id"])["name"], "Site")
        self.assertTrue(self.manager._path(record["id"], ".conf.dpapi").exists())

    def test_startup_deduplicates_shared_tunnels_and_skips_disabled_cameras(self):
        config = SimpleNamespace(
            cameras={
                str(i): SimpleNamespace(enabled=enabled, wireguard_tunnel=value)
                for i, (enabled, value) in enumerate(
                    (
                        (True, TUNNEL_ID),
                        (True, TUNNEL_ID),
                        (False, "other"),
                        (True, None),
                    )
                )
            }
        )
        with patch("gannet.util.wireguard.WireGuardManager") as manager:
            start_camera_tunnels(config)
        manager.return_value.start.assert_called_once_with(TUNNEL_ID)


class TestWireGuardApi(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config.yml"
        self.config_path.write_text("cameras: {}\n", encoding="utf-8")
        patcher = patch(
            "gannet.api.wireguard.find_config_file", return_value=str(self.config_path)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = FastAPI()
        self.app.frigate_config = SimpleNamespace(
            cameras={},
            proxy=SimpleNamespace(separator=","),
            auth=SimpleNamespace(roles={"admin": [], "viewer": []}),
        )
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.manager_patch = patch("gannet.api.wireguard.WireGuardManager")
        self.manager = self.manager_patch.start().return_value
        self.addCleanup(self.manager_patch.stop)
        self.record = {
            "id": TUNNEL_ID,
            "name": "Site",
            "routes": ["192.168.50.0/24"],
            "status": "running",
        }
        self.manager.list.return_value = [self.record]
        self.manager.create.return_value = self.record
        self.manager.get.return_value = self.record
        self.manager.status.return_value = "running"
        self.headers = {"remote-role": "admin", "remote-user": "admin"}

    def test_all_operations_require_admin(self):
        for method, path in (
            ("get", "/wireguard/tunnels"),
            ("post", "/wireguard/tunnels"),
            ("post", f"/wireguard/tunnels/{TUNNEL_ID}/start"),
            ("post", f"/wireguard/tunnels/{TUNNEL_ID}/stop"),
            ("delete", f"/wireguard/tunnels/{TUNNEL_ID}"),
        ):
            with self.subTest(path=path):
                response = getattr(self.client, method)(
                    path, headers={"remote-role": "viewer"}
                )
                self.assertEqual(response.status_code, 403)
        self.manager.list.assert_not_called()
        self.manager.start.assert_not_called()

    def test_import_never_returns_private_keys(self):
        response = self.client.post(
            "/wireguard/tunnels",
            json={"name": "Site", "config": CONFIG},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn(KEY, response.text)
        self.manager.create.assert_called_once_with("Site", CONFIG)

    def test_active_or_pending_camera_blocks_stop_and_delete(self):
        for active in (True, False):
            self.app.frigate_config.cameras = (
                {"front": SimpleNamespace(wireguard_tunnel=TUNNEL_ID)} if active else {}
            )
            self.config_path.write_text(
                f"cameras:\n  front:\n    wireguard_tunnel: {TUNNEL_ID}\n"
                if not active
                else "cameras: {}\n"
            )
            for operation in ("stop", "delete"):
                response = (
                    self.client.post(
                        f"/wireguard/tunnels/{TUNNEL_ID}/stop", headers=self.headers
                    )
                    if operation == "stop"
                    else self.client.delete(
                        f"/wireguard/tunnels/{TUNNEL_ID}", headers=self.headers
                    )
                )
                self.assertEqual(response.status_code, 409)
        self.manager.stop.assert_not_called()
        self.manager.delete.assert_not_called()

    def test_unused_tunnel_can_be_deleted(self):
        response = self.client.delete(
            f"/wireguard/tunnels/{TUNNEL_ID}", headers=self.headers
        )
        self.assertEqual(response.status_code, 204)
        self.manager.delete.assert_called_once_with(TUNNEL_ID)

    def test_unexpected_errors_do_not_leak_secrets(self):
        self.manager.create.side_effect = OSError(CONFIG)
        response = self.client.post(
            "/wireguard/tunnels",
            json={"name": "Site", "config": CONFIG},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(KEY, response.text)


class TestWireGuardCameraConfig(unittest.TestCase):
    def _config(self):
        return {
            "mqtt": {"enabled": False},
            "cameras": {
                "front": {
                    "wireguard_tunnel": TUNNEL_ID,
                    "ffmpeg": {
                        "inputs": [
                            {"path": "rtsp://192.168.50.10/live", "roles": ["detect"]}
                        ]
                    },
                    "detect": {"width": 640, "height": 480},
                }
            },
        }

    def test_camera_reference_is_persisted_without_private_configuration(self):
        from gannet.config import FrigateConfig

        with (
            patch("gannet.config.config._ensure_default_cpu_model"),
            patch(
                "gannet.util.wireguard.WireGuardManager.get",
                return_value={"id": TUNNEL_ID},
            ) as get,
        ):
            parsed = FrigateConfig(**self._config())
        self.assertEqual(parsed.cameras["front"].wireguard_tunnel, TUNNEL_ID)
        self.assertNotIn(KEY, parsed.model_dump_json())
        get.assert_called_once_with(TUNNEL_ID)

    def test_missing_saved_tunnel_is_a_configuration_error(self):
        from pydantic import ValidationError

        from gannet.config import FrigateConfig

        with (
            patch(
                "gannet.util.wireguard.WireGuardManager.get",
                side_effect=ValueError("Saved WireGuard tunnel not found."),
            ),
            self.assertRaises(ValidationError),
        ):
            FrigateConfig(**self._config())


@unittest.skipUnless(os.name == "nt", "Windows DPAPI required")
class TestNativeWireGuardEncryption(unittest.TestCase):
    def test_wireguard_dpapi_description_and_machine_scope(self):
        import win32crypt

        with tempfile.TemporaryDirectory() as directory:
            manager = WireGuardManager(Path(directory))
            # This test checks native DPAPI, not service/ACL installation.
            with patch.object(manager, "_prepare"):
                record = manager.create("Native encryption test", CONFIG)
            encrypted = manager._path(record["id"], ".conf.dpapi").read_bytes()
            self.assertNotIn(KEY.encode(), encrypted)
            description, plaintext = win32crypt.CryptUnprotectData(
                encrypted, None, None, None, 1
            )
            self.assertEqual(description, f"gannet_{record['id']}")
            self.assertEqual(plaintext, CONFIG.encode())


if __name__ == "__main__":
    unittest.main()
