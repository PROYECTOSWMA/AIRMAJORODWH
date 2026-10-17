"""Modelo peewee de la tabla ``lap_reports`` (reporte de aeronavegación de LAP).

Una fila por línea de servicio de la hoja "Aeronave" del Excel LAP, con los nombres
de cabecera normalizados con ``assets.utils.to_db_field``. La tabla es un **snapshot
sin partición ni ``period``**: el asset ``static_data_asset`` la reemplaza entera en
cada materialización (el Excel de ``static/`` es la foto vigente). Las columnas son
nullable porque el Excel puede dejar celdas vacías; las columnas sin cabecera de la
hoja se ignoran.
"""
from __future__ import annotations

from peewee import CharField, DecimalField

from assets.static_data_asset.models.base import BaseModel


class StaticLapReports(BaseModel):
    """Fila de la hoja "Aeronave" del Excel LAP."""

    class Meta:
        table_name = "static_lap_reports"

    # Réplica de las columnas con cabecera de la hoja "Aeronave", normalizadas.
    codigo_entidad = CharField(null=True)
    descripcion_entidad = CharField(null=True)
    factura = CharField(null=True)
    documento = CharField(null=True)
    fecha_factura = CharField(null=True)
    tipo_aeronave = CharField(null=True)
    matricula = CharField(null=True)
    movimiento = CharField(null=True)
    pmd = DecimalField(max_digits=18, decimal_places=4, null=True)
    servicio = CharField(null=True)
    material_sector_nombre = CharField(null=True)
    origen = CharField(null=True)
    destino = CharField(null=True)
    vuelo_llegada = CharField(null=True)
    vuelo_salida = CharField(null=True)
    fecha_hora_llegada = CharField(null=True)
    fecha_llegada = CharField(null=True)
    hora_llegada = CharField(null=True)
    fecha_hora_salida = CharField(null=True)
    fecha_salida = CharField(null=True)
    hora_salida = CharField(null=True)
    minutos = DecimalField(max_digits=18, decimal_places=4, null=True)
    recurso = CharField(null=True)
    minutos_total = DecimalField(max_digits=18, decimal_places=4, null=True)
    moneda = CharField(null=True)
    precio_unitario = DecimalField(max_digits=18, decimal_places=4, null=True)
    inc_igv = DecimalField(max_digits=18, decimal_places=4, null=True)
    importe_bruto = DecimalField(max_digits=18, decimal_places=4, null=True)
    importe_igv = DecimalField(max_digits=18, decimal_places=4, null=True)
    importe_ajuste = DecimalField(max_digits=18, decimal_places=4, null=True)
    importe_total = DecimalField(max_digits=18, decimal_places=4, null=True)
