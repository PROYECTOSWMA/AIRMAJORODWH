

from __future__ import annotations

from peewee import (
    CharField,
    DateField,
    DecimalField,
    IntegerField,
    Model,
)

from assets._common.db import db


class BaseModel(Model):
    class Meta:
        database = db


class Calendar(BaseModel):

    class Meta:
        table_name = "calendar"

    date = DateField()
    year = IntegerField()
    month = IntegerField()
    month_name = CharField()
    day = IntegerField()
    week_number = IntegerField()
    exchange_rate_sale = DecimalField(max_digits=18, decimal_places=6, null=True)
    exchange_rate_purchase = DecimalField(max_digits=18, decimal_places=6, null=True)
