"""Modelos peewee de los archivos (PDF/ZIP) de comprobantes CPE (SIRE).

Reutilizan el mismo ``db`` (SQLite) y las tablas ``sire_sales``/``sire_purchs``
como padres de la relación 1 a N. Por cada documento se guardan hasta dos filas:
una con ``tipo_documento = "PDF"`` (segmento ``/01`` de la API) y otra con
``tipo_documento = "ZIP"`` (segmento ``/02``). Además del FK se guardan ``period``
y ``empresa`` denormalizados: el upsert del padre (``upsert_proposal``) borra e
inserta con ids nuevos cada corrida, así que el asset limpia los huérfanos por
``(period, empresa)``.
"""

from __future__ import annotations

from peewee import CharField, ForeignKeyField, TextField

from assets.sire_assets.sire_proposal_asset.models.model import (
    BaseModel,
    SirePurchs,
    SireSales,
)


class SireSalesFiles(BaseModel):
    """Archivo (PDF o ZIP) de un comprobante de venta (1 a N con ``sire_sales``)."""

    class Meta:
        table_name = "sire_sales_files"

    sire_sale = ForeignKeyField(SireSales, backref="files", on_delete="CASCADE")
    period = CharField()
    empresa = CharField()
    tipo_documento = CharField()  # "PDF" o "ZIP"
    nom_archivo = CharField()
    val_archivo = TextField()  # contenido base64 devuelto por la API


class SirePurchsFiles(BaseModel):
    """Archivo (PDF o ZIP) de un comprobante de compra (1 a N con ``sire_purchs``)."""

    class Meta:
        table_name = "sire_purchs_files"

    sire_purch = ForeignKeyField(SirePurchs, backref="files", on_delete="CASCADE")
    period = CharField()
    empresa = CharField()
    tipo_documento = CharField()  # "PDF" o "ZIP"
    nom_archivo = CharField()
    val_archivo = TextField()  # contenido base64 devuelto por la API
