"""Facturas del software **Quantum Control** (JetSet Airmotive y Peniel Aerospace).

Los dos proveedores usan el mismo diseño (``Item / Part Number/Description /
Shipped / BackOrd CD / Unit Price / UOM / Total Amt`` y totales
``SubTotal / Tax Total / Misc Charge / Freight / Total / Payment Amt / Payment
Owed``), así que aquí vive la lógica común y cada carpeta tiene su módulo
(``jetset.py``, ``peniel.py``) que fija el proveedor y su tabla.

La **cabecera** (formulario de dos columnas: facturación/envío) se lee con la
rejilla por coordenadas de ``_common``; la **tabla de ítems** se lee del **texto
por líneas** (``_common.read_pages``), que es como este software la imprime: una
línea por ítem, con las columnas separadas por espacios

    ``1 101-381015-9 // 4712-6 BLEED SOLENOID VALVE 1 0 OH 2,500.00 EA 2,500.00``

Así no hay que adivinar dónde corta cada columna: el número de línea es el primer
token, la cola ``Shipped BackOrd CD Unit Price UOM Total Amt`` se lee **de derecha
a izquierda** (el importe y el precio son los dos montos, el UOM es la sigla que
va entre ellos) y lo del medio es el P/N + descripción. Las líneas que no empiezan
con número de línea (``ASSY.``, ``Serial``, ``P/N``, ``Alt``, ``Core Charge``…)
son continuación del ítem anterior y van a ``extras``.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import (
    iso_from_slash,
    limpiar,
    num,
    read_pages,
    read_words,
    rejilla,
)

# 'Etiqueta: valor' dentro de una celda (o la celda de al lado si está vacía).
_CAMPO_RE = re.compile(r"^(?P<etiqueta>[A-Za-z#][A-Za-z .#/]*?):\s*(?P<valor>.*)$")

# --- Tabla de ítems (texto) ------------------------------------------------- #
# La línea de un ítem empieza con su número de línea ('3 BLADCT 20.00 EA …');
# se exige el espacio para no confundirla con los puntos numerados del pie
# ('1. Material is subject to inspection…').
_ITEM_RE = re.compile(r"^(\d{1,3})\s+(?=\S)")
# Cola de la tabla, de derecha a izquierda: Total Amt, UOM, Unit Price y, si
# caben en la misma línea, Shipped / BackOrd / CD.
_MONTO_RE = re.compile(r"^-?[\d,]+\.\d{2}$")
_ENTERO_RE = re.compile(r"^\d{1,6}$")
_UOM_RE = re.compile(r"^[A-Z]{1,4}$")
_CD_RE = re.compile(r"^[A-Z]{2,3}$")
# P/N real del ítem cuando la columna imprime la descripción y lo deja rotulado.
_PN_RE = re.compile(r"\bP/N:?\s+(\S+)")
# Celdas vacías: este software imprime '_'.
_VACIO = "_"


def campos(filas: list[list[dict[str, Any]]]) -> dict[str, str | None]:
    """``{ETIQUETA: valor}`` de la cabecera (se queda con el primer valor lleno)."""
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
            if valor == "_":  # Quantum Control imprime '_' en los campos vacíos
                valor = None
            if etiqueta not in pares or (pares[etiqueta] is None and valor is not None):
                pares[etiqueta] = valor
    return pares


def direcciones(filas: list[list[dict[str, Any]]]) -> tuple[str | None, str | None]:
    """Bloques ``To:`` (facturación) y ``Ship To:`` (envío), en paralelo."""
    for indice, fila in enumerate(filas):
        textos = [celda["texto"].upper() for celda in fila]
        if not any(t.startswith(("TO:", "SHIP TO:")) for t in textos):
            continue
        izquierda: list[str] = []
        derecha: list[str] = []
        for siguiente in filas[indice + 1:]:
            if any(c["texto"].upper().startswith("INVOICE DATE") for c in siguiente):
                break
            for celda in siguiente:
                (izquierda if celda["x0"] < 290 else derecha).append(celda["texto"])
        return " | ".join(izquierda) or None, " | ".join(derecha) or None
    return None, None


def _parte_desc(texto: str) -> tuple[str | None, str | None, str | None]:
    """``'101-381015-9 // 4712-6 BLEED SOLENOID VALVE'`` -> P/N, alterno, descripción."""
    partes = texto.split(" // ", 1)
    tokens = partes[0].split()
    if not tokens:
        return None, None, None
    part = tokens[0]
    descripcion = " ".join(tokens[1:]).strip() or None
    alterno = None
    if len(partes) > 1:
        tokens_resto = partes[1].split()
        alterno = tokens_resto[0] if tokens_resto else None
        cola = " ".join(tokens_resto[1:]).strip()
        if cola:
            descripcion = f"{descripcion} {cola}".strip() if descripcion else cola
    return part, alterno, descripcion


def _cola_tabla(
    tokens: list[str],
) -> tuple[str | None, str | None, str | None, str | None, str | None, str | None,
           list[str]] | None:
    """Separa la cola ``… Shipped BackOrd CD Unit Price UOM Total Amt`` del texto.

    Devuelve ``(shipped, backord, cd, unit_price, uom, amount, texto)`` donde
    ``texto`` son los tokens que quedan a la izquierda (el P/N y la descripción), o
    ``None`` si la línea no trae la cola de la tabla (entonces no es un ítem).

    Se lee **de derecha a izquierda**: el último token es el importe y el penúltimo
    el UOM, que hace de separador; el monto anterior es el precio unitario. Lo que
    quede a la izquierda son las cantidades (``Shipped``, ``BackOrd``, ``CD``) si
    están en esta línea; el CD es la única que no es numérica.
    """
    resto = [t for t in tokens if t != _VACIO]
    if len(resto) < 3 or not _MONTO_RE.match(resto[-1]):
        return None
    total = resto.pop()
    if not resto or not _UOM_RE.match(resto[-1]):
        return None
    uom = resto.pop()
    if not resto or not _MONTO_RE.match(resto[-1]):
        return None
    precio = resto.pop()
    cd = resto.pop() if resto and _CD_RE.match(resto[-1]) else None
    backord = resto.pop() if resto and _ENTERO_RE.match(resto[-1]) else None
    shipped = resto.pop() if resto and _ENTERO_RE.match(resto[-1]) else None
    return shipped, backord, cd, precio, uom, total, resto


def _cantidades_sueltas(tokens: list[str]) -> tuple[str | None, str | None, str | None] | None:
    """``'58 0 NE'`` -> ``('58', '0', 'NE')``: la cantidad que cayó en otro renglón.

    Este software imprime ``Shipped BackOrd CD`` un poco más arriba que el resto de
    la línea, así que a veces salen solas debajo del ítem (factura 54402). Devuelve
    ``None`` si la línea no es eso (un ``Serial``, un ``TSN:``, una nota…).
    """
    limpios = [t for t in tokens if t != _VACIO]
    if not 2 <= len(limpios) <= 3 or not _ENTERO_RE.match(limpios[0]):
        return None
    if not all(_ENTERO_RE.match(t) or _CD_RE.match(t) for t in limpios):
        return None
    shipped = limpios[0]
    backord = limpios[1] if _ENTERO_RE.match(limpios[1]) else None
    cd = limpios[2] if len(limpios) > 2 and _CD_RE.match(limpios[2]) else None
    return shipped, backord, cd


def _bloques(lineas: list[str]) -> list[list[str]]:
    """Bloques de ítem: la línea del ítem y los renglones que cuelgan de ella.

    Un renglón nuevo abre bloque si empieza con el número de línea **y** trae la
    cola de la tabla; el resto son continuación. El bloqueo (y la tabla) termina en
    el texto legal del pie (``_FIN_EXTRAS``).
    """
    bloques: list[list[str]] = []
    for linea in lineas:
        if not linea.strip():
            continue
        if any(marca in linea.upper() for marca in _FIN_EXTRAS):
            break
        tokens = linea.split()
        if _ITEM_RE.match(linea) and _cola_tabla(tokens[1:]):
            bloques.append([linea])
        elif bloques:
            bloques[-1].append(linea)
    return bloques


def _fila(bloque: list[str], source_file: str) -> dict[str, Any]:
    """Un bloque (el ítem y sus renglones) a fila de la tabla de detalles."""
    tokens = bloque[0].split()
    item = tokens[0]
    shipped, backord, cd, precio, uom, total, resto = _cola_tabla(tokens[1:])
    texto = " ".join(resto)
    part, alt, desc = _parte_desc(texto)
    extras: list[str] = []
    for linea in bloque[1:]:
        cantidades = _cantidades_sueltas(linea.split())
        if cantidades and shipped is None and backord is None and cd is None:
            shipped, backord, cd = cantidades
        else:
            extras.append(linea)
    # Cuando la columna imprime la descripción arriba, el P/N va rotulado en un
    # renglón de debajo ('P/N: 3049291-01'): ése es el P/N real y lo de la primera
    # línea es descripción. Si la primera línea ya trae 'P/N alterno // descripción'
    # (formato normal de este software) no hay nada que corregir.
    if " // " not in texto:
        etiquetado = next(
            (m.group(1) for linea in bloque for m in (_PN_RE.search(linea),) if m), None
        )
        if etiquetado:
            part, alt, desc = etiquetado, None, texto or None
    return {
        "source_file": source_file,
        "item": item,
        "part_number": part,
        "alt_part": alt,
        "description": desc,
        "shipped": shipped,
        "backord_cd": " ".join(x for x in (backord, cd) if x) or None,
        "unit_price": num(precio),
        "uom": uom,
        "amount": num(total),
        "extras": " | ".join(extras) or None,
        "raw_line": " | ".join(bloque),
    }


def detalles(paginas: list[str], source_file: str) -> list[dict[str, Any]]:
    """Líneas de la tabla de ítems, leídas del **texto** de cada página.

    La tabla se reconoce por su fila de títulos (``Part Number/Description``) y de
    ahí para abajo; cada línea de ítem se parte con ``_cola_tabla`` y el P/N y la
    descripción con ``_parte_desc``. Las líneas sin número de línea (``ASSY.``,
    ``Serial``, ``P/N``, ``Alt``, ``Core Charge``, ``(EXCHANGE)``, ``TSN``…) son
    continuación del ítem anterior y quedan en ``extras``.
    """
    salida: list[dict[str, Any]] = []
    for pagina in paginas:
        lineas = pagina.splitlines()
        cabecera = next(
            (i for i, linea in enumerate(lineas) if "PART NUMBER/DESCRIPTION" in linea.upper()),
            None,
        )
        if cabecera is None:
            continue
        salida.extend(_fila(bloque, source_file) for bloque in _bloques(lineas[cabecera + 1:]))
    return salida


# Textos que marcan el fin de los datos de los ítems (condiciones legales, banco…).
_FIN_EXTRAS = (
    "SPECIAL CONDITIONS", "SPECIAL INSTRUCTIONS", "PAYABLE IN USD", "SUBTOTAL",
    "TAX TOTAL", "BANK WIRE", "THANK YOU", "ORDER COMPLETE", "FORM CREATED",
    "AT WWW.", "1. MATERIAL", "***", "* * *",
)



def cabecera(
    filas: list[list[dict[str, Any]]],
    pares: dict[str, str | None],
    source_file: str,
    vendor: str,
    vendor_name: str,
) -> dict[str, Any]:
    """Cabecera de una factura de Quantum Control."""
    facturacion, envio = direcciones(filas)
    return {
        "source_file": source_file,
        "vendor": vendor,
        "vendor_name": vendor_name,
        "invoice_number": pares.get("INVOICE #"),
        "invoice_date": iso_from_slash(pares.get("INVOICE DATE")),
        "date_printed": iso_from_slash(pares.get("DATE PRINTED")),
        "printed_time": pares.get("TIME"),
        "num_items": pares.get("# OF ITEMS"),
        "page": pares.get("PAGE"),
        "po_number": pares.get("CUST. PO#"),
        "order_date": iso_from_slash(pares.get("ORDER DATE")),
        "ship_date": iso_from_slash(pares.get("SHIP DATE")),
        "terms": pares.get("TERMS"),
        "weight": pares.get("WEIGHT"),
        "ship_via": pares.get("SHIP VIA"),
        "num_boxes": pares.get("# OF BOXES"),
        "ship_via_acc": pares.get("SHIP VIA ACC"),
        "sales_order": pares.get("SALES ORDER"),
        "buyer": pares.get("BUYER"),
        "cust_vat": pares.get("CUST VAT #"),
        "ship_log": pares.get("SHIP LOG #"),
        "ship_order": pares.get("SHIP ORDER"),
        "shipment": pares.get("SHIPMENT"),
        "customer_number": pares.get("CUSTOMER #"),
        "awb": pares.get("AWB"),
        "vat_number": pares.get("VAT #"),
        "prepared_by": pares.get("PREPARED BY"),
        "incoterm": pares.get("INCOTERM"),
        "freight_forward": pares.get("FF"),
        "att": pares.get("ATT"),
        "to_address": facturacion,
        "ship_to_address": envio,
        "subtotal": num(pares.get("SUBTOTAL")),
        "tax_total": num(pares.get("TAX TOTAL")),
        "misc_charge": num(pares.get("MISC CHARGE")),
        "freight": num(pares.get("FREIGHT")),
        "disc_total": num(pares.get("DISC TOTAL")),
        "total": num(pares.get("TOTAL")),
        "payment_amt": num(pares.get("PAYMENT AMT")),
        "payment_type": pares.get("PAYMENT TYPE"),
        "payment_owed": num(pares.get("PAYMENT OWED")),
        "currency": "USD",
    }


def parse(path: Path, vendor: str, vendor_name: str, marca: str) -> tuple[dict, list[dict]]:
    """Cabecera y detalles de **una** factura de Quantum Control.

    ``marca`` es el texto que identifica al proveedor (p. ej. ``"JETSET AIRMOTIVE"``).
    """
    paginas = read_pages(path)
    if marca.upper() not in "\n".join(paginas).upper():
        raise ValueError(f"{path.name}: no es una factura de {vendor}")
    filas = [fila for pagina in read_words(path) for fila in rejilla(pagina, gap=6.0)]
    pares = campos(filas)
    return (
        cabecera(filas, pares, path.name, vendor, vendor_name),
        detalles(paginas, path.name),
    )


def parse_carpeta(
    carpeta: Path, vendor: str, vendor_name: str, marca: str
) -> dict[str, list[dict]]:
    """Todas las facturas del proveedor que hay en ``carpeta``."""
    cabeceras: list[dict] = []
    lineas: list[dict] = []
    for pdf in sorted(Path(carpeta).glob("*.pdf")):
        try:
            cabecera_factura, filas = parse(pdf, vendor, vendor_name, marca)
        except ValueError:
            continue
        cabeceras.append(cabecera_factura)
        lineas.extend(filas)
    return {"header": cabeceras, "details": lineas}

