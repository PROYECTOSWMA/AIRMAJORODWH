"""Facturas de **Textron Aviation Inc.** (``INVOICE NUMBER: IJ########``).

Cabecera en pares ``ETIQUETA: valor`` (``INVOICE NUMBER``, ``DATE``, ``DUE DATE``,
``TERMS``, ``TYPE``, ``CURRENCY``, ``CUSTOMER PO#``, ``SALES ORDER NUMBER``,
``SHIP DATE``, ``TERMS CODE``, ``SHIPPING TERMS``, ``B/L NO``, ``PACKING SHEET``,
``WEIGHT (lbs)``, ``METHOD`` y los totales ``INVOICE SUB TOTAL``, ``SHIPPING AND
HANDLING CHARGES``, ``TOTAL TAX``, ``INVOICE TOTAL``, ``TOTAL UNITS``).

La tabla trae **dos precios** (``List Price`` y ``Unit Price``) y dos columnas de
descripción; el importe que vale para el cruce es el **Unit Price** (sin IGV).
Sus títulos van repartidos en tres renglones (``Line / Part Number``,
``Description 1 / Description 2 / Disc. / UOM Quantity``, ``Number / Price /
Price / Amount``) y dos columnas se llaman igual (``Number``), así que se mapea
por **posición contando desde el final** de la fila:

    … | List Price | Disc. | Unit Price | UOM | Quantity | Extended Amount

Se lee con la **rejilla por coordenadas**; algún export imprime el número de
factura como ``TextronAviationInvoice_91579509`` (solo dígitos).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import iso_from_slash, limpiar, num, read_pages, read_words, rejilla

VENDOR = "TEXTRON AVIATION"
VENDOR_NAME = "Textron Aviation Inc."

_CAMPO_RE = re.compile(r"^(?P<etiqueta>[A-Za-z][A-Za-z .#/()]*?)\s*:\s*(?P<valor>.*)$")
_ITEMS_INICIO = ("DESCRIPTION 1", "DESCRIPTION 2", "EXTENDED")
_ITEM_RE = re.compile(r"^(?P<line>\d+)\s+(?P<part>\S+)$")
# La línea del ítem, sola en su celda (el otro export parte el ítem en dos celdas).
_LINEA_RE = re.compile(r"^\d+$")
_TOTALES = (
    "INVOICE SUB TOTAL", "SHIPPING AND HANDLING CHARGES", "TOTAL TAX",
    "INVOICE TOTAL", "TOTAL UNITS",
)


def _campos(filas: list[list[dict[str, Any]]]) -> dict[str, str]:
    """``{ETIQUETA: valor}`` de la cabecera (sirve también la celda vecina)."""
    pares: dict[str, str | None] = {}
    for fila in filas:
        for indice, celda in enumerate(fila):
            match = _CAMPO_RE.match(celda["texto"])
            if not match:
                continue
            etiqueta = match.group("etiqueta").strip().upper()
            valor = limpiar(match.group("valor"))
            if valor is None and indice + 1 < len(fila):
                siguiente = fila[indice + 1]["texto"]
                if not _CAMPO_RE.match(siguiente):
                    valor = limpiar(siguiente)
            if etiqueta not in pares or (pares[etiqueta] is None and valor is not None):
                pares[etiqueta] = valor
    return {k: v for k, v in pares.items() if v is not None}


def _bloques(filas: list[list[dict[str, Any]]]) -> tuple[str | None, str | None]:
    """Bloques ``SOLD TO`` y ``SHIP TO`` (van en dos columnas)."""
    for indice, fila in enumerate(filas):
        if any(c["texto"].upper().startswith("SOLD TO:") for c in fila):
            vendido: list[str] = []
            enviado: list[str] = []
            for siguiente in filas[indice + 1:]:
                for celda in siguiente:
                    texto = celda["texto"]
                    if _CAMPO_RE.match(texto) and "SHIP" not in texto.upper():
                        break
                    (vendido if celda["x0"] < 300 else enviado).append(texto)
                if any("PERU" in c["texto"].upper() for c in siguiente):
                    break
            return " | ".join(vendido) or None, " | ".join(enviado) or None
    return None, None


def _header(
    filas: list[list[dict[str, Any]]], texto: str, source_file: str
) -> dict[str, Any]:
    """Cabecera de una factura de Textron."""
    pares = _campos(filas)
    numero = pares.get("INVOICE NUMBER")
    if numero is None:
        match = re.search(r"TextronAviationInvoice[_\s]*([A-Z0-9]+)", source_file)
        numero = match.group(1) if match else None
    vendido, enviado = _bloques(filas)
    return {
        "source_file": source_file,
        "vendor": VENDOR,
        "vendor_name": VENDOR_NAME,
        "invoice_number": numero,
        "invoice_date": iso_from_slash(pares.get("DATE")),
        "due_date": iso_from_slash(pares.get("DUE DATE")),
        "terms": pares.get("TERMS"),
        "type": pares.get("TYPE"),
        "currency": pares.get("CURRENCY"),
        "sold_to_number": pares.get("SOLD TO"),
        "seller": pares.get("SELLER"),
        "po_number": pares.get("CUSTOMER PO#"),
        "sales_order": pares.get("SALES ORDER NUMBER"),
        "ship_date": iso_from_slash(pares.get("SHIP DATE")),
        "terms_code": pares.get("TERMS CODE"),
        "shipping_terms": pares.get("SHIPPING TERMS"),
        "bl_number": pares.get("B/L NO"),
        "packing_sheet": pares.get("PACKING SHEET"),
        "weight_lbs": pares.get("WEIGHT (LBS)"),
        "method": pares.get("METHOD"),
        "order_reason": pares.get("ORDER REASON"),
        "forwarding_agent": pares.get("FORWARDING AGENT"),
        "sold_to_address": vendido,
        "ship_to_address": enviado,
        "subtotal": num(pares.get("INVOICE SUB TOTAL")),
        "shipping_handling": num(pares.get("SHIPPING AND HANDLING CHARGES")),
        "tax": num(pares.get("TOTAL TAX")),
        "total": num(pares.get("INVOICE TOTAL")),
        "total_units": pares.get("TOTAL UNITS"),
        "fed_tax_id": pares.get("FED TAX ID"),
        "account": pares.get("ACCOUNT"),
        "aba_route": pares.get("ABA ROUTE"),
        "bank": pares.get("BANK"),
    }



def _details(filas: list[list[dict[str, Any]]], source_file: str) -> list[dict[str, Any]]:
    """Líneas de la tabla de ítems (mapeo posicional desde el final de la fila)."""
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
        # El ítem viene de DOS formas según el export: junto en una celda
        # ('1 MS28778-5') o partido en dos (['1', 'MS28778-5', 'PACKING', …]). Los
        # importes se leen **desde el final** de la fila, así que lo único que hay que
        # saber es en qué celda termina el P/N (`fin_pn`): en la partida, la
        # descripción empieza una celda más a la derecha.
        junto = _ITEM_RE.match(textos[0]) if textos else None
        if junto:
            fin_pn = 0
        elif textos and _LINEA_RE.match(textos[0]) and len(textos) > 1:
            fin_pn = 1
        else:
            fin_pn = None
        if fin_pn is not None and len(textos) >= 6 + fin_pn:
            cola = textos[-6:-1]  # List Price | Disc. | Unit Price | UOM | Quantity
            descripciones = textos[fin_pn + 1:-6]
            actual = {
                "source_file": source_file,
                "line": junto.group("line") if junto else textos[0],
                "part_number": limpiar(junto.group("part") if junto else textos[1]),
                "description_1": descripciones[0] if descripciones else None,
                "description_2": " ".join(descripciones[1:]) or None
                if len(descripciones) > 1
                else None,
                "list_price": num(cola[0]),
                "discount": cola[1],
                "unit_price": num(cola[2]),
                "uom": cola[3],
                "quantity": cola[4],
                "amount": num(textos[-1]),
                "extras": None,
                "raw_line": " | ".join(textos),
            }
            salida.append(actual)
            continue
        if actual is None:
            continue
        texto = " | ".join(textos)
        if any(p in texto.upper() for p in _TOTALES) or texto.upper().startswith("PL EASE"):
            actual = None
            continue
        previo = actual["extras"]
        actual["extras"] = f"{previo} | {texto}" if previo else texto
    return salida


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** factura de Textron."""
    paginas = read_pages(path)
    texto = "\n".join(paginas)
    if "TEXTRON AVIATION" not in texto.upper():
        raise ValueError(f"{path.name}: no es una factura de Textron")
    filas = [fila for pagina in read_words(path) for fila in rejilla(pagina, gap=7.0)]
    return _header(filas, texto, path.name), _details(filas, path.name)


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las facturas de Textron de ``carpeta``."""
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

