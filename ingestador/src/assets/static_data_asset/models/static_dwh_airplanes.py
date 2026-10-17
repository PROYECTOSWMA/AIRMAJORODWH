
from __future__ import annotations

from peewee import CharField, TextField

from assets.static_data_asset.models.base import BaseModel


class StaticDwhAirplanes(BaseModel):
    """Fila del maestro de aeronaves."""

    class Meta:
        table_name = "static_dwh_airplanes"
        primary_key = False

    registration = CharField(null=True)
    owner = TextField(null=True)
    model = CharField(null=True)
    business_unit = CharField(null=True)
    base = CharField(null=True)
    passengers = CharField(null=True)
    fuel = CharField(null=True)
