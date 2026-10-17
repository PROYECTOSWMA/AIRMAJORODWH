"""Utilidades compartidas de normalización de columnas a nivel de assets.

La normalización de nombres de columna a campos de BD (snake_case, sin acentos)
y de filas (headers + arrays -> dicts con valores limpios) la usan varios
assets (p. ej. las propuestas SIRE y el flujo SISA), así que vive aquí, al
nivel de ``assets``, en lugar de duplicada en cada recurso.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def to_db_field(name: str) -> str:
    """Normaliza el nombre de una columna a un campo de BD (snake_case).

    Ej.: ``"CAR SUNAT"`` -> ``"car_sunat"``, ``"Fecha de emision"`` -> ``"fecha_de_emision"``.
    """
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w]+", "_", text.strip().lower())
    return text.strip("_")


def normalize_rows(
    columns: list[str],
    rows: list[list[Any]],
) -> list[dict[str, Any]]:
    """Convierte columnas + filas en arrays a dicts con claves snake_case.

    Cada fila se mapea contra ``columns`` normalizadas con ``to_db_field``; los
    valores ``str`` se limpian (strip) y los vacíos se convierten a ``None``.
    Si una fila trae menos valores que columnas, las claves que faltan se omiten
    (el modelo pydantic las deja en ``None``); si trae más, los sobrantes se
    ignoran.
    """
    header = [to_db_field(columna) for columna in columns]
    resultado: list[dict[str, Any]] = []
    for fila in rows:
        if not fila:
            continue
        resultado.append(
            {
                columna: (valor.strip() if isinstance(valor, str) else valor) or None
                for columna, valor in zip(header, fila)
                if columna
            }
        )
    return resultado


# Matrícula de las aeronaves de Air Majoro en su forma canónica: 'OB-1234'.
# Cubre los tecleos de los reportes manuales: '0B-2180' (el cero por la O),
# 'ob.2209', 'OB2221', 'OB 2200'...
_MATRICULA_OB = re.compile(r"^[0O]B[\-.\s]?(\d{3,4})$", re.IGNORECASE)
# Nº de documento/manifiesto de los reportes ('006-5575', '003-4560').
_DOCUMENTO = re.compile(r"^\d{2,4}-\d{3,4}$")


def normalize_matricula(value: Any) -> Any:
    """Deja la matrícula de una aeronave en su forma canónica ``'OB-1234'``.

    El centro de costo de las ventas sale de esta columna con la macro de dbt
    ``extract_cost_center``, que devuelve **los 4 caracteres siguientes al primer
    dígito**: con ``'OB-2180'`` da ``'2180'``, pero con un valor que empieza por
    dígito daba basura (``'0B-2180'`` -> ``'0B-2'``, ``'003-4560'`` -> ``'003-'``).

    Aquí se corrige el tecleo (el ``0`` por la ``O`` y los separadores de más) para
    que la matrícula sea siempre ``'OB-<número>'``. Si la celda **no** trae una
    matrícula sino un **nº de documento** (``'003-4560'``: el formato de la columna
    NRO, que alguien volcó en la columna de la aeronave) devuelve ``None``, para no
    inventar un centro de costo; cualquier otro texto (``'SAETA'``, ``'OIB-2200'``)
    se deja tal cual venía.
    """
    if not isinstance(value, str):
        return value
    texto = value.strip()
    matricula = _MATRICULA_OB.match(texto)
    if matricula:
        return f"OB-{matricula.group(1)}"
    if _DOCUMENTO.match(texto):
        return None
    return texto
