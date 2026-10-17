"""Descarga de propuestas SUNAT para compras (RCE) y ventas (RVIE).

Obtiene la propuesta vía ``TicketResource`` (ticket -> descarga del ZIP) y
devuelve las filas del CSV que contiene.
"""

from __future__ import annotations

import csv
import io
import zipfile
from typing import Any

from dagster import ConfigurableResource

from assets.sire_assets.resources.token_resource import SireTokenResource
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    PROPOSAL_CSV_SEPARATOR,
    PROPOSAL_ENCODING,
    PROPOSAL_EXTENSION,
    TICKET_POLL_SECONDS,
)
from assets.utils import to_db_field
from assets.sire_assets.sire_proposal_asset.resources.api_resource.ticket_resource import (
    PropuestaRceError,
    TicketResource,
)


class ProposalResource(ConfigurableResource):
    """Resource que descarga y parsea la propuesta (CSV) de SIRE.

    Usa ``ticket_resource`` para el flujo del ticket (solicitar, esperar y
    descargar el ZIP) y ``token_resource`` para autenticarse.
    """

    ticket_resource: TicketResource
    token_resource: SireTokenResource

    def get_proposal(
        self,
        per_tributario: str,
        book_code: str = BOOK_CODE_PURCHASES,
        poll_seconds: int = TICKET_POLL_SECONDS,
        *,
        empresa: str,
    ) -> list[dict[str, Any]]:
        """Solicita la propuesta y devuelve las filas del CSV descargado.

        ``per_tributario`` debe venir en formato ``yyyymm`` (ej. ``"202607"``) y
        ``empresa`` es el ``name`` de la empresa en ``sire_credentials.json``.

        Devuelve ``[]`` cuando el ``TicketResource`` informa de que el periodo está
        **sin comprobantes** (``None``): SUNAT contestó 422/``cod 1070`` tras los
        reintentos y no hay nada que insertar (el asset loguea el WARNING y sigue).
        """
        zip_bytes = self.ticket_resource.get_zip(
            per_tributario, book_code, poll_seconds, empresa=empresa
        )
        if zip_bytes is None:  # periodo sin comprobantes (SUNAT 422 / cod 1070)
            return []
        return read_zip(zip_bytes)

    def companies(self) -> list[str]:
        """Nombres de las empresas disponibles en ``sire_credentials.json``."""
        return self.token_resource.companies()


def read_zip(contenido_zip: bytes) -> list[dict[str, Any]]:
    """Desempaqueta el ZIP y devuelve las filas del CSV de la propuesta."""
    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as zf:
        nombres = [
            n for n in zf.namelist()
            if n.lower().endswith(PROPOSAL_EXTENSION) and not n.endswith("/")
        ]
        if not nombres:
            raise PropuestaRceError(
                f"Zip does not contain {PROPOSAL_EXTENSION} file",
                response_body=zf.namelist(),
            )
        raw = zf.read(sorted(nombres)[0])

    try:
        texto = raw.decode(PROPOSAL_ENCODING)
    except UnicodeDecodeError as exc:
        raise PropuestaRceError(
            f"Proposal file is not {PROPOSAL_ENCODING}",
        ) from exc

    rows = normalize_rows(texto)
    if not rows:
        raise PropuestaRceError("Proposal file has no data rows")
    if len(rows[0]) <= 1:
        raise PropuestaRceError(
            f"Proposal file could not be parsed as CSV with separator "
            f"{PROPOSAL_CSV_SEPARATOR!r}",
        )
    return rows


def normalize_rows(texto: str) -> list[dict[str, Any]]:
    """Devuelve las filas del CSV con claves snake_case y valores limpios.

    Claves normalizadas con ``to_db_field`` (``"CAR SUNAT"`` -> ``"car_sunat"``);
    valores ``str`` sin espacios sobrantes y vacíos convertidos a ``None``.

    SUNAT a veces parte un comprobante en dos líneas: la cabecera (con menos
    campos que el header) y una línea de montos que empieza con una celda vacía
    (placeholder de la columna de la contraparte, que ya viene en la cabecera).
    Aquí se reensamblan: toda línea más corta que el header es continuación del
    comprobante anterior. En el formato normal (1 fila = 1 comprobante, p. ej.
    ventas RVIE) no hay nada que unir.
    """
    reader = csv.reader(io.StringIO(texto), delimiter=PROPOSAL_CSV_SEPARATOR)
    lineas = list(reader)
    if not lineas or not lineas[0]:
        return []
    header = [to_db_field(columna) for columna in lineas[0]]
    ancho = len(header)

    filas: list[list[str]] = []
    for linea in lineas[1:]:
        if not linea:
            continue
        if filas and len(filas[-1]) < ancho:
            # Línea partida: continuación del comprobante anterior.
            if len(filas[-1]) + len(linea) > ancho and not (linea[0] or "").strip():
                linea = linea[1:]  # descarta la celda vacía que repite la contraparte
            filas[-1] += linea
        else:
            filas.append(linea)

    return [
        {
            to_db_field(columna): (valor.strip() if isinstance(valor, str) else valor) or None
            for columna, valor in zip(header, fila)
            if columna
        }
        for fila in filas
    ]
