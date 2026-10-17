
from __future__ import annotations

from peewee import CharField

from assets.static_data_asset.models.base import BaseModel


class StaticAuxCostCentersOverride(BaseModel):
    """Fila de override de centro de costo por documento."""

    class Meta:
        table_name = "static_aux_cost_centers_override"
        primary_key = False

    partner_doc = CharField(null=True)
    doc_serie = CharField(null=True)
    doc_number = CharField(null=True)
    cost_center = CharField(null=True)
