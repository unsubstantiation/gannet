"""Tests for credential scrubbing in the ffprobe API."""

from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from gannet.test.http_api.base_http_test import AuthTestClient, BaseTestHttp


class TestHttpFfprobe(BaseTestHttp):
    def setUp(self):
        super().setUp([])
        self.app = self.create_app()

    def client(self) -> TestClient:
        return AuthTestClient(self.app)

    def test_failed_probe_scrubs_credentials_from_stderr(self):
        failed = SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=(
                b"[tcp @ 0x1] Connection to tcp://10.0.0.1:554 failed\n"
                b"rtsp://admin:hunter2@10.0.0.1:554/video: Connection refused\n"
            ),
        )

        with patch("gannet.api.camera.ffprobe_stream", return_value=failed):
            with self.client() as client:
                response = client.get("/ffprobe", params={"paths": "camera:front_door"})

        self.assertEqual(response.status_code, 200)
        lines = response.json()[0]["stderr"]
        self.assertEqual(len(lines), 2)
        self.assertNotIn("hunter2", " ".join(lines))
        self.assertEqual(lines[1], "rtsp://*:*@10.0.0.1:554/video: Connection refused")

    def test_snapshot_uses_the_same_encoded_credentials_as_ffprobe(self):
        url = "rtsp://viewer:p@ss@10.0.0.1:8554/profile0"
        expected = "rtsp://viewer:p%40ss@10.0.0.1:8554/profile0"
        with patch(
            "gannet.api.camera.run_ffmpeg_snapshot", return_value=(b"image", "")
        ) as snapshot:
            with self.client() as client:
                response = client.get("/ffprobe/snapshot", params={"url": url})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(snapshot.call_args.args[1], expected)

    def test_snapshot_failure_does_not_log_credentials(self):
        error = "rtsp://viewer:secret@10.0.0.1:8554/profile0: Unauthorized"
        with (
            patch("gannet.api.camera.run_ffmpeg_snapshot", return_value=(None, error)),
            self.assertLogs("gannet.api.camera", level="ERROR") as logs,
        ):
            with self.client() as client:
                response = client.get(
                    "/ffprobe/snapshot", params={"url": "rtsp://10.0.0.1/profile0"}
                )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret", " ".join(logs.output))
        self.assertIn("rtsp://*:*@10.0.0.1:8554/profile0", " ".join(logs.output))
