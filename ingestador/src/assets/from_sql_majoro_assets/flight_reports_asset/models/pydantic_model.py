"""Réplica pydantic de una fila de ``flight_reports`` para validar antes del insert.

``FlightReportsResource.get_report`` devuelve las filas con claves normalizadas
con ``assets.utils.to_db_field`` (``"Fecha_Vuelo"`` -> ``fecha_vuelo``). Antes del
upsert se validan con este modelo para que los errores de tipo/fecha/decimal
salten en el programa y no en la BD. Las columnas extra que el modelo no tiene se
descartan al volcar el modelo validado.

Todos los campos son opcionales a propósito: el endpoint puede devolver celdas
vacías/null en cualquier columna y eso no debe romper la ingesta.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator


def _parse_date(value: Any) -> date | None:
    """Acepta ISO con hora ('2026-08-01T00:00:00.0000000'), ISO o 'dd/mm/yyyy'.

    El endpoint devuelve ``Fecha_Vuelo`` como fecha ISO con 7 dígitos de fracción
    ('2026-08-01T00:00:00.0000000'), que ``datetime.fromisoformat`` no parsea tal
    cual: se toma solo la parte de la fecha. Vacío -> ``None``.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip().replace("T", " ").split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {value!r}")


FlightDate = Annotated[date | None, BeforeValidator(_parse_date)]


def _parse_decimal(value: Any, places: int) -> Decimal | None:
    """Convierte a Decimal de ``places`` decimales; vacío/None -> None.

    ``json.loads`` devuelve floats (p. ej. ``3.5``) y ``Decimal(3.5)`` arrastra
    ruido binario; se pasa por ``str`` y se redondea.
    """
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(
        Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP
    )


def _hours(value: Any) -> Decimal | None:
    return _parse_decimal(value, 2)


Hours = Annotated[Decimal | None, BeforeValidator(_hours)]


class FlightReportRow(BaseModel):
    """Fila del reporte de estadísticas de vuelos.

    Réplica de ``FlightReports`` sin ``period``, que inyecta el asset al hacer el
    upsert.
    """

    fecha_vuelo: FlightDate = None
    sede_operacion: str | None = None
    matricula: str | None = None
    horas_vuelo: Hours = None
    total_pasajeros: int | None = None
