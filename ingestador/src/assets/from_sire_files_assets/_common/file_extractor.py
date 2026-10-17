"""Extracción del XML del comprobante desde el archivo de SUNAT (sin I/O).

El archivo que SUNAT entrega en el segmento 02 (el ``val_archivo`` de
``sire_purchs_files``) es un ZIP con dos XML: el comprobante (``*.xml``) y su
respuesta ``R-*.XML``. Aquí se localiza el del comprobante y se devuelve como
``str`` para que el parser trabaje **solo con texto** (una regex), sin volver a
mirar el ZIP.
"""

from __future__ import annotations

import io
import zipfile

# Prefijo del XML de respuesta de SUNAT: se ignora (no es el comprobante).
_RESPUESTA_PREFIX = "R-"


class SireXmlError(Exception):
    """El archivo SIRE no es un ZIP legible o no trae el XML del comprobante."""


class XmlComprobante(str):
    """XML del comprobante: su contenido (``str``) y su nombre dentro del ZIP.

    Es el texto del XML —para pasárselo tal cual al parser— y además lleva
    ``filename``, el nombre del XML dentro del ZIP que usan la tabla
    ``from_sire_*_cost_centers`` y el dbt como clave.
    """

    filename: str

    def __new__(cls, filename: str, xml: str) -> "XmlComprobante":
        comprobante = super().__new__(cls, xml)
        comprobante.filename = filename
        return comprobante


def extract_xml(file_bytes: bytes) -> XmlComprobante:
    """Devuelve el XML del comprobante (el XML que **no** empieza por ``R-``).

    ``file_bytes`` es el archivo de SUNAT ya decodificado (el ZIP del comprobante).
    Lanza ``SireXmlError`` si no es un ZIP legible o si no contiene ese XML.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
            for info in zf.infolist():
                if (
                    not info.is_dir()
                    and not info.filename.startswith(_RESPUESTA_PREFIX)
                    and info.filename.lower().endswith(".xml")
                ):
                    return XmlComprobante(
                        info.filename, zf.read(info).decode("utf-8", "replace")
                    )
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise SireXmlError(f"El archivo no es un ZIP legible: {exc}") from exc
    raise SireXmlError("El ZIP no trae el XML del comprobante (XML sin prefijo R-)")
