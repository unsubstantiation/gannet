"""Tests that IPC handler errors cannot stall inter-process communication."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import zmq

from gannet.comms.dispatcher import Dispatcher
from gannet.comms.inter_process import InterProcessCommunicator


class TestInterProcessHandlerErrors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.address = f"ipc://{os.path.join(self.tmp.name, 'comms')}"

        with patch("gannet.comms.inter_process.SOCKET_REP_REQ", self.address):
            self.communicator = InterProcessCommunicator()

        self.context = zmq.Context()
        self.requestor = self.context.socket(zmq.REQ)
        self.requestor.setsockopt(zmq.RCVTIMEO, 5000)
        self.requestor.connect(self.address)

    def tearDown(self):
        self.requestor.close(linger=0)
        self.context.destroy(linger=0)
        self.communicator.stop()
        self.tmp.cleanup()

    def test_handler_exception_still_replies_and_keeps_reading(self):
        def dispatcher(topic, value):
            if topic == "boom":
                raise ValueError("handler failed")
            return value

        self.communicator.subscribe(dispatcher)
        self.communicator.start()

        with self.assertLogs("gannet.comms.inter_process", level="ERROR"):
            self.requestor.send_json(("boom", None))
            self.assertEqual(self.requestor.recv_json(), [])

        self.requestor.send_json(("echo", "ok"))
        self.assertEqual(self.requestor.recv_json(), "ok")
        self.assertTrue(self.communicator.reader_thread.is_alive())


class TestDispatcherPublishErrors(unittest.TestCase):
    def test_failing_communicator_does_not_block_the_others(self):
        failing = MagicMock()
        failing.publish.side_effect = ValueError("publish failed")
        healthy = MagicMock()

        with (
            patch("gannet.comms.dispatcher.CameraActivityManager"),
            patch("gannet.comms.dispatcher.AudioActivityManager"),
        ):
            dispatcher = Dispatcher(
                MagicMock(), MagicMock(), MagicMock(), {}, [failing, healthy]
            )

        healthy.publish.reset_mock()

        with self.assertLogs("gannet.comms.dispatcher", level="ERROR"):
            dispatcher.publish("reviews", "{}")
            dispatcher.publish_local("notices", "[]")

        healthy.publish.assert_any_call("reviews", "{}", False)
        healthy.publish.assert_any_call("notices", "[]", False)


if __name__ == "__main__":
    unittest.main()
