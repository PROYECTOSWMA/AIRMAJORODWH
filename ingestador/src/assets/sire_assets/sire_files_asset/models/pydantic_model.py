"""Réplica pydantic de un archivo de comprobante CPE (PDF/ZIP).

``CpeFilesResource.get_file`` devuelve el dict ``{"nom_archivo", "val_archivo"}``
(ya normalizado desde ``nomArchivo``/``valArchivo`` de la API). Antes del upsert
se valida con este modelo para que los errores de tipo salten en el programa y no
en la BD. ``tipo_documento`` no viene de la API: lo inyecta el asset según el
segmento consultado (``/01`` PDF, ``/02`` ZIP), igual que ``period``/``empresa``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class SireFile(BaseModel):
    """Un archivo (PDF o ZIP) de un comprobante.

    Réplica de las tablas ``sire_sales_files``/``sire_purchs_files`` (sin el FK
    ni ``period``/``empresa``, que inyecta el asset al hacer el upsert).
    """

    tipo_documento: Literal["PDF", "ZIP"]
    nom_archivo: str
    val_archivo: str
