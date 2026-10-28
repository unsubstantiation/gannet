"""Tests for the detector stuck notice raised by the Frigate watchdog."""

import unittest
from unittest.mock import MagicMock, patch

from gannet.watchdog import FrigateWatchdog


class TestDetectorStuckNotice(unittest.TestCase):
    def _stuck_detector(self) -> MagicMock:
        detector = MagicMock()
        detector.detection_start.value = 1.0
        detector.detect_process.is_alive.return_value = True
        return detector

    def test_stuck_restart_raises_notice(self):
        detector = self._stuck_detector()
        watchdog = FrigateWatchdog({"ov": detector}, MagicMock())

        with (
            patch("gannet.watchdog.datetime") as mock_datetime,
            patch("gannet.watchdog.raise_notice") as raise_notice,
        ):
            mock_datetime.datetime.now.return_value.timestamp.return_value = 100.0
            watchdog._check_detectors()

        detector.start_or_restart.assert_called_once()
        raise_notice.assert_called_once_with(
            "detector_stuck", scope="ov", params={"detector": "ov"}
        )

    def test_healthy_detector_raises_nothing(self):
        detector = self._stuck_detector()
        detector.detection_start.value = 0.0
        watchdog = FrigateWatchdog({"ov": detector}, MagicMock())

        with patch("gannet.watchdog.raise_notice") as raise_notice:
            watchdog._check_detectors()

        raise_notice.assert_not_called()


class TestDeadDetectorRestart(unittest.TestCase):
    """A dead detector restarts the app once, with a reason worth logging."""

    def _dead_detector(self) -> MagicMock:
        detector = MagicMock()
        detector.detection_start.value = 0.0
        detector.detect_process.is_alive.return_value = False
        detector.detect_process.exitcode = 1
        detector.detect_process.pid = 4321
        return detector

    def test_dead_detector_requests_one_restart_with_a_reason(self):
        watchdog = FrigateWatchdog({"ov": self._dead_detector()}, MagicMock())

        with patch("gannet.watchdog.restart_frigate") as restart:
            watchdog._check_detectors()
            watchdog._check_detectors()  # watchdog ticks again during shutdown

        restart.assert_called_once()
        reason = restart.call_args.args[0]
        self.assertIn("ov", reason)
        self.assertIn("4321", reason)
        self.assertIn("1", reason)

    def test_a_recovered_detector_can_request_a_future_restart(self):
        detector = self._dead_detector()
        watchdog = FrigateWatchdog({"ov": detector}, MagicMock())

        with patch("gannet.watchdog.restart_frigate") as restart:
            watchdog._check_detectors()
            detector.detect_process.is_alive.return_value = True
            watchdog._check_detectors()
            detector.detect_process.is_alive.return_value = False
            watchdog._check_detectors()

        self.assertEqual(restart.call_count, 2)
