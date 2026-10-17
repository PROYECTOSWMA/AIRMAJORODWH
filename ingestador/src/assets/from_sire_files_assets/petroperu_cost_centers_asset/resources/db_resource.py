"""Resource de BD de las aeronaves de PETROLEOS DEL PERU - PETROPERU S.A.

Solo define el modelo peewee (``from_sire_petroperu_cost_centers``) y el RUC del
proveedor; la lógica de lectura/upsert vive en ``AeronaveSireSqliteResource``.
"""

from __future__ import annotations

from assets.from_sire_files_assets._common.db_resource import (
    AeronaveSireSqliteResource,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.models.model import (
    PetroperuCostCenter,
)


class PetroperuCostCenterSqliteResource(AeronaveSireSqliteResource):
    """Aeronaves de los ZIP SIRE de PETROLEOS DEL PERU - PETROPERU S.A."""

    _model = PetroperuCostCenter
    _ruc = "20100128218"
