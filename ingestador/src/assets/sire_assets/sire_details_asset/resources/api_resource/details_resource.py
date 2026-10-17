"""Consulta de detalles (ítems de línea) de comprobantes CPE de SUNAT api-cpe.

Un comprobante (factura, boleta, NC, ND) se consulta individualmente en
``/v1/contribuyente/consultacpe/comprobantes/{senderruc}-{tipo}-{serie}-{numero}-{rol}``.
La respuesta trae, entre otros, ``comprobantes[].informacionItems``: los ítems de
línea del documento. Eso es lo único que este resource devuelve.

La lógica HTTP (URL, headers, retry ante 500 y mapeo de status a excepciones)
vive en la base compartida ``DetailsAndFilesResource``; aquí solo se hereda y se
implementa el parseo de la respuesta (``_parse_response``).
"""

from __future__ import annotations

# Se importan (aunque no se usen aquí) para que los tests existentes, que
# parchean ``details_mod.requests`` / ``details_mod.time``, sigan apuntando al
# mismo objeto módulo que usa la base compartida.
import requests  # noqa: F401
import time  # noqa: F401
from typing import Any

from assets.sire_assets.resources.details_and_files_resource import (
    DetailsAndFilesResource,
    SireApiError,
    SireApiMissing,
    SireApiUnauthorized,
)
from assets.sire_assets.sire_details_asset.resources.api_resource.constants import (
    CPE_DETAILS_BASE_URL,
    DETAILS_USER_AGENT,
    camel_to_snake,
)

# Aliases de las excepciones compartidas para no romper los imports del asset y
# de los tests existentes.
CpeDetailsError = SireApiError
CpeDetailsMissing = SireApiMissing
CpeDetailsUnauthorized = SireApiUnauthorized


class CpeDetailsResource(DetailsAndFilesResource):
    """Resource que consulta los ítems de un comprobante CPE de SUNAT.

    Hereda de ``DetailsAndFilesResource`` todo el flujo HTTP (URL, headers, retry
    ante 500 y mapeo de status) y devuelve los ítems de ``informacionItems`` con
    claves snake_case.
    """

    base_url: str = CPE_DETAILS_BASE_URL
    user_agent: str = DETAILS_USER_AGENT

    def _parse_response(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extrae ``informacionItems`` del body de consulta (respuesta 200)."""
        return extract_items(data)


def extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extrae ``informacionItems`` del body de consulta y normaliza las claves.

    Devuelve una lista de dicts con claves snake_case. Si no hay ``comprobantes``
    o el primero no trae ``informacionItems``, devuelve ``[]``.
    """
    comprobantes = data.get("comprobantes") or []
    if not comprobantes:
        return []
    items = comprobantes[0].get("informacionItems") or []
    return [
        {camel_to_snake(str(k)): v for k, v in item.items()}
        for item in items
        if isinstance(item, dict)
    ]
