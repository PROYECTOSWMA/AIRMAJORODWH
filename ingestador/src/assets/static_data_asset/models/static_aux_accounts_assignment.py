
from __future__ import annotations

from peewee import CharField

from assets.static_data_asset.models.base import BaseModel


class StaticAuxAccountsAssignment(BaseModel):
    """Fila de regla RUC + patrón de servicio → cuenta."""

    class Meta:
        table_name = "static_aux_accounts_assignment"
        primary_key = False

    partner_doc = CharField(null=True)
    partner_desc = CharField(null=True)
    serv_desc_pattern = CharField(null=True)
    account = CharField(null=True)
