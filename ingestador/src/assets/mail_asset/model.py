from __future__ import annotations
from peewee import CharField, ForeignKeyField, Model, TextField
from assets._common.db import db


class BaseModel(Model):
    class Meta:
        database = db


class Email(BaseModel):
    class Meta:
        table_name = "emails"

    # control
    id = CharField(primary_key=True)
    partition_date = CharField()
    mailbox = CharField(default="")

    # data
    sender = CharField(default="")
    subject = TextField(default="")
    body = TextField(default="")
    thread_id = CharField(null=True)
    header_date = CharField(null=True)
    received_date = CharField(null=True)


class EmailAttachments(BaseModel):
    email = ForeignKeyField(Email, backref="attachments")
    filename = CharField()
    data = TextField()

    class Meta:
        table_name = "email_attachments"


Email.add_index(Email.partition_date, name="emails_partition_date")
