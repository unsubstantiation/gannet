# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Tests for the notification delivery TTL setting.

A notification sent while an alert is active used to be dropped whenever the
device was unreachable, so only the notification sent when the alert ended ever
arrived. The `notifications.ttl` option lets the push service retry the active
notification for a bounded time instead.
"""

import unittest

from pydantic import ValidationError

from gannet.config import FrigateConfig
from gannet.config.camera.notification import (
    NOTIFICATION_TTL_SECONDS,
    NotificationTTLEnum,
)


def build_config(notifications: dict | None = None) -> FrigateConfig:
    return FrigateConfig(
        **{
            "mqtt": {"host": "mqtt"},
            "notifications": notifications or {},
            "cameras": {
                "front_door": {
                    "ffmpeg": {
                        "inputs": [
                            {
                                "path": "rtsp://10.0.0.1:554/video",
                                "roles": ["detect"],
                            },
                        ]
                    },
                }
            },
        }
    )


class TestNotificationTTL(unittest.TestCase):
    def test_immediate_is_the_default_and_sends_no_ttl(self):
        config = build_config()

        self.assertEqual(config.notifications.ttl, NotificationTTLEnum.immediate)
        self.assertEqual(NOTIFICATION_TTL_SECONDS[config.notifications.ttl], 0)

    def test_reliable_retries_for_thirty_seconds(self):
        config = build_config({"ttl": "reliable"})

        self.assertEqual(config.notifications.ttl, NotificationTTLEnum.reliable)
        self.assertEqual(NOTIFICATION_TTL_SECONDS[config.notifications.ttl], 30)

    def test_unknown_value_is_rejected(self):
        with self.assertRaises(ValidationError):
            build_config({"ttl": "forever"})


if __name__ == "__main__":
    unittest.main()
