"""Modelo peewee de la tabla ``seesol_rh`` (comprobantes de renta RH).

Una fila por comprobante de renta del reporte RH que devuelve el SEE-SOL. Las
columnas de la cabecera se normalizan con ``assets.utils.to_db_field``. ``period``
es el mes de la partición (``"2026-08-01"``) y ``empresa`` la empresa a la que
pertenece el reporte. Los campos numéricos son nullable porque el reporte puede
traerlos vacíos o ``-``.

Comparte el ``db`` (``DatabaseProxy``) de ``assets._common.db``, como el resto de
los modelos del repo, así que el motor es intercambiable (SQLite/PostgreSQL).
"""
from __future__ import annotations

from peewee import CharField, DecimalField, Model, TextField

from assets._common.db import db


class BaseModel(Model):
    """Modelo peewee enlazado al ``db`` compartido del repo."""

    class Meta:
        database = db


class Rh(BaseModel):
    """Fila del reporte RH de comprobantes de renta."""

    class Meta:
        table_name = "seesol_rh"

    period = CharField()
    empresa = CharField()

    # Réplica de las 16 columnas de la cabecera del reporte, normalizadas.
    fecha_de_emision = CharField(null=True)
    tipo_doc_emitido = CharField(null=True)
    nro_doc_emitido = CharField(null=True)
    estado_doc_emitido = CharField(null=True)
    tipo_de_doc_emisor = CharField(null=True)
    nro_doc_emisor = CharField(null=True)
    apellidos_y_nombres_denominacion_o_razon_social_del_emisor = CharField(null=True)
    tipo_de_renta = CharField(null=True)
    gratuito = CharField(null=True)
    descripcion = TextField(null=True)
    observacion = TextField(null=True)
    moneda_de_operacion = CharField(null=True)
    renta_bruta = DecimalField(max_digits=18, decimal_places=2, null=True)
    impuesto_a_la_renta = DecimalField(max_digits=18, decimal_places=2, null=True)
    renta_neta = DecimalField(max_digits=18, decimal_places=2, null=True)
    monto_neto_pendiente_de_pago = DecimalField(
        max_digits=18, decimal_places=2, null=True
    )
