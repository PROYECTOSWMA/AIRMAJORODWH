"""Tests de la base ``AbstractDbResource`` (agnóstica del motor SQLite/PostgreSQL)."""

import pytest

import assets._common.db as db_mod
from assets._common.abstract_resource import AbstractDbResource
from assets.static_data_asset.models.static_payroll import StaticPayroll


class _PlanillaDbResource(AbstractDbResource):
    """Subclase mínima para ejercitar la base con una tabla conocida."""

    def _tables(self):
        return (StaticPayroll,)

    def replace_por_oficina(self, oficina, rows):
        return self._replace(
            StaticPayroll, StaticPayroll.oficina == oficina, rows, {"oficina": oficina}
        )


def _row(nombre: str = "X") -> dict:
    return {"nombre": nombre}


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un DatabaseProxy compartido: entre tests se cierra y se desenlaza.
    yield
    if db_mod.db.obj is not None:
        try:
            db_mod.db.obj.close()
        except Exception:
            pass
        db_mod.db.initialize(None)


def test_engine_sqlite_construye_sqlitedatabase(tmp_path):
    from peewee import SqliteDatabase

    res = _PlanillaDbResource(database_path=str(tmp_path / "db.sqlite"))
    res._ensure_db()
    assert isinstance(db_mod.db.obj, SqliteDatabase)


def test_engine_postgres_construye_postgresqldatabase():
    from peewee import PostgresqlDatabase

    res = _PlanillaDbResource(
        engine="postgres",
        database_path="dwh_aim_db",
        host="localhost",
        port=5432,
        user="u",
        password="p",
    )
    # ``_connect_db`` enlaza el proxy sin abrir conexión (no hay Postgres en el test).
    res._connect_db()
    assert isinstance(db_mod.db.obj, PostgresqlDatabase)


def test_max_variables_por_motor():
    assert (
        _PlanillaDbResource(engine="sqlite")._max_variables()
        == db_mod._SQLITE_MAX_VARIABLES
    )
    assert _PlanillaDbResource(engine="postgres")._max_variables() == 65535


def test_chunked_divide_en_lotes():
    assert list(db_mod.chunked([1, 2, 3, 4, 5], 2)) == [(1, 2), (3, 4), (5,)]


def test_replace_borra_lo_filtrado_e_inserta(tmp_path):
    res = _PlanillaDbResource(database_path=str(tmp_path / "db.sqlite"))
    assert res.replace_por_oficina("LIMA", [_row("A"), _row("B")]) == 2
    assert StaticPayroll.select().where(StaticPayroll.oficina == "LIMA").count() == 2

    # Re-ejecutar con el mismo filtro: borra e inserta (no acumula).
    assert res.replace_por_oficina("LIMA", [_row("C")]) == 1
    assert {r.nombre for r in StaticPayroll.select()} == {"C"}


def test_replace_muchas_filas_no_supera_el_limite(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = _PlanillaDbResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [_row(f"N{i:03d}") for i in range(50)]
    assert res.replace_por_oficina("LIMA", rows) == 50
    assert StaticPayroll.select().where(StaticPayroll.oficina == "LIMA").count() == 50


def test_reenlaza_el_proxy_entre_rutas(tmp_path):
    a = str(tmp_path / "a.sqlite")
    b = str(tmp_path / "b.sqlite")

    _PlanillaDbResource(database_path=a).replace_por_oficina("LIMA", [_row("A")])
    _PlanillaDbResource(database_path=b).replace_por_oficina("LIMA", [_row("B")])
    # El proxy apunta al último enlace: solo la fila de ``b``.
    assert StaticPayroll.select().count() == 1
    assert StaticPayroll.get().nombre == "B"

    # Volver a ``a`` conserva sus filas.
    _PlanillaDbResource(database_path=a).replace_por_oficina("LIMA", [_row("A2")])
    assert StaticPayroll.select().count() == 1
    assert StaticPayroll.get().nombre == "A2"


def test_existing_keys_y_insert_new_es_idempotente(tmp_path):
    res = _PlanillaDbResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [
        {"oficina": "LIMA", "nombre": "A"},
        {"oficina": "LIMA", "nombre": "B"},
        {"oficina": "LIMA", "nombre": "A"},  # duplicado dentro de la corrida
    ]
    existing = res._existing_keys(StaticPayroll, "oficina", ["LIMA"], ("oficina", "nombre"))
    assert existing == set()
    assert res._insert_new(StaticPayroll, rows, ("oficina", "nombre"), existing) == 2
    assert StaticPayroll.select().count() == 2

    # Reintento: no inserta nada (append-only) y respeta lo existente.
    existing = res._existing_keys(StaticPayroll, "oficina", ["LIMA"], ("oficina", "nombre"))
    assert existing == {("LIMA", "A"), ("LIMA", "B")}
    assert res._insert_new(StaticPayroll, rows, ("oficina", "nombre"), existing) == 0
    assert StaticPayroll.select().count() == 2


def test_insert_new_trocea_el_insert(tmp_path, monkeypatch):
    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = _PlanillaDbResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [{"oficina": "LIMA", "nombre": f"N{i:03d}"} for i in range(50)]
    assert res._insert_new(StaticPayroll, rows, ("oficina", "nombre")) == 50
    assert StaticPayroll.select().count() == 50


def test_replace_con_where_none_borra_toda_la_tabla(tmp_path):
    """``where=None`` = reemplazo total de la tabla (lo usan los estáticos)."""
    res = _PlanillaDbResource(database_path=str(tmp_path / "db.sqlite"))
    assert res._replace(StaticPayroll, None, [{"nombre": "A"}]) == 1
    assert res._replace(StaticPayroll, None, [{"nombre": "B"}]) == 1
    assert [r.nombre for r in StaticPayroll.select()] == ["B"]

    # Y con la tabla llena, un volcado vacío la deja vacía.
    assert res._replace(StaticPayroll, None, []) == 0
    assert StaticPayroll.select().count() == 0
