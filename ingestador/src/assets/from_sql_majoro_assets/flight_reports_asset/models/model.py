"""Modelo peewee de la tabla ``flight_reports`` (reporte de estadísticas de vuelos).

Usa su propio ``db`` (SQLite) con el mismo archivo que el resto del repo, pero la
tabla es independiente: no tiene relación con ninguna otra tabla del proyecto (no
la lee ningún modelo de dbt salvo su copia directa ``flight_reports``).

Las columnas son las que devuelve ``USP_ESTADISTICAS_VUELOS_PERIODO`` con
``@OpcionReporte=4`` normalizadas por ``assets.utils.to_db_field``:
``"Fecha_Vuelo"`` -> ``fecha_vuelo``, ``"Sede_Operacion"`` -> ``sede_operacion``,
``"Matricula"`` -> ``matricula``, ``"Horas_Vuelo"`` -> ``horas_vuelo`` y
``"Total_Pasajeros"`` -> ``total_pasajeros``. El campo ``period`` lo inyecta el
asset (el mes de la partición) para poder hacer un upsert total idempotente.
"""

from __future__ import annotations

from peewee import (
    CharField,
    DateField,
    DecimalField,
    IntegerField,
    Model,
)

from assets._common.db import db


class BaseModel(Model):
    class Meta:
        database = db


class FlightReports(BaseModel):
    """Fila del reporte de estadísticas de vuelos por mes (período)."""

    class Meta:
        table_name = "flight_reports"

    # Mes de la partición (clave del upsert total); el resto son columnas del reporte.
    period = CharField()
    fecha_vuelo = DateField(null=True)
    sede_operacion = CharField(null=True)
    matricula = CharField(null=True)
    horas_vuelo = DecimalField(max_digits=18, decimal_places=2, null=True)
    total_pasajeros = IntegerField(null=True)
