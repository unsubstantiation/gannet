"""Peewee migrations -- 040_add_recordings_audio_duration.py.

Stores the summed length of a segment's audio samples next to its keyframe
index, so playback can skip a clip whose audio ended before the clip starts
(a camera audio dropout). Nullable so legacy rows stay NULL, meaning unknown.
"""

import peewee as pw

SQL = pw.SQL


def migrate(migrator, database, fake=False, **kwargs):
    migrator.sql('ALTER TABLE "recordings" ADD COLUMN "audio_duration" REAL')


def rollback(migrator, database, fake=False, **kwargs):
    pass
