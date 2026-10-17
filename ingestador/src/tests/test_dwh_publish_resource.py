"""Tests del motor de publicación y de su resource (`DwhPublishResource`).

Este módulo tiene **todo** el motor de publicación (DuckDB -> PostgreSQL); antes estaba
repartido entre `sync_db.py` (raíz) y este resource, que era un envoltorio.

**No tocan PostgreSQL**: cubren el mapeo de tipos DuckDB -> Postgres, los metadatos del
DuckDB (con ficheros temporales), el parseo de credenciales, la selección `--only`/`--exclude`,
los códigos de salida del CLI y que `publish()` le pase la config del resource al motor (con
`publicar` doblado). La prueba de publicación REAL se hace a mano contra el DWH en dry-run:

    python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --dry-run
"""

from __future__ import annotations

import duckdb
import pytest

from assets.dwh_assets.dwh_publish_asset.resources import publish_resource as pr
from assets.dwh_assets.dwh_publish_asset.resources.publish_resource import (
    DuckdbNoDisponibleError,
    DwhPublishError,
    DwhPublishResource,
)


# ---------------------------------------------------------------------------
# Tipos DuckDB -> PostgreSQL
# ---------------------------------------------------------------------------
def test_pg_type_mapea_los_tipos_de_duckdb() -> None:
    assert pr.pg_type("BIGINT") == "BIGINT"
    assert pr.pg_type("INTEGER") == "INTEGER"
    assert pr.pg_type("VARCHAR") == "TEXT"
    assert pr.pg_type("DOUBLE") == "DOUBLE PRECISION"
    assert pr.pg_type("DATE") == "DATE"
    assert pr.pg_type("TIMESTAMP") == "TIMESTAMP"
    assert pr.pg_type("TIMESTAMP WITH TIME ZONE") == "TIMESTAMPTZ"
    assert pr.pg_type("DECIMAL(18,2)") == "NUMERIC(18,2)"
    assert pr.pg_type("DECIMAL") == "NUMERIC"
    assert pr.pg_type("HUGEINT") == "NUMERIC(38,0)"
    assert pr.pg_type("BLOB") == "BYTEA"


def test_pg_type_tipo_no_soportado_cae_a_text() -> None:
    assert pr.pg_type("STRUCT(a INTEGER)") == "TEXT"
    assert pr.pg_type("INTEGER[]") == "TEXT"


# ---------------------------------------------------------------------------
# Metadatos del DuckDB
# ---------------------------------------------------------------------------
def test_duckdb_connect_abre_en_solo_lectura(tmp_path) -> None:
    path = tmp_path / "origen.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (a BIGINT)")
    con.close()

    con = pr.duckdb_connect(path)
    try:
        assert pr.duckdb_tables(con) == ["t"]
    finally:
        con.close()


def test_duckdb_connect_reabre_rw_si_ya_esta_abierto_en_el_proceso(tmp_path) -> None:
    """Regresión 2026-09-18: `dbt_run` + `publish_dwh` en el MISMO proceso.

    dbt deja el fichero abierto en read-write; el `read_only=True` de la publicación
    fallaba con "different configuration than existing connections". El helper debe
    reabrir con la configuración existente.
    """
    path = tmp_path / "origen.duckdb"
    ya_abierto = duckdb.connect(str(path))
    ya_abierto.execute("CREATE TABLE t (a BIGINT)")

    try:
        con = pr.duckdb_connect(path)
        try:
            assert pr.duckdb_tables(con) == ["t"]
        finally:
            con.close()
    finally:
        ya_abierto.close()


def test_duckdb_connect_propaga_los_demas_errores(monkeypatch, tmp_path) -> None:
    def falso_connect(*args, **kwargs):
        raise duckdb.IOException("Could not set lock on file")

    monkeypatch.setattr(pr.duckdb, "connect", falso_connect)

    with pytest.raises(duckdb.IOException):
        pr.duckdb_connect(tmp_path / "x.duckdb")


def test_duckdb_tables_ignora_las_vistas_y_ordena(tmp_path) -> None:
    path = tmp_path / "origen.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE zeta (a BIGINT)")
    con.execute("CREATE TABLE alfa (a BIGINT)")
    con.execute("CREATE VIEW vistita AS SELECT 1 AS x")
    con.close()

    con = duckdb.connect(str(path), read_only=True)
    try:
        assert pr.duckdb_tables(con) == ["alfa", "zeta"]
    finally:
        con.close()


def test_duckdb_columns_respeta_el_orden(tmp_path) -> None:
    path = tmp_path / "origen.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (b VARCHAR, a BIGINT, c DECIMAL(10,2))")
    con.close()

    con = duckdb.connect(str(path), read_only=True)
    try:
        assert pr.duckdb_columns(con, "t") == [
            ("b", "VARCHAR"),
            ("a", "BIGINT"),
            ("c", "DECIMAL(10,2)"),
        ]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Credenciales y schema destino
# ---------------------------------------------------------------------------
def test_pg_params_separa_host_y_puerto(monkeypatch) -> None:
    monkeypatch.setenv("PGHOST", "51.38.243.200:5447")
    monkeypatch.setenv("PGDATABASE", "dwh_aim_db")
    monkeypatch.setenv("PGUSER", "dwh_aim_user")
    monkeypatch.setenv("PGPASSWORD", "secreto")
    monkeypatch.delenv("PGPORT", raising=False)

    assert pr.pg_params() == {
        "host": "51.38.243.200",
        "port": 5447,
        "dbname": "dwh_aim_db",
        "user": "dwh_aim_user",
        "password": "secreto",
    }


def test_pg_params_defaults(monkeypatch) -> None:
    for var in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        monkeypatch.delenv(var, raising=False)

    assert pr.pg_params() == {
        "host": "localhost",
        "port": 5432,
        "dbname": "postgres",
        "user": "postgres",
        "password": "",
    }


def test_schema_destino_usa_pgdwh_schema(monkeypatch) -> None:
    monkeypatch.setenv("PGDWH_SCHEMA", "dwh_prueba")

    assert pr.schema_destino() == "dwh_prueba"

    monkeypatch.delenv("PGDWH_SCHEMA")

    assert pr.schema_destino() == "dwh"


# ---------------------------------------------------------------------------
# Selección de tablas
# ---------------------------------------------------------------------------
def test_seleccionar_tablas_aplica_only_y_exclude() -> None:
    tablas = ["alfa", "beta", "gamma"]

    assert pr.seleccionar_tablas(tablas, None, None) == tablas
    assert pr.seleccionar_tablas(tablas, "alfa, gamma", None) == ["alfa", "gamma"]
    assert pr.seleccionar_tablas(tablas, None, "beta") == ["alfa", "gamma"]
    assert pr.seleccionar_tablas(tablas, "alfa, beta, gamma", "beta") == ["alfa", "gamma"]


# ---------------------------------------------------------------------------
# CLI (códigos de salida), sin tocar PostgreSQL
# ---------------------------------------------------------------------------
def test_main_avisa_si_no_existe_el_duckdb(tmp_path) -> None:
    assert pr.main(["--duckdb", str(tmp_path / "no_existe.duckdb")]) == 2


def test_main_avisa_si_no_hay_tablas(tmp_path) -> None:
    path = tmp_path / "vacio.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE VIEW vistita AS SELECT 1 AS x")
    con.close()

    assert pr.main(["--duckdb", str(path)]) == 1


def test_publicar_marca_codigo_2_si_no_puede_abrir_el_duckdb(tmp_path) -> None:
    with pytest.raises(DuckdbNoDisponibleError) as excinfo:
        pr.publicar(duckdb_path=tmp_path / "no_existe.duckdb", schema="dwh")

    assert excinfo.value.codigo_salida == 2



# ---------------------------------------------------------------------------
# Resource: defaults, paso de la config al motor y lectura del DuckDB
# ---------------------------------------------------------------------------
def test_defaults_del_resource() -> None:
    res = DwhPublishResource()

    assert res.duckdb_path == str(pr.DEFAULT_DUCKDB)
    assert res.schema_name == pr.schema_destino()
    assert res.only is None
    assert res.exclude is None
    assert res.dry_run is False
    assert res.recreate is False


def test_publish_pasa_la_config_al_motor(monkeypatch) -> None:
    llamadas = []

    def falso_publicar(**kwargs):
        llamadas.append(kwargs)
        return 7

    monkeypatch.setattr(pr, "publicar", falso_publicar)

    res = DwhPublishResource(
        duckdb_path="/tmp/x.duckdb",
        schema_name="dwh_prueba",
        only="moves,calendar",
        exclude="dwh_movimientos",
        recreate=True,
        dry_run=True,
    )

    assert res.publish() == 7
    assert llamadas == [
        {
            "duckdb_path": "/tmp/x.duckdb",
            "schema": "dwh_prueba",
            "only": "moves,calendar",
            "exclude": "dwh_movimientos",
            "dry_run": True,
            "recreate": True,
        }
    ]


def test_publish_propaga_el_error_del_motor(monkeypatch) -> None:
    def falso_publicar(**kwargs):
        raise DwhPublishError("sin credenciales de PostgreSQL")

    monkeypatch.setattr(pr, "publicar", falso_publicar)

    with pytest.raises(DwhPublishError) as excinfo:
        DwhPublishResource(duckdb_path="/tmp/x.duckdb").publish()

    assert "sin credenciales de PostgreSQL" in str(excinfo.value)


def test_tables_lista_las_tablas_base_del_duckdb(tmp_path):
    path = tmp_path / "origen.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE zeta (a BIGINT)")
    con.execute("CREATE TABLE alfa (a BIGINT)")
    con.execute("CREATE VIEW vistita AS SELECT 1 AS x")
    con.close()

    assert DwhPublishResource(duckdb_path=str(path)).tables() == ["alfa", "zeta"]


def test_tables_aplica_only_y_exclude(tmp_path):
    path = tmp_path / "origen.duckdb"
    con = duckdb.connect(str(path))
    for tabla in ("alfa", "beta", "gamma"):
        con.execute(f"CREATE TABLE {tabla} (a BIGINT)")
    con.close()

    res = DwhPublishResource(duckdb_path=str(path), only="alfa,beta", exclude="beta")

    assert res.tables() == ["alfa"]


def test_tables_sin_duckdb_da_error_claro(tmp_path):
    with pytest.raises(DuckdbNoDisponibleError) as excinfo:
        DwhPublishResource(duckdb_path=str(tmp_path / "no_existe.duckdb")).tables()

    assert "DuckDB" in str(excinfo.value)


def test_tables_con_el_duckdb_ya_abierto_en_este_proceso(tmp_path):
    """Regresión 2026-09-18: `dbt_run` y `publish_dwh` en el MISMO proceso.

    dbt deja el DuckDB abierto en read-write, así que un `connect(..., read_only=True)`
    fallaba con "Can't open a connection to same database file with a different
    configuration than existing connections" y el step `publish_dwh` caía.
    """
    path = tmp_path / "origen.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE alfa (a BIGINT)")
    con.execute("CREATE TABLE zeta (a BIGINT)")
    try:
        assert DwhPublishResource(duckdb_path=str(path)).tables() == ["alfa", "zeta"]
    finally:
        con.close()

