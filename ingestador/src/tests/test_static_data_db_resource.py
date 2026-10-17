"""Tests de ``StaticDataSqliteResource`` (snapshots y los 7 CSV de referencia).

Se comprueba que el resource crea las **11** tablas (4 snapshots + los 7 CSV de
referencia/maestros), que ninguna de las 4 snapshots tiene ``period`` (ya no lo declaran:
eran el marco del RH) y que el reemplazo de la tabla **completa** funciona tanto en los
CSV como en los snapshots: las tablas de los CSV no tienen clave primaria ni ``id``
(reflejan el CSV tal cual) y pueden traer filas repetidas. La tabla ``seesol_rh`` ya no
la alimenta este resource (tiene el suyo: ``src/tests/test_seesol_rh_db_resource.py``).
"""

import pytest

import assets._common.db as db_mod
from assets.static_data_asset.models.static_dwh_airplanes import StaticDwhAirplanes
from assets.static_data_asset.models.static_payroll import StaticPayroll
from assets.static_data_asset.resources.db_resource import StaticDataSqliteResource

# Nombres REALES de las tablas (iguales a los ``table_name`` de los modelos).
TABLAS_SNAPSHOTS = (
    "static_ambulance_sales_reports",
    "static_lap_reports",
    "static_payroll",
    "sales_selva",
)

TABLAS_CSV = (
    "static_dwh_master_accounts",
    "static_dwh_master_account_groups",
    "static_dwh_airplanes",
    "static_dwh_cost_centers",
    "static_aux_accounts_assignment",
    "static_aux_airports",
    "static_aux_cost_centers_override",
)


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un DatabaseProxy global compartido: se desenlaza entre tests para
    # que cada recurso lo apunte al archivo SQLite temporal que le corresponde.
    yield
    if db_mod.db.obj is not None:
        try:
            db_mod.db.obj.close()
        except Exception:
            pass
        db_mod.db.initialize(None)


def _avion(registration: str = "1919") -> dict:
    return {
        "registration": registration,
        "owner": "RIBBAN HOLDING S.A.",
        "model": "CESSNA207A",
        "business_unit": "SERVICIO_TURISTICO",
        "base": "NAZCA",
        "passengers": "6",
        "fuel": "100LL",
    }


def test_ensure_db_crea_las_tablas(tmp_path):
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res._ensure_db()
    creadas = set(db_mod.db.get_tables())
    assert {*TABLAS_SNAPSHOTS, *TABLAS_CSV} <= creadas


def test_tablas_de_los_csv_no_tienen_columna_id(tmp_path):
    """Las tablas de los CSV reflejan el CSV exactamente (sin ``id`` de peewee)."""
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res._ensure_db()
    columnas = [c.name for c in db_mod.db.get_columns("static_dwh_airplanes")]
    assert columnas == [
        "registration",
        "owner",
        "model",
        "business_unit",
        "base",
        "passengers",
        "fuel",
    ]


def test_replace_all_inserta_y_reemplaza_la_tabla_completa(tmp_path):
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    assert res.replace_all(StaticDwhAirplanes, [_avion()]) == 1
    assert StaticDwhAirplanes.select().count() == 1

    # Volcar el CSV con menos filas NO acumula: borra la tabla entera antes.
    assert res.replace_all(StaticDwhAirplanes, []) == 0
    assert StaticDwhAirplanes.select().count() == 0

    assert res.replace_all(StaticDwhAirplanes, [_avion("2180")]) == 1
    assert [f.registration for f in StaticDwhAirplanes.select()] == ["2180"]


def test_replace_all_admite_filas_repetidas_del_csv(tmp_path):
    """Sin clave primaria, un CSV con filas duplicadas se carga tal cual."""
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    assert res.replace_all(StaticDwhAirplanes, [_avion(), _avion()]) == 2
    assert StaticDwhAirplanes.select().count() == 2


def test_replace_all_conserva_los_valores_como_texto(tmp_path):
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.replace_all(StaticDwhAirplanes, [_avion()])
    fila = StaticDwhAirplanes.get()
    assert fila.model == "CESSNA207A"
    assert fila.passengers == "6"
    assert fila.fuel == "100LL"


def test_replace_all_trocea_el_insert(tmp_path, monkeypatch):
    """Muchas filas no deben superar el límite de variables SQL de SQLite."""
    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [_avion(f"{i:04d}") for i in range(50)]
    assert res.replace_all(StaticDwhAirplanes, rows) == 50
    assert StaticDwhAirplanes.select().count() == 50


def test_las_tablas_de_snapshots_no_tienen_columna_period(tmp_path):
    """Sin RH aquí, los 4 snapshots ya no llevan ``period`` (ni partición)."""
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res._ensure_db()
    for tabla in TABLAS_SNAPSHOTS:
        assert "period" not in {c.name for c in db_mod.db.get_columns(tabla)}, tabla


def test_replace_all_vuelca_un_snapshot_entero(tmp_path):
    """Los snapshots usan el mismo reemplazo total que los CSV (no acumulan)."""
    res = StaticDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    assert res.replace_all(StaticPayroll, [{"nombre": "A"}, {"nombre": "B"}]) == 2
    assert {f.nombre for f in StaticPayroll.select()} == {"A", "B"}

    assert res.replace_all(StaticPayroll, [{"nombre": "C"}]) == 1
    assert [f.nombre for f in StaticPayroll.select()] == ["C"]
