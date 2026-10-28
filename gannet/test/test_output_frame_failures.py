# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Shared-memory failure diagnostics should remain useful under load."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gannet.output.output import FrameReadFailureTracker, OutputProcess


class TestOutputCameraAdd(unittest.TestCase):
    def test_disabled_camera_does_not_start_idle_output_process(self):
        process = OutputProcess.__new__(OutputProcess)
        process.config = SimpleNamespace(
            cameras={"offline": SimpleNamespace(enabled_in_config=False)}
        )
        cameras, previews, write_times = {}, {}, {}
        with (
            patch("gannet.output.output.JsmpegCamera") as converter,
            patch("gannet.output.output.PreviewRecorder") as recorder,
        ):
            process.add_camera("offline", Mock(), cameras, previews, write_times, None)
        converter.assert_not_called()
        recorder.assert_not_called()
        self.assertEqual((cameras, previews, write_times), ({}, {}, {}))


class TestFrameReadFailureTracker(unittest.TestCase):
    def test_warning_is_throttled_per_camera_and_reports_possible_causes(self):
        tracker = FrameReadFailureTracker(warning_interval=60)
        with (
            patch("gannet.output.output.time.monotonic", return_value=100) as clock,
            patch("gannet.output.output.logger") as logger,
        ):
            for _ in range(8):
                tracker.failed("front", 5, 4.2)
            self.assertEqual(logger.warning.call_count, 1)
            self.assertIn("processing falls behind", logger.warning.call_args.args[0])
            self.assertIn("SHM_MAX_FRAMES", logger.warning.call_args.args[0])
            self.assertEqual(logger.warning.call_args.args[-1], 4.2)

            # A brief recovery resets the consecutive count, but not the
            # rate limit. Another camera is tracked independently.
            tracker.succeeded("front")
            for _ in range(6):
                tracker.failed("front", 5, 0.2)
            self.assertEqual(logger.warning.call_count, 1)
            for _ in range(2):
                tracker.failed("side", 1, 0)
            self.assertEqual(logger.warning.call_count, 2)

            clock.return_value = 160
            tracker.failed("front", 5, 2)
            self.assertEqual(logger.warning.call_count, 3)

            tracker.remove("front")
            for _ in range(6):
                tracker.failed("front", 5, 1)
            self.assertEqual(logger.warning.call_count, 4)
