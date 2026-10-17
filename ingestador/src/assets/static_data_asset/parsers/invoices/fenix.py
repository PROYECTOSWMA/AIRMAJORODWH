"""Facturas de **Fenix Aerospace, LLC** (``INVC-########``).

Diseño propio de Fenix, en inglés y con etiquetas a la izquierda:

* cabecera: ``Invoice Date``, ``Invoice #``, ``SO #``, ``RLS #``, ``Customer PO #``,
  ``VAT/Tax ID:``, ``Website``, bloques ``BILL TO`` / ``SHIP TO``, fila
  ``Requisitioner Phone Terms AWB Ship Date`` y fila
  ``# of Pieces Total Weight Incoterms Port/Dest Shipped Via Shipped Via Acct``;
* tabla de ítems: ``LN PART NO SERIAL NUMBER DESCRIPTION CN QTY UOM UNIT PRICE TOTAL``
  (la descripción puede ocupar varias palabras y el P/N llevar espacios).

Detalles del PDF que hay que respetar:

* Fenix imprime literalmente ``NULL`` cuando un campo va vacío: se guarda ``None``.
* Después de cada ítem pueden venir renglones de metadatos (``HTS``, ``ECCN``,
  ``COUNTRY OF ORIGIN``, ``ALT FOR …``, ``MFG CERTS``): se guardan en ``extras``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import (
    block_value,
    cabecera_y_datos,
    find_value,
    iso,
    limpiar,
    month_number,
    num,
    pares_tabla,
    read_pages,
    read_tables,
    read_words,
    rejilla,
    texto_celda,
    valor,
)

VENDOR = "FENIX AEROSPACE LLC"
VENDOR_NAME = "Fenix Aerospace, LLC"

_META_PREFIJOS = (
    "HTS", "ECCN", "COUNTRY OF ORIGIN", "MFG CERTS", "MFGC CERTS", "SHELF LIFE",
    "ALT ", "PACK OF", "MOQ", "UM :", "UM:", "PAR",
)
_INVOICE_DATE_RE = re.compile(r"Invoice Date\s+(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})")
_INVOICE_NUM_RE = re.compile(r"Invoice #\s*:?\s*(\S+)")
_TOTAL_RE = re.compile(r"(?m)^(?P<etiqueta>[A-Z][A-Z ]*?)\s*\$(?P<monto>[\d,]+\.\d{2})\s*$")

def _fecha(texto: str) -> str | None:
    match = _INVOICE_DATE_RE.search(texto)
    if not match:
        return None
    return iso(match.group(3), month_number(match.group(2)), match.group(1))


def _comentarios(tablas: list[Any]) -> str | None:
    """Texto del recuadro 'Comments or Special Instructions' (si lo trae)."""
    for tabla in tablas:
        for indice, fila in enumerate(tabla):
            if fila and fila[0] and "Comments or Special Instructions" in str(fila[0]):
                if indice + 1 < len(tabla) and tabla[indice + 1]:
                    return texto_celda(tabla[indice + 1][0])
    return None


def _monto(texto: str, etiqueta: str) -> str | None:
    """Monto de una línea 'ETIQUETA $1,234.00' (SUBTOTAL/TAX SUBTOTAL/TOTAL)."""
    for match in _TOTAL_RE.finditer(texto):
        if match.group("etiqueta").strip() == etiqueta:
            return num(match.group("monto"))
    return None


def _campo(palabras: list[Any], etiqueta: str, **kw: Any) -> str | None:
    return valor(find_value(palabras, etiqueta, **kw))


def _header(paginas: list[str], palabras: list[Any], tablas: list[Any], source_file: str) -> dict[str, Any]:
    """Cabecera de una factura de Fenix (todos los campos del PDF)."""
    texto = "\n".join(paginas)
    fila_req = pares_tabla(tablas, "Requisitioner")
    fila_piezas = pares_tabla(tablas, "# of Pieces")
    numero = _INVOICE_NUM_RE.search(texto)
    return {
        "source_file": source_file,
        "vendor": VENDOR,
        "vendor_name": limpiar(
            next((l for l in paginas[0].splitlines() if "Aerospace" in l), None)
        ),
        "invoice_number": valor(numero.group(1)) if numero else None,
        "invoice_date": _fecha(texto),
        "invoice_terms": fila_req.get("TERMS") or _campo(palabras, "Terms", below=14),
        "so_number": _campo(palabras, "SO #") or _campo(palabras, "SO"),
        "rls_number": _campo(palabras, "RLS #"),
        "po_number": _campo(palabras, "Customer PO #") or _campo(palabras, "Customer PO"),
        "vat_tax_id": _campo(palabras, "VAT/Tax ID:"),
        "website": _campo(palabras, "Website:"),
        "requisitioner": fila_req.get("REQUISITIONER"),
        "requisitioner_phone": fila_req.get("PHONE"),
        "awb": fila_req.get("AWB"),
        "ship_date": fila_req.get("SHIP DATE"),
        "num_pieces": fila_piezas.get("# OF PIECES"),
        "total_weight": fila_piezas.get("TOTAL WEIGHT"),
        "incoterms": fila_piezas.get("INCOTERMS"),
        "port_dest": fila_piezas.get("PORT/DEST"),
        "shipped_via": fila_piezas.get("SHIPPED VIA"),
        "shipped_via_acct": fila_piezas.get("SHIPPED VIA ACCT"),
        "billing_contact": _campo(palabras, "Billing Contact:"),
        "billing_phone": _campo(palabras, "Billing Phone:"),
        "billing_email": _campo(palabras, "Billing Email:"),
        "contact": _campo(palabras, "Contact:", x_max=200),
        "contact_phone": _campo(palabras, "Contact Phone:", x_max=200),
        "bill_to": block_value(palabras, "BILL TO", x_tol=2.0, x_span=200.0, y_span=70.0),
        "ship_to": block_value(palabras, "SHIP TO", x_tol=2.0, x_span=200.0, y_span=70.0),
        "subtotal": _monto(texto, "SUBTOTAL"),
        "tax": _monto(texto, "TAX SUBTOTAL"),
        "freight": _monto(texto, "FREIGHT"),
        "total": _monto(texto, "TOTAL"),
        "currency": "USD",
        "comments": _comentarios(tablas),
    }



def _es_meta(linea: str) -> bool:
    """¿La línea posterior a un ítem son metadatos (HTS, ECCN, ALT, …)?"""
    return any(linea.upper().startswith(pref) for pref in _META_PREFIJOS)


# Títulos de la tabla de ítems -> nombre de la columna en la tabla de detalles.
_COLUMNAS_ITEMS = {
    "LN": "line_number",
    "PART NO": "part_number",
    "SERIAL NUMBER": "serial_number",
    "DESCRIPTION": "description",
    "CN": "condition",
    "QTY": "qty",
    "UOM": "uom",
    "UNIT PRICE": "unit_price",
    "TOTAL": "amount",
}

_DETALLE_VACIO = {
    "line_number": None,
    "part_number": None,
    "serial_number": None,
    "description": None,
    "condition": None,
    "qty": None,
    "uom": None,
    "unit_price": None,
    "amount": None,
    "extras": None,
}


def _details(paginas_palabras: list[Any], source_file: str) -> list[dict[str, Any]]:
    """Filas de la tabla de ítems (por coordenadas, con sus metadatos).

    La tabla la delimita su propia fila de títulos
    (``LN PART NO SERIAL NUMBER DESCRIPTION CN QTY UOM UNIT PRICE TOTAL``) y cada
    dato se coloca en su columna por **x**: así una descripción de varias palabras
    no se confunde con la columna vecina ni la desplaza una columna vacía.
    """
    detalles: list[dict[str, Any]] = []
    for numero_pagina, palabras in enumerate(paginas_palabras, start=1):
        _, filas = cabecera_y_datos(
            rejilla(palabras, gap=7.0), ("PART NO", "DESCRIPTION", "UNIT PRICE", "QTY")
        )
        actual: dict[str, Any] | None = None
        for numero_fila, fila in enumerate(filas, start=1):
            datos = {
                _COLUMNAS_ITEMS[titulo]: valor
                for titulo, valor in fila.items()
                if titulo in _COLUMNAS_ITEMS
            }
            if datos.get("line_number", "").isdigit():
                actual = {**_DETALLE_VACIO, **datos}
                actual["qty"] = num(actual["qty"]) or actual["qty"]
                actual["unit_price"] = num(actual["unit_price"])
                actual["amount"] = num(actual["amount"])
                actual["source_file"] = source_file
                actual["page"] = numero_pagina
                actual["row_number"] = numero_fila
                actual["raw_line"] = " | ".join(
                    f"{k}={v}" for k, v in fila.items()
                )
                detalles.append(actual)
                continue
            # Metadatos del ítem (HTS, ECCN, COUNTRY OF ORIGIN, ALT FOR …).
            texto = " ".join(fila.values()).strip()
            if actual is not None and _es_meta(texto):
                previo = actual["extras"]
                actual["extras"] = f"{previo} | {texto}" if previo else texto
    return detalles



def _es_factura(texto: str) -> bool:
    return "FENIX AEROSPACE" in texto.upper() and bool(_INVOICE_NUM_RE.search(texto))


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** factura de Fenix."""
    paginas = read_pages(path)
    if not _es_factura("\n".join(paginas)):
        raise ValueError(f"{path.name}: no es una factura de Fenix")
    palabras = read_words(path)
    return (
        _header(paginas, palabras[0], read_tables(path)[0], path.name),
        _details(palabras, path.name),
    )


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las facturas de Fenix de ``carpeta``."""
    cabeceras: list[dict[str, Any]] = []
    detalles: list[dict[str, Any]] = []
    for pdf in sorted(Path(carpeta).glob("*.pdf")):
        try:
            cabecera, filas = parse_pdf(pdf)
        except ValueError:
            continue
        cabeceras.append(cabecera)
        detalles.extend(filas)
    return {"header": cabeceras, "details": detalles}

