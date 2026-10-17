"""Constantes y helpers del flujo de detalles de comprobantes CPE (SUNAT api-cpe)."""

import re

from assets.sire_assets.resources.details_and_files_resource import (
    CPE_DETAILS_BASE_URL,  # noqa: F401
    ROLE_EMISOR,
    ROLE_RECEPTOR,
)

# Header requerido por la API de consulta de comprobantes.
DETAILS_USER_AGENT = "Mozilla"


# Tipos de documento SIRE (tabla 10 SUNAT): ``tipo_cp_doc`` -> tipo de la URL.
TIPO_DOC_FACTURA = 1
TIPO_DOC_BOLETA = 3
TIPO_DOC_NC = 7
TIPO_DOC_ND = 8

TIPO_URL_FACTURA = "01"
TIPO_URL_BOLETA = "03"


def map_tipo(tipo_cp_doc: int | None, tipo_cp_modificado: int | None) -> str:
    """Devuelve el ``tipo`` que va en la URL de consulta de un comprobante.

    - Factura (``tipo_cp_doc`` = 1) -> ``"01"``
    - Boleta (``tipo_cp_doc`` = 3) -> ``"03"``
    - NC (``tipo_cp_doc`` = 7) -> ``"F7"`` si modifica factura, ``"B7"`` si boleta
    - ND (``tipo_cp_doc`` = 8) -> ``"F8"`` si modifica factura, ``"B8"`` si boleta

    Una NC/ND con ``tipo_cp_modificado`` distinto de 1 o 3 lanza ``ValueError``
    (caso no esperado). Cualquier otro ``tipo_cp_doc`` también.
    """
    if tipo_cp_doc == TIPO_DOC_FACTURA:
        return TIPO_URL_FACTURA
    if tipo_cp_doc == TIPO_DOC_BOLETA:
        return TIPO_URL_BOLETA
    if tipo_cp_doc in (TIPO_DOC_NC, TIPO_DOC_ND):
        if tipo_cp_modificado == TIPO_DOC_FACTURA:
            return f"F{tipo_cp_doc}"
        if tipo_cp_modificado == TIPO_DOC_BOLETA:
            return f"B{tipo_cp_doc}"
        raise ValueError(
            f"tipo_cp_doc={tipo_cp_doc} requiere tipo_cp_modificado 1 (factura) "
            f"o 3 (boleta); se recibió {tipo_cp_modificado!r}"
        )
    raise ValueError(f"tipo_cp_doc no manejado: {tipo_cp_doc!r}")


def camel_to_snake(name: str) -> str:
    """Convierte una clave camelCase de la API a snake_case.

    ``"codUnidadMedida"`` -> ``"cod_unidad_medida"``, ``"mtoICBPER"`` -> ``"mto_icbper"``.
    """
    return re.sub(
        r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])",
        "_",
        name,
    ).lower()
