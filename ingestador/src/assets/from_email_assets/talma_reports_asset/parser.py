"""Parsing del Excel adjunto de Talma (sin I/O).

Cada correo de los remitentes de Talma (``facturacion.centralizada@talma.com.pe``
/ ``shirley.guerra@talma.com.pe``) trae un adjunto Excel (``.xlsx`` / ``.xls``)
con una tabla de reportes. La cabecera está en la fila 4, desde la celda **A4
hasta la Y4** (columnas ``FECHA``, ``ESTACION``, ``AEROLINEA``, ``RSIR``,
``AERONAVE``, ``MATRICULA``, ``VUELO L``, ``VUELO S``, ``HORA L``, ``HORA S``,
``DIFERENCIA``, ``PEA ORIGEN``, ``PEA DESTINO``, ``CANTIDAD``, ``EQUIPO``,
``PESO (KG)``, ``SERVICIO``, ``TARIFA``, ``MONEDA``, ``ESTADO`` y ``TIPO RSIR``;
la columna U va en blanco). Los datos van hacia abajo hasta que la **columna D
(RSIR)** queda en blanco, que marca el final de la tabla.

El parseo es table-driven por **nombre de columna**: se recorre **todas las
hojas** buscando la fila que contenga la cabecera (así se tolera que el Excel
traiga títulos/notas arriba y que la hoja cambie de nombre). Los nombres se
normalizan (quitar acentos, espacios y puntuación) para que variaciones de
tipografía no rompan el mapeo. Los valores se devuelven como texto tal cual
vienen del Excel (solo se reproduce el formato de visualización de fechas/horas),
sin conversión de tipos: la columna RSIR trae ceros a la izquierda que no deben
perderse.

Si no se encuentra la cabecera se lanza ``TalmaParseError`` y el asset derrumba
la partición (fail-fast, sin insertar nada del mes).
"""

from __future__ import annotations

import datetime
import io
import re
import unicodedata
from typing import Any

from openpyxl import load_workbook


def _normalize_header(text: str) -> str:
    """Normaliza un nombre de columna: mayúsculas, sin acentos, sin espacios ni
    puntuación (``\"PEA Origen\"`` -> ``\"PEAORIGEN\"``)."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", ascii_only.upper())


# Cabecera esperada: nombre de columna (normalizado) -> campo (snake_case).
# Los 21 campos salen tal cual de la tabla del Excel (la columna U va vacía).
_HEADER_FIELDS: dict[str, str] = {
    "FECHA": "fecha",
    "ESTACION": "estacion",
    "AEROLINEA": "aerolinea",
    "RSIR": "rsir",
    "AERONAVE": "aeronave",
    "MATRICULA": "matricula",
    "VUELO L": "vuelo_l",
    "VUELO S": "vuelo_s",
    "HORA L": "hora_l",
    "HORA S": "hora_s",
    "DIFERENCIA": "diferencia",
    "PEA ORIGEN": "pea_origen",
    "PEA DESTINO": "pea_destino",
    "CANTIDAD": "cantidad",
    "EQUIPO": "equipo",
    "PESO (KG)": "peso_kg",
    "SERVICIO": "servicio",
    "TARIFA": "tarifa",
    "MONEDA": "moneda",
    "ESTADO": "estado",
    "TIPO RSIR": "tipo_rsir",
}

# header normalizado -> campo (la búsqueda se hace sobre el texto normalizado).
_NORM_TO_FIELD = {_normalize_header(k): v for k, v in _HEADER_FIELDS.items()}

# Cabeceras núcleo que identifican de forma inequívoca la tabla de Talma: si no
# aparecen todas juntas en una fila, esa fila no se considera la cabecera.
_CORE_HEADERS = {_normalize_header(k) for k in ("FECHA", "ESTACION", "AEROLINEA", "RSIR")}


class TalmaParseError(Exception):
    """El Excel de Talma no se pudo parsear (cabecera requerida ausente)."""


def _cell_to_text(value: Any) -> str:
    """Convierte el valor de una celda a texto tal cual se muestra en el Excel.

    - ``None`` -> ``""``
    - ``datetime``/``date`` -> ``"dd/mm/yyyy"`` (formato del ejemplo
      ``01/12/2025``); si trae hora -> ``"dd/mm/yyyy HH:MM:SS"``.
    - ``time`` -> ``"HH:MM"`` (o ``"HH:MM:SS"`` si trae segundos).
    - El resto -> ``str(value)`` (los numéricos se guardan como texto, igual que
      el resto de los assets, para no perder precisión ni ceros a la izquierda).
    """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        if value.time() == datetime.time(0, 0):
            return value.strftime("%d/%m/%Y")
        return value.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, datetime.time):
        if value.second or value.microsecond:
            return value.strftime("%H:%M:%S")
        return value.strftime("%H:%M")
    return str(value)


def _find_header_row(rows: list[tuple]) -> int | None:
    """Índice de la fila que contiene la cabecera de Talma (la del A4:Y4)."""
    for row_idx, row in enumerate(rows):
        norm = {_normalize_header(_cell_to_text(c)) for c in row}
        if _CORE_HEADERS.issubset(norm):
            return row_idx
    return None


def _rsir_col_index(header_norm: list[str]) -> int:
    """Columna de la cabecera que corresponde a RSIR (columna D, índice 3)."""
    for idx, norm in enumerate(header_norm):
        if _NORM_TO_FIELD.get(norm) == "rsir":
            return idx
    return 3


def _parse_sheet(sheet) -> list[dict[str, str]]:
    """Lee las filas de datos de una hoja a partir de su fila de cabecera.

    Los datos van hacia abajo hasta que la columna RSIR queda en blanco, que
    marca el fin de la tabla (se ignoran las filas posteriores).
    """
    rows = list(sheet.iter_rows(values_only=True))
    header_row = _find_header_row(rows)
    if header_row is None:
        return []

    header_norm = [_normalize_header(_cell_to_text(c)) for c in rows[header_row]]
    # índice de columna -> campo destino (los labels desconocidos se ignoran).
    col_to_field: dict[int, str] = {}
    for idx, norm in enumerate(header_norm):
        field = _NORM_TO_FIELD.get(norm)
        if field is not None:
            col_to_field[idx] = field

    rsir_col = _rsir_col_index(header_norm)

    records: list[dict[str, str]] = []
    for raw_row in rows[header_row + 1 :]:
        rsir_value = _cell_to_text(raw_row[rsir_col]) if rsir_col < len(raw_row) else ""
        # La columna D (RSIR) en blanco marca el final de la tabla.
        if not rsir_value.strip():
            break
        record: dict[str, str] = {}
        for idx, value in enumerate(raw_row):
            field = col_to_field.get(idx)
            if field is not None:
                record[field] = _cell_to_text(value)
        records.append(record)
    return records


def _parse_xlsx(xlsx_bytes: bytes) -> list[dict[str, str]]:
    """Parsea un Excel OOXML (``.xlsx``) y devuelve los registros.

    Busca la fila de cabecera en **todas** las hojas (cada hoja puede traer su
    propia tabla) y junta las filas de datos de cada una en el orden de aparición.
    """
    try:
        wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise TalmaParseError(f"no se pudo abrir el Excel: {exc}") from exc

    records: list[dict[str, str]] = []
    for sheet in wb.worksheets:
        records.extend(_parse_sheet(sheet))
    wb.close()

    if not records:
        raise TalmaParseError("no se encontró la cabecera de Talma en ninguna hoja")
    return records


# Magic bytes para detectar el formato real del adjunto.
_XLSX_MAGIC = b"PK\x03\x04"           # Excel OOXML (zip)
_BIFF_MAGIC = b"\xd0\xcf\x11\xe0"     # Excel .xls binario legacy (OLE2)


def _decode_text(data: bytes) -> str:
    """Decodifica el contenido de un adjunto de texto, probando UTF-8 y latin-1."""
    for encoding in ("utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _detect_delimiter(line: str) -> str:
    """Delimitador de un archivo de texto: el que más aparezca en la cabecera."""
    counts = {delim: line.count(delim) for delim in ("\t", ";", ",", "|")}
    return max(counts, key=counts.get)


def _parse_delimited_text(text: str) -> list[dict[str, str]]:
    """Parsea un archivo de texto delimitado (TSV/CSV) con la tabla de Talma.

    Los ``.xls`` que envía Talma pueden ser en realidad texto con separador TAB:
    la fila con la cabecera (A4:Y4) es la cabecera y cada fila siguiente un
    registro, hasta que la columna RSIR quede en blanco. Se detecta el
    delimitador por frecuencia en la cabecera.
    """
    lines = text.splitlines()
    if not lines:
        return []
    delimiter = _detect_delimiter(lines[0])
    rows = [line.split(delimiter) for line in lines]

    header_row = _find_header_row([tuple(r) for r in rows])
    if header_row is None:
        return []

    header_norm = [_normalize_header(c) for c in rows[header_row]]
    col_to_field: dict[int, str] = {}
    for idx, norm in enumerate(header_norm):
        field = _NORM_TO_FIELD.get(norm)
        if field is not None:
            col_to_field[idx] = field

    rsir_col = _rsir_col_index(header_norm)

    records: list[dict[str, str]] = []
    for cells in rows[header_row + 1 :]:
        rsir_value = cells[rsir_col].strip() if rsir_col < len(cells) else ""
        # La columna D (RSIR) en blanco marca el final de la tabla.
        if not rsir_value:
            break
        record: dict[str, str] = {}
        for idx, value in enumerate(cells):
            field = col_to_field.get(idx)
            if field is not None:
                record[field] = value.strip()
        records.append(record)
    return records


def parse_report_data(data: bytes) -> list[dict[str, str]]:
    """Parsea un adjunto Talma y devuelve la lista de registros de la tabla.

    Detecta el formato real del adjunto:

    - **Excel OOXML** (``PK`` = ``.xlsx``): se parsea con openpyxl (todas las
      hojas).
    - **Texto delimitado** (los ``.xls`` que envía Talma pueden ser TSV/CSV): se
      parsea por su delimitador (tab/semicolon/comma/pipe).

    Un ``.xls`` binario legacy (BIFF/OLE2) no se soporta (requeriría xlrd).
    """
    if data.startswith(_XLSX_MAGIC):
        records = _parse_xlsx(data)
    elif data.startswith(_BIFF_MAGIC):
        raise TalmaParseError(
            "archivo .xls binario (BIFF/OLE2) no soportado: usar .xlsx o texto TSV"
        )
    else:
        records = _parse_delimited_text(_decode_text(data))

    if not records:
        raise TalmaParseError("no se encontró la cabecera de Talma en el archivo")
    return records
