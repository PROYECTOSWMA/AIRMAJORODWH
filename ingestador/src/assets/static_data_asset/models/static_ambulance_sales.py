
from __future__ import annotations

from peewee import CharField, DecimalField, TextField
from playhouse.sqlite_ext import JSONField

from assets.static_data_asset.models.base import BaseModel


class StaticAmbulanceSales(BaseModel):
    """Fila de la hoja "VUELOS B200 2026" del libro VENTAS."""

    class Meta:
        table_name = "static_ambulance_sales_reports"

    # Réplica de las columnas A..Y que tienen cabecera, normalizadas con ``to_db_field``.
    codigo = CharField(null=True)
    cliente = CharField(null=True)
    aeronave = CharField(null=True)
    fecha_vlo = CharField(null=True)
    factura = CharField(null=True)
    # Derivada de `factura` (la calcula parse_factura_fields al ingerir el Excel):
    # lista completa de facturas del vuelo como array JSON (columna TEXT).
    agregado_factura = JSONField(null=True)
    ruta = CharField(null=True)
    servicio_paciente = CharField(null=True)
    ft_no = CharField(null=True)
    soles = DecimalField(max_digits=18, decimal_places=2, null=True)
    dolares = DecimalField(max_digits=18, decimal_places=2, null=True)
    status = CharField(null=True)
    fecha_pago = CharField(null=True)
    banco = CharField(null=True)
    pilotos_cop = CharField(null=True)
    hora_de_vuelo = CharField(null=True)
    hora_retiro = CharField(null=True)
    observaciones = TextField(null=True)
