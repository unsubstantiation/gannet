# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Camera credential inspection must be admin-only and scoped to one camera."""

from unittest.mock import patch

from gannet.models import Event, Recordings, ReviewSegment
from gannet.test.http_api.base_http_test import AuthTestClient, BaseTestHttp
from gannet.util.env import FRIGATE_ENV_VARS


class TestCameraCredentials(BaseTestHttp):
    def setUp(self):
        super().setUp([Event, Recordings, ReviewSegment])
        self.minimal_config["cameras"]["front_door"].update(
            {
                "ffmpeg": {
                    "inputs": [
                        {
                            "path": "rtsp://alice:p%40ss@camera.example/stream",
                            "roles": ["detect"],
                        },
                        {
                            "path": "rtsp://127.0.0.1:8554/front_record",
                            "roles": ["record"],
                        },
                    ]
                },
                "live": {
                    "streams": {"Main": "front_live", "Other": "front_object"},
                    "transcode": {"enabled": True, "source": "front_transcode"},
                },
                "onvif": {
                    "host": "camera.example",
                    "user": "ptz",
                    "password": "ptz-secret",
                },
            }
        )
        self.minimal_config["cameras"]["other"] = {
            "ffmpeg": {
                "inputs": [
                    {"path": "rtsp://other:other-secret@camera/", "roles": ["detect"]}
                ]
            },
            "detect": {"width": 640, "height": 360},
            "live": {"streams": {"Other": "other_live"}},
        }
        self.minimal_config["go2rtc"] = {
            "streams": {
                "front_live": ["ffmpeg:http://camera/flv?user=alice&password=secret"],
                "front_record": "rtsp://alice:record-secret@camera/record",
                "front_object": {
                    "url": "rtsps://alice:object-secret@camera/live",
                    "unrelated": "must-not-leak",
                },
                "front_transcode": {
                    "url": ["rtsp://alice:transcode-secret@camera/live", 42],
                    "unrelated": "must-not-leak",
                },
                "other_live": "rtsp://other:other-secret@camera/other",
            }
        }
        self.app = super().create_app()

    def test_admin_sees_only_explicitly_linked_sources_and_onvif(self):
        with AuthTestClient(self.app) as client:
            response = client.get("/config/cameras/front_door/credentials")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        data = response.json()
        self.assertEqual(
            data["inputs"][0]["path"], "rtsp://alice:p%40ss@camera.example/stream"
        )
        self.assertEqual(
            set(data["go2rtc"]),
            {"front_live", "front_record", "front_object", "front_transcode"},
        )
        self.assertEqual(
            data["go2rtc"]["front_object"], "rtsps://alice:object-secret@camera/live"
        )
        self.assertEqual(
            data["go2rtc"]["front_transcode"],
            ["rtsp://alice:transcode-secret@camera/live"],
        )
        self.assertEqual(data["onvif"], {"user": "ptz", "password": "ptz-secret"})
        self.assertNotIn("other-secret", response.text)
        self.assertNotIn("must-not-leak", response.text)

    def test_restream_environment_placeholders_are_resolved_for_admin(self):
        streams = self.app.frigate_config.go2rtc.model_extra["streams"]
        streams["front_live"] = "rtsp://alice:{FRIGATE_CAMERA_PASSWORD}@camera/live"
        with (
            patch.dict(FRIGATE_ENV_VARS, {"FRIGATE_CAMERA_PASSWORD": "from-env"}),
            AuthTestClient(self.app) as client,
        ):
            response = client.get("/config/cameras/front_door/credentials")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["go2rtc"]["front_live"],
            "rtsp://alice:from-env@camera/live",
        )

    def test_only_loopback_rtsp_inputs_associate_restreams(self):
        camera = self.app.frigate_config.cameras["front_door"]
        cases = (
            ("rtsp://localhost:8554/front_record", True),
            ("rtsps://[::1]:8554/front%5Frecord?video=1", True),
            ("rtsp://192.168.1.2:8554/front_record", False),
            ("rtsp://127.0.0.1/front_record", False),
            ("rtsp://127.0.0.1:bad/front_record", False),
            ("http://localhost:8554/front_record", False),
        )
        with AuthTestClient(self.app) as client:
            for path, expected in cases:
                with self.subTest(path=path):
                    camera.ffmpeg.inputs[1].path = path
                    response = client.get("/config/cameras/front_door/credentials")
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        "front_record" in response.json()["go2rtc"], expected
                    )

    def test_viewers_are_denied_and_unknown_camera_is_not_found(self):
        with AuthTestClient(self.app) as client:
            response = client.get(
                "/config/cameras/front_door/credentials",
                headers={"remote-user": "viewer", "remote-role": "viewer"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("secret", response.text)
            self.assertEqual(
                client.get("/config/cameras/missing/credentials").status_code, 404
            )
