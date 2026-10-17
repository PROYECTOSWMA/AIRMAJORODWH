"""Tests del asset único ``static_data_asset`` (fuentes estáticas).

Se prueba que el asset itera las specs de ``STATIC_SPECS``, **reemplaza cada tabla
completa** (snapshots) y vuelca los **CSV de referencia** de ``CSV_SPECS`` a sus
tablas de la BD. El asset **no** tiene particiones ni ``period``: el contexto no
aporta clave y los 3 modelos de los snapshots ya no declaran ``period``. Para no
depender de los binarios ni de los CSV reales de la carpeta ``static``, se reemplaza
``STATIC_DIR`` por un directorio temporal con archivos dummy y se inyectan
specs/parsers falsos y un resource de BD stub.

El reporte RH del SEE-SOL (``seesol_rh``) **ya no** pasa por aquí: lo ingiere
``seesol_rh_monthly`` (tests en ``test_seesol_rh_asset.py``).
"""
import pytest

from assets.static_data_asset.models.sales_selva import SalesSelva
from assets.static_data_asset.models.static_ambulance_sales import StaticAmbulanceSales
from assets.static_data_asset.models.static_lap_aeronave import StaticLapReports
from assets.static_data_asset.models.static_payroll import StaticPayroll
from assets.static_data_asset.static_data_asset import (
    static_data_asset,
)

_ASSET_FN = static_data_asset.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass


class _Ctx:
    """Contexto mínimo: sin particiones, solo el logger.

    A propósito **no** expone ``partition_key``: si el asset intentara leerlo, el
    test caería con ``AttributeError``.
    """

    def __init__(self):
        self.log = _Log()


class _Db:
    """Resource de BD stub: registra los reemplazos que pide el asset."""

    def __init__(self):
        self.replaces = []  # (model, rows) de snapshots y CSV

    def replace_all(self, model, rows):
        self.replaces.append((model, rows))
        return len(rows)


def _spec(tabla, patron):
    return {
        "tabla": tabla,
        "patron": patron,
        "parser": lambda path: [{"origen": tabla}],
        "model": f"model::{tabla}",
    }


def _static_dir(tmp_path, nombres=("VENTAS_2026.xlsm", "LAP_Aeronave.xlsx", "Planilla.ods")):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    for nombre in nombres:
        (static_dir / nombre).write_text("dummy", encoding="utf-8")
    return static_dir


@pytest.fixture(autouse=True)
def _sin_csv_specs(monkeypatch):
    """Por defecto los tests no tocan los CSV ni las facturas reales."""
    import assets.static_data_asset.static_data_asset as mod

    monkeypatch.setattr(mod, "CSV_SPECS", [])
    monkeypatch.setattr(mod, "INVOICE_SPECS", [])


def _spec_facturas(carpeta, parser):
    """Spec de una subcarpeta de facturas con sus DOS tablas (header/details)."""
    return {
        "carpeta": carpeta,
        "parser": parser,
        "tablas": (
            ("tabla_header", "model::header", "header"),
            ("tabla_details", "model::details", "details"),
        ),
    }


def test_el_asset_no_tiene_particiones_ni_periodo():
    # Decisión de diseño: sin RH aquí (tiene su propio asset mensual), el estático ya no
    # necesita partición anual ni la columna ``period`` en sus 4 snapshots.
    assert static_data_asset.partitions_def is None
    for modelo in (StaticAmbulanceSales, StaticLapReports, StaticPayroll, SalesSelva):
        assert not hasattr(modelo, "period"), modelo.__name__


def test_static_data_asset_reemplaza_los_snapshots_y_los_csv(tmp_path, monkeypatch):
    import assets.static_data_asset.static_data_asset as mod

    static_dir = _static_dir(tmp_path)
    specs = [
        _spec("ambulancia_ventas_reports", "VENTAS*"),
        _spec("lap_reports", "LAP*"),
        _spec("planilla", "Planilla*"),
    ]
    monkeypatch.setattr(mod, "STATIC_DIR", static_dir)
    monkeypatch.setattr(mod, "STATIC_SPECS", specs)

    db = _Db()

    out = _ASSET_FN(_Ctx(), db)

    # Cada snapshot reemplaza su tabla completa con su modelo y las filas del parser.
    assert [m for m, _ in db.replaces] == [
        "model::ambulancia_ventas_reports",
        "model::lap_reports",
        "model::planilla",
    ]
    assert db.replaces[0][1] == [{"origen": "ambulancia_ventas_reports"}]

    # El RH no se toca aquí (tiene su propio asset mensual).
    assert not hasattr(db, "rh_upserts")

    assert out.value == {
        "ambulancia_ventas_reports": 1,
        "lap_reports": 1,
        "planilla": 1,
    }
    # Sin partición no hay metadata de periodo.
    assert "period" not in out.metadata
    assert out.metadata["planilla_archivo"].text == "Planilla.ods"


def test_static_data_asset_falla_si_falta_un_archivo(tmp_path, monkeypatch):
    import assets.static_data_asset.static_data_asset as mod

    static_dir = _static_dir(tmp_path, nombres=("VENTAS_2026.xlsm",))

    monkeypatch.setattr(mod, "STATIC_DIR", static_dir)
    monkeypatch.setattr(mod, "STATIC_SPECS", [_spec("lap_reports", "LAP*")])

    try:
        _ASSET_FN(_Ctx(), _Db())
    except ValueError as exc:
        assert "LAP*" in str(exc)
    else:
        raise AssertionError("debería haber lanzado ValueError por archivo faltante")


def test_static_data_asset_vuelca_los_csv_de_referencia_a_la_bd(tmp_path, monkeypatch):
    """Cada ``CSV_SPECS`` se parsea del disco y reemplaza su tabla completa."""
    import assets.static_data_asset.static_data_asset as mod

    static_dir = _static_dir(tmp_path, nombres=("dwh_static_airplanes.csv",))
    (static_dir / "dwh_static_airplanes.csv").write_text(
        "registration,owner,passengers\n1919,RIBBAN HOLDING S.A.,6\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "STATIC_DIR", static_dir)
    monkeypatch.setattr(mod, "STATIC_SPECS", [])
    monkeypatch.setattr(
        mod,
        "CSV_SPECS",
        [{"tabla": "dwh_static_airplanes", "model": "model::airplanes"}],
    )

    db = _Db()
    out = _ASSET_FN(_Ctx(), db)

    assert db.replaces == [
        (
            "model::airplanes",
            [{"registration": "1919", "owner": "RIBBAN HOLDING S.A.", "passengers": "6"}],
        )
    ]
    # El resumen y la metadata llevan la tabla y el archivo del CSV (Dagster los
    # envuelve en MetadataValue, de ahí `.text` / `.value`).
    assert out.value["dwh_static_airplanes"] == 1
    assert out.metadata["dwh_static_airplanes_archivo"].text == "dwh_static_airplanes.csv"
    assert out.metadata["dwh_static_airplanes_rows_upserted"].value == 1


def test_static_data_asset_falla_si_falta_un_csv(tmp_path, monkeypatch):
    import assets.static_data_asset.static_data_asset as mod

    monkeypatch.setattr(mod, "STATIC_DIR", _static_dir(tmp_path, nombres=("VENTAS_2026.xlsm",)))
    monkeypatch.setattr(mod, "STATIC_SPECS", [])
    monkeypatch.setattr(
        mod,
        "CSV_SPECS",
        [{"tabla": "static_aux_airports", "model": "model::airports"}],
    )

    db = _Db()
    try:
        _ASSET_FN(_Ctx(), db)
    except FileNotFoundError as exc:
        assert "static_aux_airports.csv" in str(exc)
    else:
        raise AssertionError("debería haber lanzado FileNotFoundError por CSV faltante")
    assert db.replaces == []


def test_static_data_asset_spec_de_carpeta_llena_dos_tablas(tmp_path, monkeypatch):
    """Un spec de facturas recibe la carpeta y llena sus DOS tablas (cabecera y detalles)."""
    import assets.static_data_asset.static_data_asset as mod

    static_dir = _static_dir(tmp_path)
    carpeta = static_dir / "INVOICE INTERNACIONALES" / "FENIX AEROSPACE"
    carpeta.mkdir(parents=True)
    (carpeta / "factura.pdf").write_text("dummy", encoding="utf-8")

    visto: dict = {}

    def _parser(ruta):
        visto["ruta"] = ruta
        return {"header": [{"po_number": "825-2026"}], "details": [{"item": "1"}]}

    monkeypatch.setattr(mod, "STATIC_DIR", static_dir)
    monkeypatch.setattr(mod, "STATIC_SPECS", [])
    monkeypatch.setattr(
        mod,
        "INVOICE_SPECS",
        [_spec_facturas("INVOICE INTERNACIONALES/FENIX AEROSPACE", _parser)],
    )

    db = _Db()
    out = _ASSET_FN(_Ctx(), db)

    # El parser recibe la CARPETA (no un archivo) y reemplaza las DOS tablas.
    assert visto["ruta"] == carpeta
    assert db.replaces == [
        ("model::header", [{"po_number": "825-2026"}]),
        ("model::details", [{"item": "1"}]),
    ]
    assert out.value["tabla_header"] == 1
    assert out.value["tabla_details"] == 1
    assert out.metadata["tabla_header_archivo"].text == "INVOICE INTERNACIONALES/FENIX AEROSPACE"


def test_static_data_asset_falla_si_falta_la_carpeta(tmp_path, monkeypatch):
    import assets.static_data_asset.static_data_asset as mod

    monkeypatch.setattr(mod, "STATIC_DIR", _static_dir(tmp_path))
    monkeypatch.setattr(mod, "STATIC_SPECS", [])
    monkeypatch.setattr(
        mod,
        "INVOICE_SPECS",
        [
            _spec_facturas(
                "INVOICE INTERNACIONALES/FENIX AEROSPACE", lambda ruta: {"header": [], "details": []}
            )
        ],
    )

    try:
        _ASSET_FN(_Ctx(), _Db())
    except ValueError as exc:
        assert "INVOICE INTERNACIONALES" in str(exc)
    else:
        raise AssertionError("debería haber lanzado ValueError por carpeta faltante")
