"""Parsing del Excel ``Reporte abastecimiento <fecha>-MAJORO.xlsx`` (sin I/O).

El remitente ``invoicem.lubes@terpel.com`` adjunta un Excel por día con una única hoja
``vuelos <fecha>``. La cabecera **no está en la primera fila**: se localiza la fila que
contiene ``TICKET`` y ``GALONES`` y, a partir de ahí, cada fila de datos se convierte
en un ``dict`` con las columnas del reporte:

``FECHA, TICKET, PRODUCTO, AEROLINEA, VUELO, GALONES, SCOP, PRECIO, MONTO, N°FACTURA``
(la primera columna es un índice sin cabecera y se ignora). Las filas de totales/pie
sin ``TICKET`` (p. ej. el total de ``GALONES``) se desechan: no son un vuelo.

Las celdas se guardan **como texto** (igual que los tickets): el Excel mezcla enteros,
decimales y fechas, y convertirlos aquí complicaría el upsert sin aportar nada.
"""

from __future__ import annotations

import datetime as dt
import io
from typing import Any

import openpyxl

# Campos del reporte (orden del modelo peewee).
_REPORT_FIELDS = (
    "fecha",
    "ticket",
    "producto",
    "aerolinea",
    "vuelo",
    "galones",
    "scop",
    "precio",
    "monto",
    "n_factura",
)

# Label de la cabecera -> campo. ``N°FACTURA`` tiene variantes (``°``/``º``/espacios),
# así que además se acepta cualquier label que empiece por ``N`` y contenga ``FACTURA``.
_HEADER_LABELS = {
    "FECHA": "fecha",
    "TICKET": "ticket",
    "PRODUCTO": "producto",
    "AEROLINEA": "aerolinea",
    "VUELO": "vuelo",
    "GALONES": "galones",
    "SCOP": "scop",
    "PRECIO": "precio",
    "MONTO": "monto",
    "N°FACTURA": "n_factura",
    "NºFACTURA": "n_factura",
    "NROFACTURA": "n_factura",
}

# Labels sin los que no se reconoce la cabecera del reporte.
_REQUIRED_HEADER = ("ticket", "galones")


class TerpelReportParseError(Exception):
    """El Excel del reporte de abastecimiento no se pudo abrir o no tiene cabecera."""


def _normalize_header(value: Any) -> str:
    """Label de cabecera normalizado: sin espacios y en mayúsculas."""
    return "".join(str(value if value is not None else "").split()).upper()


def _field_for(label: str) -> str | None:
    """Campo del modelo para un label de cabecera (o ``None`` si no es una columna)."""
    if not label:
        return None
    if label in _HEADER_LABELS:
        return _HEADER_LABELS[label]
    if label.startswith("N") and "FACTURA" in label:
        return "n_factura"
    return None


def _cell_text(value: Any) -> str:
    """Celda -> texto (las fechas se normalizan a ``YYYY-MM-DD``)."""
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value).strip()


def _map_columns(header_row: tuple) -> dict[int, str]:
    """Índice de columna -> campo para la fila de cabecera dada."""
    cols: dict[int, str] = {}
    for idx, cell in enumerate(header_row):
        field = _field_for(_normalize_header(cell))
        if field is not None:
            cols[idx] = field
    return cols


def _row_to_dict(row: tuple, cols: dict[int, str]) -> dict[str, str]:
    """Convierte una fila de datos en el dict del modelo (celdas vacías -> ``""``)."""
    fila = {field: "" for field in _REPORT_FIELDS}
    for idx, field in cols.items():
        if idx < len(row):
            fila[field] = _cell_text(row[idx])
    return fila


def parse_reporte_xlsx(xlsx_bytes: bytes) -> list[dict[str, str]]:
    """Parsea el Excel del reporte y devuelve una fila por vuelo.

    Recorre las hojas hasta encontrar una con la cabecera esperada (``TICKET`` y
    ``GALONES``); las filas de datos empiezan justo después. Lanza
    ``TerpelReportParseError`` si no hay ninguna hoja con esa cabecera.
    """
    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(xlsx_bytes), read_only=True, data_only=True
        )
    except Exception as exc:
        raise TerpelReportParseError(f"no se pudo abrir el Excel: {exc}") from exc

    try:
        for sheet in workbook.worksheets:
            cols: dict[int, str] | None = None
            filas: list[dict[str, str]] = []
            for row in sheet.iter_rows(values_only=True):
                if cols is None:
                    candidatas = _map_columns(row)
                    if all(req in candidatas.values() for req in _REQUIRED_HEADER):
                        cols = candidatas
                    continue
                fila = _row_to_dict(row, cols)
                # Las filas sin TICKET son de totales/pie (p. ej. el total de GALONES)
                # y no son un vuelo: se descartan.
                if fila["ticket"]:
                    filas.append(fila)
            if cols is not None and filas:
                return filas
        raise TerpelReportParseError(
            "no se encontró la cabecera del reporte (TICKET/GALONES)"
        )
    finally:
        workbook.close()
