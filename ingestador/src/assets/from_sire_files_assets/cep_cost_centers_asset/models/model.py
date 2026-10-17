"""Modelo peewee de la tabla ``from_sire_cep_cost_centers``.

Una fila por aeronave ``OB-####`` extraída del XML de compras SIRE de
CONSORCIO ENERGÉTICO DEL PERÚ (RUC 20613566881). ``id_file`` es una Foreign Key
al ``id`` de la fila de ``sire_purchs_files`` (el ZIP del que salió el XML) y
``filename`` es el nombre del XML dentro del ZIP. ``period`` es la clave de la
partición mensual.
"""

from __future__ import annotations

from peewee import AutoField, CharField, ForeignKeyField

from assets.sire_assets.sire_files_asset.models.model import SirePurchsFiles
from assets.sire_assets.sire_proposal_asset.models.model import BaseModel


class CepCostCenter(BaseModel):
    """Aeronave de un XML de compras SIRE de CONSORCIO ENERGÉTICO DEL PERÚ."""

    class Meta:
        table_name = "from_sire_cep_cost_centers"

    id = AutoField()            # PK autoincremental (``id`` del enunciado)
    period = CharField()        # partición mensual (p. ej. "2026-01-01")
    file = ForeignKeyField(
        SirePurchsFiles,
        backref="cep_cost_centers",
        on_delete="CASCADE",
        object_id_name="id_file",
        column_name="id_file",
    )  # ZIP padre en ``sire_purchs_files``; acceso crudo vía ``id_file``
    filename = CharField()      # nombre del XML (sin el prefijo ``R-``) dentro del ZIP
    aeronave = CharField()      # matrícula OB-####
