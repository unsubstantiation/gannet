"""Test camera user and password cleanup."""

import subprocess
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gannet.util.builtin import (
    clean_camera_user_pass,
    escape_special_characters,
    is_masked_camera_path,
)
from gannet.util.services import ffprobe_stream


class TestUserPassCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.rtsp_with_pass = "rtsp://user:password@192.168.0.2:554/live"
        self.rtsp_with_special_pass = "rtsp://user:password`~!@#$%^&*()-_;',.<>:\"\\{\\}\\[\\]@@192.168.0.2:554/live"
        self.rtsp_no_pass = "rtsp://192.168.0.3:554/live"

    def test_cleanup(self):
        """Test that user / pass are cleaned up."""
        clean = clean_camera_user_pass(self.rtsp_with_pass)
        assert clean != self.rtsp_with_pass
        assert "user:password" not in clean

    def test_no_cleanup(self):
        """Test that nothing changes when no user / pass are defined."""
        clean = clean_camera_user_pass(self.rtsp_no_pass)
        assert clean == self.rtsp_no_pass

    def test_special_char_password(self):
        """Test that special characters in pw are escaped, but not others."""
        escaped = escape_special_characters(self.rtsp_with_special_pass)
        assert (
            escaped
            == "rtsp://user:password%60~%21%40%23%24%25%5E%26%2A%28%29-_%3B%27%2C.%3C%3E%3A%22%5C%7B%5C%7D%5C%5B%5C%5D%40@192.168.0.2:554/live"
        )

    def test_no_special_char_password(self):
        """Test that no change is made to path with no special characters."""
        escaped = escape_special_characters(self.rtsp_with_pass)
        assert escaped == self.rtsp_with_pass

    def test_escapes_only_userinfo_and_preserves_encoded_credentials(self):
        cases = {
            # A complete ordinary RTSP URL must reach ffprobe unchanged.
            "rtsp://admin:example123@192.168.1.4:8554/profile0": (
                "rtsp://admin:example123@192.168.1.4:8554/profile0"
            ),
            # Percent-encoded credentials must not be encoded a second time.
            "rtsp://user%40example.com:p%40ss%20%2F%2520@cam:8554/profile0": (
                "rtsp://user%40example.com:p%40ss%20%2F%2520@cam:8554/profile0"
            ),
            "rtsps://user:pass%zz@camera/stream": (
                "rtsps://user:pass%25zz@camera/stream"
            ),
            # Encode raw userinfo but do not replace matching text in the path.
            "rtsp://a+b:a+b@camera/a+b?value=a+b": (
                "rtsp://a%2Bb:a%2Bb@camera/a+b?value=a+b"
            ),
            "rtsp://name@example.com:pa ss@camera/profile": (
                "rtsp://name%40example.com:pa%20ss@camera/profile"
            ),
            "rtsp://u:p@ss@camera/profile@home?email=a@b": (
                "rtsp://u:p%40ss@camera/profile@home?email=a@b"
            ),
            # An @ in the path or query does not introduce credentials.
            "rtsp://camera:8554/profile@home?email=a@b": (
                "rtsp://camera:8554/profile@home?email=a@b"
            ),
            "rtsp://camera:8554/profile?email=a@b": (
                "rtsp://camera:8554/profile?email=a@b"
            ),
            "rtsp://camera/profile?next=http://user:p+ss@other": (
                "rtsp://camera/profile?next=http://user:p+ss@other"
            ),
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(escape_special_characters(url), expected)
                self.assertEqual(escape_special_characters(expected), expected)


class TestUserPassMasking(unittest.TestCase):
    def setUp(self) -> None:
        self.rtsp_log_message = "Did you mean file:rtsp://user:password@192.168.1.3:554"

    def test_rtsp_in_log_message(self):
        """Test that the rtsp url in a log message is escaped."""
        escaped = clean_camera_user_pass(self.rtsp_log_message)
        print(f"The escaped is {escaped}")
        assert escaped == "Did you mean file:rtsp://*:*@192.168.1.3:554"

    def test_masks_userinfo_and_credential_query_forms(self):
        cases = {
            "rtsp://first.last@mail.com:p%40w@10.0.0.2/live": "rtsp://*:*@10.0.0.2/live",
            "rtsp://user+tag:pw@10.0.0.2/live": "rtsp://*:*@10.0.0.2/live",
            "rtsp://:pw@10.0.0.2/live": "rtsp://*:*@10.0.0.2/live",
            "tapo://cloudpassword@10.0.0.2": "tapo://*:*@10.0.0.2",
            "rtsp://u:p@ss@10.0.0.2/live": "rtsp://*:*@10.0.0.2/live",
            "rtsp://user:pa/ss@10.0.0.2/live": "rtsp://*:*@10.0.0.2/live",
            "rtsp://u:p@ss#x@10.0.0.2/live": "rtsp://*:*@10.0.0.2/live",
            "rtsp://admin:2024/pw@10.0.0.2/x": "rtsp://*:*@10.0.0.2/x",
            "rtsp://admin:12#abc@10.0.0.2/x": "rtsp://*:*@10.0.0.2/x",
            "rtsp://admin:7?x@10.0.0.2/x": "rtsp://*:*@10.0.0.2/x",
            "rtsps://u:1/2@h/x": "rtsps://*:*@h/x",
            "rtsp://admin:pre&token=suf@10.0.0.2/x": "rtsp://*:*@",
            "rtsp://admin:a?pwd=b@10.0.0.2/x": "rtsp://*:*@",
            "rtsp://10.0.0.2:554/live?password=pre@suf": "rtsp://*:*@",
            "http://10.0.0.2:88/cgi?cmd=snap&usr=admin&pwd=P@ss": "http://*:*@",
            "ffmpeg:http://h:80/flv?user=u&password=p@ss#video=copy": (
                "ffmpeg:http://*:*@"
            ),
            "rtsp://u:p@10.0.0.2:554/live?token=t": "rtsp://*:*@10.0.0.2:554/live?token=*",
            "http://h/x?api_key=a&apikey=b&access_token=c": (
                "http://h/x?api_key=*&apikey=*&access_token=*"
            ),
            "http://h/cgi?user=admin&password=x": "http://h/cgi?user=*&password=*",
            "http://h/cgi?password=x&user=admin&channel=1": (
                "http://h/cgi?password=*&user=*&channel=1"
            ),
            "http://h/x?usr=a&pwd=b": "http://h/x?usr=*&pwd=*",
            "http://h/x?username=a&password=b": "http://h/x?username=*&password=*",
            "rtsp://host/live?user=admin&password=p@ss": (
                "rtsp://host/live?user=*&password=*"
            ),
            "rtsps://10.0.0.2:7441/private-token?enableSrtp=1": (
                "rtsps://10.0.0.2:7441/*?enableSrtp=1"
            ),
            "rtsp://[::1]:7447/private-token": "rtsp://[::1]:7447/*",
            "rtsps://protect:7441/token,with@specials": "rtsps://protect:7441/*",
            "rtsps://protect:7441/token1,rtsp://protect:7447/token2": (
                "rtsps://protect:7441/*,rtsp://protect:7447/*"
            ),
            "ffmpeg:rtsps://user:pw@protect:7441/abc_def-123?token=secret": (
                "ffmpeg:rtsps://*:*@protect:7441/*?token=*"
            ),
            "ring:?refresh_token=abc.def": "ring:?refresh_token=*",
            "nest:?client_id=1&client_secret=s&refresh_token=t&project_id=p": (
                "nest:?client_id=1&client_secret=*&refresh_token=*&project_id=p"
            ),
            "homekit://10.0.0.2:51827?client_id=c&client_private=k&device_id=d": (
                "homekit://10.0.0.2:51827?client_id=c&client_private=*&device_id=d"
            ),
            "exec:ffmpeg -i rtsp://u:p@h/s -c copy -f rtsp {output}": (
                "exec:ffmpeg -i rtsp://*:*@h/s -c copy -f rtsp {output}"
            ),
            "ffmpeg -i rtsp://u:p@h/1 -i http://h/snap?user=a&password=b -f null": (
                "ffmpeg -i rtsp://*:*@h/1 -i http://h/snap?user=*&password=* -f null"
            ),
        }

        for line, expected in cases.items():
            with self.subTest(line=line):
                masked = clean_camera_user_pass(line)
                self.assertEqual(masked, expected)
                self.assertTrue(is_masked_camera_path(masked))
                self.assertEqual(clean_camera_user_pass(masked), masked)

    def test_xmeye_path_credentials_are_masked_conservatively(self):
        cases = {
            "rtsp://cam:554/user=alice&password=p%40ss%26word&channel=1&stream=0.sdp?real_stream": (
                "rtsp://cam:554/user=*&channel=1&stream=0.sdp?real_stream"
            ),
            "rtsp://cam/user=admin&password=&channel=2&stream=1.sdp?": (
                "rtsp://cam/user=*&channel=2&stream=1.sdp?"
            ),
            "rtsps://cam:8554/user=al_ice_password=p@ss,with_underscores_channel=9_stream=1.sdp?real_stream": (
                "rtsps://cam:8554/user=*_channel=9_stream=1.sdp?real_stream"
            ),
            "rtsp://cam/live/user=admin_password=secret_channel=0_stream=0_onvif=0.sdp?real_stream": (
                "rtsp://cam/live/user=*_channel=0_stream=0_onvif=0.sdp?real_stream"
            ),
            "ffmpeg:rtsp://name:pass@cam/user=alice_password=secret_channel=1_stream=0.sdp?real_stream": (
                "ffmpeg:rtsp://*:*@cam/user=*_channel=1_stream=0.sdp?real_stream"
            ),
            # Unknown suffixes and raw whitespace are hidden rather than
            # guessing which characters belong to the credentials.
            "rtsp://cam/user=alice&password=has spaces&token=secret: failed": (
                "rtsp://cam/user=*"
            ),
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                masked = clean_camera_user_pass(line)
                self.assertEqual(masked, expected)
                self.assertTrue(is_masked_camera_path(masked))
                self.assertEqual(clean_camera_user_pass(masked), masked)

        encoded = (
            "source=rtsp%3A%2F%2Fcam%3A554%2Fuser%3Dalice%26password%3Dsecret"
            "%26channel%3D1%26stream%3D0.sdp%3Freal_stream: failed"
        )
        self.assertEqual(
            clean_camera_user_pass(encoded),
            "source=rtsp%3A%2F%2Fcam%3A554%2Fuser%3D*",
        )

        multiple = (
            "rtsp://a/user=alice&password=p%2Cq&channel=1&stream=0.sdp?real_stream,"
            "rtsp://b/user=bob_password=other_channel=2_stream=1.sdp?real_stream"
        )
        self.assertEqual(
            clean_camera_user_pass(multiple),
            "rtsp://a/user=*&channel=1&stream=0.sdp?real_stream,"
            "rtsp://b/user=*_channel=2_stream=1.sdp?real_stream",
        )

    def test_safe_strings_unchanged(self):
        for line in (
            "rtsp://10.0.0.2:554/live",
            "rtsp://10.0.0.2:7447/",
            "rtsp://10.0.0.2:7442/not-a-protect-stream",
            "ffmpeg:front_door#video=copy",
            "rtsp://127.0.0.1:8554/front_door?video=copy&audio=aac",
            "homekit://10.0.0.2:51827?device_id=d",
            "http://10.0.0.1/snap.jpg?email=me@x.com",
            "http://h/x?auth=a&author=b&authorization=c&user_agent=d&autoken=e",
            "http://h/x?private=1&passthrough=1",
            "Camera front_door is not responding",
        ):
            with self.subTest(line=line):
                self.assertEqual(clean_camera_user_pass(line), line)
                self.assertFalse(is_masked_camera_path(line))

    def test_commas_outside_credentials_survive(self):
        """ffprobe splits multiple paths on commas left after masking."""
        for line in (
            "rtsp://a/x,rtsp://u:p@b/y",
            "rtsp://a:554/x,rtsp://u:p@b/y",
        ):
            with self.subTest(line=line):
                self.assertIn(",", clean_camera_user_pass(line))
        self.assertNotIn(",", clean_camera_user_pass("rtsp://u:p,q@b/y"))

    def test_long_line_masks_in_linear_time(self):
        """Log lines run through the mask, so a long one must stay fast."""
        start = time.perf_counter()
        clean_camera_user_pass("rtsp://u:p" * 20000)
        clean_camera_user_pass("rtsp://" + "a." * 40000)
        clean_camera_user_pass("rtsp%3A%2F%2Fcamera" * 20000)
        self.assertLess(time.perf_counter() - start, 1)


class TestFfprobeAuthentication(unittest.TestCase):
    def setUp(self):
        self.ffmpeg = SimpleNamespace(ffprobe_path="ffprobe.exe")
        self.url = "rtsp://viewer:pa%40ss%20word@192.168.1.4:8554/profile0"

    def test_detailed_probe_requests_stream_codec_types(self):
        succeeded = subprocess.CompletedProcess([], 0, b"{}", b"")
        with patch("gannet.util.services.sp.run", return_value=succeeded) as run:
            ffprobe_stream(self.ffmpeg, self.url, detailed=True)

        command = run.call_args.args[0]
        stream_entries = next(
            value
            for index, value in enumerate(command)
            if index > 0
            and command[index - 1] == "-show_entries"
            and value.startswith("stream=")
        )
        self.assertIn("codec_type", stream_entries.split("=", 1)[1].split(","))

    def test_authentication_failure_does_not_retry_credentials(self):
        for error in (
            b"method DESCRIBE failed: 401 (Unauthorized)",
            b"Server returned 403 Forbidden",
            b"authorization failed",
            b"authentication failed",
        ):
            with self.subTest(error=error):
                failed = subprocess.CompletedProcess([], 1, b"", error)
                with patch("gannet.util.services.sp.run", return_value=failed) as run:
                    result = ffprobe_stream(self.ffmpeg, self.url, detailed=True)
                self.assertIs(result, failed)
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0][-1], self.url)

    def test_transport_failure_retries_with_tcp(self):
        failed = subprocess.CompletedProcess([], 1, b"", b"Connection timed out")
        succeeded = subprocess.CompletedProcess([], 0, b"{}", b"")
        with patch(
            "gannet.util.services.sp.run", side_effect=[failed, succeeded]
        ) as run:
            result = ffprobe_stream(self.ffmpeg, self.url)
        self.assertIs(result, succeeded)
        self.assertEqual(run.call_count, 2)
        first, second = [call.args[0] for call in run.call_args_list]
        self.assertNotIn("-rtsp_transport", first)
        self.assertIn("-rtsp_transport", second)
        self.assertEqual(second[second.index("-rtsp_transport") + 1], "tcp")
        self.assertEqual(first[-1], self.url)
        self.assertEqual(second[-1], self.url)

    def test_anonymous_rtsp_and_rtsps_still_retry_transport_errors(self):
        for url in ("rtsp://camera/profile0", "rtsps://camera/profile0"):
            with self.subTest(url=url):
                failed = subprocess.CompletedProcess([], 1, b"", b"Connection refused")
                with patch("gannet.util.services.sp.run", return_value=failed) as run:
                    ffprobe_stream(self.ffmpeg, url)
                self.assertEqual(run.call_count, 2)
