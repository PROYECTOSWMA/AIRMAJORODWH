"""Resource de BD para las propuestas SIRE (agnóstico del motor).

Hereda de ``AbstractDbResource`` (conexión, motor y helpers de insert). Aquí solo
se declara el modelo, la **clave natural** de un comprobante y el insert
**append-only** de la propuesta.
"""

from __future__ import annotations

from assets._common.abstract_resource import AbstractDbResource
from assets.sire_assets.sire_proposal_asset.models.model import SirePurchs, SireSales
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)

# Clave natural de un comprobante dentro de un periodo. `empresa` separa las dos
# empresas que comparten tabla y `nro_doc_identidad` es la contraparte (el
# proveedor en compras, el cliente en ventas): dos emisores distintos pueden usar
# la misma serie/número.
NATURAL_KEY = (
    "empresa",
    "tipo_cp_doc",
    "serie_del_cdp",
    "nro_cp_o_doc_nro_inicial_rango",
    "nro_doc_identidad",
)


class SireSqliteResource(AbstractDbResource):
    """Resource que inserta (append-only) las filas nuevas de la propuesta SIRE."""

    def _tables(self) -> tuple[type, ...]:
        return (SireSales, SirePurchs)

    def insert_proposal_new(
        self,
        period: str,
        rows: list[dict],
        book_code: str = BOOK_CODE_PURCHASES,
        *,
        empresa: str,
    ) -> int:
        """Inserta solo los comprobantes que aún no están en la tabla.

        La identidad es ``NATURAL_KEY`` dentro del periodo: los ids no cambian
        nunca, así que los hijos (``sire_*_details`` / ``sire_*_files``) no quedan
        huérfanos al re-materializar el mismo mes. **La primera versión gana**: una
        rectificatoria posterior del mismo comprobante no actualiza la fila ya
        guardada. ``period`` y ``empresa`` se inyectan en cada fila (igual que hacía
        el antiguo upsert). Devuelve el número de filas insertadas.
        """
        model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        existing = self._existing_keys(model, "period", [period], NATURAL_KEY)
        rows_with_meta = [
            {**row, "period": period, "empresa": empresa} for row in rows
        ]
        return self._insert_new(model, rows_with_meta, NATURAL_KEY, existing)

