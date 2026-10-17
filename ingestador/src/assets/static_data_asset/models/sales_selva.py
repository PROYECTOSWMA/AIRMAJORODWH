"""Modelo peewee de la tabla ``sales_selva`` (reporte de ventas Air Majoro).

Consolida en una sola tabla todas las hojas del libro estático
``static/1.- REPORTE DE VENTAS AL 19.092026.xlsx`` (una hoja por mes y empresa:
``SELVA ...`` = Air Majoro Selva, ``S.A ...`` = Air Majoro S.A.).

El libro **no** tiene un esquema homogéneo (hojas con distinto número de columnas,
encabezados repetidos y columnas sin título), así que la tabla guarda:

* ``sheet_name``: nombre de la hoja de origen;
* ``row_number``: fila de Excel (1-based; la cabecera es la fila 1) para rastrear cada
  registro, útil para distinguir los subtotales (filas sin ``fecha``/``nro``);
* y **todas** las columnas de datos como texto: el nombre es el de la cabecera
  normalizado con ``to_db_field``; las columnas sin título quedan como
  ``col_<índice>`` y los encabezados repetidos se sufijan ``_2``.

Todo se guarda como texto (``CharField``) porque el libro mezcla en las mismas columnas
fechas, importes y notas (``"2026-09-01 00:00:00"``, ``"01,03,26"``, ``"15450.0"``...).
Las celdas vacías y el marcador ``"-"`` del libro se guardan como ``NULL``.
"""
from __future__ import annotations

from peewee import CharField, IntegerField

from assets.static_data_asset.models.base import BaseModel


class SalesSelva(BaseModel):
    """Fila del reporte de ventas (una hoja del libro = muchas filas)."""

    class Meta:
        table_name = "sales_selva"

    # Origen: nombre de la hoja y fila de Excel.
    sheet_name = CharField(null=True)
    row_number = IntegerField(null=True)

    # --- Cabecera común a las hojas "SELVA" y "S.A" ---
    fecha = CharField(null=True)
    nro_manif = CharField(null=True)
    avion = CharField(null=True)
    tripulacion = CharField(null=True)
    agente = CharField(null=True)
    tipo_de_vuelo = CharField(null=True)
    de = CharField(null=True)
    a = CharField(null=True)
    ad = CharField(null=True)
    md = CharField(null=True)
    inf = CharField(null=True)
    cia = CharField(null=True)
    tot_pax = CharField(null=True)
    carga = CharField(null=True)
    total = CharField(null=True)
    saldo = CharField(null=True)
    contado = CharField(null=True)
    pago_anticipado = CharField(null=True)
    f_dep = CharField(null=True)
    deposito = CharField(null=True)
    creditos = CharField(null=True)
    adic = CharField(null=True)
    comision = CharField(null=True)

    # --- Variantes de cabecera de las hojas "S.A" ---
    nro = CharField(null=True)
    vuelo = CharField(null=True)
    pasajes = CharField(null=True)
    pasaje = CharField(null=True)
    c0ntado = CharField(null=True)
    # Segunda columna ``CREDITOS`` de las hojas "S.A" (la que sigue a ``DEPOSITO``).
    creditos_2 = CharField(null=True)
    credito = CharField(null=True)

    # --- Conceptos extra que solo aparecen en algunas hojas ---
    tiempo_de_vuelo = CharField(null=True)
    gastos = CharField(null=True)
    monto_de_voucher = CharField(null=True)
    essalud = CharField(null=True)
    prosegur = CharField(null=True)
    maj_s_a = CharField(null=True)
    majoro_sa = CharField(null=True)
    ventas_c_autor_jefe_de_base = CharField(null=True)
    fenix = CharField(null=True)
    mtc = CharField(null=True)
    depositos = CharField(null=True)
    montos_del_dep = CharField(null=True)

    # Columnas sin título con datos (posición 0-based dentro de la hoja).
    col_24 = CharField(null=True)
    col_25 = CharField(null=True)
