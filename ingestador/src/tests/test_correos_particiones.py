"""Tests de la cadena de correo: particiones diarias compartidas, políticas y helper.

Fija el diseño acordado:

- los 7 assets de correo comparten la MISMA definición diaria (requisito de Dagster
  para que padre e hijo puedan materializarse en un mismo run);
- ``ingest_emails`` y ``corpac_files_daily`` declaran
  ``BackfillPolicy.multi_run(max_partitions_per_run=30)`` (un run por cada trozo de hasta
  30 días, que la función recorre con ``partition_days``) y ``corpac_data_daily`` y los 4
  assets de reportes declaran ``BackfillPolicy.single_run()`` (un único run para todo
  el rango, recorrido con ``partition_days``);
- ningún asset declara condiciones de automatización: el disparo es el cron externo.
"""

import datetime as dt

from assets._common.partitions import correos_daily_partitions_def, partition_days
from assets.from_email_assets.adp_reports_asset.adp_reports_asset import adp_reports_daily
from assets.from_email_assets.corpac_assets.corpac_data_asset.corpac_data_asset import (
    corpac_data_daily,
)
from assets.from_email_assets.corpac_assets.corpac_files_asset.corpac_files_asset import (
    corpac_files_daily,
)
from assets.from_email_assets.talma_reports_asset.talma_reports_asset import (
    talma_reports_daily,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.terpel_invoicem_asset import (
    terpel_invoicem_daily,
)
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.terpel_tickets_asset import (
    terpel_tickets_daily,
)
from assets.mail_asset.mail_asset import ingest_emails

CADENA = {
    "ingest_emails": ingest_emails,
    "corpac_files_daily": corpac_files_daily,
    "corpac_data_daily": corpac_data_daily,
    "talma_reports_daily": talma_reports_daily,
    "adp_reports_daily": adp_reports_daily,
    "terpel_tickets_daily": terpel_tickets_daily,
    "terpel_invoicem_daily": terpel_invoicem_daily,
}

# Cada run de un backfill cubre hasta 30 días (la función los recorre con
# ``partition_days``); el cron diario sigue materializando 1 día por run.
CON_MULTI_RUN = {"ingest_emails": 30, "corpac_files_daily": 30}
# Un único run para todo el rango.
CON_SINGLE_RUN = set(CADENA) - set(CON_MULTI_RUN)

# Hora fija para comparar los espacios de particiones sin depender del reloj.
_AHORA = dt.datetime(2026, 9, 17, 12, 0, tzinfo=dt.timezone.utc)


class _Contexto:
    """Contexto mínimo (como los stubs de los tests de assets)."""

    def __init__(self, partition_key="2026-08-14", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys


class _Log:
    def info(self, *args, **kwargs):
        pass


class _ContextoConLog(_Contexto):
    log = _Log()


def _spec(asset):
    """AssetSpec del asset (AssetsDefinition.specs es un dict key -> spec)."""
    return next(iter(asset.specs))


def test_todos_comparten_la_misma_definicion_diaria():
    esperadas = correos_daily_partitions_def.get_partition_keys(current_time=_AHORA)
    for nombre, asset in CADENA.items():
        keys = asset.partitions_def.get_partition_keys(current_time=_AHORA)
        assert keys == esperadas, nombre
        assert len(keys) > 200  # diaria desde 2026-01-01
        assert keys[0] == "2026-01-01"
        # end_offset por defecto: la última partición es AYER (no el día en curso).
        assert keys[-1] == "2026-09-16"


def test_grupo_from_email_y_politicas_por_grupo():
    for nombre, asset in CADENA.items():
        assert set(asset.group_names_by_key.values()) == {"from_email"}, nombre
        politica = asset.backfill_policy
        assert politica is not None, nombre
        if nombre in CON_MULTI_RUN:
            # ``multi_run(N)``: runs troceados, N particiones como máximo por run.
            assert politica.max_partitions_per_run == CON_MULTI_RUN[nombre], nombre
        else:
            # ``single_run()``: un único run para todo el rango.
            assert politica.max_partitions_per_run is None, nombre


def test_ningun_asset_declara_condiciones_de_automatizacion():
    for nombre, asset in CADENA.items():
        assert _spec(asset).automation_condition is None, nombre


def test_las_dependencias_son_identidad():
    assert {d.asset_key.to_user_string() for d in _spec(corpac_files_daily).deps} == {
        "ingest_emails"
    }
    assert {d.asset_key.to_user_string() for d in _spec(corpac_data_daily).deps} == {
        "corpac_files_daily"
    }
    for nombre in ("talma_reports_daily", "adp_reports_daily",
                   "terpel_tickets_daily", "terpel_invoicem_daily"):
        assert {d.asset_key.to_user_string() for d in _spec(CADENA[nombre]).deps} == {
            "ingest_emails"
        }, nombre


def test_partition_days_una_particion():
    assert partition_days(_ContextoConLog("2026-08-14")) == ["2026-08-14"]


def test_partition_days_rango_de_un_backfill_single_run():
    ctx = _ContextoConLog(partition_keys=["2026-08-13", "2026-08-14"])
    assert partition_days(ctx) == ["2026-08-13", "2026-08-14"]


def test_partition_days_rango_troceado_de_un_backfill_multi_run():
    # ``multi_run(max_partitions_per_run=30)``: el run trae el trozo de rango completo
    # (p. ej. los 30 días del chunk), no un día suelto.
    trozo = [f"2026-08-{dia:02d}" for dia in range(1, 31)]
    assert partition_days(_ContextoConLog(partition_keys=trozo)) == trozo


def test_partition_days_tolera_contextos_sin_partition_keys():
    class _Minimo:
        partition_key = "2026-08-14"

    assert partition_days(_Minimo()) == ["2026-08-14"]
