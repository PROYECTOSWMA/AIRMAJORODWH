
from assets.sire_assets.sire_details_asset.resources.api_resource.constants import (
    CPE_DETAILS_BASE_URL,
    DETAILS_USER_AGENT,
    ROLE_EMISOR,
    ROLE_RECEPTOR,
    map_tipo,
)

# Tipos de archivo que devuelve la API en los segmentos 01 (PDF) y 02 (ZIP).
FILE_KIND_PDF = "PDF"
FILE_KIND_ZIP = "ZIP"

# Segmento final de la URL de consulta: ``/01`` (PDF) y ``/02`` (ZIP).
FILE_SUFFIX_PDF = "/01"
FILE_SUFFIX_ZIP = "/02"