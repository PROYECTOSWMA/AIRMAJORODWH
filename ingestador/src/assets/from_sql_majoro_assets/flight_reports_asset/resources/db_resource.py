"""Resource de BD para la tabla ``flight_reports`` (agnóstico del motor).

Hereda de ``AbstractDbResource`` (conexión, motor y upsert total). Aquí solo se
declara la tabla y el upsert total de la partición (borra el mes e inserta las
filas dadas).
"""

from __future__ import annotations

from assets._common.abstract_resource import AbstractDbResource
from assets.from_sql_majoro_assets.flight_reports_asset.models.model import FlightReports


class FlightReportsSqliteResource(AbstractDbResource):
    """Resource que hace upsert total por período de la tabla ``flight_reports``."""

    def _tables(self) -> tuple[type, ...]:
        return (FlightReports,)

    def upsert_report(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las filas de ``period`` por las dadas (upsert total)."""
        return self._replace(
            FlightReports, FlightReports.period == period, rows, {"period": period}
        )
