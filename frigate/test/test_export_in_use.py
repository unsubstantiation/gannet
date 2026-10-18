"""Tests for the exports an FFmpeg process still has open.

Frigate refuses to delete an export that is still being written, and the
check has to work on Windows, where the process is called ``ffmpeg.exe`` and
the paths are spelled with backslashes.
"""

import ntpath
import os
import tempfile
import unittest
from unittest.mock import patch

from frigate.api.export import _get_files_in_use, _is_ffmpeg_process


class _FakeOpenFile:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeProcess:
    """The parts of a psutil process the export check uses."""

    def __init__(self, name: str, *paths: str) -> None:
        self._name = name
        self._paths = paths

    def name(self) -> str:
        return self._name

    def open_files(self) -> list[_FakeOpenFile]:
        return [_FakeOpenFile(path) for path in self._paths]


class TestIsFfmpegProcess(unittest.TestCase):
    def test_matches_the_windows_executable_name(self):
        self.assertTrue(_is_ffmpeg_process(_FakeProcess("ffmpeg.exe")))

    def test_matches_the_plain_executable_name(self):
        self.assertTrue(_is_ffmpeg_process(_FakeProcess("ffmpeg")))

    def test_ignores_other_processes(self):
        self.assertFalse(_is_ffmpeg_process(_FakeProcess("go2rtc.exe")))
        self.assertFalse(_is_ffmpeg_process(_FakeProcess("ffprobe.exe")))

    def test_ignores_a_process_without_a_name(self):
        self.assertFalse(_is_ffmpeg_process(_FakeProcess("")))


class TestGetFilesInUse(unittest.TestCase):
    def setUp(self) -> None:
        self.export_dir = os.path.join(tempfile.gettempdir(), "frigate-exports")

    def _files_in_use(self, *processes: _FakeProcess) -> set[str]:
        with patch("frigate.api.export.EXPORT_DIR", self.export_dir):
            with patch(
                "frigate.api.export.psutil.process_iter", return_value=processes
            ):
                return _get_files_in_use()

    def test_finds_a_file_held_by_ffmpeg(self):
        path = os.path.join(self.export_dir, "Package thief_abc123.mp4")

        self.assertEqual(
            self._files_in_use(_FakeProcess("ffmpeg.exe", path)),
            {"package thief_abc123.mp4"},
        )

    def test_ignores_files_outside_the_export_directory(self):
        path = os.path.join(tempfile.gettempdir(), "somewhere-else.mp4")

        self.assertEqual(self._files_in_use(_FakeProcess("ffmpeg.exe", path)), set())

    def test_ignores_other_processes(self):
        path = os.path.join(self.export_dir, "Package thief_abc123.mp4")

        self.assertEqual(self._files_in_use(_FakeProcess("go2rtc.exe", path)), set())

    def test_the_names_are_case_insensitive(self):
        """Windows file names are case insensitive, so the comparison is too."""
        path = os.path.join(self.export_dir, "Package thief_abc123.mp4")

        self.assertEqual(
            self._files_in_use(_FakeProcess("ffmpeg.exe", path)),
            {"package thief_abc123.mp4"},
        )

    def test_windows_paths_match_by_case_and_not_by_prefix(self):
        """Use Windows path rules even when CI itself is running on POSIX."""
        process = _FakeProcess(
            "ffmpeg.exe",
            r"c:\frigate\exports\Package thief_abc123.mp4",
            r"C:\Frigate\exports_evil\other.mp4",
        )

        with patch("frigate.api.export.EXPORT_DIR", r"C:\Frigate\exports"):
            with patch(
                "frigate.api.export.psutil.process_iter", return_value=[process]
            ):
                with patch("frigate.util.platform.os.path", ntpath):
                    files_in_use = _get_files_in_use()

        self.assertEqual(files_in_use, {"package thief_abc123.mp4"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
