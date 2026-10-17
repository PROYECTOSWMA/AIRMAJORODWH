

from __future__ import annotations

from assets._common.db import db
from assets.from_sire_files_assets._common.db_resource import (
    AeronaveSireSqliteResource,
)
from assets.from_sire_files_assets.icaro_cost_centers_asset.models.model import (
    IcaroCostCenter,
)

class IcaroCostCenterSqliteResource(AeronaveSireSqliteResource):
    """Aeronaves de los ZIP SIRE de ICARO DIECISIETE S.A.S. SUCURSAL PERU."""

    _model = IcaroCostCenter
    _ruc = "20602542115"
