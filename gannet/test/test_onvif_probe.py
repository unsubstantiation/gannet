import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from zeep.exceptions import Fault, TransportError
from zeep.transports import AsyncTransport

from gannet.api.camera import (
    _build_digest_transport,
    _connect_onvif_camera,
    onvif_probe,
)


def _make_camera(update_side_effect=None):
    """Build a mock ONVIFCamera whose update_xaddrs can raise or succeed."""
    camera = MagicMock()
    camera.update_xaddrs = AsyncMock(side_effect=update_side_effect)
    return camera


class TestConnectOnvifCamera(unittest.IsolatedAsyncioTestCase):
    async def test_password_digest_succeeds_first(self):
        # Cameras that accept PasswordDigest authenticate on the first attempt
        # and should never trigger the PasswordText fallback.
        camera = _make_camera()

        with patch("gannet.api.camera.ONVIFCamera", return_value=camera) as mock_cls:
            result = await _connect_onvif_camera(
                "cam.local", 80, "user", "pass", None, "basic"
            )

        self.assertIs(result, camera)
        mock_cls.assert_called_once()
        self.assertTrue(mock_cls.call_args.kwargs["encrypt"])

    async def test_falls_back_to_password_text(self):
        # A PasswordDigest rejection should retry once with PasswordText.
        camera_digest = _make_camera(update_side_effect=Fault("token rejected"))
        camera_text = _make_camera()

        with patch(
            "gannet.api.camera.ONVIFCamera",
            side_effect=[camera_digest, camera_text],
        ) as mock_cls:
            result = await _connect_onvif_camera(
                "cam.local", 80, "user", "pass", None, "basic"
            )

        self.assertIs(result, camera_text)
        self.assertEqual(mock_cls.call_count, 2)
        self.assertTrue(mock_cls.call_args_list[0].kwargs["encrypt"])
        self.assertFalse(mock_cls.call_args_list[1].kwargs["encrypt"])

    async def test_both_encodings_fail_raises_first_fault(self):
        # When both encodings fault, the original (PasswordDigest) fault is
        # surfaced so the caller's existing Fault handler reports it.
        first_fault = Fault("digest rejected")
        camera_digest = _make_camera(update_side_effect=first_fault)
        camera_text = _make_camera(update_side_effect=Fault("text rejected"))

        with patch(
            "gannet.api.camera.ONVIFCamera",
            side_effect=[camera_digest, camera_text],
        ) as mock_cls:
            with self.assertRaises(Fault) as ctx:
                await _connect_onvif_camera(
                    "cam.local", 80, "user", "pass", None, "basic"
                )

        self.assertIs(ctx.exception, first_fault)
        self.assertEqual(mock_cls.call_count, 2)

    async def test_transport_error_is_not_retried(self):
        # Connection-level errors (timeout, refused, unreachable) should
        # propagate immediately without doubling latency on a second encoding.
        camera = _make_camera(update_side_effect=TransportError("unreachable"))

        with patch("gannet.api.camera.ONVIFCamera", side_effect=[camera]) as mock_cls:
            with self.assertRaises(TransportError):
                await _connect_onvif_camera(
                    "cam.local", 80, "user", "pass", None, "basic"
                )

        mock_cls.assert_called_once()

    async def test_digest_auth_replaces_service_transports(self):
        # auth_type "digest" wires an HTTP digest transport onto each service,
        # independently of the WS-Security encoding.
        camera = _make_camera()

        with (
            patch("gannet.api.camera.ONVIFCamera", return_value=camera),
            patch(
                "gannet.api.camera._build_digest_transport",
                return_value="TRANSPORT",
            ) as mock_transport,
        ):
            result = await _connect_onvif_camera(
                "cam.local", 80, "user", "pass", None, "digest"
            )

        self.assertIs(result, camera)
        mock_transport.assert_called_once_with("user", "pass")
        self.assertEqual(camera.devicemgmt.zeep_client.transport, "TRANSPORT")
        self.assertEqual(camera.media.zeep_client.transport, "TRANSPORT")
        self.assertEqual(camera.ptz.zeep_client.transport, "TRANSPORT")

    async def test_basic_auth_does_not_replace_transports(self):
        # Without digest auth, no transport override is built.
        camera = _make_camera()

        with (
            patch("gannet.api.camera.ONVIFCamera", return_value=camera),
            patch("gannet.api.camera._build_digest_transport") as mock_transport,
        ):
            await _connect_onvif_camera("cam.local", 80, "user", "pass", None, "basic")

        mock_transport.assert_not_called()


class TestBuildDigestTransport(unittest.TestCase):
    def test_returns_async_transport(self):
        transport = _build_digest_transport("user", "pass")
        self.assertIsInstance(transport, AsyncTransport)


class TestOnvifStreamCredentials(unittest.IsolatedAsyncioTestCase):
    async def _probe(
        self, uri, *, username="view@er", password="p@ss /%40+", test=True
    ):
        camera = MagicMock()
        device = MagicMock()
        device.GetDeviceInformation = AsyncMock(return_value={})
        media = MagicMock()
        media.GetProfiles = AsyncMock(return_value=[{"token": "main"}] if uri else [])
        media.GetStreamUri = AsyncMock(return_value={"Uri": uri})
        camera.create_devicemgmt_service = AsyncMock(return_value=device)
        camera.create_media_service = AsyncMock(return_value=media)
        camera.create_ptz_service = AsyncMock(side_effect=RuntimeError("no PTZ"))
        camera.close = AsyncMock()
        ffmpeg = object()
        request = SimpleNamespace(
            app=SimpleNamespace(frigate_config=SimpleNamespace(ffmpeg=ffmpeg))
        )
        with (
            patch("gannet.api.camera._connect_onvif_camera", return_value=camera),
            patch(
                "gannet.api.camera.ffprobe_stream",
                return_value=SimpleNamespace(returncode=0),
            ) as ffprobe,
            self.assertLogs("gannet.api.camera", level="DEBUG") as logs,
        ):
            response = await onvif_probe(
                request,
                host="camera.local",
                port=80,
                username=username,
                password=password,
                test=test,
                auth_type="basic",
            )
        self.assertEqual(response.status_code, 200)
        return json.loads(response.body), ffprobe, " ".join(logs.output)

    async def test_profile_uri_encodes_credentials_once_before_probe_and_save(self):
        result, ffprobe, logs = await self._probe(
            "rtsp://camera.local:8554/profile0?label=a@b"
        )
        expected = (
            "rtsp://view%40er:p%40ss%20%2F%2540%2B@camera.local:8554/profile0?label=a@b"
        )
        self.assertEqual(result["rtsp_candidates"][0]["uri"], expected)
        self.assertEqual(result["rtsp_tested"][0]["uri"], expected)
        ffprobe.assert_called_once_with(unittest.mock.ANY, expected, detailed=False)
        self.assertNotIn("p%40ss", logs)
        self.assertNotIn("p@ss", logs)

    async def test_embedded_url_credentials_take_precedence_and_are_not_logged(self):
        uri = "rtsps://inside:embedded%40secret@camera.local/profile0"
        result, ffprobe, logs = await self._probe(uri)
        self.assertEqual(result["rtsp_candidates"][0]["uri"], uri)
        self.assertEqual(result["rtsp_tested"][0]["uri"], uri)
        ffprobe.assert_called_once_with(unittest.mock.ANY, uri, detailed=False)
        self.assertNotIn("embedded%40secret", logs)

    async def test_fallback_patterns_encode_credentials(self):
        result, ffprobe, _ = await self._probe(None, test=False)
        self.assertTrue(result["rtsp_candidates"])
        self.assertTrue(
            all(
                candidate["uri"].startswith(
                    "rtsp://view%40er:p%40ss%20%2F%2540%2B@camera.local:554/"
                )
                for candidate in result["rtsp_candidates"]
            )
        )
        ffprobe.assert_not_called()

    async def test_anonymous_and_empty_password_are_preserved(self):
        uri = "rtsp://camera.local/profile0"
        anonymous, _, _ = await self._probe(uri, username="", password="", test=False)
        self.assertEqual(anonymous["rtsp_candidates"][0]["uri"], uri)
        no_password, _, _ = await self._probe(
            uri, username="viewer", password="", test=False
        )
        self.assertEqual(
            no_password["rtsp_candidates"][0]["uri"],
            "rtsp://viewer:@camera.local/profile0",
        )


if __name__ == "__main__":
    unittest.main()
