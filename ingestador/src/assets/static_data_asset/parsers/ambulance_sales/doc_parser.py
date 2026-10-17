"""Parseo del campo ``factura`` del libro VENTAS (hoja "VUELOS B200 2026").

Cada vuelo trae 1 o 2 facturas escritas de formas muy irregulares en el Excel:

    F001-4791    F001-4792        -> dos documentos separados por espacios
    F001-4884 y F001-4885         -> dos documentos separados por 'Y'/'y'
    F001-4941- F001-4983          -> separador '- ' (guion + espacio)
    F001-5102-5103                -> serie compartida (F001-5102 y F001-5103)
    F001 4880 Y F001-4881         -> serie y numero partidos por espacio
    F0014897                      -> serie + numero concatenados (sin guion)

Antes esto se resolvía en dbt (``macros/parse_factura.sql``). Ahora se calcula al
ingerir el Excel y se guarda en la tabla ``ambulancia_ventas_reports`` como una
sola columna:

    * ``agregado_factura`` -> array JSON con **todas** las facturas del vuelo
      (``'["F001-4791","F001-4792"]'``; ``[]`` si la celda viene vacía).

La lógica reproduce la de las macros de dbt (limpieza, lista canónica
"SERIE-NUM[,SERIE-NUM]" y separación de documentos) para no cambiar resultados.
"""
from __future__ import annotations

import re

# Corridas de 2+ espacios -> uno solo.
_MULTI_SPACE = re.compile(r" {2,}")
# Numero de documento: solo digitos ASCII (equivalente a NOT GLOB '*[^0-9]*').
_DIGITS = re.compile(r"[0-9]+")
# Digitos iniciales de un texto (equivalente a CAST(x AS INTEGER) de SQLite).
_LEADING_INT = re.compile(r"\s*([+-]?[0-9]+)")

_DOC_SEP = ","


def _clean_factura(raw: object) -> str:
    """Mayusculas + trim + espacios colapsados y separadores ' Y ' / '- ' a ' '."""
    texto = "" if raw is None else str(raw)
    return _MULTI_SPACE.sub(" ", texto.strip().upper()).replace(" Y ", " ").replace(
        "- ", " "
    )


def _shared_serie(f: str) -> str:
    """Caso serie compartida: ``'F001-5102-5103'`` -> ``'F001-5102,F001-5103'``."""
    corte = f.index("-")
    serie, resto = f[:corte], f[corte + 1 :]
    corte2 = resto.index("-")
    return f"{serie}-{resto[:corte2]},{serie}-{resto[corte2 + 1 :]}"


def _space_case(f: str) -> str:
    """Caso con espacios: documentos separados por uno o más espacios.

    Si el primer token es una serie (sin guion) y el segundo es numérico, se
    juntan como ``SERIE-NUM`` (``'F001 4880 F001-4881'`` -> ``'F001-4880,F001-4881'``);
    si no, los espacios se cambian por comas.
    """
    corte = f.index(" ")
    first, rafter = f[:corte], f[corte + 1 :]
    corte2 = rafter.find(" ")
    second = rafter if corte2 == -1 else rafter[:corte2]
    if "-" not in first and _DIGITS.fullmatch(second):
        return first + "-" + second + rafter[len(second) :].replace(" ", _DOC_SEP)
    return f.replace(" ", _DOC_SEP)


def _canonical(f: str) -> str:
    """Lista canónica ``"SERIE-NUM[,SERIE-NUM]"``; ``''`` si viene vacío."""
    if f == "":
        return ""
    if " " in f:
        return _space_case(f)
    if f.count("-") == 2:
        return _shared_serie(f)
    if f.count("-") == 0 and len(f) > 4:
        return f[:4] + "-" + f[4:]
    return f


def _sqlite_cast_int(texto: str) -> int:
    """Replica ``CAST(texto AS INTEGER)`` de SQLite (dígitos iniciales; si no, 0)."""
    match = _LEADING_INT.match(texto)
    return int(match.group(1)) if match else 0


def split_documento(doc: str | None) -> tuple[str | None, int | None]:
    """Parte un documento ``"SERIE-NUM"`` en ``(serie, numero)``.

    Devuelve ``(None, None)`` si no hay documento o no trae guion (igual que las
    macros ``factura_serie``/``factura_num``).
    """
    if not doc or "-" not in doc:
        return None, None
    serie, _, numero = doc.partition("-")
    return serie, _sqlite_cast_int(numero)


def _normalizar_doc(doc: str) -> str:
    """Deja el documento como ``SERIE-NUM`` (limpia el caso del separador '- ')."""
    serie, numero = split_documento(doc)
    if serie is not None and numero is not None:
        return f"{serie}-{numero}"
    return doc


def parse_factura(raw: object) -> tuple[str | None, str | None]:
    """``(primera, otras)`` de un ``factura`` crudo.

    ``primera`` es el 1er documento como "SERIE-NUM" (``''`` si no hay factura) y
    ``otras`` el resto (2º documento y siguientes, ``None`` si solo hay uno).
    """
    clist = _canonical(_clean_factura(raw))
    if clist == "":
        return "", None
    if _DOC_SEP in clist:
        primera, otras = clist.split(_DOC_SEP, 1)
    else:
        primera, otras = clist, None
    return _normalizar_doc(primera), otras


def parse_factura_list(raw: object) -> list[str]:
    """Lista ordenada de facturas (``SERIE-NUM``) de un ``factura`` crudo.

    Devuelve ``[]`` si la celda viene vacía (igual que ``parse_factura`` devuelve
    ``('', None)``).
    """
    clist = _canonical(_clean_factura(raw))
    if clist == "":
        return []
    return [_normalizar_doc(doc) for doc in clist.split(_DOC_SEP)]


def parse_factura_fields(raw: object) -> dict[str, object]:
    """Columna derivada de ``factura`` para ``ambulancia_ventas_reports``."""
    return {"agregado_factura": parse_factura_list(raw)}
