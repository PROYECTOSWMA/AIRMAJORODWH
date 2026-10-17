"""Resource HTTP del reporte RH del SEE-SOL y sus constantes de protocolo."""

from assets.seesol_rh_asset.resources.api_resource.constants import EMPRESAS
from assets.seesol_rh_asset.resources.api_resource.rh_resource import (
    RhResource,
    SeesolRhError,
    descargar_reporte,
    rango_del_mes,
)

__all__ = [
    "EMPRESAS",
    "RhResource",
    "SeesolRhError",
    "descargar_reporte",
    "rango_del_mes",
]
