"""The config endpoints must read and write the config file as UTF-8.

Windows opens text files in the ANSI code page unless an encoding is given,
so a camera name or label with characters outside that code page would either
fail to save or be written in a form the UTF-8 loader cannot parse on the next
start. These tests round-trip non-ASCII text through the API.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi import Request

from gannet.api.auth import get_allowed_cameras_for_filter, get_current_user
from gannet.api.fastapi_app import create_fastapi_app
from gannet.config import FrigateConfig
from gannet.config.camera.updater import CameraConfigUpdatePublisher
from gannet.models import Event, Recordings, ReviewSegment
from gannet.test.http_api.base_http_test import AuthTestClient, BaseTestHttp

# Characters outside cp1252 (Windows-1252, the usual ANSI code page) and an
# emoji outside the BMP; both must survive a save and a reload.
NON_ASCII_NAME = "Вход 入口 🚪"


class TestHttpConfigEncoding(BaseTestHttp):
    def setUp(self):
        super().setUp(models=[Event, Recordings, ReviewSegment])
        self.minimal_config = {
            "mqtt": {"host": "mqtt"},
            "cameras": {
                "front_door": {
                    "ffmpeg": {
                        "inputs": [
                            {"path": "rtsp://10.0.0.1:554/video", "roles": ["detect"]}
                        ]
                    },
                    "detect": {"height": 1080, "width": 1920, "fps": 5},
                }
            },
        }
        fd, self.config_path = tempfile.mkstemp(suffix=".yml")
        os.close(fd)
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write(
                "mqtt:\n"
                "  host: mqtt\n"
                "cameras:\n"
                "  front_door:\n"
                f"    friendly_name: {NON_ASCII_NAME}\n"
                "    ffmpeg:\n"
                "      inputs:\n"
                "        - path: rtsp://10.0.0.1:554/video\n"
                "          roles:\n"
                "            - detect\n"
                "    detect:\n"
                "      height: 1080\n"
                "      width: 1920\n"
                "      fps: 5\n"
            )
        self.addCleanup(
            lambda: os.path.exists(self.config_path) and os.unlink(self.config_path)
        )

        find_patch = patch(
            "gannet.api.app.find_config_file", return_value=self.config_path
        )
        find_patch.start()
        self.addCleanup(find_patch.stop)

    def tearDown(self):
        self.app.dependency_overrides.clear()
        super().tearDown()

    def _create_app(self):
        mock_publisher = Mock(spec=CameraConfigUpdatePublisher)
        mock_publisher.publisher = MagicMock()
        app = create_fastapi_app(
            FrigateConfig(**self.minimal_config),
            self.db,
            None,
            None,
            None,
            None,
            None,
            None,
            mock_publisher,
            None,
            enforce_default_admin=False,
        )

        async def mock_get_current_user(request: Request):
            return {"username": "admin", "role": "admin"}

        async def mock_get_allowed_cameras_for_filter(request: Request):
            return list(self.minimal_config["cameras"].keys())

        app.dependency_overrides[get_current_user] = mock_get_current_user
        app.dependency_overrides[get_allowed_cameras_for_filter] = (
            mock_get_allowed_cameras_for_filter
        )
        self.app = app
        return app

    def _file_text(self) -> str:
        with open(self.config_path, "rb") as f:
            return f.read().decode("utf-8")

    def test_config_raw_returns_non_ascii_text(self):
        with AuthTestClient(self._create_app()) as client:
            resp = client.get("/config/raw")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(NON_ASCII_NAME, resp.text)

    def test_config_save_writes_utf8(self):
        new_name = NON_ASCII_NAME + " ✓"
        body = self._file_text().replace(NON_ASCII_NAME, new_name)

        with AuthTestClient(self._create_app()) as client:
            resp = client.post("/config/save?save_option=saveonly", content=body)

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn(new_name, self._file_text())

    def test_config_set_preserves_non_ascii_text(self):
        with AuthTestClient(self._create_app()) as client:
            resp = client.put(
                "/config/set",
                json={
                    "config_data": {"birdseye": {"inactivity_threshold": 5}},
                    "update_topic": "config/birdseye",
                    "requires_restart": 0,
                },
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        text = self._file_text()
        self.assertIn(NON_ASCII_NAME, text)
        self.assertIn("inactivity_threshold: 5", text)


if __name__ == "__main__":
    unittest.main()
