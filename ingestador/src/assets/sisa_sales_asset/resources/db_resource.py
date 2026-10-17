"""Resource de BD para la tabla ``sisa_sales`` (agnóstico del motor).

Hereda de ``AbstractDbResource`` (conexión, motor y upsert total). Aquí solo se
declara la tabla y el upsert total de la partición: como el borrado es por todo
el mes, el asset reúne las filas de las 3 sedes y hace una sola llamada.
"""

from __future__ import annotations

from assets._common.abstract_resource import AbstractDbResource
from assets.sisa_sales_asset.models.model import SisaCreditNote, SisaSales


class SisaSalesSqliteResource(AbstractDbResource):
    """Resource que hace upsert total por período de ``sisa_sales`` y ``sisa_credit_notes``."""

    def _tables(self) -> tuple[type, ...]:
        return (SisaSales, SisaCreditNote)

    def upsert_sales(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las filas de ``period`` por las dadas (upsert total)."""
        return self._replace(
            SisaSales, SisaSales.period == period, rows, {"period": period}
        )

    def upsert_credit_notes(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las notas de crédito de ``period`` por las dadas (upsert total)."""
        return self._replace(
            SisaCreditNote,
            SisaCreditNote.period == period,
            rows,
            {"period": period},
        )

