"""Modelo peewee de la tabla ``from_sire_icaro_cost_centers``.

Una fila por aeronave extraída del ticket de la ``cac:InvoiceLine`` del XML de
compras SIRE de ICARO DIECISIETE S.A.S. (RUC 20602542115). ``id_file`` es una
Foreign Key al ``id`` de la fila de ``sire_purchs_files`` (el ZIP del que salió el
XML) y ``filename`` es el nombre del XML dentro del ZIP. ``period`` es la clave de
la partición mensual. Las columnas del ticket (``nro_ticket``, ``texto_planta``,
``texto_matricula``, ``matricula`` y ``schema_info``) son ``null`` en las filas
anteriores a su incorporación (la tabla se migra con ``ALTER TABLE``).
"""

from __future__ import annotations

from peewee import AutoField, CharField, ForeignKeyField

from assets.sire_assets.sire_files_asset.models.model import SirePurchsFiles
from assets.sire_assets.sire_proposal_asset.models.model import BaseModel


class IcaroCostCenter(BaseModel):
    """Aeronave de un XML de compras SIRE de ICARO DIECISIETE S.A.S."""

    class Meta:
        table_name = "from_sire_icaro_cost_centers"

    id = AutoField()            # PK autoincremental (``id`` del enunciado)
    period = CharField()        # partición mensual (p. ej. "2026-01-01")
    file = ForeignKeyField(
        SirePurchsFiles,
        backref="icaro_cost_centers",
        on_delete="CASCADE",
        object_id_name="id_file",
        column_name="id_file",
    )  # ZIP padre en ``sire_purchs_files``; acceso crudo vía ``id_file``
    filename = CharField()      # nombre del XML (sin el prefijo ``R-``) dentro del ZIP
    aeronave = CharField()      # matrícula de 4 dígitos (lo lee el dbt)
    nro_ticket = CharField(null=True)       # nro del ticket de la InvoiceLine
    texto_planta = CharField(null=True)     # planta del ticket (CHICLAYO, PISCO, ...)
    texto_matricula = CharField(null=True)  # matrícula tal cual viene (OB2092, OB2104P)
    matricula = CharField(null=True)        # 4 primeros dígitos de ``texto_matricula``
    schema_info = CharField(null=True)      # texto completo del ticket

