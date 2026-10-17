"""Órdenes de compra de Air Majoro (un solo parser para sus seis subcarpetas).

Las POs son un **formulario propio** de Air Majoro (mismo diseño para Fenix,
JetSet, Kal, Peniel, Precision y Textron): cabecera con etiquetas y valores en una
retícula de tres columnas, y una tabla de ítems real. Por eso **no** se lee por
líneas (el texto de la página mezcla las columnas) sino con el **grid** que
pdfplumber detecta (``read_tables``):

* la **cabecera** se arma con los pares *etiqueta -> valor* de la tabla del
  formulario (el valor está a la derecha en la misma fila y, si no, justo debajo
  en la misma columna: así se leen los bloques del proveedor y del forwarder); y
* los **ítems** salen de la tabla de la orden, respetando sus columnas.

La tabla de ítems tiene 12 columnas, pero las **etiquetas cambian** según cómo se
rellenó la PO (a veces hay ``CC`` y a veces ``CONDITION``; en una variante hay
``TYPE OF SERVICE``/``SERIAL``/``OBSERVATION``). Cada valor se guarda en la
columna donde **está** en el PDF, con el nombre que el PDF le pone:

    ITEM | CATALOGUE TYPE | PART NUMBER | I/W | [CONDITION] | DESCRIPTION |
    [CC] | QTY | UM | UNIT COST | TOTAL COST | AERONAVE | TIPO DE MANTENIMIENTO

⚠️ Quien llena la PO no es consistente: la **aeronave** (``OB2180``, ``B200``,
``STOCK``) aparece unas veces en la columna ``CC`` y otras en ``AERONAVE``, y la
**condición** (``NEW``/``OH``) en ``I/W`` o en ``CC``. Aquí se respeta lo que dice
el PDF; el cruce posterior debe mirar las dos columnas.

Contrato: ``parse_pdf(path) -> (header, details)`` y
``parse(carpeta) -> {"header": [...], "details": [...]}`` (recursivo, porque las
POs viven en seis subcarpetas de proveedor).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ._common import (
    cell,
    find_value,
    iso_from_text,
    label_pos,
    limpiar,
    norm_label,
    num,
    read_pages,
    read_tables,
    read_words,
    texto_celda,
)

# Etiquetas de la tabla de ítems -> nombre de la columna en la tabla de detalles.
_LABELS = {
    "item": "item",
    "catalogue type": "catalogue_type",
    "catalog ue type": "catalogue_type",
    "catalo gue type": "catalogue_type",
    "type of service": "catalogue_type",
    "part number": "part_number",
    "i/w": "i_w",
    "condition": "condition",
    "description": "description",
    "cc": "cc",
    "serial": "serial",
    "qty": "qty",
    "um": "um",
    "unit cost": "unit_cost",
    "total cost": "total_cost",
    "aeronave": "aeronave",
    "tipo de mantenimiento": "maintenance_note",
    "tipo de mantenimient": "maintenance_note",
    "tipo de mantenimient o": "maintenance_note",
    "observ ation": "maintenance_note",
    "observation": "maintenance_note",
}

# Columnas posibles de la tabla de detalles (vacías si el PDF no las imprime).
COLUMNAS = (
    "item", "catalogue_type", "part_number", "i_w", "condition", "description",
    "cc", "serial", "qty", "um", "unit_cost", "total_cost", "aeronave",
    "maintenance_note", "page", "source_file", "raw_line",
)

# Etiquetas del formulario de la cabecera (para reconocer una celda-etiqueta).
_ETIQUETAS_FORM = {
    "ORDER TYPE", "DATE", "PAYMENT TERMS", "DELIVERY TERMS", "CATEGORY",
    "LEAD TIME", "QUOTE", "SUPPLIER", "SHIPPING ADDRESS", "BUYER", "PAGES N",
    "NAME", "CONTACT", "EMAIL", "PHONE", "ADDRESS", "RUC",
}

_PO_TITULO_RE = re.compile(
    r"^\s*((?:PURCHASE|EXCHANGE|REPAIR|SERVICE)(?:\s+(?:ORDER|SERVICE))*)",
    re.IGNORECASE | re.MULTILINE,
)
# Nº de PO: 'PO 687-2026', 'PO 700', 'LOG-RO- 0133-2025'.
_PO_NUM_RE = re.compile(
    r"(?:ORDER|SERVICE)\s+N\S*\s*((?:PO|LOG-?RO|RO|OS)?\.?[\s\-]*\d[\d\-/ ]*)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")


# --------------------------------------------------------------------------- #
# Tabla de ítems
# --------------------------------------------------------------------------- #

def _es_tabla_items(fila: list[Any]) -> bool:
    """¿La fila es la cabecera de la tabla de ítems de la PO?"""
    etiquetas = [norm_label(c) for c in fila]
    if not etiquetas:
        return False
    if etiquetas[0] == "ITEM":
        return True
    return any(e.replace(" ", "") == "PARTNUMBER" for e in etiquetas)


def _columnas(fila: list[Any]) -> list[str | None]:
    """Columna canónica de cada celda de la cabecera de la tabla de ítems."""
    return [_LABELS.get(norm_label(c).lower()) for c in fila]


def _fila_items(fila: list[Any], columnas: list[str | None]) -> dict[str, Any] | None:
    """Fila de ítem -> detalle; ``None`` si la fila no es un ítem válido."""
    item = cell(fila, 0)
    if not item or not re.match(r"^\d+$", item):
        return None
    detalle: dict[str, Any] = {col: None for col in COLUMNAS}
    detalle["item"] = item
    for indice, nombre in enumerate(columnas):
        if nombre and nombre != "item":
            detalle[nombre] = cell(fila, indice)
    for campo in ("unit_cost", "total_cost"):
        if detalle.get(campo):
            detalle[campo] = num(detalle[campo])
    detalle["raw_line"] = " | ".join(
        valor for valor in (limpiar(c) for c in fila) if valor
    ) or None
    return detalle


def _items(paginas_tablas: list[Any], source_file: str) -> list[dict[str, Any]]:
    """Todos los ítems de la PO (una fila por ítem; ``page`` para ubicarlo)."""
    items: list[dict[str, Any]] = []
    for numero_pagina, tablas in enumerate(paginas_tablas, start=1):
        for tabla in tablas:
            columnas: list[str | None] | None = None
            for fila in tabla:
                if columnas is None:
                    if _es_tabla_items(fila):
                        columnas = _columnas(fila)
                    continue
                detalle = _fila_items(fila, columnas)
                if detalle is not None:
                    detalle["page"] = numero_pagina
                    detalle["source_file"] = source_file
                    items.append(detalle)
    return items


# --------------------------------------------------------------------------- #
# Cabecera (formulario)
# --------------------------------------------------------------------------- #

def _etiqueta(celda: Any) -> str | None:
    """Nombre canónico de una celda-etiqueta del formulario (o ``None``)."""
    if not limpiar(celda):
        return None
    etiqueta = norm_label(celda).rstrip(":").replace("°", "").strip()
    return etiqueta if etiqueta in _ETIQUETAS_FORM else None


def _pares_formulario(tablas: list[Any]) -> dict[str, str | None]:
    """``{etiqueta: valor}`` de las tablas del formulario.

    El valor es la primera celda con contenido a la **derecha** en la misma fila y,
    si no hay (o lo que hay es otra etiqueta), la celda **de debajo** en la misma
    columna: así se leen los bloques multilínea (proveedor, forwarder).
    """
    pares: dict[str, str | None] = {}
    for tabla in tablas:
        for numero_fila, fila in enumerate(tabla):
            for indice, celda in enumerate(fila):
                etiqueta = _etiqueta(celda)
                if etiqueta is None or etiqueta in pares:
                    continue
                valor: str | None = None
                for celda2 in fila[indice + 1:]:
                    if limpiar(celda2) is None:
                        continue
                    if _etiqueta(celda2) is None:
                        valor = texto_celda(celda2)
                    break
                if valor is None and numero_fila + 1 < len(tabla):
                    siguiente = tabla[numero_fila + 1]
                    if indice < len(siguiente):
                        abajo = texto_celda(siguiente[indice])
                        if abajo is not None and _etiqueta(siguiente[indice]) is None:
                            valor = abajo
                pares[etiqueta] = valor
    return pares


def _celda_con(tablas: list[Any], *claves: str, inicio: bool = False) -> str | None:
    """Texto de la primera celda que contiene (o empieza por) alguna clave."""
    for tabla in tablas:
        for fila in tabla:
            for celda in fila:
                texto = texto_celda(celda)
                if not texto:
                    continue
                plano = " ".join(texto.split())
                for clave in claves:
                    if plano.lower().startswith(clave.lower()) if inicio else clave.lower() in plano.lower():
                        return texto
    return None


def _campo(words: list[dict[str, Any]], label: str, **kw: Any) -> str | None:
    """Valor de una etiqueta buscada por coordenadas (respaldo del formulario)."""
    return limpiar(find_value(words, label, **kw))


def _lineas(bloque: str | None) -> list[str]:
    """Líneas de un bloque multilínea del formulario."""
    return [linea.strip() for linea in (bloque or "").split("\n") if linea.strip()]



# Sub-etiquetas dentro de un bloque de contacto (proveedor / forwarder).
_SUBLABELS_LINEA = tuple(
    f"{pref}:" for pref in (
        "Name", "Contact", "Email", "Correo", "Phone", "Direct", "Fax", "Office", "Address",
    )
)


def _es_subetiqueta(linea: str) -> bool:
    """¿La línea empieza con una sub-etiqueta del bloque ("Contact:", "Email:", …)?"""
    return any(linea.upper().startswith(pref.upper()) for pref in _SUBLABELS_LINEA)


def _nombre_bloque(bloque: str | None) -> str | None:
    """Nombre del bloque: lo que sigue a ``Name:`` o la primera línea útil.

    En el bloque del proveedor el nombre va suelto en la primera línea; en el del
    forwarder viene como ``Name: MAGNUM FREIGHT``.
    """
    for linea in _lineas(bloque):
        match = re.match(r"^Name\s*:?\s*(.+)$", linea, re.IGNORECASE)
        if match:
            return limpiar(match.group(1))
    for linea in _lineas(bloque):
        if not _es_subetiqueta(linea):
            return limpiar(re.sub(r"^(?:Attn|ATT)\s*:?\s*", "", linea))
    return None


def _parte_bloque(bloque: str | None, etiqueta: str) -> str | None:
    """Valor de una sub-etiqueta dentro de un bloque multilínea.

    El valor puede continuar en las líneas siguientes (direcciones); se corta al
    topar con otra sub-etiqueta.
    """
    lineas = _lineas(bloque)
    patron = re.compile(rf"^{etiqueta}\s*:?\s*(.*)$", re.IGNORECASE)
    for indice, linea in enumerate(lineas):
        match = patron.match(linea)
        if not match:
            continue
        partes = [match.group(1).strip()]
        for siguiente in lineas[indice + 1:]:
            if _es_subetiqueta(siguiente):
                break
            partes.append(siguiente)
        return limpiar(" ".join(parte for parte in partes if parte))
    return None


def _con_email(texto: str | None) -> str | None:
    """Correo dentro de un texto ('Email:Sales Juan <j@x.com>' -> 'j@x.com')."""
    match = _EMAIL_RE.search(texto or "")
    return match.group(0) if match else None


def _ultimo_monto(texto: str, patron: str) -> str | None:
    """Último monto del texto que cumple el patrón (el TOTAL va al final)."""
    montos = re.findall(patron, texto, re.IGNORECASE)
    return num(montos[-1]) if montos else None


def _aprobado(texto: str) -> str | None:
    """Quién firma la PO ('GENERAL MANAGER', 'FINANCE MANAGER', …)."""
    for linea in texto.splitlines():
        match = re.search(r"APPROVED\s+BY\s*[-:]?\s*(.*)$", linea, re.IGNORECASE)
        if match and limpiar(match.group(1)):
            return limpiar(match.group(1))
    return None


def _datos_billing(tablas: list[Any], words: list[dict[str, Any]]) -> dict[str, str | None]:
    """Razón social, RUC y dirección de Air Majoro (columna izquierda del formulario).

    La dirección viene **repartida** en varias celdas de esa columna (una por
    renglón del PDF), así que se recogen en orden las líneas de la columna 0 que
    están por encima de la tabla de ítems.
    """
    celda_emp = _celda_con(tablas, "Billing Adress", "Billing Address")
    empresa = None
    if celda_emp:
        empresa = limpiar(re.sub(r"^Billing\s+\w+\s*:?\s*", "", celda_emp, flags=re.I))
    ruc = None
    partes: list[str] = []
    for tabla in tablas[:1]:  # solo el formulario (la tabla de ítems puede ir aparte)
        for fila in tabla:
            if not fila or _es_tabla_items(fila):
                break
            celda = texto_celda(fila[0])
            if not celda:
                continue
            if "@" in celda or celda.lower().startswith("phone:"):
                continue  # bloque de contactos de Air Majoro
            if re.match(r"(?i)^Ruc\b", celda):
                lineas = _lineas(celda)
                ruc = limpiar(re.sub(r"(?i)^Ruc\s*:?\s*", "", lineas[0]))
                partes.extend(lineas[1:])
                continue
            if re.match(r"(?i)^Billing\b", celda) or not celda[0].isalpha():
                continue
            partes.extend(_lineas(celda))
    return {
        "billing_company": empresa,
        "ruc": ruc,
        "billing_address": " | ".join(partes) or None,
        "billing_contact": " | ".join(_lineas(_celda_con(tablas, "@airmajoro.com"))) or None,
    }



def _header(
    palabras: list[list[dict[str, Any]]],
    paginas_tablas: list[Any],
    texto: str,
    source_file: str,
) -> dict[str, Any]:
    """Cabecera de una PO: los campos del formulario, tal como están en el PDF."""
    tablas = paginas_tablas[0] if paginas_tablas else []
    words = palabras[0] if palabras else []
    pares = _pares_formulario(tablas)
    plano = " ".join(texto.split())
    titulo = _PO_TITULO_RE.search(texto)
    numero = _PO_NUM_RE.search(plano)
    # La fecha puede estar a la derecha de su etiqueta o en otro renglón (layout
    # desplazado): primero el campo del formulario y, si no, el texto.
    fecha_raw = limpiar(pares.get("DATE"))
    if fecha_raw is None:
        encontrada = re.search(r"\b(\d{1,2}-[A-Za-z]{3}-\d{2,4})\b", plano)
        fecha_raw = encontrada.group(1) if encontrada else None
    moneda = re.search(r"\b(USD|EUR|PEN)\b", plano.upper())

    def campo(etiqueta: str, **kw: Any) -> str | None:
        """Campo del formulario: primero la tabla, si no, por coordenadas."""
        canon = norm_label(etiqueta).rstrip(":").replace("°", "").strip()
        if canon in pares:
            return limpiar(pares[canon])
        return _campo(words, etiqueta, **kw)

    bloque_sup = pares.get("SUPPLIER")
    if bloque_sup is None:
        bloque_sup = _campo(words, "Supplier", misma_linea=False, below=30.0)
    bloque_env = _celda_con(tablas, "Name:", inicio=True)
    if bloque_env is None:
        pos = label_pos(words, "Shipping Address")
        if pos is not None:
            bloque_env = _campo(words, "Name", top_min=pos["top"] - 2, top_max=pos["top"] + 60)

    return {
        "source_file": source_file,
        "po_type": titulo.group(1).upper() if titulo else None,
        "po_number": limpiar(numero.group(1)) if numero else None,
        "po_date": iso_from_text(fecha_raw),
        "po_date_raw": fecha_raw,
        **_datos_billing(tablas, words),
        "supplier": _nombre_bloque(bloque_sup),
        "supplier_contact": _parte_bloque(bloque_sup, "Contact"),
        "supplier_email": _con_email(_parte_bloque(bloque_sup, "Email"))
        or _con_email(bloque_sup),
        "supplier_phone": _parte_bloque(bloque_sup, "Phone"),
        "supplier_address": _parte_bloque(bloque_sup, "Address"),
        "order_type": campo("Order Type"),
        "payment_terms": campo("Payment Terms"),
        "delivery_terms": campo("Delivery Terms"),
        "category": campo("Category"),
        "lead_time": campo("Lead time"),
        "quote": campo("Quote"),
        "shipping_name": _nombre_bloque(bloque_env),
        "shipping_contact": _parte_bloque(bloque_env, "Contact"),
        "shipping_email": _con_email(_parte_bloque(bloque_env, "Email"))
        or _con_email(bloque_env),
        "shipping_phone": _parte_bloque(bloque_env, "Phone"),
        "shipping_address": _parte_bloque(bloque_env, "Address"),
        "buyer": campo("Buyer"),
        "pages": campo("Pages N"),
        "currency": moneda.group(1).upper() if moneda else None,
        "subtotal": _ultimo_monto(plano, r"SUB\s*TOTAL\s*\$?\s*([\d.,]+)"),
        "shipping_handling": _ultimo_monto(
            plano, r"SHIPPING\s*&\s*HANDL\w*\s*\$?\s*([\d.,]+)"
        ),
        "tax": limpiar((re.search(r"\bTAX\s*([\d]{1,2}\s*%)", plano) or [None, None])[1]),
        "total": _ultimo_monto(plano, r"TOTAL\s*\$?\s*([\d.,]+)"),
        "remarks": re.search(r"Remarks:\s*(.+?)(?:\s+\d+\.-|$)", plano).group(1)
        if re.search(r"Remarks:\s*(.+?)(?:\s+\d+\.-|$)", plano)
        else None,
        "approved_by": _aprobado(texto),
    }


def parse_pdf(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cabecera y detalles de **una** orden de compra (1 PDF).

    El ``source_file`` lleva la **carpeta** delante (``'JETSET/xxx.pdf'``): es la
    carpeta la que dice **de qué proveedor** es la orden (una carpeta = un proveedor,
    igual que en las facturas) y además evita que dos PDF con el mismo nombre en
    subcarpetas distintas mezclen sus ítems (la cabecera y los detalles se cruzan por
    ``source_file``).
    """
    paginas = read_pages(path)
    palabras = read_words(path)
    tablas = read_tables(path)
    texto = "\n".join(paginas)
    source_file = f"{path.parent.name}/{path.name}"
    return _header(palabras, tablas, texto, source_file), _items(tablas, source_file)


def es_po(path: Path) -> bool:
    """¿El PDF es una orden de compra / reparación de Air Majoro?"""
    return bool(_PO_TITULO_RE.search("\n".join(read_pages(path))))


def parse(carpeta: Path) -> dict[str, list[dict[str, Any]]]:
    """Todas las POs de ``carpeta`` (recursivo: seis subcarpetas de proveedor).

    Se procesa **un parser para todas** porque las seis subcarpetas usan el mismo
    diseño; los PDF que no son órdenes (adjuntos sueltos o facturas mal ubicadas)
    se ignoran.
    """
    cabeceras: list[dict[str, Any]] = []
    detalles: list[dict[str, Any]] = []
    for pdf in sorted(Path(carpeta).rglob("*.pdf")):
        if not es_po(pdf):
            continue
        cabecera, filas = parse_pdf(pdf)
        cabeceras.append(cabecera)
        detalles.extend(filas)
    return {"header": cabeceras, "details": detalles}

