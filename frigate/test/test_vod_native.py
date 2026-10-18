"""Native HLS playlist and segment generation for the Windows gateway."""

import asyncio
import contextlib
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from frigate.api import vod_native
from frigate.api.vod_native import (
    VodPlaylist,
    VodSegment,
    build_playlist,
    find_segment,
    parse_segment_name,
    render_segment,
    start_cache_maintenance,
)


def _recording(root: str, name: str) -> str:
    """A recording file that exists, which is what a playlist entry needs."""
    path = os.path.join(root, name)

    with open(path, "wb") as file:
        file.write(b"recording")

    return path


def _playlist(directory: str, segments: list[VodSegment]) -> VodPlaylist:
    return VodPlaylist(
        camera="front_door",
        stream_type="main",
        start=segments[0].start if segments else 0.0,
        end=segments[-1].end if segments else 0.0,
        segments=segments,
    )


class _FakeProcess:
    """The part of an asyncio subprocess that remuxing a segment uses."""

    def __init__(self, hang: bool = False) -> None:
        # a process that has not exited yet has no return code, which is what
        # tells the caller it is still running
        self.returncode: int | None = None
        self.hang = hang
        self.killed = False
        self.waited = False

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.hang:
            await asyncio.sleep(3600)

        return b"", b""

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        self.waited = True
        self.returncode = -9
        return self.returncode


class _Remux:
    """Stand in for ffmpeg, writing what it was asked to write."""

    def __init__(
        self, payload: bytes = b"", returncode: int = 0, hang: bool = False
    ) -> None:
        self.payload = payload
        self.returncode = returncode
        self.commands: list[list[str]] = []
        self.process = _FakeProcess(hang)

    async def __call__(self, *command: str, **_kwargs) -> _FakeProcess:
        self.commands.append(list(command))

        if self.payload:
            with open(command[-1], "wb") as file:
                file.write(self.payload)

        if not self.process.hang:
            self.process.returncode = self.returncode

        return self.process


class TestPlaylistSegmentOffsets(unittest.TestCase):
    """A playlist entry knows where its recording file starts."""

    def test_a_range_starting_inside_a_file_seeks_to_the_requested_position(self):
        """The first entry is clipped forward, so ffmpeg has to seek into it.

        Every entry used to be remuxed from the start of its file while the
        playlist advertised the clipped position, which played video from
        before the requested range and left the timeline out of step with the
        recording it came from.
        """
        with tempfile.TemporaryDirectory() as root:
            recording = _recording(root, "00.00.mp4")
            rows = [
                {
                    "path": recording,
                    "start_time": 100.0,
                    "end_time": 160.0,
                    "stream_type": "main",
                }
            ]

            with patch.object(vod_native, "_recordings_for_range", return_value=rows):
                playlist = build_playlist("front_door", 130.0, 160.0)

        segment = playlist.segments[0]

        self.assertEqual(segment.start, 130.0)
        self.assertEqual(segment.duration, 30.0)
        self.assertEqual(segment.file_start, 100.0)
        self.assertAlmostEqual(segment.offset, 30.0)

    def test_a_file_covered_by_the_range_starts_at_zero(self):
        with tempfile.TemporaryDirectory() as root:
            recording = _recording(root, "00.00.mp4")
            rows = [
                {
                    "path": recording,
                    "start_time": 100.0,
                    "end_time": 160.0,
                    "stream_type": "main",
                }
            ]

            with patch.object(vod_native, "_recordings_for_range", return_value=rows):
                playlist = build_playlist("front_door", 90.0, 200.0)

        segment = playlist.segments[0]

        self.assertEqual(segment.start, 100.0)
        self.assertAlmostEqual(segment.offset, 0.0)

    def test_the_seek_offset_reaches_the_ffmpeg_command(self):
        remux = _Remux(payload=b"segment")

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            recording = _recording(root, "00.00.mp4")
            segment = VodSegment(
                index=0,
                path=recording,
                start=130.0,
                duration=30.0,
                file_start=100.0,
            )

            asyncio.run(render_segment(_playlist(cache, [segment]), segment))

        command = remux.commands[0]

        self.assertEqual(command[command.index("-ss") + 1], "30.000")
        self.assertEqual(command[command.index("-t") + 1], "30.000")

    def test_no_codec_specific_bitstream_filter_is_forced(self):
        """The remux has to work for HEVC recordings as well as H.264.

        ``h264_mp4toannexb`` was passed for every MP4 input. ffmpeg refuses
        to apply it to an HEVC stream and exits, so cameras recording H.265
        could not be played back at all. The mpegts muxer inserts the right
        filter for the codec it is given, so none should be requested.
        """
        remux = _Remux(payload=b"segment")

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            recording = _recording(root, "00.00.mp4")
            segment = VodSegment(
                index=0,
                path=recording,
                start=100.0,
                duration=10.0,
                file_start=100.0,
            )

            asyncio.run(render_segment(_playlist(cache, [segment]), segment))

        command = remux.commands[0]

        self.assertNotIn("-bsf:v", command)
        self.assertNotIn("h264_mp4toannexb", command)
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertEqual(command[command.index("-f") + 1], "mpegts")

    def enter_cache(self, root: str, remux: _Remux) -> str:
        cache = os.path.join(root, "vod")
        self.enterContext(patch.object(vod_native, "VOD_CACHE_ROOT", cache))
        self.enterContext(
            patch.object(vod_native, "resolve_ffmpeg_binary", return_value="ffmpeg")
        )
        self.enterContext(
            patch.object(vod_native.asyncio, "create_subprocess_exec", remux)
        )
        return cache


class TestRenderSegment(unittest.IsolatedAsyncioTestCase):
    """Segment files a player can be handed without a second look."""

    def enter_cache(self, root: str, remux: _Remux | None = None) -> str:
        """Point the cache at a temporary directory for the whole test."""
        cache = os.path.join(root, "vod")
        self.enterContext(patch.object(vod_native, "VOD_CACHE_ROOT", cache))
        self.enterContext(
            patch.object(vod_native, "resolve_ffmpeg_binary", return_value="ffmpeg")
        )

        if remux is not None:
            self.enterContext(
                patch.object(vod_native.asyncio, "create_subprocess_exec", remux)
            )

        return cache

    @staticmethod
    def _segment(recording: str) -> VodSegment:
        return VodSegment(
            index=0,
            path=recording,
            start=0.0,
            duration=10.0,
            file_start=0.0,
        )

    async def test_a_complete_segment_is_moved_into_place(self):
        remux = _Remux(payload=b"segment")

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            recording = _recording(root, "00.00.mp4")
            segment = self._segment(recording)
            playlist = _playlist(cache, [segment])

            path = await render_segment(playlist, segment)

            self.assertEqual(path, os.path.join(playlist.directory, segment.name))
            # the temporary name it was remuxed under is not left behind
            self.assertEqual(os.listdir(playlist.directory), [segment.name])

    async def test_a_remux_that_writes_nothing_is_not_cached(self):
        """An empty file would be served forever, because only its size is checked."""
        remux = _Remux(payload=b"")

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            recording = _recording(root, "00.00.mp4")
            segment = self._segment(recording)
            playlist = _playlist(cache, [segment])

            self.assertIsNone(await render_segment(playlist, segment))
            self.assertEqual(os.listdir(playlist.directory), [])

    async def test_a_failed_remux_leaves_no_partial_segment(self):
        """A cached segment is served without being checked again."""
        remux = _Remux(payload=b"half a segment", returncode=1)

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            recording = _recording(root, "00.00.mp4")
            segment = self._segment(recording)
            playlist = _playlist(cache, [segment])

            self.assertIsNone(await render_segment(playlist, segment))
            self.assertEqual(os.listdir(playlist.directory), [])

    async def test_a_timed_out_remux_is_killed_and_leaves_no_partial_segment(self):
        """A remux left running keeps the recording file open on Windows."""
        remux = _Remux(payload=b"half a segment", hang=True)

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            self.enterContext(patch.object(vod_native, "SEGMENT_TIMEOUT", 0.05))
            recording = _recording(root, "00.00.mp4")
            segment = self._segment(recording)
            playlist = _playlist(cache, [segment])

            self.assertIsNone(await render_segment(playlist, segment))

            self.assertTrue(remux.process.killed)
            self.assertTrue(remux.process.waited)
            self.assertEqual(os.listdir(playlist.directory), [])

    async def test_a_cached_segment_refreshes_the_directory_the_sweep_reads(self):
        """Re-serving an entry has to keep its cache directory alive.

        The sweep expires directories by their own modification time, which
        touching a file inside one does not change, so a range watched for
        longer than the cache lifetime was remuxed from scratch.
        """
        remux = _Remux(payload=b"should not run")

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root, remux)
            recording = _recording(root, "00.00.mp4")
            segment = self._segment(recording)
            playlist = _playlist(cache, [segment])
            os.makedirs(playlist.directory, exist_ok=True)

            cached = os.path.join(playlist.directory, segment.name)

            with open(cached, "wb") as file:
                file.write(b"segment")

            stale = time.time() - vod_native.VOD_CACHE_TTL - 60
            os.utime(cached, (stale, stale))
            os.utime(playlist.directory, (stale, stale))

            path = await render_segment(playlist, segment)

            self.assertEqual(path, cached)
            self.assertEqual(remux.commands, [])
            self.assertGreater(os.stat(playlist.directory).st_mtime, stale)
            self.assertGreater(os.stat(cached).st_mtime, stale)

    async def test_a_missing_ffmpeg_is_reported_without_a_traceback(self):
        async def missing(*_args, **_kwargs):
            raise FileNotFoundError("ffmpeg.exe")

        with tempfile.TemporaryDirectory() as root:
            cache = self.enter_cache(root)
            self.enterContext(
                patch.object(vod_native.asyncio, "create_subprocess_exec", missing)
            )
            recording = _recording(root, "00.00.mp4")
            segment = self._segment(recording)

            self.assertIsNone(
                await render_segment(_playlist(cache, [segment]), segment)
            )


class TestCacheSweep(unittest.TestCase):
    """The sweep keeps what is in use and drops what is not."""

    def test_only_stale_directories_are_removed(self):
        with tempfile.TemporaryDirectory() as cache:
            stale = os.path.join(cache, "stale")
            fresh = os.path.join(cache, "fresh")

            for directory in (stale, fresh):
                os.makedirs(directory)

            old = time.time() - vod_native.VOD_CACHE_TTL - 60
            os.utime(stale, (old, old))

            with patch.object(vod_native, "VOD_CACHE_ROOT", cache):
                vod_native._sweep_cache()

            self.assertEqual(os.listdir(cache), ["fresh"])

    def test_the_sweep_task_is_kept_alive(self):
        """An event loop holds only a weak reference to the tasks it runs."""

        async def start_and_stop() -> None:
            task = start_cache_maintenance()

            self.assertIsNotNone(task)
            self.assertIn(task, vod_native._SWEEP_TASKS)

            task.cancel()

            with contextlib.suppress(asyncio.CancelledError):
                await task

            await asyncio.sleep(0)
            self.assertNotIn(task, vod_native._SWEEP_TASKS)

        with tempfile.TemporaryDirectory() as cache:
            with patch.object(vod_native, "VOD_CACHE_ROOT", cache):
                asyncio.run(start_and_stop())


class TestPlaylistRendering(unittest.TestCase):
    def test_the_master_playlist_points_at_its_sibling_media_playlist(self):
        """The variant URI is relative, so it resolves against the master URL.

        A player fetching ``.../master.m3u8`` then asks for ``.../index.m3u8``
        on the same route, whichever route shape and timestamp formatting it
        used. An absolute URL rebuilt from parsed floats was not reliably one
        the routes accepted.
        """
        playlist = _playlist(
            "cache",
            [
                VodSegment(
                    index=0,
                    path="recording.mp4",
                    start=1700000000.5,
                    duration=10.0,
                    file_start=1700000000.5,
                )
            ],
        )

        lines = playlist.master_m3u8().splitlines()

        self.assertEqual(lines[0], "#EXTM3U")
        self.assertEqual(lines[-1], "index.m3u8")
        self.assertTrue(lines[-2].startswith("#EXT-X-STREAM-INF:"))
        self.assertIn("BANDWIDTH=", lines[-2])
        # the recordings are not 1280x720, so the variant must not claim it
        self.assertNotIn("RESOLUTION", lines[-2])


class TestHourRange(unittest.TestCase):
    """The ``/vod/{YYYY-MM}/{day}/{hour}/{camera}/{tz}`` form of a range."""

    def test_the_hour_is_local_to_the_requested_zone_on_that_day(self):
        """The offset in force on the requested day is the one that applies.

        The hour used to be shifted by the zone's *current* UTC offset, so in
        a zone with daylight saving every hour asked for across the seasonal
        boundary from today came back an hour early or late.
        """
        # Anchorage is UTC-9 in January and UTC-8 in July; whichever applies
        # today, both of these have to be right at the same time
        winter = vod_native.hour_range("2024-01", 15, 10, "America,Anchorage")
        summer = vod_native.hour_range("2024-07", 15, 10, "America,Anchorage")

        self.assertIsNotNone(winter)
        self.assertIsNotNone(summer)
        self.assertEqual(
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(winter[0])),
            "2024-01-15 19:00",
        )
        self.assertEqual(
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(summer[0])),
            "2024-07-15 18:00",
        )

    def test_a_range_is_one_hour_long(self):
        start, end = vod_native.hour_range("2024-03", 10, 1, "America,New_York")

        self.assertAlmostEqual(end - start, 3600 - 0.001, places=3)

    def test_utc_is_used_without_a_zone(self):
        start, _end = vod_native.hour_range("2024-03", 1, 5, None)

        self.assertEqual(
            time.strftime("%Y-%m-%d %H:%M", time.gmtime(start)), "2024-03-01 05:00"
        )

    def test_an_invalid_date_is_rejected(self):
        self.assertIsNone(vod_native.hour_range("2024-13", 1, 0, None))
        self.assertIsNone(vod_native.hour_range("2024-02", 30, 0, None))
        self.assertIsNone(vod_native.hour_range("2024-02", 1, 24, None))
        self.assertIsNone(vod_native.hour_range("front_door", 1, 0, None))


class TestSegmentLookup(unittest.TestCase):
    def test_a_name_outside_the_playlist_is_not_a_segment(self):
        playlist = _playlist(
            "cache",
            [
                VodSegment(
                    index=0,
                    path="recording.mp4",
                    start=0.0,
                    duration=10.0,
                    file_start=0.0,
                )
            ],
        )

        self.assertIsNone(find_segment(playlist, "seg-00001.ts"))
        self.assertIsNone(find_segment(playlist, "../../etc/passwd"))
        self.assertEqual(parse_segment_name("seg-00000.ts"), 0)
        self.assertIsNone(parse_segment_name("seg-0.ts"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
