import peewee as pw

from gannet.models import Event


def migrate(migrator, database, fake=False, **kwargs):
    migrator.change_fields(Event, sub_label=pw.CharField(max_length=100, null=True))


def rollback(migrator, database, fake=False, **kwargs):
    migrator.change_fields(Event, sub_label=pw.CharField(max_length=20, null=True))
