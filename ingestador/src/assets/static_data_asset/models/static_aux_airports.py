
from __future__ import annotations

from peewee import CharField, TextField

from assets.static_data_asset.models.base import BaseModel


class StaticAuxAirports(BaseModel):

    class Meta:
        table_name = "static_aux_airports"
        primary_key = False

    icao = CharField(null=True)
    iata = CharField(null=True)
    denominacion = TextField(null=True)
    ubicacion = TextField(null=True)
    departamento = CharField(null=True)
