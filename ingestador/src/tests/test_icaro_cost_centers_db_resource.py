"""Tests de la migración de las columnas del ticket en ``from_sire_icaro_cost_centers``.

``create_tables`` crea la tabla si falta pero **no** agrega columnas a una tabla ya
existente: el resource de ICARO las migra con ``ALTER TABLE`` (idempotente).
"""

import sqlite3

import pytest

from assets._common.db import db
from assets.from_sire_files_assets.icaro_cost_centers_asset.resources.db_resource import (
    IcaroCostCenterSqliteResource,
)

_TABLA = "from_sire_icaro_cost_centers"
_COLUMNAS_TICKET = (
    "nro_ticket",
    "texto_planta",
    "texto_matricula",
    "matricula",
    "schema_info",
)


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un singleton global: cerrar la conexión entre tests para que cada
    # uno apunte al archivo SQLite temporal que le corresponde.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)


def _resource(tmp_path):
    return IcaroCostCenterSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _tabla_vieja(db_path):
    """Crea la tabla de ICARO como era antes de las columnas del ticket."""
    con = sqlite3.connect(str(db_path))
    con.execute(
        f'CREATE TABLE "{_TABLA}" '
        "(id INTEGER PRIMARY KEY, period TEXT, id_file INTEGER, "
        "filename TEXT, aeronave TEXT)"
    )
    con.commit()
    con.close()


def test_ensure_columns_agrega_las_columnas_del_ticket(tmp_path):
    db_path = tmp_path / "db.sqlite"
    _tabla_vieja(db_path)

    res = _resource(tmp_path)
    res._ensure_db()

    columnas = {c.name for c in db.get_columns(_TABLA)}
    assert set(_COLUMNAS_TICKET) <= columnas


def test_ensure_columns_es_idempotente(tmp_path):
    db_path = tmp_path / "db.sqlite"
    _tabla_vieja(db_path)

    res = _resource(tmp_path)
    res._ensure_db()
    res._ensure_db()

    nombres = [c.name for c in db.get_columns(_TABLA)]
    assert nombres.count("matricula") == 1
    assert set(_COLUMNAS_TICKET) <= set(nombres)


def test_tabla_nueva_ya_trae_las_columnas_del_ticket(tmp_path):
    # Sin tabla previa, ``create_tables`` la crea con las columnas del modelo y la
    # migración no tiene nada que hacer.
    res = _resource(tmp_path)
    res._ensure_db()

    columnas = {c.name for c in db.get_columns(_TABLA)}
    assert set(_COLUMNAS_TICKET) <= columnas
