"""Resource de BD para la tabla ``dwh_calendar`` (agnóstico del motor).

Hereda de ``AbstractDbResource`` (conexión, motor y upsert). Aquí solo se declara
la tabla y el upsert de la ventana semanal (por rango de fechas ``[start, end)``).
"""

from __future__ import annotations

from datetime import date

from assets._common.abstract_resource import AbstractDbResource
from assets.calendar_asset.models.model import Calendar


class CalendarSqliteResource(AbstractDbResource):
    """Resource que hace upsert de la ventana semanal de ``dwh_calendar``."""

    def _tables(self) -> tuple[type, ...]:
        return (Calendar,)

    def upsert_week(self, start_date: date, end_date: date, rows: list[dict]) -> int:
        """Reemplaza las filas de ``dwh_calendar`` con ``date`` en ``[start, end)``."""
        return self._replace(
            Calendar,
            (Calendar.date >= start_date) & (Calendar.date < end_date),
            rows,
        )
