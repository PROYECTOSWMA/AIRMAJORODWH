"""Facturas de **Precision Aviation Group / Precision Heliparts** (PENTAGON).

Diseño del software PENTAGON 2000, con la cabecera en pares
``Etiqueta : valor`` (``No.``, ``S.O. No.``, ``Customer P.O.``, ``Invoice Date``,
``Due Date``, ``Ship Via``, ``Incoterms``, ``Shipped Date``, ``Terms``, ``Our
Contact``, ``Email``…) y la tabla

    Line | P/N & Description | Cnd | Qty Ordered | Shipped | Unit Sell Price | Amount

La descripción va **debajo** del P/N (``GOVERNOR PT6``), y las líneas de
devolución de core (``AR``) no traen importe: el ``amount`` se calcula con
unit × cantidad. Se lee con la **rejilla por coordenadas** y se mapea por
posición (las columnas son fijas en este PDF).

El número de factura y el total pueden partirse entre las dos páginas
(``No. : 992140 24`` + ``Sales Invoice No. 99214024``), así que se aceptan las
dos formas.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import (
    iso_from_text,
    limpiar,
    num,
    read_pages,
    read_words,
    rejilla,
)

VENDOR = "PRECISION HELIPARTS INC."
VENDOR_NAME = "Precision Heliparts Inc."
_MARCA = "PRECISION HELIPARTS"

# 'Etiqueta : valor' (con o sin espacios alrededor de los dos puntos).
_CAMPO_RE = re.compile(r"^(?P<etiqueta>[A-Za-z][A-Za-z .#/]*?)\s*:\s*(?P<valor>.*)$")
_ITEMS_INICIO = ("P/N & DESCRIPTION", "QTY ORDERED", "SELL PRICE")
# '1' | '8210-003-01' | 'OH' | '1EA' | '1' | '$ 2,950.00 EA' | '$ 2,950.00'
_ITEM_RE = re.compile(r"^\d+$")
_CANTIDAD_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$")
_PRECIO_RE = re.compile(r"^\$\s*([\d,]+\.\d{2})\s*([A-Za-z]*)$")
# '(Qty. Back 0)' es una nota del PDF, no parte de la descripción.
_QTY_BACK_RE = re.compile(r"\s*\(Qty\.\s*Back\s*\d+\)\s*", re.IGNORECASE)


def _textos(fila: list[dict[str, Any]]) -> list[str]:
    """Textos de una fila con la celda de los dos puntos **pegada a la anterior**.

    Este PDF imprime el ``:`` en su propia celda cuando el hueco es ancho
    (``['Customer P.O.', ':PO 717-2026']``): sin pegarlos, la etiqueta se queda sin
    dos puntos, ninguna celda de la cabecera casa y se pierden datos (el nº de PO,
    la fecha de factura y el vencimiento salían en blanco).
    """
    textos: list[str] = []
    for celda in fila:
        texto = celda["texto"]
        if texto.startswith(":") and textos:
            textos[-1] = f"{textos[-1]} {texto}"
        else:
            textos.append(texto)
    return textos


def _campos(filas: list[list[dict[str, Any]]]) -> dict[str, str]:
    """``{ETIQUETA: valor}`` de la cabecera (usa también la celda vecina)."""
    pares: dict[str, str | None] = {}
    for fila in filas:
        textos = _textos(fila)
        for indice, texto in enumerate(textos):
            match = _CAMPO_RE.match(texto)
            if not match:
                continue
            etiqueta = match.group("etiqueta").strip().upper()
            valor = limpiar(match.group("valor"))
            if valor is None and indice + 1 < len(textos):
                siguiente = textos[indice + 1]
                if not _CAMPO_RE.match(siguiente):
                    valor = limpiar(siguiente)
            if etiqueta not in pares or (pares[etiqueta] is None and valor is not None):
                pares[etiqueta] = valor
    return {k: v for k, v in pares.items() if v is not None}


def _header(
    filas: list[list[dict[str, Any]]], texto: str, source_file: str
) -> dict[str, Any]:
    """Cabecera de una factura de Precision/PAG."""
    pares = _campos(filas)
    numero = pares.get("SALES INVOICE NO.") or pares.get("NO.")
    if numero:
        # 'No. : 992140 24 Pg:1/2' -> '99214024' (la página va pegada al número).
        numero = re.split(
            r"pg", numero.replace(" ", ""), maxsplit=1, flags=re.IGNORECASE
        )[0] or None
    balance = re.search(r"Balance:\s*\[[A-Z]+\]\s*\$?\s*([\d,.]+)", texto)
    return {
        "source_file": source_file,
        "vendor": VENDOR,
        "vendor_name": VENDOR_NAME,
        "invoice_number": numero,
        "invoice_date": iso_from_text(pares.get("INVOICE DATE")),
        "due_date": iso_from_text(pares.get("DUE DATE")),
        "print_date": iso_from_text((pares.get("PRINT DATE") or "").split("  ", 1)[0]),
        "printed_by": pares.get("PRINTED BY"),
        "print_no": pares.get("PRINT NO."),
        "page": pares.get("PAGE"),
        "account_number": pares.get("ACCOUNT NO."),
        "so_number": pares.get("S.O. NO."),
        "our_ref": pares.get("OUR REF"),
        "po_number": pares.get("CUSTOMER P.O."),
        "your_ref": pares.get("YOUR REF"),
        "ship_via": pares.get("SHIP VIA"),
        "ship_via_acc": pares.get("SHIP VIA ACCT."),
        "incoterms": pares.get("INCOTERMS"),
        "shipped_date": iso_from_text(pares.get("SHIPPED DATE")),
        "terms": pares.get("TERMS"),
        "our_contact": pares.get("OUR CONTACT"),
        "email": pares.get("EMAIL"),
        "domestic_awb": pares.get("DOMESTIC AWB"),
        "intl_awb": pares.get("INT'L AWB"),
        "cod_amt": pares.get("COD AMT."),
        "origin": pares.get("ORIGIN"),
        "contract": pares.get("CONTRACT"),
        "transport": pares.get("TRANSPORT"),
        "invoiced_to": pares.get("BILL TO"),
        "sold_to": pares.get("SOLD TO"),
        "shipped_to": pares.get("SHIPPED TO"),
        "remit_to": pares.get("REMIT PAYMENT TO"),
        "subtotal": num((pares.get("SUB TOTAL") or "").replace("$", "")),
        "total": num((pares.get("TOTAL") or "").replace("$", "")),
        "balance": num(balance.group(1)) if balance else None,
        "currency": "USD" if "USD" in texto else None,
    }



def _details(filas: list[list[dict[str, Any]]], source_file: str) -> list[dict[str, Any]]:
    """Líneas de la tabla de ítems (la descripción va en el renglón siguiente)."""
    inicio = 0
    for indice, fila in enumerate(filas):
        unido = " ".join(c["texto"].upper() for c in fila)
        if all(etq in unido for etq in _ITEMS_INICIO):
            inicio = indice + 1
            break
    salida: list[dict[str, Any]] = []
    actual: dict[str, Any] | None = None
    for fila in filas[inicio:]:
        textos = [celda["texto"] for celda in fila]
        if textos and _ITEM_RE.match(textos[0]) and len(textos) >= 5:
            cantidad = _CANTIDAD_RE.match(textos[3]) if len(textos) > 3 else None
            precio = _PRECIO_RE.match(textos[-2]) if len(textos) >= 2 else None
            actual = {
                "source_file": source_file,
                "line": textos[0],
                "part_number": textos[1] if len(textos) > 1 else None,
                "condition": textos[2] if len(textos) > 2 else None,
                "qty_ordered": cantidad.group(1) if cantidad else None,
                "uom": cantidad.group(2) if cantidad else None,
                "qty_shipped": textos[4] if len(textos) > 4 else None,
                "unit_price": num(precio.group(1)) if precio else None,
                "amount": num(textos[-1]) if textos[-1] else None,
                "description": None,
                "extras": None,
                "raw_line": " | ".join(textos),
            }
            salida.append(actual)
            continue
        if actual is None:
            continue
        texto = " | ".join(textos)
        if any(
            p in texto.upper()
            for p in ("ALL PAYMENTS ARE SUBJECT", "SUB TOTAL", "COPYRIGHT (C)", "TOTAL:")
        ):
            actual = None
            continue
        if actual["description"] is None and not texto.upper().startswith(
            (
                "ECCN", "HTS", "PICK TICKET", "PRIORITY", "NOTE:", "SERIAL",
                "TAG DATE", "END USER", "RETURN CORE", "ALT#",
            )
        ):
            actual["description"] = _QTY_BACK_RE.sub("", texto).strip() or texto
            continue
        previo = actual["extras"]
        actual["extras"] = f"{previo} | {texto}" if previo else texto
    return salida


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** factura de Precision/PAG."""
    paginas = read_pages(path)
    texto = "\n".join(paginas)
    if _MARCA not in texto.upper() and "PRECISION AVIATION GROUP" not in texto.upper():
        raise ValueError(f"{path.name}: no es una factura de Precision")
    filas = [fila for pagina in read_words(path) for fila in rejilla(pagina, gap=7.0)]
    return _header(filas, texto, path.name), _details(filas, path.name)


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las facturas de Precision de ``carpeta``."""
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

