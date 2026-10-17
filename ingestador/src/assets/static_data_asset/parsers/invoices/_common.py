"""Utilidades comunes de los parsers de facturas y órdenes de compra del exterior.

Todo lo de aquí es **puro** (strings, listas de palabras y ``Path`` de PDF): no hay
I/O de red ni estado global. Lo comparten los siete parsers de
``static/INVOICE INTERNACIONALES`` (las seis facturas de proveedor y el de
órdenes de compra).

Los PDF traen texto nativo (no hay OCR). Los parsers leen **dos capas**:

* el **texto por líneas** (``read_pages``) para los formatos de software ajeno
  (Quantum Control, PENTAGON, Fenix, Kal, Textron), que son columnas separadas
  por espacios y se resuelven con expresiones regulares; y
* las **palabras con coordenadas** (``read_words`` / ``find_value``) para los
  formularios de Air Majoro (las órdenes de compra), donde no se puede confiar en
  el orden de las líneas porque la página tiene dos columnas.

Convenciones (compartidas con el resto de ``static_data_asset``):

* todos los valores se guardan como **texto** (los modelos son ``CharField``);
* los **montos** se normalizan a un número plano (``1.234,56`` y ``1234.56`` dan
  ``1234.56``) y se guardan sin símbolo de moneda (la moneda tiene su columna);
* las **fechas** se normalizan a ISO (``AAAA-MM-DD``) cuando se pueden leer;
* cada fila lleva el ``source_file`` (y, en los detalles, la ``page``) para poder
  revisar el PDF original a mano.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pdfplumber


class InvoiceIntlParseError(Exception):
    """Un PDF de la carpeta no se pudo abrir o parsear."""


# --------------------------------------------------------------------------- #
# Montos
# --------------------------------------------------------------------------- #

def dec(raw: object) -> Decimal | None:
    """Convierte un monto en texto a ``Decimal`` aceptando formato US y europeo.

    * ``1,193.00`` -> 1193.00  (coma de miles, punto decimal)
    * ``1.872,16`` -> 1872.16  (punto de miles, coma decimal)
    * ``450,00``   -> 450.00   (coma decimal)
    * ``888.34``   -> 888.34
    """
    if raw is None:
        return None
    texto = str(raw).replace("$", "").replace(" ", "").strip()
    if not texto:
        return None
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        entero, _, decimales = texto.rpartition(",")
        if len(decimales) == 2 and entero:
            texto = f"{entero}.{decimales}"
        else:
            texto = texto.replace(",", "")
    # Quita lo que no sea dígito, signo o punto (p. ej. 'USD', 'EA').
    texto = re.sub(r"[^0-9.\-]", "", texto)
    if not texto or texto in {"-", "."}:
        return None
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def num(raw: object) -> str | None:
    """``Decimal``/texto de monto -> cadena para un ``CharField`` (o ``None``)."""
    if isinstance(raw, Decimal):
        return f"{raw:f}"
    valor = dec(raw)
    return None if valor is None else f"{valor:f}"


def limpiar(raw: object) -> str | None:
    """Texto de una celda a ``str`` de una línea, o ``None`` si queda vacío."""
    if raw is None:
        return None
    texto = " ".join(str(raw).split())
    return texto or None


def texto_celda(celda: object) -> str | None:
    """Como ``limpiar`` pero **conservando** los saltos de línea internos.

    Los bloques del formulario (proveedor, forwarder, dirección) son una sola
    celda con varias líneas: aquí importa no aplanarlas.
    """
    if celda is None:
        return None
    lineas = [linea.strip() for linea in str(celda).splitlines()]
    texto = "\n".join(linea for linea in lineas if linea)
    return texto or None


def valor(raw: object) -> str | None:
    """Texto de un campo, tratando como vacío el literal ``NULL`` de algunos PDFs."""
    texto = texto_celda(raw)
    if texto is None or texto.upper() in {"NULL", "N/A"}:
        return None
    return texto

# --------------------------------------------------------------------------- #
# Fechas
# --------------------------------------------------------------------------- #

_MONTHS = {
    "ENE": "01", "FEB": "02", "MAR": "03", "ABR": "04", "MAY": "05", "JUN": "06",
    "JUL": "07", "AGO": "08", "SET": "09", "OCT": "10", "NOV": "11", "DIC": "12",
    "JAN": "01", "APR": "04", "AUG": "08", "SEP": "09", "DEC": "12",
}
_MONTHS_LONG = {
    "JANUARY": "01", "FEBRUARY": "02", "MARCH": "03", "APRIL": "04", "MAY": "05",
    "JUNE": "06", "JULY": "07", "AUGUST": "08", "SEPTEMBER": "09", "OCTOBER": "10",
    "NOVEMBER": "11", "DECEMBER": "12",
    "ENERO": "01", "FEBRERO": "02", "MARZO": "03", "ABRIL": "04", "MAYO": "05",
    "JUNIO": "06", "JULIO": "07", "AGOSTO": "08", "SETIEMBRE": "09",
    "SEPTIEMBRE": "09", "OCTUBRE": "10", "NOVIEMBRE": "11", "DICIEMBRE": "12",
}

# Rango de años aceptado (igual que la macro `normalize_date` del DWH).
YEAR_MIN, YEAR_MAX = 1900, 2030


def month_number(name: object) -> str | None:
    """Mes a dos dígitos: ``'FEB'``/``'February'``/``'SET'`` -> ``'02'``/``'09'``."""
    if not name:
        return None
    clave = str(name).strip().upper()
    return _MONTHS.get(clave[:3]) or _MONTHS_LONG.get(clave)


def iso(year: object, month: object, day: object) -> str | None:
    """``(2026, '04', 3)`` -> ``'2026-04-03'``; ``None`` si la fecha no es válida."""
    try:
        anio, mes, dia = int(str(year)), int(str(month)), int(str(day))
    except (TypeError, ValueError):
        return None
    if not (YEAR_MIN <= anio <= YEAR_MAX):
        return None
    if not (1 <= mes <= 12 and 1 <= dia <= 31):
        return None
    return f"{anio:04d}-{mes:02d}-{dia:02d}"


def iso_from_slash(raw: object, day_first: bool = False) -> str | None:
    """``m/d/aa`` o ``m/d/aaaa`` (formato US) a ISO; ``d/m/aa`` si ``day_first``.

    OJO con el orden: por defecto es el de **EE.UU.** (mes/día/año), así que
    ``'03/26/26'`` es el **26 de marzo** (no el 3 de junio). Antes estaba invertido:
    las fechas con día > 12 quedaban en ``None`` (`mes=26` es inválido) y las de día
    ≤ 12 salían **con el mes y el día cambiados** (doc_date en el mes equivocado).
    """
    if not raw:
        return None
    match = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})\s*$", str(raw))
    if not match:
        return None
    a, b, anio = (int(x) for x in match.groups())
    if anio < 100:
        anio += 2000
    dia, mes = (a, b) if day_first else (b, a)
    return iso(anio, mes, dia)


def iso_from_text(raw: object) -> str | None:
    """Fecha en texto a ISO: ``'FEBRUARY 4, 2026'``, ``'15-Ene-26'``, ``'02/02/26'``,
    ``'Feb-04-2026'``.

    Es un *best effort*: si no reconoce el formato devuelve ``None`` (nunca
    inventa una fecha).
    """
    if not raw:
        return None
    texto = str(raw).strip()
    match = re.match(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$", texto)
    if match:
        return iso(match.group(3), month_number(match.group(1)), match.group(2))
    match = re.match(r"^(\d{1,2})[-/\s]([A-Za-z]{3})[a-z]*[-/\s](\d{2,4})$", texto)
    if match:
        anio = int(match.group(3))
        if anio < 100:
            anio += 2000
        return iso(anio, month_number(match.group(2)), match.group(1))
    # Mes primero, separado por guion o barra: 'Feb-04-2026' (Precision/PAG). Es el
    # formato de EE.UU. escrito al revés que el patrón anterior ('02-Feb-2026').
    match = re.match(r"^([A-Za-z]{3})[a-z]*[-/](\d{1,2})[-/](\d{2,4})$", texto)
    if match:
        anio = int(match.group(3))
        if anio < 100:
            anio += 2000
        return iso(anio, month_number(match.group(1)), match.group(2))
    return iso_from_slash(texto)


# --------------------------------------------------------------------------- #
# Lectura de PDFs
# --------------------------------------------------------------------------- #

def read_pages(path: Path) -> list[str]:
    """Texto de cada página del PDF (lista vacía si el PDF no tiene páginas)."""
    try:
        with pdfplumber.open(path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception as exc:  # PDF corrupto / no es PDF
        raise InvoiceIntlParseError(f"no se pudo abrir el PDF: {exc}") from exc


def read_words(path: Path) -> list[list[dict[str, Any]]]:
    """Palabras con coordenadas de cada página (``x0``, ``x1``, ``top``, ``text``)."""
    try:
        with pdfplumber.open(path) as pdf:
            return [page.extract_words() for page in pdf.pages]
    except Exception as exc:
        raise InvoiceIntlParseError(f"no se pudo abrir el PDF: {exc}") from exc



def read_tables(path: Path) -> list[list[list[list[str | None]]]]:
    """Tablas de cada página (grid de celdas tal como lo ve pdfplumber)."""
    try:
        with pdfplumber.open(path) as pdf:
            return [page.extract_tables() for page in pdf.pages]
    except Exception as exc:
        raise InvoiceIntlParseError(f"no se pudo abrir el PDF: {exc}") from exc


# --------------------------------------------------------------------------- #
# Palabras, etiquetas y bloques
# --------------------------------------------------------------------------- #

def norm_token(texto: object) -> str:
    """Token comparable: mayúsculas y solo letras/números/``/``."""
    return re.sub(r"[^A-Z0-9/]+", "", str(texto or "").upper())


def norm_label(texto: object) -> str:
    """Etiqueta comparable: una línea, mayúsculas, espacios simples."""
    return " ".join(str(texto or "").split()).upper()


def label_pos(
    words: list[dict[str, Any]],
    label: str,
    *,
    x_min: float | None = None,
    x_max: float | None = None,
    top_min: float | None = None,
    top_max: float | None = None,
) -> dict[str, Any] | None:
    """Primera palabra de una etiqueta (``None`` si no está en la página).

    Se usa para localizar el **bloque** al que pertenece un campo: p. ej. el
    ``Contact`` del proveedor está por encima del ``Contact`` del forwarder.
    """
    tokens = [norm_token(t) for t in label.split()]
    if not tokens:
        return None
    seq = [norm_token(w["text"]) for w in words]
    for i in range(len(seq) - len(tokens) + 1):
        if seq[i : i + len(tokens)] != tokens:
            continue
        first = words[i]
        if x_min is not None and first["x0"] < x_min:
            continue
        if x_max is not None and first["x1"] > x_max:
            continue
        if top_min is not None and first["top"] < top_min:
            continue
        if top_max is not None and first["top"] > top_max:
            continue
        return first
    return None


def find_value(
    words: list[dict[str, Any]],
    label: str,
    *,
    tol: float = 3.5,
    below: float = 0.0,
    x_min: float | None = None,
    x_max: float | None = None,
    top_min: float | None = None,
    top_max: float | None = None,
    valor_x_min: float | None = None,
    valor_x_max: float | None = None,
    misma_linea: bool = True,
    above: float = 0.0,
) -> str | None:
    """Valor de un campo de formulario, buscando la etiqueta por coordenadas.

    Primero toma lo que está **a la derecha en la misma línea** y, si no hay
    nada, lo que está **justo debajo** en la misma columna (p. ej. la fecha de una
    orden de compra, que a veces cae en otro renglón). ``x_min``/``x_max`` y
    ``top_min``/``top_max`` acotan dónde está la **etiqueta**; ``valor_x_min`` /
    ``valor_x_max`` acotan dónde puede estar el **valor** (los formularios de las
    PO tienen tres columnas y el mismo renglón mezcla las tres). Con
    ``misma_linea=False`` se busca solo debajo de la etiqueta.
    """
    tokens = [norm_token(t) for t in label.split()]
    if not tokens:
        return None
    seq = [norm_token(w["text"]) for w in words]
    for i in range(len(seq) - len(tokens) + 1):
        if seq[i : i + len(tokens)] != tokens:
            continue
        first, last = words[i], words[i + len(tokens) - 1]
        if x_min is not None and first["x0"] < x_min:
            continue
        if x_max is not None and first["x1"] > x_max:
            continue
        if top_min is not None and first["top"] < top_min:
            continue
        if top_max is not None and first["top"] > top_max:
            continue
        if misma_linea:
            fila = [
                w for w in words
                if abs(w["top"] - first["top"]) <= tol and w["x0"] >= last["x1"] - 1.0
                and (valor_x_min is None or w["x0"] >= valor_x_min)
                and (valor_x_max is None or w["x0"] <= valor_x_max)
            ]
            if fila:
                fila.sort(key=lambda w: w["x0"])
                texto = " ".join(w["text"] for w in fila).strip()
                if texto:
                    return texto
        if below:
            debajo = [
                w for w in words
                if first["top"] < w["top"] <= first["top"] + below
                and w["x0"] >= first["x0"] - 2.0
                and (valor_x_min is None or w["x0"] >= valor_x_min)
                and (valor_x_max is None or w["x0"] <= valor_x_max)
            ]
            if debajo:
                debajo.sort(key=lambda w: (w["top"], w["x0"]))
                tope = debajo[0]["top"]
                texto = " ".join(
                    w["text"] for w in debajo if abs(w["top"] - tope) <= tol
                ).strip()
                if texto:
                    return texto
        if above:
            encima = [
                w for w in words
                if first["top"] - above <= w["top"] < first["top"]
                and w["x0"] >= first["x0"] - 2.0
                and (valor_x_min is None or w["x0"] >= valor_x_min)
                and (valor_x_max is None or w["x0"] <= valor_x_max)
            ]
            if encima:
                encima.sort(key=lambda w: (-w["top"], w["x0"]))
                tope = encima[0]["top"]
                texto = " ".join(
                    reversed([w["text"] for w in encima if abs(w["top"] - tope) <= tol])
                ).strip()
                if texto:
                    return texto
    return None


def block_value(
    words: list[dict[str, Any]],
    label: str,
    *,
    x_tol: float = 8.0,
    x_span: float = 220.0,
    y_span: float = 95.0,
    tol: float = 3.5,
) -> str | None:
    """Bloque de varias líneas (direcciones) a la derecha/debajo de ``label``.

    Devuelve las líneas que caen dentro de la banda horizontal de la etiqueta,
    unidas por ``' | '`` (una dirección ocupa varios renglones). **No** incluye la
    línea de la propia etiqueta, solo lo que viene debajo.
    """
    tokens = [norm_token(t) for t in label.split()]
    if not tokens:
        return None
    seq = [norm_token(w["text"]) for w in words]
    for i in range(len(seq) - len(tokens) + 1):
        if seq[i : i + len(tokens)] != tokens:
            continue
        first = words[i]
        y0 = first["top"] + tol
        dentro = [
            w for w in words
            if y0 < w["top"] <= y0 + y_span
            and first["x0"] - x_tol <= w["x0"] <= first["x0"] + x_span
        ]
        if not dentro:
            continue
        dentro.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
        lineas: list[str] = []
        actual: list[str] = []
        actual_top: float | None = None
        for w in dentro:
            if actual_top is None or abs(w["top"] - actual_top) <= tol:
                actual.append(w["text"])
                if actual_top is None:
                    actual_top = w["top"]
            else:
                lineas.append(" ".join(actual))
                actual = [w["text"]]
                actual_top = w["top"]
        if actual:
            lineas.append(" ".join(actual))
        return " | ".join(lineas) or None
    return None


# --------------------------------------------------------------------------- #
# Rejilla de una página (líneas visuales y celdas)
# --------------------------------------------------------------------------- #

def rejilla(
    words: list[dict[str, Any]],
    *,
    y_tol: float = 3.0,
    gap: float = 8.0,
) -> list[list[dict[str, Any]]]:
    """Como ``tabla_pagina`` pero cada celda lleva su ``texto``, ``x0`` y ``x1``.

    Guardar la x es lo que permite **alinear** la fila de datos con la fila de
    títulos cuando alguna columna va vacía (un hueco sin dato no ocupa celda).
    """
    ordenadas = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    lineas: list[list[dict[str, Any]]] = []
    for palabra in ordenadas:
        if lineas and abs(palabra["top"] - lineas[-1][0]["top"]) <= y_tol:
            lineas[-1].append(palabra)
        else:
            lineas.append([palabra])
    filas: list[list[dict[str, Any]]] = []
    for linea in lineas:
        linea = sorted(linea, key=lambda w: w["x0"])
        celdas: list[dict[str, Any]] = []
        actual: list[dict[str, Any]] = [linea[0]]
        for anterior, palabra in zip(linea, linea[1:]):
            if palabra["x0"] - anterior["x1"] > gap:
                celdas.append(_celda_coords(actual))
                actual = [palabra]
            else:
                actual.append(palabra)
        celdas.append(_celda_coords(actual))
        filas.append([celda for celda in celdas if celda["texto"]])
    return [fila for fila in filas if fila]


def _celda_coords(palabras: list[dict[str, Any]]) -> dict[str, Any]:
    """Celda a partir de sus palabras (texto y rango horizontal)."""
    return {
        "texto": " ".join(w["text"] for w in palabras).strip(),
        "x0": min(w["x0"] for w in palabras),
        "x1": max(w["x1"] for w in palabras),
    }


def cabecera_y_datos(
    filas: list[list[dict[str, Any]]],
    etiquetas: tuple[str, ...],
    *,
    minimo: int = 3,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Localiza la fila de títulos que contiene ``etiquetas`` y devuelve sus datos.

    Devuelve ``(fila_de_titulos, filas_siguientes_alineadas)``. Las filas de datos
    se alinean por **x** con los títulos, así que una columna vacía no desplaza
    las demás (con ``alinear_x``).
    """
    for indice, fila in enumerate(filas):
        textos = " ".join(celda["texto"].upper() for celda in fila)
        if sum(1 for etiqueta in etiquetas if etiqueta.upper() in textos) >= minimo:
            titulos = fila
            datos = [alinear_x(titulos, siguiente) for siguiente in filas[indice + 1:]]
            return titulos, datos
    return [], []


def alinear_x(
    titulos: list[dict[str, Any]], celdas: list[dict[str, Any]]
) -> dict[str, str]:
    """Reparte cada celda en la columna de ``titulos`` cuya x se solapa.

    La celda se asigna a la columna con **mayor solapamiento** horizontal y, si no
    solapa con ninguna (p. ej. el valor es más ancho que su título), a la más
    cercana. Devuelve ``{titulo: texto}``.
    """
    resultado: dict[str, str] = {}
    for celda in celdas:
        mejor, mejor_solape = None, 0.0
        for titulo in titulos:
            solape = min(celda["x1"], titulo["x1"]) - max(celda["x0"], titulo["x0"])
            if solape > mejor_solape:
                mejor, mejor_solape = titulo, solape
        if mejor is None:
            mejor = min(
                titulos,
                key=lambda t: abs((t["x0"] + t["x1"]) / 2 - (celda["x0"] + celda["x1"]) / 2),
            )
        texto = titulos[titulos.index(mejor)]["texto"]
        previo = resultado.get(texto)
        resultado[texto] = f"{previo} {celda['texto']}" if previo else celda["texto"]
    return resultado



def cell(row: list[str | None], index: int) -> str | None:
    """Celda ``index`` de una fila de tabla, en una línea y sin vacíos de sobra."""
    if index < 0 or index >= len(row):
        return None
    return limpiar(row[index])


def pares_tabla(tablas: list[Any], ancla: str) -> dict[str, str | None]:
    """``{etiqueta: valor}`` de una tabla con una fila de etiquetas.

    Busca la tabla cuya fila de etiquetas contiene ``ancla`` y empareja cada
    etiqueta con la celda de **la fila siguiente** en la misma columna. Lo usan las
    facturas que imprimen una fila de títulos y otra de valores (p. ej. Fenix:
    ``Requisitioner / Phone / Terms / AWB / Ship Date``).
    """
    clave = ancla.upper()
    for tabla in tablas:
        for indice, fila in enumerate(tabla):
            etiquetas = [limpiar(c) for c in fila]
            if not any(e and clave in e.upper() for e in etiquetas):
                continue
            if indice + 1 >= len(tabla):
                continue
            valores = tabla[indice + 1]
            pares: dict[str, str | None] = {}
            for columna, etiqueta in enumerate(etiquetas):
                if not etiqueta:
                    continue
                pares[norm_label(etiqueta)] = valor(
                    valores[columna] if columna < len(valores) else None
                )
            return pares
    return {}


