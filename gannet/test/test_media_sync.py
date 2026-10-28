"""Tests for the media library sync helpers."""

import datetime
import os
import tempfile
import unittest
from unittest.mock import patch

from peewee import SqliteDatabase

from gannet.models import Recordings
from gannet.util import media


class TestLimitedRecordingScan(unittest.TestCase):
    """The limited scan must only walk hours newer than the 36h cutoff."""

    def setUp(self):
        self.db = SqliteDatabase(":memory:")
        self.db.bind([Recordings])
        self.db.connect()
        self.db.create_tables([Recordings])
        self.addCleanup(self.db.close)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        now = datetime.datetime.now().astimezone(datetime.UTC)
        # the same floor the sync uses for its 36 hour checkpoint
        checkpoint = now.replace(
            minute=0, second=0, microsecond=0
        ) - datetime.timedelta(hours=36)
        old_hour = checkpoint - datetime.timedelta(hours=2)
        new_hour = now - datetime.timedelta(hours=1)

        self.old_file = self._touch(old_hour, "cam", "00.00.mp4")
        self.new_file = self._touch(new_hour, "cam", "00.01.mp4")

    def _touch(self, when: datetime.datetime, camera: str, name: str) -> str:
        path = os.path.join(
            self.tmp.name,
            when.strftime("%Y-%m-%d"),
            when.strftime("%H"),
            camera,
            name,
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb"):
            pass
        return path

    def test_limited_scan_excludes_hours_older_than_the_cutoff(self):
        with patch.object(media, "RECORD_DIR", self.tmp.name):
            result = media.sync_recordings(limited=True, dry_run=True, force=True)

        # the old hour must not be walked, so only the fresh file is checked
        self.assertEqual(result.files_checked, 1)
        self.assertEqual(result.orphan_paths, [self.new_file])

    def test_full_scan_walks_every_hour(self):
        with patch.object(media, "RECORD_DIR", self.tmp.name):
            result = media.sync_recordings(limited=False, dry_run=True, force=True)

        self.assertEqual(result.files_checked, 2)
        self.assertCountEqual(result.orphan_paths, [self.old_file, self.new_file])


class TestRecordingDbScanPaging(unittest.TestCase):
    """The DB half of the recordings sync has to visit every row.

    ``peewee`` numbers pages from 1, so a scan that walks ``range(num_pages)``
    reads the first page twice and never reads the last one.
    """

    PAGE_SIZE = 1000

    def setUp(self):
        self.db = SqliteDatabase(":memory:")
        self.db.bind([Recordings])
        self.db.connect()
        self.db.create_tables([Recordings])
        self.addCleanup(self.db.close)

    def test_db_scan_checks_every_recording_row(self):
        # one row past the first page is what the off-by-one lost
        total = self.PAGE_SIZE + 500
        rows = [
            {
                "id": f"{index:030d}",
                "camera": "cam",
                "path": os.path.join("recordings", f"{index:030d}.mp4"),
                "start_time": datetime.datetime.now()
                .astimezone(datetime.UTC)
                .timestamp(),
                "end_time": datetime.datetime.now()
                .astimezone(datetime.UTC)
                .timestamp(),
                "duration": 10.0,
            }
            for index in range(total)
        ]

        with self.db.atomic():
            for batch_start in range(0, total, 500):
                Recordings.insert_many(rows[batch_start : batch_start + 500]).execute()

        self.assertEqual(Recordings.select().count(), total)

        with tempfile.TemporaryDirectory() as empty_dir:
            with patch.object(media, "RECORD_DIR", empty_dir):
                result = media.sync_recordings(dry_run=True, force=True)

        # none of the paths exist on disk, so every row is an orphan
        self.assertEqual(result.orphans_found, total)
        self.assertEqual(len(set(result.orphan_db_paths)), total)


if __name__ == "__main__":
    unittest.main()
