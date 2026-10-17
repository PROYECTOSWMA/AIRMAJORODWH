"""Modelo peewee de la tabla ``from_sire_petroperu_cost_centers``.

Una fila por aeronave ``OB-####`` extraída del XML de compras SIRE de
PETROLEOS DEL PERU - PETROPERU S.A. (RUC 20100128218). ``id_file`` es una Foreign
Key al ``id`` de la fila de ``sire_purchs_files`` (el ZIP del que salió el XML) y
``filename`` es el nombre del XML dentro del ZIP. ``period`` es la clave de la
partición mensual.

``aeropuerto`` y ``aeropuerto_completo`` salen del ``DatoAdicional`` de código 31
del comprobante: ``aeropuerto_completo`` es su ``Valor`` completo y ``aeropuerto``
su **última palabra**. Las filas anteriores a su incorporación quedan en ``NULL``
(la tabla se migra con ``ALTER TABLE`` desde el resource).
"""

from __future__ import annotations

from peewee import AutoField, CharField, ForeignKeyField

from assets.sire_assets.sire_files_asset.models.model import SirePurchsFiles
from assets.sire_assets.sire_proposal_asset.models.model import BaseModel


class PetroperuCostCenter(BaseModel):
    """Aeronave de un XML de compras SIRE de PETROLEOS DEL PERU - PETROPERU S.A."""

    class Meta:
        table_name = "from_sire_petroperu_cost_centers"

    id = AutoField()            # PK autoincremental (``id`` del enunciado)
    period = CharField()        # partición mensual (p. ej. "2026-01-01")
    file = ForeignKeyField(
        SirePurchsFiles,
        backref="petroperu_cost_centers",
        on_delete="CASCADE",
        object_id_name="id_file",
        column_name="id_file",
    )  # ZIP padre en ``sire_purchs_files``; acceso crudo vía ``id_file``
    filename = CharField()      # nombre del XML (sin el prefijo ``R-``) dentro del ZIP
    aeronave = CharField()      # matrícula OB-####
    # DatoAdicional de código 31: ``aeropuerto`` = última palabra del Valor,
    # ``aeropuerto_completo`` = Valor completo (NULL en filas previas).
    aeropuerto = CharField(null=True)
    aeropuerto_completo = CharField(null=True)
