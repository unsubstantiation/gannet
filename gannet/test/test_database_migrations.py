# SPDX-License-Identifier: LicenseRef-GNCL-1.0
"""Database upgrades retain legacy data without restoring removed runtime fields."""

import unittest

from peewee import SqliteDatabase
from peewee_migrate import Router

from gannet.models import Event


class TestEventMigrationCompatibility(unittest.TestCase):
    def test_fresh_database_does_not_restore_legacy_orm_field(self):
        with SqliteDatabase(":memory:") as db:
            Router(db).run()
            self.assertIn(
                "plus_id", {column.name for column in db.get_columns("event")}
            )
            self.assertNotIn("plus_id", Event._meta.fields)

    def test_historical_migration_can_be_rolled_back_and_reapplied(self):
        with SqliteDatabase(":memory:") as db:
            router = Router(db)
            router.run(name="010_add_plus_image_id")
            self.assertIn(
                "plus_id", {column.name for column in db.get_columns("event")}
            )

            # The old recordings table is created from today's ORM during
            # this synthetic replay, producing an unrelated index on a column
            # that was added by a later migration. Real 010-era databases do
            # not have that index; SQLite validates all indexes on DROP COLUMN.
            db.execute_sql("DROP INDEX IF EXISTS recordings_activity")
            Router(db).rollback()
            self.assertNotIn(
                "plus_id", {column.name for column in db.get_columns("event")}
            )
            self.assertNotIn("plus_id", Event._meta.fields)

            Router(db).run(name="010_add_plus_image_id")
            self.assertIn(
                "plus_id", {column.name for column in db.get_columns("event")}
            )
            self.assertNotIn("plus_id", Event._meta.fields)

    def test_pre_and_post_legacy_column_upgrades_preserve_events(self):
        for migration, legacy_id in (
            ("009_add_object_filter_ratio", None),
            ("010_add_plus_image_id", "old-image-id"),
        ):
            with self.subTest(migration=migration), SqliteDatabase(":memory:") as db:
                router = Router(db)
                router.run(name=migration)
                columns = (
                    "id, label, camera, start_time, end_time, top_score, "
                    "false_positive, zones, thumbnail, has_clip, has_snapshot, "
                    "region, box, area, retain_indefinitely, ratio"
                )
                values = (
                    "'event-1', 'car', 'driveway', 100, 101, 0.9, "
                    "0, '[]', '', 1, 1, '[]', '[]', 0, 0, 1.0"
                )
                db.execute_sql(f"INSERT INTO event ({columns}) VALUES ({values})")
                if legacy_id:
                    db.execute_sql(
                        "UPDATE event SET plus_id = ? WHERE id = 'event-1'",
                        (legacy_id,),
                    )

                router.run()
                self.assertEqual(
                    db.execute_sql("SELECT label, plus_id FROM event").fetchone(),
                    ("car", legacy_id),
                )
                self.assertNotIn("plus_id", Event._meta.fields)
                with db.bind_ctx([Event]):
                    event = Event.get_by_id("event-1")
                    event.label = "vehicle"
                    event.save()
                self.assertEqual(
                    db.execute_sql("SELECT label, plus_id FROM event").fetchone(),
                    ("vehicle", legacy_id),
                )


if __name__ == "__main__":
    unittest.main()
