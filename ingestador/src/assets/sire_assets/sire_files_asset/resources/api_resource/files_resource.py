"""Consulta de archivos (PDF/ZIP) de comprobantes CPE de SUNAT api-cpe.

Misma API que ``sire_details_asset`` pero con un segmento final en la URL:
``/01`` devuelve el PDF y ``/02`` el ZIP del comprobante. La respuesta es un
objeto con ``nomArchivo`` (nombre del archivo) y ``valArchivo`` (contenido en
base64).

La lógica HTTP (retry 500, status 200/401/500 y excepciones) vive en la base
compartida ``DetailsAndFilesResource``; aquí solo se implementa el parseo de la
respuesta y el mapeo de ``tipo_archivo`` (``"PDF"``/``"ZIP"``) al segmento. A
diferencia de ``CpeDetailsResource``, este resource **no define una política de
retry propia**: usa la de la base (``retry_max_attempts=50`` y
``retry_wait_seconds=0.001``).
"""

from __future__ import annotations

from typing import Any

from assets.sire_assets.resources.details_and_files_resource import (
    DetailsAndFilesResource,
    SireApiError,
    SireApiMissing,
    SireApiUnexpectedStatus,
    SireApiUnauthorized,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.constants import (
    FILE_KIND_PDF,
    FILE_KIND_ZIP,
    FILE_SUFFIX_PDF,
    FILE_SUFFIX_ZIP,
    ROLE_EMISOR,
)

# Aliases de las excepciones compartidas para los imports del asset y los tests.
CpeFilesError = SireApiError
CpeFilesMissing = SireApiMissing
CpeFilesUnauthorized = SireApiUnauthorized


class CpeFilesResource(DetailsAndFilesResource):
    def get_file(
        self,
        senderruc: str,
        tipo: str,
        serie: str,
        numero: int | str,
        *,
        tipo_archivo: str,
        empresa: str,
        rol: int = ROLE_EMISOR,
    ) -> dict[str, str]:
        """Consulta el archivo ``tipo_archivo`` (``"PDF"`` o ``"ZIP"``).

        ``senderruc`` es el RUC del emisor consultado, ``rol`` es 1 (emisor) o 2
        (receptor) y ``empresa`` se usa para resolver el token. Devuelve
        ``{"nom_archivo": ..., "val_archivo": ...}``.
        """
        suffix = FILE_SUFFIX_PDF if tipo_archivo == FILE_KIND_PDF else FILE_SUFFIX_ZIP
        return self.get_items(
            senderruc, tipo, serie, numero, rol, empresa=empresa, suffix=suffix
        )

    def _parse_response(self, data: dict[str, Any]) -> dict[str, str]:
        """Extrae ``nomArchivo``/``valArchivo`` del body de consulta (respuesta 200)."""
        return extract_file(data)


def extract_file(data: dict[str, Any]) -> dict[str, str]:
    """Extrae ``nomArchivo``/``valArchivo`` del body de consulta.

    Devuelve el dict con claves snake_case. Si falta alguno de los dos campos
    lanza ``CpeFilesError`` (respuesta no esperada).
    """
    nom_archivo = data.get("nomArchivo")
    val_archivo = data.get("valArchivo")
    if not nom_archivo or val_archivo is None:
        raise CpeFilesError(f"Respuesta sin nomArchivo/valArchivo: {data!r}")
    return {"nom_archivo": str(nom_archivo), "val_archivo": str(val_archivo)}
