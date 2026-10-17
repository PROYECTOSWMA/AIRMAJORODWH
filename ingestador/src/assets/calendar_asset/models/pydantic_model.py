"""Réplica pydantic de una fila de ``dwh_calendar`` para validar antes del insert.

Los datos de la fecha se derivan en el asset; el modelo solo valida tipos y
convierte la fecha y los decimales (el endpoint devuelve ``fecha`` y los montos
como texto/número). Los errores de tipo saltan en el programa y no en la BD.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator


def _parse_date(value: Any) -> date | None:
    """Acepta fechas ISO ('2025-01-01'); vacío -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {value!r}")


CalendarDate = Annotated[date | None, BeforeValidator(_parse_date)]


def _parse_decimal(value: Any) -> Decimal | None:
    """Convierte a Decimal de 6 decimales; vacío/None -> None.

    ``json.loads`` puede devolver float (p. ej. ``3.77``) y ``Decimal(3.77)``
    arrastra ruido binario; se pasa por ``str`` y se redondea.
    """
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


ExchangeRate = Annotated[Decimal | None, BeforeValidator(_parse_decimal)]


class CalendarRow(BaseModel):
    """Fila de ``dwh_calendar`` (sin ``period``: la clave es ``date``)."""

    date: CalendarDate = None
    year: int | None = None
    month: int | None = None
    month_name: str | None = None
    day: int | None = None
    week_number: int | None = None
    exchange_rate_sale: ExchangeRate = None
    exchange_rate_purchase: ExchangeRate = None
