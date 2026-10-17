"""Modelos peewee de los detalles de comprobantes CPE (SIRE).

Reutilizan el mismo ``db`` (SQLite) y las tablas ``sire_sales``/``sire_purchs``
como padres de la relación 1 a N. Además del FK se guardan ``period`` y ``empresa``
denormalizados: el upsert del padre (``upsert_proposal``) borra e inserta con ids
nuevos cada corrida, así que el upsert de detalle se hace por ``(period, empresa)``
y eso limpia también cualquier detalle huérfano de corridas anteriores.
"""

from __future__ import annotations

from peewee import CharField, DecimalField, ForeignKeyField

from assets.sire_assets.sire_proposal_asset.models.model import (
    BaseModel,
    SirePurchs,
    SireSales,
)


class SireSalesDetails(BaseModel):
    """Ítem de línea de un comprobante de venta (1 a N con ``sire_sales``)."""

    class Meta:
        table_name = "sire_sales_details"

    sire_sale = ForeignKeyField(SireSales, backref="details", on_delete="CASCADE")
    period = CharField()
    empresa = CharField()

    # Réplica literal de informacionItems. Ningún campo es anulable.
    # cnt_items es Decimal: SUNAT manda cantidades fraccionarias (p. ej. kilos).
    cnt_items = DecimalField(max_digits=18, decimal_places=2)
    cod_unidad_medida = CharField()
    des_unidad_medida = CharField()
    des_codigo = CharField()
    des_item = CharField()
    mto_val_unitario = DecimalField(max_digits=18, decimal_places=2)
    mto_icbper = DecimalField(max_digits=18, decimal_places=2)
    mto_desc = DecimalField(max_digits=18, decimal_places=2)
    mto_imp_total = DecimalField(max_digits=18, decimal_places=2)


class SirePurchsDetails(BaseModel):
    """Ítem de línea de un comprobante de compra (1 a N con ``sire_purchs``)."""

    class Meta:
        table_name = "sire_purchs_details"

    sire_purch = ForeignKeyField(SirePurchs, backref="details", on_delete="CASCADE")
    period = CharField()
    empresa = CharField()

    # Réplica literal de informacionItems. Ningún campo es anulable.
    # cnt_items es Decimal: SUNAT manda cantidades fraccionarias (p. ej. kilos).
    cnt_items = DecimalField(max_digits=18, decimal_places=2)
    cod_unidad_medida = CharField()
    des_unidad_medida = CharField()
    des_codigo = CharField()
    des_item = CharField()
    mto_val_unitario = DecimalField(max_digits=18, decimal_places=2)
    mto_icbper = DecimalField(max_digits=18, decimal_places=2)
    mto_desc = DecimalField(max_digits=18, decimal_places=2)
    mto_imp_total = DecimalField(max_digits=18, decimal_places=2)
