"""Contrato de la rama de ventas del reporte estático "1.- REPORTE DE VENTAS".

El libro estático se ingiere en la tabla ``sales_selva`` (asset ``static_data_asset``)
y ``dbt`` lo añade a ``sales_std``/``moves`` bajo la cuenta NUEVA ``704106``
(«VENTAS SELVA»), filtrando las cobranzas/pagos y sin duplicar documentos. Como no hay
framework de tests de dbt en pytest, aquí se fija el CONTRATO del pipeline:

* el maestro de cuentas tiene la cuenta ``704106 = VENTAS SELVA`` (y sus códigos son
  únicos);
* la rama ``selva_sales_std`` lee ``sales_selva``, deja la cuenta ``704106`` y excluye
  las filas de cobranzas/pagos;
* ``sales_std`` une la rama nueva.
"""
from pathlib import Path

from assets.static_data_asset.parsers.csv_static import parse_csv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DBT = _REPO_ROOT / "src" / "dbt" / "models"
_CUENTAS_CSV = _REPO_ROOT / "static" / "dwh_static_master_accounts.csv"


def _leer(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_maestro_de_cuentas_tiene_ventas_selva():
    cuentas = parse_csv(_CUENTAS_CSV)
    codigos = [c["codigo_pcge"] for c in cuentas]
    # La cuenta nueva es única (no choca con ninguna anterior), como pidió el negocio.
    assert codigos.count("704106") == 1

    ventas_selva = [c for c in cuentas if c["codigo_pcge"] == "704106"]
    assert ventas_selva[0]["cuenta"] == "VENTAS SELVA"
    assert ventas_selva[0]["grupo"] == "VENTAS"


def test_rama_selva_lee_sales_selva_y_filtra_cobranzas():
    sql = _leer(_DBT / "sales" / "from_reports" / "selva_sales_std.sql")

    # Lee la tabla que llena la ingesta estática.
    assert "FROM sales_selva" in sql
    # Deja la cuenta nueva del maestro.
    assert "704106" in sql
    # Filtra las cobranzas/pagos (a nivel dbt, como pidió el negocio).
    assert "'COBRANZA', 'PP VENTAS', 'PP CARGA'" in sql
    # Deduplica documentos (una fila por serie+número).
    assert "PARTITION BY d.doc_serie, d.doc_number" in sql


def test_sales_std_une_la_rama_selva():
    sql = _leer(_DBT / "sales" / "sales_std.sql")
    assert "ref('selva_sales_std')" in sql
    # La rama de SELVA sigue siendo la última de la unión de ventas; lo que cambió
    # (2026-10-09) es que la unión va envuelta para poder añadir la columna 27 del
    # contrato, `appended_tipo_mantenimiento` (en ventas va NULL).
    ultima_rama = sql.rstrip().rsplit("UNION ALL", 1)[-1]
    assert "SELECT * FROM selva" in ultima_rama
    assert ultima_rama.rstrip().endswith(") AS ventas")
    assert "CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento" in sql
