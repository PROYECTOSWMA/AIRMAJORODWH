
from __future__ import annotations

from peewee import CharField, TextField

from assets.static_data_asset.models.base import BaseModel


class StaticDwhMasterAccounts(BaseModel):
    """Fila del maestro de cuentas del EERR."""

    class Meta:
        table_name = "static_dwh_master_accounts"
        primary_key = False

    codigo_pcge = CharField(null=True)
    grupo = CharField(null=True)
    cuenta = TextField(null=True)
    cuenta_pcge = TextField(null=True)
    comentario = TextField(null=True)
