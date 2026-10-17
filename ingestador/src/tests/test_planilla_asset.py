"""Tests del parser de la planilla estática ``static/Planilla.ods``.

El parser se prueba directamente sobre el archivo estático real del repo. La
ingesta en sí (upsert de la partición) ahora la cubre el asset único
``static_data_asset`` (ver ``test_static_data_asset.py``).
"""
from decimal import Decimal
from pathlib import Path

from assets.static_data_asset.parsers.payroll import parse_planilla

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLANILLA_PATH = _REPO_ROOT / "static" / "Planilla.ods"


def test_parse_planilla_sobre_archivo_real():
    filas = parse_planilla(_PLANILLA_PATH)

    f = filas[0]
    assert f["periodo"] == "2025"
    assert f["mes"] == "01"
    assert f["pivot"] == "01-2025"
    assert f["dni"] == "44111103"
    assert f["codigo"] == "1-0059"
    # Los acentos se conservan tal cual vienen en el ODS.
    assert f["nombre"] == "ACUÑA LAZO JOSE RICARDO"
    assert f["cargo"] == "Tripulante Técnico-Piloto"
    assert f["area"] == "ÁREA RESPONSABLE DE OPERA"
    assert f["remuner"] == Decimal("4142.35")
    assert f["tc"] == Decimal("3.728")
    assert f["dias"] == Decimal("30")
    # Montos con separador de miles a Decimal.
    assert f["sueldo"] == Decimal("4142.35")
    assert f["total_ingresos"] == Decimal("8251.18")
    assert f["total_dsctos"] == Decimal("1126.61")
    assert f["neto_a_pagar"] == Decimal("7124.57")
    # Celda vacía -> None.
    assert f["adelanto_de_sueldo"] is None


def test_parse_planilla_campos_numericos_vacios():
    filas = parse_planilla(_PLANILLA_PATH)
    # Columnas de concepto que pueden venir vacías en algunas filas.
    assert all("total_ingresos" in f for f in filas)
    # Algunos montos opcionales son None (no 0) cuando la celda está vacía.
    hay_none = any(f["adelanto_de_sueldo"] is None for f in filas)
    assert hay_none



