"""Parsing del Excel adjunto de ADP (sin I/O).

Cada correo de ``ladyliz.moreno@adp.com.pe`` trae un adjunto Excel (``.xlsx`` /
``.xlsm``) con una tabla de servicios de aeronavegación. La cabecera son 30
columnas fijas (``SERVICIO``, ``NRO_OPERACION``, ``OPERACION``, ``APTO``,
``ORIGEN``, ``DESTINO``, ``VUELO_LLEGADA``, ``VUELO_SALIDA``,
``FEC/HORA-LLEGADA``, ``FEC/HORA-SALIDA``, ``TOTAL_HORAS``, ``NUM.PASAJEROS``,
``IMP.UNITARIO``, ``PESO_CARGA``, ``DESCRIPCION_SERVICIO``, ``MATRICULA``,
``TIPO_AERO.``, ``PMD``, ``OACI``, ``VUELO``, ``IMP.IGV``, ``FACTURA SD``,
``REFERENCIA``, ``CLIENTE``, ``NOM_CLIENTE``, ``FECHA``, ``MONEDA``,
``CLIENTE O.``, ``CLIENTE ORIGEN``, ``ESTADO OPERAC.``) y cada fila debajo es un
registro.

El parseo es table-driven por **nombre de columna**: se recorre **todas las
hojas** buscando la fila que contenga los 30 labels (así se tolera que el Excel
traiga títulos/notas arriba y que la hoja cambie de nombre), y se leen todas las
filas de datos desde ahí hasta el final. Los nombres se normalizan (quitar
acentos, espacios y puntuación) para que variaciones de tipografía no rompan el
mapeo.

Si no se encuentra la cabecera se lanza ``AdpParseError`` y el asset derrumba la
partición (fail-fast, sin insertar nada del mes).
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
    puntuación (``"FEC/HORA-LLEGADA"`` -> ``"FECHORALLEGADA"``)."""
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", ascii_only.upper())


# Cabecera esperada: nombre de columna (normalizado) -> campo (snake_case).
# Los 30 campos salen tal cual de la tabla del Excel.
_HEADER_FIELDS: dict[str, str] = {
    "SERVICIO": "servicio",
    "NRO_OPERACION": "nro_operacion",
    "OPERACION": "operacion",
    "APTO": "apto",
    "ORIGEN": "origen",
    "DESTINO": "destino",
    "VUELO_LLEGADA": "vuelo_llegada",
    "VUELO_SALIDA": "vuelo_salida",
    "FEC/HORA-LLEGADA": "fec_hora_llegada",
    "FEC/HORA-SALIDA": "fec_hora_salida",
    "TOTAL_HORAS": "total_horas",
    "NUM.PASAJEROS": "num_pasajeros",
    "IMP.UNITARIO": "imp_unitario",
    "PESO_CARGA": "peso_carga",
    "DESCRIPCION_SERVICIO": "descripcion_servicio",
    "MATRICULA": "matricula",
    "TIPO_AERO.": "tipo_aero",
    "PMD": "pmd",
    "OACI": "oaci",
    "VUELO": "vuelo",
    "IMP.IGV": "imp_igv",
    "FACTURA SD": "factura_sd",
    "REFERENCIA": "referencia",
    "CLIENTE": "cliente",
    "NOM_CLIENTE": "nom_cliente",
    "FECHA": "fecha",
    "MONEDA": "moneda",
    "CLIENTE O.": "cliente_o",
    "CLIENTE ORIGEN": "cliente_origen",
    "ESTADO OPERAC.": "estado_operac",
}

# Labels normalizados esperados (todos distintos entre sí, sin colisiones).
_EXPECTED_HEADERS = {_normalize_header(k) for k in _HEADER_FIELDS}

# header normalizado -> campo (la búsqueda se hace sobre el texto normalizado).
_NORM_TO_FIELD = {_normalize_header(k): v for k, v in _HEADER_FIELDS.items()}


class AdpParseError(Exception):
    """El Excel de ADP no se pudo parsear (cabecera requerida ausente)."""


def _cell_to_text(value: Any) -> str:
    """Convierte el valor de una celda a texto sin perder el dato.

    - ``None`` -> ``""``
    - ``datetime``/``date`` -> ``"dd.mm.yyyy HH:MM:SS"`` / ``"dd.mm.yyyy"``
      (formato de las fechas del ejemplo ``30.07.2026 13:37:00``).
    - El resto -> ``str(value)`` (los numéricos se guardan como texto, igual
      que Terpel, para no perder precisión ni ceros a la izquierda).
    """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(value, datetime.date):
        return value.strftime("%d.%m.%Y")
    return str(value)


def _find_header_row(sheet) -> int | None:
    """Fila (0-based) de la hoja que contiene la cabecera de los 30 campos."""
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
        norm = {_normalize_header(_cell_to_text(c)) for c in row}
        # La cabecera se reconoce si aparecen todos los labels esperados.
        if _EXPECTED_HEADERS.issubset(norm):
            return row_idx
    return None


def _parse_sheet(sheet) -> list[dict[str, str]]:
    """Lee las filas de datos de una hoja a partir de su fila de cabecera."""
    header_row = _find_header_row(sheet)
    if header_row is None:
        return []

    rows = list(sheet.iter_rows(values_only=True))
    header_norm = [_normalize_header(_cell_to_text(c)) for c in rows[header_row]]
    # índice de columna -> campo destino (los labels desconocidos se ignoran).
    col_to_field: dict[int, str] = {}
    for idx, norm in enumerate(header_norm):
        field = _NORM_TO_FIELD.get(norm)
        if field is not None:
            col_to_field[idx] = field

    records: list[dict[str, str]] = []
    for raw_row in rows[header_row + 1 :]:
        # Una fila de datos requiere al menos un campo poblado; si todos los
        # valores están vacíos se descarta (separador / fin de tabla).
        if all(_cell_to_text(c) == "" for c in raw_row):
            continue
        record: dict[str, str] = {}
        for idx, value in enumerate(raw_row):
            field = col_to_field.get(idx)
            if field is not None:
                record[field] = _cell_to_text(value)
        records.append(record)
    return records


def _parse_xlsx(xlsx_bytes: bytes) -> list[dict[str, str]]:
    """Parsea un Excel OOXML (``.xlsx`` / ``.xlsm``) y devuelve los registros.

    Busca la fila de cabecera en **todas** las hojas (cada hoja puede traer su
    propia tabla) y junta las filas de datos de cada una en el orden de aparición.
    """
    try:
        wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise AdpParseError(f"no se pudo abrir el Excel: {exc}") from exc

    records: list[dict[str, str]] = []
    for sheet in wb.worksheets:
        records.extend(_parse_sheet(sheet))
    wb.close()

    if not records:
        raise AdpParseError(
            f"no se encontró la cabecera de {len(_HEADER_FIELDS)} campos en ninguna hoja"
        )
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
    """Parsea un archivo de texto delimitado (TSV/CSV) con la tabla de ADP.

    Los ``.xls`` que envía ADP son en realidad texto con separador TAB: la
    primera fila con los 30 labels es la cabecera y cada fila siguiente un
    registro. Se detecta el delimitador por frecuencia en la cabecera.
    """
    lines = text.splitlines()
    if not lines:
        return []
    delimiter = _detect_delimiter(lines[0])
    rows = [line.split(delimiter) for line in lines]

    header_row: int | None = None
    for i, cells in enumerate(rows):
        norm = {_normalize_header(c) for c in cells}
        if _EXPECTED_HEADERS.issubset(norm):
            header_row = i
            break
    if header_row is None:
        return []

    col_to_field: dict[int, str] = {}
    for idx, cell in enumerate(rows[header_row]):
        field = _NORM_TO_FIELD.get(_normalize_header(cell))
        if field is not None:
            col_to_field[idx] = field

    records: list[dict[str, str]] = []
    for cells in rows[header_row + 1 :]:
        # Fila de datos: requiere al menos un campo con contenido.
        if all(not c.strip() for c in cells):
            continue
        record: dict[str, str] = {}
        for idx, value in enumerate(cells):
            field = col_to_field.get(idx)
            if field is not None:
                record[field] = value.strip()
        records.append(record)
    return records


def parse_report_data(data: bytes) -> list[dict[str, str]]:
    """Parsea un adjunto ADP y devuelve la lista de registros de la tabla.

    Detecta el formato real del adjunto:

    - **Excel OOXML** (``PK`` = ``.xlsx`` / ``.xlsm``): se parsea con openpyxl
      (todas las hojas).
    - **Texto delimitado** (los ``.xls`` que envía ADP son TSV/CSV): se parsea
      por su delimitador (tab/semicolon/comma/pipe).

    Un ``.xls`` binario legacy (BIFF/OLE2) no se soporta (requeriría xlrd).
    """
    if data.startswith(_XLSX_MAGIC):
        records = _parse_xlsx(data)
    elif data.startswith(_BIFF_MAGIC):
        raise AdpParseError(
            "archivo .xls binario (BIFF/OLE2) no soportado: usar .xlsx o texto TSV"
        )
    else:
        records = _parse_delimited_text(_decode_text(data))

    if not records:
        raise AdpParseError(
            f"no se encontró la cabecera de {len(_HEADER_FIELDS)} campos en el archivo"
        )
    return records
