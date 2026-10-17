"""Parser de los reportes RH (comprobantes de renta) del SEE-SOL.

El reporte que devuelve ``accion=descargaConsultaReceptor`` es texto delimitado
por ``|`` con una fila de cabecera de **16 columnas**. La ``Descripción`` puede
traer saltos de línea embebidos, por lo que una fila lógica puede ocupar varias
líneas físicas. Para reconstruir los registros de forma robusta se marca el final
de cada línea (el ``|`` seguido de salto de línea) y se agrupan los tokens de a
**16 campos**.

El parser trabaja sobre **texto** (no sobre la ruta de un archivo) porque su
único consumidor es ``RhResource``, que obtiene ese texto por HTTP.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from assets.utils import to_db_field

# Cantidad exacta de columnas de la cabecera del reporte RH.
N_FIELDS = 16

# Marcador interno de fin de registro (solo lo usa el parser).
_SENTINEL = "\x00"

# Columnas numéricas del reporte (se convierten a Decimal; vacío/'-' -> None).
_NUMERIC_FIELDS = {
    "renta_bruta",
    "impuesto_a_la_renta",
    "renta_neta",
    "monto_neto_pendiente_de_pago",
}


def _clean_text(value: Any) -> Any:
    """Limpia un valor de texto: strip y '' -> None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_decimal(value: Any) -> Any:
    """Convierte un campo numérico a Decimal (o None si viene vacío/'-')."""
    if value is None:
        return None
    text = str(value).strip()
    if text in ("", "-"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _parse_records(text: str) -> list[list[str]]:
    """Divide el texto en registros de ``N_FIELDS`` campos (cabecera incluida).

    Se normaliza ``\\r\\n`` -> ``\\n``, se marca el fin de cada línea (``|\\n`` ->
    ``|\\x00``) y se divide por ``|``. El marcador ``\\x00`` (fin de registro) queda
    pegado al inicio del primer campo del registro siguiente y se elimina de cada
    token; el resto se agrupa de a ``N_FIELDS``. Así los saltos de línea embebidos
    dentro de la ``Descripción`` no rompen el registro.
    """
    norm = text.replace("\r\n", "\n").replace("|\n", f"|{_SENTINEL}")
    # El marcador de fin de registro queda pegado al inicio del primer campo del
    # registro siguiente; se elimina de cada token. Como un registro siempre tiene
    # exactamente N_FIELDS campos, el agrupamiento no se desalinea.
    tokens = [t.replace(_SENTINEL, "") for t in norm.split("|")]
    registros: list[list[str]] = []
    for i in range(0, len(tokens), N_FIELDS):
        chunk = tokens[i : i + N_FIELDS]
        if len(chunk) == N_FIELDS:
            registros.append(chunk)
    return registros


def parse_rh_text(text: str) -> list[dict[str, Any]]:
    """Parsea el contenido de un reporte RH y devuelve las filas como dicts.

    La primera línea se toma como cabecera (claves normalizadas con
    ``to_db_field``); el resto son las filas de datos. Los campos numéricos se
    convierten a ``Decimal`` (o ``None`` si vienen vacíos o ``-``).
    """
    registros = _parse_records(text)
    if not registros:
        return []
    header = [to_db_field(col) for col in registros[0]]
    filas: list[dict[str, Any]] = []
    for registro in registros[1:]:
        fila: dict[str, Any] = {}
        for nombre, valor in zip(header, registro):
            if nombre in _NUMERIC_FIELDS:
                fila[nombre] = _to_decimal(valor)
            else:
                fila[nombre] = _clean_text(valor)
        filas.append(fila)
    return filas
