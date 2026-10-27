# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""The network scanner is bounded and accessible only to administrators."""

import asyncio
import socketserver
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gannet.api.camera_discovery import router
from gannet.util.camera_discovery import CameraDiscoveryManager


class TestCameraDiscoveryApi(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.frigate_config = SimpleNamespace(
            auth=SimpleNamespace(roles={"admin": [], "viewer": []}),
            proxy=SimpleNamespace(separator=","),
        )
        self.app.state.camera_discovery = CameraDiscoveryManager()
        self.app.include_router(router)

    def test_viewers_cannot_start_read_or_cancel_scans(self):
        with TestClient(self.app) as client:
            for role in ("viewer", None):
                headers = {"remote-role": role} if role else {}
                with self.subTest(role=role):
                    self.assertEqual(
                        client.post(
                            "/camera_discovery", json={}, headers=headers
                        ).status_code,
                        403,
                    )
                    self.assertEqual(
                        client.get(
                            "/camera_discovery/abc", headers=headers
                        ).status_code,
                        403,
                    )
                    self.assertEqual(
                        client.delete(
                            "/camera_discovery/abc", headers=headers
                        ).status_code,
                        403,
                    )
            self.assertIsNone(self.app.state.camera_discovery.current)

    def test_admin_can_start_poll_cancel_and_handle_conflicts(self):
        async def waiting_discovery(callback, interfaces):
            await asyncio.Event().wait()

        headers = {"remote-role": "admin"}
        with (
            patch(
                "gannet.util.camera_discovery.discover_onvif",
                side_effect=waiting_discovery,
            ),
            patch("gannet.util.camera_discovery.local_interfaces", return_value=[]),
            TestClient(self.app) as client,
        ):
            response = client.post(
                "/camera_discovery",
                json={"target": "192.168.4.12", "ports": "554,20000-20002"},
                headers=headers,
            )
            self.assertEqual(response.status_code, 202, response.text)
            scan_id = response.json()["id"]
            self.assertEqual(response.json()["total"], 4)
            self.assertEqual(response.json()["status"], "discovering")
            self.assertEqual(
                client.post("/camera_discovery", json={}, headers=headers).status_code,
                409,
            )
            self.assertEqual(
                client.get("/camera_discovery/wrong", headers=headers).status_code, 404
            )
            self.assertEqual(
                client.get(f"/camera_discovery/{scan_id}", headers=headers).json()[
                    "id"
                ],
                scan_id,
            )
            stopped = client.delete(f"/camera_discovery/{scan_id}", headers=headers)
            self.assertEqual(stopped.status_code, 200)
            self.assertEqual(stopped.json()["status"], "cancelled")
            self.assertEqual(stopped.json()["total"], 4)

    def test_admin_scan_fingerprints_a_real_rtsp_service(self):
        class RtspHandler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.settimeout(2)
                request = b""
                while b"\r\n\r\n" not in request and len(request) < 4096:
                    chunk = self.request.recv(4096 - len(request))
                    if not chunk:
                        return
                    request += chunk
                if request.startswith(b"OPTIONS rtsp://"):
                    self.request.sendall(
                        b"RTSP/1.0 401 Unauthorized\r\nCSeq: 1\r\n\r\n"
                    )

        # Real sockets exercise the API-to-worker path. Production deliberately
        # rejects loopback scan targets, so map this test target to loopback.
        with socketserver.TCPServer(("127.0.0.1", 0), RtspHandler) as server:
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.01},
                daemon=True,
            )
            thread.start()
            try:
                with (
                    patch(
                        "gannet.util.camera_discovery.parse_target",
                        return_value=["127.0.0.1"],
                    ),
                    patch(
                        "gannet.util.camera_discovery.discover_onvif", new=AsyncMock()
                    ),
                    patch(
                        "gannet.util.camera_discovery.local_interfaces", return_value=[]
                    ),
                    TestClient(self.app) as client,
                ):
                    headers = {"remote-role": "admin"}
                    response = client.post(
                        "/camera_discovery",
                        json={
                            "target": "192.168.1.42",
                            "ports": str(server.server_address[1]),
                        },
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 202, response.text)
                    scan_id = response.json()["id"]
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        result = client.get(
                            f"/camera_discovery/{scan_id}", headers=headers
                        ).json()
                        if (
                            result["status"] != "scanning"
                            and result["status"] != "discovering"
                        ):
                            break
                        time.sleep(0.01)
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual((result["scanned"], result["total"]), (1, 1))
                    [device] = result["devices"]
                    [service] = device["services"]
                    self.assertEqual(service["protocol"], "rtsp")
                    self.assertEqual(service["port"], server.server_address[1])
                    self.assertTrue(service["requires_auth"])
            finally:
                server.shutdown()
                thread.join(timeout=2)

    def test_invalid_targets_and_ports_are_rejected_before_scanning(self):
        headers = {"remote-role": "admin"}
        with TestClient(self.app) as client:
            for body in (
                {"target": "8.8.8.8", "ports": "554"},
                {"target": "192.168.0.0/16", "ports": "554"},
                {"target": "192.168.0.1", "ports": "0"},
            ):
                with self.subTest(body=body):
                    response = client.post(
                        "/camera_discovery", json=body, headers=headers
                    )
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIsNone(self.app.state.camera_discovery.current)
            response = client.post(
                "/camera_discovery",
                json={"target": "192.168.0.1", "ports": "1" * 513},
                headers=headers,
            )
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
