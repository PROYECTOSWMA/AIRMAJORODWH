"""Tests de los jobs con nombre del pipeline (``src/jobs.py`` + ``definitions.py``).

Fijan el diseño acordado:

- un job por cadena, y **dentro de cada job todos los assets particionados comparten la
  misma `PartitionsDefinition`** (requisito de Dagster para materializarlos en un run);
- **ningún** ``ScheduleDefinition`` ni ``automation_condition``: el disparo es el cron
  externo (la ventana —"SIRE: mes anterior + mes actual todos los días"— es regla de
  negocio y no se deduce del estado de particiones);
- la capa analítica es un job **sin particiones** (``dbt_run`` -> ``publish_dwh``) donde el
  orden lo dan las deps.
"""

from __future__ import annotations

import definitions
from dagster import AssetKey

_DEFS = definitions.defs
_REPO = _DEFS.get_repository_def()


def _key(nombre: str) -> AssetKey:
    return AssetKey(nombre)


def _job(nombre):
    for job in _REPO.get_all_jobs():
        if job.name == nombre:
            return job
    raise AssertionError(f"no existe el job '{nombre}'")


def _keys(job) -> list[str]:
    return sorted(k.to_user_string() for k in job.asset_layer.executable_asset_keys)


def _partitions_defs(job):
    return {id(job.asset_layer.get(k).partitions_def) for k in job.asset_layer.executable_asset_keys}


def _ancestros(nombre: str) -> set[str]:
    """Cierre transitivo hacia arriba de un asset (para probar deps indirectas)."""

    def _subir(actual: str, vistos: set[str]) -> set[str]:
        for padre in _REPO.asset_graph.get(_key(actual)).parent_keys:
            p = padre.to_user_string()
            if p not in vistos:
                vistos.add(p)
                _subir(p, vistos)
        return vistos

    return _subir(nombre, set())


def test_los_jobs_del_cron_existen_con_su_seleccion():
    assert _keys(_job("correo_daily_job")) == [
        "adp_reports_daily",
        "cep_docs_daily",
        "corpac_data_daily",
        "corpac_files_daily",
        "ingest_emails",
        "talma_reports_daily",
        "terpel_invoicem_daily",
        "terpel_tickets_daily",
    ]
    assert _keys(_job("sire_monthly_job")) == [
        "cep_cost_centers_monthly",
        "icaro_cost_centers_monthly",
        "petroperu_cost_centers_monthly",
        "sire_details_monthly",
        "sire_files_monthly",
        "sire_proposal_monthly",
    ]
    assert _keys(_job("rh_monthly_job")) == ["seesol_rh_monthly"]


def test_cada_job_comparte_una_unica_definicion_de_particiones():
    for job in _REPO.get_all_jobs():
        if job.name == "__ASSET_JOB":
            continue  # el implícito mezcla todas las cadenas por definición
        assert len(_partitions_defs(job)) == 1, job.name


def test_el_job_del_dwh_no_tiene_particiones_y_publica_despues_de_dbt():
    job = _job("dwh_publish_job")

    assert _keys(job) == ["dbt_run", "publish_dwh"]
    assert job.partitions_def is None
    deps = {
        k.to_user_string()
        for k in _REPO.asset_graph.get(_key("publish_dwh")).parent_keys
    }
    # `publish_dwh` cuelga de `dbt_run` (el orden lo impone el grafo, no el operador).
    assert deps == {"dbt_run"}


def test_el_dbt_run_no_es_particionable_y_depende_de_la_ingesta():
    nodo = _REPO.asset_graph.get(_key("dbt_run"))

    assert nodo.partitions_def is None
    assert nodo.group_name == "dwh"
    # 16 de los 19 assets de ingesta: dbt no lee las tablas de `sire_files_monthly`
    # (`sire_*_files`), `ingest_emails` (`emails`/`email_attachments`) ni
    # `corpac_files_daily` (`from_email_corpac_files`), así que no son deps suyas.
    assert len(nodo.parent_keys) == 16


def test_el_dwh_no_tiene_sire_files_como_dep_directa():
    # `dbt_run` **no** declara `sire_files_monthly` (dbt no lee las tablas
    # `sire_*_files`), pero lo tiene como ancestro INDIRECTO mientras los cost centers
    # (que sí son fuentes de dbt) dependan de él: es el precio de que la extracción de
    # aeronaves espere a que los ZIP estén descargados.
    assert "sire_files_monthly" not in {
        k.to_user_string() for k in _REPO.asset_graph.get(_key("dbt_run")).parent_keys
    }
    assert "sire_files_monthly" in _ancestros("dbt_run")


def test_los_cost_centers_dependen_solo_de_los_archivos():
    # Los 3 son idénticos: una única dep (`sire_files_monthly`) y ningún acceso a la
    # propuesta en el grafo (entra por transitividad, no como dep directa). El SQL
    # tampoco consulta `sire_purchs` (lo fija test_cost_centers_db_resource.py).
    for nombre in (
        "cep_cost_centers_monthly",
        "icaro_cost_centers_monthly",
        "petroperu_cost_centers_monthly",
    ):
        padres = {
            k.to_user_string()
            for k in _REPO.asset_graph.get(_key(nombre)).parent_keys
        }
        assert padres == {"sire_files_monthly"}, nombre
        assert _ancestros(nombre) == {
            "sire_files_monthly",
            "sire_proposal_monthly",
        }, nombre


def test_la_cadena_de_correo_resuelve_un_trozo_de_30_dias():
    # Políticas mixtas a propósito (`ingest_emails`/`corpac_files_daily` con multi_run(30) +
    # `corpac_data_daily` y los 4 reportes con single_run): Dagster se queda con la mínima,
    # que son los 30 días por run del `multi_run(30)`. Lo que materializa el cron (1 día por run
    # con `--partition`) no depende de la política del job.
    politica = _job("correo_daily_job").backfill_policy

    assert politica.max_partitions_per_run == 30


def test_no_hay_schedules():
    assert list(_REPO.schedule_defs) == []


def test_ningun_asset_declara_condiciones_de_automatizacion():
    grafo = _REPO.asset_graph
    for key in grafo.get_all_asset_keys():
        assert getattr(grafo.get(key), "automation_condition", None) is None, key
