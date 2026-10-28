"""Tests for native Windows restart requests."""

import os
import signal
import tempfile
import unittest
from unittest.mock import patch

from gannet.util.services import (
    RESTART_MARKER_NAME,
    consume_restart_request,
    restart_frigate,
)


class TestRestartFrigate(unittest.TestCase):
    @patch("gannet.util.services.signal.raise_signal")
    def test_restart_raises_signal_for_graceful_shutdown(self, mock_raise):
        restart_frigate()

        mock_raise.assert_called_once_with(signal.SIGINT)

    @patch("gannet.util.services.get_tmp_dir")
    @patch("gannet.util.services.signal.raise_signal")
    def test_restart_writes_the_launcher_marker(self, _mock_raise, mock_tmp):
        """The launcher restarts Frigate only when the marker is on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            mock_tmp.return_value = tmp

            restart_frigate()

            self.assertTrue(
                os.path.isfile(os.path.join(tmp, RESTART_MARKER_NAME)),
            )

    @patch("gannet.util.services.get_tmp_dir")
    @patch("gannet.util.services.signal.raise_signal")
    def test_restart_records_the_reason_for_the_launcher(self, _mock_raise, mock_tmp):
        """A restart loop is diagnosable only if the marker says why."""
        with tempfile.TemporaryDirectory() as tmp:
            mock_tmp.return_value = tmp

            restart_frigate("detector ov (PID 42) exited with code 1")

            with open(os.path.join(tmp, RESTART_MARKER_NAME), encoding="utf-8") as file:
                self.assertEqual(file.read(), "detector ov (PID 42) exited with code 1")

    @patch("gannet.util.services.get_tmp_dir")
    @patch("gannet.util.services.signal.raise_signal")
    def test_default_reason_is_explicit(self, _mock_raise, mock_tmp):
        with tempfile.TemporaryDirectory() as tmp:
            mock_tmp.return_value = tmp

            restart_frigate()

            with open(os.path.join(tmp, RESTART_MARKER_NAME), encoding="utf-8") as file:
                self.assertEqual(file.read(), "unspecified")

    @patch("gannet.util.services.get_tmp_dir")
    @patch("gannet.util.services.signal.raise_signal")
    def test_reason_is_one_short_line(self, _mock_raise, mock_tmp):
        with tempfile.TemporaryDirectory() as tmp:
            mock_tmp.return_value = tmp

            restart_frigate("bad\nreason " + "x" * 300)

            with open(os.path.join(tmp, RESTART_MARKER_NAME), encoding="utf-8") as file:
                content = file.read()
            self.assertNotIn("\n", content)
            self.assertLessEqual(len(content), 200)

    @patch("gannet.util.services.get_tmp_dir")
    @patch("gannet.util.services.signal.raise_signal")
    def test_unwritable_restart_marker_does_not_stop_the_shutdown(
        self, mock_raise, mock_tmp
    ):
        """A marker write failure still allows a graceful application stop."""
        with tempfile.TemporaryDirectory() as tmp:
            mock_tmp.return_value = tmp
            os.mkdir(os.path.join(tmp, RESTART_MARKER_NAME))

            restart_frigate()

            mock_raise.assert_called_once_with(signal.SIGINT)


class TestConsumeRestartRequest(unittest.TestCase):
    """The marker is the only thing that says Frigate wants to come back."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.marker = os.path.join(self._tmp.name, RESTART_MARKER_NAME)

    def _consume(self) -> bool:
        with patch("gannet.util.services.get_tmp_dir", return_value=self._tmp.name):
            return consume_restart_request()

    def test_no_marker_means_no_restart(self):
        self.assertFalse(self._consume())

    def test_a_marker_is_consumed_exactly_once(self):
        with open(self.marker, "w", encoding="utf-8") as file:
            file.write("restart")

        self.assertTrue(self._consume())
        self.assertFalse(os.path.exists(self.marker))

        # a stop that follows a restart must not start Frigate again
        self.assertFalse(self._consume())

    @patch("gannet.util.services.os.remove")
    def test_a_marker_that_cannot_be_cleared_still_asks_for_a_restart(
        self, mock_remove
    ):
        """The marker is the request, so failing to clear it is not a no."""
        mock_remove.side_effect = PermissionError("in use by another process")

        self.assertTrue(self._consume())


if __name__ == "__main__":
    unittest.main()
