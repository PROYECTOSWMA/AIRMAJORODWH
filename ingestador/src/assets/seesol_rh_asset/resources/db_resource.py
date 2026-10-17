"""Resource de BD para la tabla ``seesol_rh`` (agnóstico del motor).

Hereda de ``AbstractDbResource`` (conexión, motor y upsert) y declara su única
tabla. El upsert es **por (mes, empresa)**: cada materialización del asset
reemplaza solo lo que acaba de descargar de esa empresa en ese mes, así que la
otra empresa (o los otros meses) no se tocan aunque su descarga haya fallado.
"""

from __future__ import annotations

from assets._common.abstract_resource import AbstractDbResource
from assets.seesol_rh_asset.models.rh import Rh


class SeesolRhSqliteResource(AbstractDbResource):
    """Resource que hace el upsert por (mes, empresa) de ``seesol_rh``."""

    def _tables(self) -> tuple[type, ...]:
        return (Rh,)

    def count_month(self, period: str, empresa: str) -> int:
        """Filas actuales de ``seesol_rh`` de ese ``(period, empresa)``.

        Se consulta **antes** del upsert para poder avisar si el reporte nuevo
        trae menos filas que el anterior (un mes todavía incompleto en SUNAT).
        """
        self._ensure_db()
        return (
            Rh.select()
            .where((Rh.period == period) & (Rh.empresa == empresa))
            .count()
        )

    def upsert_month(self, period: str, empresa: str, rows: list[dict]) -> int:
        """Reemplaza las filas de ``(period, empresa)`` por las dadas.

        Borra solo esa combinación mes+empresa e inserta ``rows`` (cada fila trae
        los 16 campos del reporte; ``period`` y ``empresa`` se inyectan aquí para
        que la fila quede consistente con el filtro del borrado). Devuelve el
        número de filas insertadas.
        """
        return self._replace(
            Rh,
            (Rh.period == period) & (Rh.empresa == empresa),
            rows,
            {"period": period, "empresa": empresa},
        )
