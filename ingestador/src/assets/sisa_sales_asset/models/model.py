"""Modelo peewee de la tabla ``sisa_sales`` (liquidación contable de ventas SISA).

Usa su propio ``db`` (SQLite) con el mismo archivo que el resto del repo: el
asset no tiene relación con los assets SIRE, así que no comparte sus tablas ni
su instancia de BD.

Los nombres de columna son la normalización literal de las columnas del endpoint
vía ``assets.utils.to_db_field`` (``"FECHAEMISIO"`` -> ``fechaemisio``): esa
función no separa palabras concatenadas en mayúsculas, solo convierte a
snake_case lo que ya viene separado.
"""

from __future__ import annotations

from peewee import (
    CharField,
    DateField,
    DecimalField,
    IntegerField,
    Model,
    TextField,
)

from assets._common.db import db


class BaseModel(Model):
    class Meta:
        database = db


class SisaSales(BaseModel):
    """Fila de la liquidación contable de ventas por (empresa, sede) y mes."""

    class Meta:
        table_name = "sisa_sales"

    period = CharField()
    nombre_empresa = CharField()
    nombre_sede = CharField()

    # Réplica literal de las columnas del endpoint, normalizadas con ``to_db_field``.
    # Columnas nullable: el endpoint puede devolver celdas vacías/null.
    numerofila = IntegerField(null=True)
    codorgdoref = CharField(null=True)
    codperdoref = CharField(null=True)
    codseddoref = CharField(null=True)
    codempdoref = CharField(null=True)
    codregdoref = CharField(null=True)
    codnvedoref = CharField(null=True)
    nomtipmoned = CharField(null=True)
    t01tipdoref = CharField(null=True)
    nro_documento = CharField(null=True)
    fechaemisio = DateField(null=True)
    fechavuelo = DateField(null=True)
    numeroderuc = CharField(null=True)
    ruc_cliente20 = CharField(null=True)
    razonsocial = CharField(null=True)
    dorefsubtot = DecimalField(max_digits=18, decimal_places=2, null=True)
    dorefimpimp = DecimalField(max_digits=18, decimal_places=2, null=True)
    doreftotnum = DecimalField(max_digits=18, decimal_places=2, null=True)
    cuenta_contable = CharField(null=True)
    nomtipopago = CharField(null=True)
    aenavmatric = CharField(null=True)
    nomsitdoref = CharField(null=True)
    t01lugorige = CharField(null=True)
    desorigen = CharField(null=True)
    t01lugdesti = CharField(null=True)
    desdestino = CharField(null=True)
    tipcammoned = DecimalField(max_digits=18, decimal_places=4, null=True)
    cantidad = DecimalField(max_digits=18, decimal_places=4, null=True)
    observacion = TextField(null=True)


class SisaCreditNote(BaseModel):
    """Fila de las **notas de crédito** de SISA (``sisa_credit_notes``).

    Columnas del procedure ``USP_UVW_LIQUIDACION_NOTACREDITO`` normalizadas con
    ``to_db_field``. Estas filas se RESTAN de las ventas.
    """

    class Meta:
        table_name = "sisa_credit_notes"

    period = CharField()
    nombre_empresa = CharField()
    nombre_sede = CharField()

    numerofila = IntegerField(null=True)
    codorgdoref = CharField(null=True)
    codempdoref = CharField(null=True)
    codseddoref = CharField(null=True)
    codperdoref = CharField(null=True)
    codregdoref = CharField(null=True)
    codnvedoref = CharField(null=True)
    nomtipdoref = CharField(null=True)
    razonsocial = CharField(null=True)
    numeroderuc = CharField(null=True)
    sunatnserie = CharField(null=True)
    sunatnforma = CharField(null=True)
    fechaemisio = DateField(null=True)
    fechavuelo = DateField(null=True)
    t01tipopago = CharField(null=True)
    t01tipmoned = CharField(null=True)
    nomtipmoned = CharField(null=True)
    nomtipopago = CharField(null=True)
    dorefsubtot = DecimalField(max_digits=18, decimal_places=4, null=True)
    dorefdespor = DecimalField(max_digits=18, decimal_places=4, null=True)
    dorefdesimp = DecimalField(max_digits=18, decimal_places=4, null=True)
    dorefimppor = DecimalField(max_digits=18, decimal_places=4, null=True)
    dorefimpimp = DecimalField(max_digits=18, decimal_places=4, null=True)
    doreftotnum = DecimalField(max_digits=18, decimal_places=4, null=True)
    doreftotlet = CharField(null=True)
    t01sitdoref = CharField(null=True)
    swestadoreg = CharField(null=True)
    sunatnfodve = CharField(null=True)
    nomsitdoref = CharField(null=True)
