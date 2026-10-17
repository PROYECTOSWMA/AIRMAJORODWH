
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from assets.utils import to_db_field


def parse_csv(path: str | Path) -> list[dict[str, Any]]:
    """Devuelve las filas del CSV de ``path`` como dicts ``columna -> valor``.

    Las claves son las cabeceras normalizadas con ``to_db_field`` (deben coincidir
    con los campos del modelo peewee de la tabla) y los valores son texto, con
    ``""`` y celdas ausentes convertidas a ``None``.
    """
    with Path(path).open("r", encoding="utf-8-sig", newline="") as archivo:
        reader = csv.DictReader(archivo)
        header = [to_db_field(columna) for columna in (reader.fieldnames or [])]
        filas: list[dict[str, Any]] = []
        for registro in reader:
            fila: dict[str, Any] = {}
            for columna, valor in zip(header, registro.values()):
                if not columna:
                    continue
                fila[columna] = valor.strip() if isinstance(valor, str) else valor
                if fila[columna] == "":
                    fila[columna] = None
            filas.append(fila)
        return filas
