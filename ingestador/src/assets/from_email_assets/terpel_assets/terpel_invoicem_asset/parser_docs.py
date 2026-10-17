"""Parsing puro de las facturas Terpel del remitente invoicem (sin I/O).

Funciones puras sin conexión a datos fuera del programa: solo reciben strings/bytes y
devuelven strings/bytes. Por eso este módulo no es un resource.

El remitente ``invoicem.lubes@terpel.com`` adjunta las facturas como PDFs ``Fact_*``
sueltos o dentro de ZIPs ``FACTURA(S) ...`` (junto a los XML de SUNAT, que se
ignoran). De cada PDF se extraen dos campos por regex sobre el texto plano
(``pdfplumber``):

- ``orden_de_compra``: texto tras el label ``ORDEN DE COMPRA:`` (p. ej. ``DT 2618503502``)
- ``observaciones``: texto tras el label ``OBSERVACIONES:`` (p. ej. ``DT 2622003503``)

Y de esos dos campos se deriva ``agregado_o_entrega``: el **índice del ticket**
(el número que sigue a ``DT``, que enlaza con ``o_entrega`` de las tablas de tickets).

Si un campo no aparece se deja en ``"`` (no derrumba la partición): se prefiere una
fila con el campo vacío antes que fallar todo el mes.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile

import pdfplumber


class TerpelDocParseError(Exception):
    """El PDF de factura Terpel no se pudo abrir/leer."""


_ORDEN_DE_COMPRA_RE = re.compile(
    r"ORDEN\s+DE\s+COMPRA\s*:?\s*([^\n]+)",
    re.IGNORECASE,
)
_OBSERVACIONES_RE = re.compile(
    r"OBSERVACIONES\s*:?\s*([^\n]+)",
    re.IGNORECASE,
)
# Dígitos iniciales de un texto (réplica ``CAST(x AS INTEGER)`` de SQLite).
_LEADING_INT_RE = re.compile(r"\s*([+-]?[0-9]+)")


def _first_value(normalized: str, pattern: re.Pattern) -> str:
    """Primer valor no vacío tras el label (o ``""`` si no aparece)."""
    for match in re.finditer(pattern, normalized):
        value = match.group(1).strip()
        if value:
            return value
    return ""


def _normalize_text(text: str) -> str:
    """Colapsa el whitespace horizontal pero conserva las líneas del PDF."""
    return "\n".join(
        " ".join(line.split()) for line in text.splitlines() if line.strip()
    )


def extract_fact_text(pdf_bytes: bytes) -> str:
    """Extrae el texto de todas las páginas del PDF de factura ``Fact_*``."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise TerpelDocParseError("PDF sin páginas")
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except TerpelDocParseError:
        raise
    except Exception as exc:
        raise TerpelDocParseError(f"no se pudo abrir el PDF: {exc}") from exc


def _sqlite_cast_int(texto: str) -> int:
    """Réplica ``CAST(texto AS INTEGER)`` de SQLite (dígitos iniciales; si no, 0)."""
    match = _LEADING_INT_RE.match(texto)
    return int(match.group(1)) if match else 0


def parse_o_entrega(orden_de_compra: str, observaciones: str) -> int | None:
    """Índice del ticket (``o_entrega``) derivado de la orden de compra.

    Reproduce el ``CASE`` que hacía dbt en ``cost_centers``: el número que sigue a
    ``DT`` en ``orden_de_compra`` y, si ahí no aparece, en ``observaciones`` (el
    ``LIKE '%DT%'`` de SQLite es case-insensitive). Devuelve ``None`` si no hay ``DT``
    en ninguno de los dos campos.
    """
    for texto in (orden_de_compra, observaciones):
        if not texto:
            continue
        pos = texto.upper().find("DT")
        if pos != -1:
            return _sqlite_cast_int(texto[pos + 2 :])
    return None


def parse_fact_text(text: str) -> dict[str, object]:
    """Extrae ``orden_de_compra``/``observaciones`` y deriva ``agregado_o_entrega``."""
    normalized = _normalize_text(text)
    orden_de_compra = _first_value(normalized, _ORDEN_DE_COMPRA_RE)
    observaciones = _first_value(normalized, _OBSERVACIONES_RE)
    return {
        "orden_de_compra": orden_de_compra,
        "observaciones": observaciones,
        "agregado_o_entrega": parse_o_entrega(orden_de_compra, observaciones),
    }


def parse_fact_pdf(pdf_bytes: bytes) -> dict[str, object]:
    """Parsea un PDF de factura Terpel y devuelve sus campos (con ``agregado_o_entrega``)."""
    return parse_fact_text(extract_fact_text(pdf_bytes))


def extract_zip_pdf_entries(zip_bytes: bytes) -> list[dict[str, str]]:
    """Desempaqueta el ZIP y devuelve **todas** sus entradas PDF.

    Cada entrada es ``{"filename": nombre, "data": contenido en base64}`` (la misma
    convención que ``email_attachments``/``sire_*_files``). Los directorios y cualquier
    archivo que no sea ``.pdf`` (los XML/CDR de SUNAT, p. ej.) se ignoran: el asset
    clasifica después cada PDF por su nombre (facturas vs tickets).
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return [
            {
                "filename": info.filename,
                "data": base64.b64encode(zf.read(info)).decode("ascii"),
            }
            for info in zf.infolist()
            if not info.is_dir() and info.filename.lower().endswith(".pdf")
        ]
