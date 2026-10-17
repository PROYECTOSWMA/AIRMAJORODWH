
from __future__ import annotations

from peewee import CharField, TextField, IntegerField

from assets.static_data_asset.models.base import BaseModel


class StaticDwhMasterAccountGroups(BaseModel):
    class Meta:
        table_name = "static_dwh_master_account_groups"
        primary_key = False
    tipo = CharField()
    grupo = CharField()
    orden = IntegerField()
