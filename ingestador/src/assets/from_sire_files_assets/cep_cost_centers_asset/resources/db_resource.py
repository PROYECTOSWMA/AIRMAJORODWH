"""Resource de BD de las aeronaves de CONSORCIO ENERGÉTICO DEL PERÚ.

Solo define el modelo peewee (``from_sire_cep_cost_centers``) y el RUC del proveedor; la
lógica de lectura/upsert vive en ``AeronaveSireSqliteResource``.
"""

from __future__ import annotations

from assets.from_sire_files_assets._common.db_resource import (
    AeronaveSireSqliteResource,
)
from assets.from_sire_files_assets.cep_cost_centers_asset.models.model import (
    CepCostCenter,
)


class CepCostCenterSqliteResource(AeronaveSireSqliteResource):
    """Aeronaves de los ZIP SIRE de CONSORCIO ENERGÉTICO DEL PERÚ."""

    _model = CepCostCenter
    _ruc = "20613566881"
