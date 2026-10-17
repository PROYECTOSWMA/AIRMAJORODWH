"""Tests de los assets del DWH: ``dbt_run`` (dbt sobre DuckDB) y ``publish_dwh``.

Los assets se invocan por su función de cómputo subyacente con recursos stub (como el
resto de la suite), así que **no** se corre dbt ni se toca PostgreSQL. Fijan el contrato:
sin particiones, grupo ``dwh``, las 16 fuentes como deps de ``dbt_run``, la dependencia
``publish_dwh -> dbt_run`` y que ninguno devuelva ``Output`` con valor.
"""

from __future__ import annotations

import pytest
from dagster import MaterializeResult

from assets.dwh_assets.dbt_run_asset.dbt_run_asset import dbt_run
from assets.dwh_assets.dbt_run_asset.resources.dbt_resource import DEFAULT_PROJECT_DIR
from assets.dwh_assets.dwh_publish_asset.dwh_publish_asset import publish_dwh
from assets.dwh_assets.dwh_publish_asset.resources.publish_resource import DwhPublishError

_DBT_FN = dbt_run.op.compute_fn.decorated_fn
_PUBLISH_FN = publish_dwh.op.compute_fn.decorated_fn

# Las 16 fuentes que dbt lee de `db.sqlite` (todo lo que hay que haber materializado antes).
# Faltan a propósito los 3 assets cuyas tablas no lee ningún modelo: `sire_files_monthly`
# (`sire_*_files`), `ingest_emails` (`emails`/`email_attachments`) y `corpac_files_daily`
# (`from_email_corpac_files`).
FUENTES = {
    "corpac_data_daily",
    "cep_docs_daily",
    "sire_proposal_monthly",
    "sire_details_monthly",
    "sisa_sales_monthly",
    "flight_reports_asset",
    "terpel_tickets_daily",
    "terpel_invoicem_daily",
    "adp_reports_daily",
    "talma_reports_daily",
    "cep_cost_centers_monthly",
    "icaro_cost_centers_monthly",
    "petroperu_cost_centers_monthly",
    "static_data_asset",
    "calendar_weekly",
    "seesol_rh_monthly",
}


class _Log:
    def __init__(self):
        self.mensajes = []

    def info(self, *args, **kwargs):
        self.mensajes.append(args)

    def warning(self, *args, **kwargs):
        self.mensajes.append(args)


class _Ctx:
    log = _Log()


class _DbtStub:
    project_dir = str(DEFAULT_PROJECT_DIR)
    target = "dev"

    def run(self):
        return {
            "args": ["run", "--project-dir", self.project_dir],
            "elapsed_seconds": 2.57,
            "statuses": {"success": 6},
            "models_run": 6,
            "failed_models": [],
        }


class _PublishStub:
    duckdb_path = "/tmp/analytics_poc.duckdb"
    schema_name = "dwh"
    dry_run = False

    def __init__(self):
        self.llamadas = []

    def tables(self):
        return ["moves", "partners"]

    def publish(self):
        self.llamadas.append("publish")
        return 1234


def _spec(asset):
    """AssetSpec del asset (AssetsDefinition.specs es un dict key -> spec)."""
    return next(iter(asset.specs))


def test_dbt_run_sin_particiones_en_el_grupo_dwh():
    spec = _spec(dbt_run)

    assert spec.key.to_user_string() == "dbt_run"
    assert spec.group_name == "dwh"
    assert spec.partitions_def is None
    assert dbt_run.partitions_def is None


def test_dbt_run_depende_de_las_16_fuentes():
    deps = {d.asset_key.to_user_string() for d in _spec(dbt_run).deps}

    assert deps == FUENTES


def test_publish_dwh_depende_solo_de_dbt_run():
    spec = _spec(publish_dwh)

    assert spec.key.to_user_string() == "publish_dwh"
    assert spec.group_name == "dwh"
    assert spec.partitions_def is None
    assert {d.asset_key.to_user_string() for d in spec.deps} == {"dbt_run"}


def test_ninguno_devuelve_output_con_valor():
    # MaterializeResult sin valor: se salta el IO manager (un `Output` con valor solo
    # funciona con una partición; aquí no hay particiones, pero se mantiene el patrón de
    # los assets de rango para no volver a pisar la misma piedra).
    for fn in (_DBT_FN, _PUBLISH_FN):
        assert fn.__annotations__.get("return") is MaterializeResult


def test_dbt_run_devuelve_la_metadata_del_resumen():
    out = _DBT_FN(_Ctx(), _DbtStub())

    assert out.metadata["models_run"] == 6
    assert out.metadata["elapsed_seconds"] == 2.57
    assert out.metadata["dbt_target"] == "dev"
    assert out.metadata["dbt_project_dir"] == str(DEFAULT_PROJECT_DIR)
    assert out.metadata["statuses"].data == {"success": 6}


def test_publish_dwh_publica_y_reporta_las_tablas():
    res = _PublishStub()

    out = _PUBLISH_FN(_Ctx(), res)

    assert res.llamadas == ["publish"]
    assert out.metadata["tables_count"] == 2
    assert out.metadata["tables"].data == ["moves", "partners"]
    assert out.metadata["pg_schema"] == "dwh"
    assert out.metadata["dry_run"] is False
    assert out.metadata["rows_published"] == 1234


def test_publish_dwh_propaga_el_fallo_de_la_publicacion():
    class _Falla(_PublishStub):
        def publish(self):
            raise DwhPublishError("sin credenciales de PostgreSQL")

    with pytest.raises(DwhPublishError):
        _PUBLISH_FN(_Ctx(), _Falla())


def test_publish_dwh_avisa_si_el_duckdb_no_tiene_tablas():
    class _Vacio(_PublishStub):
        def tables(self):
            return []

    out = _PUBLISH_FN(_Ctx(), _Vacio())

    assert out.metadata["tables_count"] == 0
    assert out.metadata["tables"].data == []
