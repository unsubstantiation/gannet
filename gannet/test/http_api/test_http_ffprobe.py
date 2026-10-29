"""Tests for credential scrubbing in the ffprobe API."""

from types import SimpleNamespace
from unittest.mock import patch

import requests
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

    def test_failed_probe_scrubs_protect_path_token_from_stderr(self):
        failed = SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=b"rtsps://protect:7441/private-token?enableSrtp=1: Unauthorized\n",
        )
        with patch("gannet.api.camera.ffprobe_stream", return_value=failed):
            with self.client() as client:
                response = client.get("/ffprobe", params={"paths": "camera:front_door"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()[0]["stderr"],
            ["rtsps://protect:7441/*?enableSrtp=1: Unauthorized"],
        )

    def test_xmeye_probe_errors_hide_path_credentials(self):
        url = (
            "rtsp://camera:554/user=xmUser_password=xmPass@with_under"
            "_channel=1_stream=0.sdp?real_stream"
        )
        failed = SimpleNamespace(
            returncode=1,
            stdout=b"",
            stderr=(f"{url}: Connection refused\n").encode(),
        )
        with patch("gannet.api.camera.ffprobe_stream", return_value=failed) as probe:
            with self.client() as client:
                response = client.get("/ffprobe", params={"paths": url})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(probe.call_args.args[1], url)
        self.assertEqual(response.json()[0]["stderr"], ["rtsp://camera:554/user=*"])
        self.assertNotIn("xmUser", response.text)
        self.assertNotIn("xmPass", response.text)

    def test_xmeye_go2rtc_error_response_hides_path_credentials(self):
        url = "rtsp://camera/user=xmUser&password=xmPass&channel=1&stream=0.sdp?real_stream"
        # Native errors may echo the source with the entire URL encoded, so
        # ordinary URL redaction is not sufficient for arbitrary bodies.
        error = SimpleNamespace(
            ok=False,
            text=f"unable to connect to {url} or rtsp%3A%2F%2Fcamera%2Fuser%3DxmUser_password%3DxmPass",
            status_code=400,
        )
        with patch("gannet.api.camera.requests.put", return_value=error):
            with self.assertLogs("gannet.api.camera", level="ERROR") as logs:
                with self.client() as client:
                    response = client.put("/go2rtc/streams/temp", params={"src": url})
        self.assertEqual(response.status_code, 400)
        self.assertIn("go2rtc HTTP 400", response.text)
        for secret in ("xmUser", "xmPass"):
            self.assertNotIn(secret, response.text)
            self.assertNotIn(secret, " ".join(logs.output))

    def test_xmeye_go2rtc_exception_does_not_log_encoded_source(self):
        url = "rtsp://camera/user=xmUser&password=xmPass&channel=1&stream=0.sdp?real_stream"
        error = requests.RequestException(
            "src=rtsp%3A%2F%2Fcamera%2Fuser%3DxmUser_password%3DxmPass"
        )
        with patch("gannet.api.camera.requests.put", side_effect=error):
            with self.assertLogs("gannet.api.camera", level="ERROR") as logs:
                with self.client() as client:
                    response = client.put("/go2rtc/streams/temp", params={"src": url})
        self.assertEqual(response.status_code, 500)
        for secret in ("xmUser", "xmPass"):
            self.assertNotIn(secret, response.text)
            self.assertNotIn(secret, " ".join(logs.output))

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
