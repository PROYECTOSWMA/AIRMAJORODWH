"""Tests del parser del reporte de ambulancias (``parse_ambulancia_ventas``).

Cubre el defecto real de la hoja "VUELOS B200 2026": **debajo de la tabla hay otra
tabla** (el COSTO por hora de cada aeronave) y sus filas también tienen la columna A
con dato (``'HORAS'``, 60, 65, 70, 75, 80), así que el parser las leía como si fuesen
vuelos (6 filas basura, con la aeronave y la fecha corridas de columna). También fija
que la matrícula quede en su forma canónica ``'OB-1234'``.

Se corre además sobre el Excel real del repo, para fijar el contrato del asset
``static_data_asset``.
"""
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

from assets.static_data_asset.parsers.ambulance_sales.ambulance_sales_parser import (
    parse_ambulancia_ventas,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_XLSM_PATH = _REPO_ROOT / "static" / "VENTAS-C X C 2026_ACT 25-08-2026.xlsm"


def _libro(path: Path) -> None:
    """Hoja con la tabla de vuelos y, debajo, el bloque de COSTO (que NO es tabla)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "VUELOS B200 2026"
    ws.append(["CODIGO", "CLIENTE", "AERONAVE", "FECHA VLO", "FACTURA", "SOLES"])
    ws.append(
        ["15012026", "ESSALUD PUCALLPA", "OB2092", datetime(2026, 1, 15), "F001-4710", 8220]
    )
    ws.append(
        [
            "18012026",
            "SALUDPOL",
            "0B2209",
            datetime(2026, 1, 18),
            "F001-4728 y F001-4729",
            12000,
        ]
    )
    # --- de aquí para abajo, la OTRA tabla: la columna A no trae fechas ddmmaaaa.
    ws.append([None, None, None, None, None, None])
    ws.append([None, None, "COSTO", None, None, None])
    ws.append(["HORAS", "0B2104", "0B2209", "0B2092", None, None])
    ws.append([60, 2663, 2479, 2505, None, None])
    wb.save(path)


def test_solo_lee_las_filas_de_la_tabla(tmp_path):
    path = tmp_path / "amb.xlsx"
    _libro(path)

    filas = parse_ambulancia_ventas(path)

    # El bloque de COSTO de abajo ('HORAS', 60) no entra.
    assert [f["codigo"] for f in filas] == ["15012026", "18012026"]
    # Matrículas canónicas: 'OB2092' y '0B2209' -> 'OB-2092' / 'OB-2209'.
    assert [f["aeronave"] for f in filas] == ["OB-2092", "OB-2209"]
    # La columna derivada sigue calculándose (2ª factura del vuelo).
    assert filas[1]["agregado_factura"] == ["F001-4728", "F001-4729"]


@pytest.mark.skipif(not _XLSM_PATH.is_file(), reason="falta el Excel estático")
def test_sobre_archivo_real():
    filas = parse_ambulancia_ventas(_XLSM_PATH)

    # 431 vuelos: las filas 2..538 menos el bloque de COSTO por hora del final.
    assert len(filas) == 431
    assert all(len(str(f["codigo"])) == 8 and str(f["codigo"]).isdigit() for f in filas)
    assert {f["aeronave"] for f in filas} == {"OB-2092", "OB-2104", "OB-2209", "OB-2221"}
