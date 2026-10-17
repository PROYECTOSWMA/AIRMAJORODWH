
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from assets.utils import to_db_field

# Namespaces del formato OpenDocument (ODS).
_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}

# Columnas numéricas (índice de columna de la cabecera) que se convierten a
# Decimal; el resto se guardan como texto (identificadores, fechas, códigos).
_NUMERIC_COLUMNS = {
    11,  # remuner
    12,  # tc
    13,  # dias
    *range(21, 58),  # 21..57 (sueldo, conceptos, totales, aportes...)
    59,  # impneto
    *range(62, 71),  # 62..70 (otros conceptos y reintegros)
}

# Hoja del libro que se lee.
PLANILLA_SHEET_NAME = "PLANILLA"


def _clean_text(value: Any) -> Any:
    """Limpia texto: strip y '' -> None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_monto(value: Any) -> Any:
    """Convierte un monto con separador de miles a Decimal (o None)."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _cell_text(cell) -> str:
    """Texto de una celda ODS (une los párrafos ``text:p``)."""
    ps = cell.findall("text:p", _NS)
    if not ps:
        return ""
    return " ".join("".join(p.itertext()) for p in ps)


def _iter_cells(row, limit: int):
    """Itera ``(índice, texto)`` de las celdas de una fila hasta ``limit``.

    Maneja ``table:number-columns-repeated`` y corta en ``limit`` para no
    expandir las celdas vacías de relleno que LibreOffice escribe al final de
    cada fila (hasta 16384 columnas).
    """
    idx = 0
    for cell in row:
        rep = int(cell.get(f"{{{_NS['table']}}}number-columns-repeated", "1"))
        text = _cell_text(cell)
        for _ in range(rep):
            if idx >= limit:
                return
            yield idx, text
            idx += 1


def _row_values(row, limit: int) -> list[str]:
    """Devuelve la fila como lista de ``limit`` textos."""
    values = [""] * limit
    for idx, text in _iter_cells(row, limit):
        values[idx] = text
    return values


def _header_columns(table):
    """Devuelve ``(headers, max_col)``: {indice: nombre_normalizado} y el mayor índice."""
    rows = table.findall("table:table-row", _NS)
    header_elems = rows[0].findall("table:table-cell", _NS)
    headers: dict[int, str] = {}
    max_col = 0
    col_index = 0
    for cell in header_elems:
        rep = int(cell.get(f"{{{_NS['table']}}}number-columns-repeated", "1"))
        text = _cell_text(cell).strip()
        for _ in range(rep):
            if text:
                headers[col_index] = to_db_field(text)
                max_col = max(max_col, col_index)
            col_index += 1
    return headers, max_col


def parse_planilla(path: Path) -> list[dict[str, Any]]:
    """Lee la hoja ``PLANILLA`` y devuelve las filas como dicts.

    La primera fila es la cabecera; se ignoran las columnas sin cabecera y las
    filas totalmente vacías. Los montos van a ``Decimal``.
    """
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("content.xml"))

    body = root.find("office:body", _NS)
    spreadsheet = body.find("office:spreadsheet", _NS)
    table = spreadsheet.find("table:table", _NS)
    if table is None:
        return []

    rows = table.findall("table:table-row", _NS)
    if len(rows) < 2:
        return []

    headers, max_col = _header_columns(table)
    if not headers:
        return []
    limit = max_col + 1

    filas: list[dict[str, Any]] = []
    for row in rows[1:]:
        values = _row_values(row, limit)
        if not any(v.strip() for v in values):
            continue
        fila: dict[str, Any] = {}
        for idx, name in headers.items():
            value = values[idx] if idx < len(values) else ""
            if idx in _NUMERIC_COLUMNS:
                fila[name] = _normalize_monto(value)
            else:
                fila[name] = _clean_text(value)
        filas.append(fila)
    return filas
