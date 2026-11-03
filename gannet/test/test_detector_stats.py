"""Tests for per-detector process statistics."""

import unittest
from unittest.mock import MagicMock, patch

from gannet.stats.util import get_detector_stats


def _detector(detection_start: float = 2.5) -> MagicMock:
    detector = MagicMock()
    detector.avg_inference_speed.value = 0.01
    detector.detection_start.value = detection_start
    detector.detect_process.pid = 42
    return detector


class TestDetectorStats(unittest.TestCase):
    def test_native_detector_stats_include_speed_and_process(self):
        # detection_start is a monotonic timestamp, reported as wall clock so
        # the API keeps returning an absolute time
        with patch("gannet.stats.util.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            mock_time.time.return_value = 5000.0
            stats = get_detector_stats({"detectors": {"onnx:0": _detector()}})

        self.assertEqual(
            stats["onnx:0"],
            {"inference_speed": 10.0, "detection_start": 4002.5, "pid": 42},
        )

    def test_idle_detector_reports_zero_detection_start(self):
        stats = get_detector_stats({"detectors": {"onnx:0": _detector(0.0)}})

        self.assertEqual(stats["onnx:0"]["detection_start"], 0.0)


if __name__ == "__main__":
    unittest.main()
