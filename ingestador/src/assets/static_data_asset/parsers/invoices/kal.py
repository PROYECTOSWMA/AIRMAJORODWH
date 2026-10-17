"""Facturas de **Kal-Airparts / Kal-Aviation LLC** (``Invoice KA26-####``).

Diseño propio de Kal. Cabecera en dos columnas (``SOLD TO`` / ``SHIP TO``) y una
tabla con los títulos **en dos renglones** (``ORDER QTY`` y ``SHIP QTY`` van
debajo), por lo que aquí no se puede alinear por títulos: se lee la **rejilla por
coordenadas** (``_common.rejilla``) y se mapean las celdas por **posición**, como
las imprime el PDF:

    ORDER QTY | SHIP QTY | COND | P/N: … descripción | … | UNIT PRICE | AMOUNT

La tabla se **envuelve**: el HTS/ECCN, el ``Lot No`` y los importes pueden caer en
los renglones siguientes (``Lot No: 062323 262.40 524.80``), así que los dos
últimos importes que aparezcan antes del ítem siguiente son *unit price* y
*amount*.

⚠️ En esta carpeta hay un PDF que **no** es una factura
(``Kal- Aviation USA LLC  PO 702-2026.pdf``): es una **orden de compra** y se
ignora (el parser exige la marca ``Invoice`` de Kal).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import iso_from_text, limpiar, num, read_pages, read_words, rejilla

VENDOR = "KAL AIRPARTS"
VENDOR_NAME = "Kal-Airparts"

_INVOICE_RE = re.compile(r"^\s*Invoice\s+(\S+)", re.MULTILINE)
_DATE_RE = re.compile(r"DATE:\s*([A-Za-z]+ \d{1,2}, \d{4})")
_PN_RE = re.compile(r"P/N:\s*(\S+)\s*(.*)$")
_MONTOS_RE = re.compile(r"[\d,]+\.\d{2}")


def _pares(filas: list[list[dict[str, Any]]], ancla: str) -> dict[str, str | None]:
    """``{titulo: valor}`` de la fila de títulos que contiene ``ancla``."""
    for indice, fila in enumerate(filas):
        textos = [celda["texto"] for celda in fila]
        if not any(ancla.upper() in t.upper() for t in textos):
            continue
        if indice + 1 >= len(filas):
            continue
        valores = [celda["texto"] for celda in filas[indice + 1]]
        return {
            titulo.upper(): (valores[i] if i < len(valores) else None)
            for i, titulo in enumerate(textos)
        }
    return {}


def _header(
    filas: list[list[dict[str, Any]]], texto: str, source_file: str
) -> dict[str, Any]:
    """Cabecera de una factura de Kal."""
    cliente = _pares(filas, "CUSTOMER NO.")
    pedido = _pares(filas, "SALES ORDER NO.")
    numero = _INVOICE_RE.search(texto)
    fecha = _DATE_RE.search(texto)
    total = None
    for fila in filas:
        celda = " ".join(c["texto"] for c in fila)
        match = re.search(r"Total Due.*?([\d,]+\.\d{2})", celda)
        if match:
            total = num(match.group(1))
    sold_to: list[str] = []
    ship_to: list[str] = []
    for indice, fila in enumerate(filas):
        if any(c["texto"].upper().startswith("TO:") for c in fila):
            for siguiente in filas[indice + 1:]:
                if "MONTHLY" in " ".join(c["texto"] for c in siguiente).upper():
                    break
                for celda in siguiente:
                    destino = sold_to if celda["x0"] < 300 else ship_to
                    destino.append(re.sub(r"^TO:\s*", "", celda["texto"]))
            break
    return {
        "source_file": source_file,
        "vendor": VENDOR,
        "vendor_name": VENDOR_NAME,
        "invoice_number": limpiar(numero.group(1)) if numero else None,
        "invoice_date": iso_from_text(fecha.group(1)) if fecha else None,
        "po_number": cliente.get("CUSTOMER ORDER NO.") or cliente.get("CUSTOMER ORDER NO"),
        "customer_number": cliente.get("CUSTOMER NO."),
        "sales_person": cliente.get("SALES PERSON"),
        "ship_via": cliente.get("SHIP VIA"),
        "terms": cliente.get("TERMS"),
        "sales_order": pedido.get("SALES ORDER NO."),
        "order_date": pedido.get("ORDER DATE"),
        "ship_date": pedido.get("SHIP DATE"),
        "sold_to": " | ".join(sold_to) or None,
        "ship_to": " | ".join(ship_to) or None,
        "total_due": total,
        "currency": "USD" if "US Currency" in texto else None,
        "approved_by": limpiar(
            (re.search(r"Approved by\s+(.+)", texto) or [None, None])[1]
        ),
    }


def _details(filas: list[list[dict[str, Any]]], source_file: str) -> list[dict[str, Any]]:
    """Ítems de Kal (cantidades, condición, P/N y los dos últimos importes)."""
    inicio = 0
    for indice, fila in enumerate(filas):
        textos = " ".join(c["texto"].upper() for c in fila)
        if "PRODUCT CODE/DESCRIPTION" in textos:
            inicio = indice + 1
            break
    salida: list[dict[str, Any]] = []
    actual: dict[str, Any] | None = None
    for fila in filas[inicio:]:
        textos = [celda["texto"] for celda in fila]
        if textos and re.match(r"^\d+$", textos[0]) and len(textos) >= 3:
            pn = next((t for t in textos[3:] if t.upper().startswith("P/N")), None)
            match = _PN_RE.search(pn or "")
            montos = _MONTOS_RE.findall(" | ".join(textos[4:]))
            actual = {
                "source_file": source_file,
                "item": textos[0],
                "order_qty": textos[1] if len(textos) > 1 else None,
                "ship_qty": textos[2] if len(textos) > 2 else None,
                "condition": textos[3] if len(textos) > 3 else None,
                "part_number": limpiar(match.group(1)) if match else None,
                "description": limpiar(match.group(2)) if match else None,
                "unit_price": num(montos[-2]) if len(montos) >= 2 else None,
                "amount": num(montos[-1]) if montos else None,
                "extras": None,
                "raw_line": " | ".join(textos),
            }
            salida.append(actual)
            continue
        if actual is None:
            continue
        texto = " | ".join(textos)
        if any(p in texto.upper() for p in ("TOTAL DUE", "APPROVED BY")):
            actual = None
            continue
        montos = _MONTOS_RE.findall(texto)
        if montos:
            if len(montos) >= 2:
                actual["unit_price"], actual["amount"] = num(montos[-2]), num(montos[-1])
            elif actual["amount"] is None:
                actual["amount"] = num(montos[-1])
            continue
        previo = actual["extras"]
        actual["extras"] = f"{previo} | {texto}" if previo else texto
    return salida


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** factura de Kal."""
    paginas = read_pages(path)
    texto = "\n".join(paginas)
    if not _INVOICE_RE.search(texto) or "kal" not in texto.lower():
        raise ValueError(f"{path.name}: no es una factura de Kal")
    filas = [fila for pagina in read_words(path) for fila in rejilla(pagina, gap=7.0)]
    return _header(filas, texto, path.name), _details(filas, path.name)


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las facturas de Kal de ``carpeta``."""
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

