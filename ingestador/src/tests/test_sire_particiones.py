"""Tests de la cadena SIRE: particiones mensuales, políticas y helpers.

Fija el diseño acordado (espejo de ``test_correos_particiones.py``):

- los 6 assets de SIRE comparten la MISMA definición **mensual** (requisito de
  Dagster para que padre e hijo puedan materializarse en un mismo run);
- **ninguno** declara ``BackfillPolicy``: cada partición (mes) es un run propio y
  el cron materializa el **mes anterior + el mes actual** partición a partición;
- las dependencias son **identidad** (sin ``TimeWindowPartitionMapping``): los
  detalles/archivos dependen de la propuesta y los cost centers **solo** de los
  archivos (la propuesta entra por dependencia transitiva);
- ningún asset declara condiciones de automatización: el disparo es el cron externo;
- **ningún** asset de la cadena devuelve un ``Output`` con valor: el resumen va en la
  metadata del materialization event, así que los 6 devuelven ``MaterializeResult``
  sin valor.
"""

import datetime as dt

from dagster import MaterializeResult

from assets._common.partitions import (
    partition_days,
    partition_months,
    sire_monthly_partitions_def,
)
from assets.from_sire_files_assets.cep_cost_centers_asset.cep_cost_centers_asset import (
    cep_cost_centers_monthly,
)
from assets.from_sire_files_assets.icaro_cost_centers_asset.icaro_cost_centers_asset import (
    icaro_cost_centers_monthly,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.petroperu_cost_centers_asset import (
    petroperu_cost_centers_monthly,
)
from assets.sire_assets.sire_details_asset.sire_details_asset import sire_details_monthly
from assets.sire_assets.sire_files_asset.sire_files_asset import sire_files_monthly
from assets.sire_assets.sire_proposal_asset.sire_proposal_asset import (
    sire_proposal_monthly,
)

CADENA = {
    "sire_proposal_monthly": sire_proposal_monthly,
    "sire_details_monthly": sire_details_monthly,
    "sire_files_monthly": sire_files_monthly,
    "cep_cost_centers_monthly": cep_cost_centers_monthly,
    "icaro_cost_centers_monthly": icaro_cost_centers_monthly,
    "petroperu_cost_centers_monthly": petroperu_cost_centers_monthly,
}

# Los 2 assets que consumen la propuesta directamente.
CON_DEP_PROPUESTA = {"sire_details_monthly", "sire_files_monthly"}

# Hora fija para comparar los espacios de particiones sin depender del reloj.
_AHORA = dt.datetime(2026, 9, 17, 12, 0, tzinfo=dt.timezone.utc)


class _Contexto:
    """Contexto mínimo (como los stubs de los tests de assets)."""

    def __init__(self, partition_key="2026-08-01", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys


def _spec(asset):
    """AssetSpec del asset (AssetsDefinition.specs es un dict_values)."""
    return next(iter(asset.specs))


def _deps(asset):
    """``{asset_key: partition_mapping}`` de las dependencias declaradas."""
    return {d.asset_key.to_user_string(): d.partition_mapping for d in _spec(asset).deps}


def _es_identidad(mapping) -> bool:
    """Sin mapping explícito (o el de identidad): no hay salto de particiones."""
    return mapping is None or type(mapping).__name__ == "IdentityPartitionMapping"


def test_todos_comparten_la_misma_definicion_mensual():
    esperadas = sire_monthly_partitions_def.get_partition_keys(current_time=_AHORA)
    for nombre, asset in CADENA.items():
        keys = asset.partitions_def.get_partition_keys(current_time=_AHORA)
        assert keys == esperadas, nombre
        assert keys[0] == "2026-01-01"
        # end_offset=1: el mes en curso YA es una partición válida (el cron lo
        # re-materializa cada día junto al mes anterior).
        assert keys[-1] == "2026-09-01"
        assert len(keys) == 9  # enero..septiembre de 2026


def test_grupo_from_sire():
    for nombre, asset in CADENA.items():
        assert set(asset.group_names_by_key.values()) == {"from_sire"}, nombre


def test_ningun_asset_declara_condiciones_de_automatizacion():
    for nombre, asset in CADENA.items():
        assert _spec(asset).automation_condition is None, nombre


def test_ningun_asset_devuelve_output_con_valor():
    # El resumen del trabajo (filas, missing...) viaja en la metadata del
    # materialization event: un ``Output`` con valor pasaría por el IO manager por
    # defecto, que no aporta nada aquí. La anotación de retorno debe ser
    # ``MaterializeResult``.
    for nombre, asset in CADENA.items():
        fn = asset.op.compute_fn.decorated_fn
        assert fn.__annotations__.get("return") is MaterializeResult, nombre


def test_las_dependencias_son_identidad():
    # La propuesta no tiene dependencias.
    assert _deps(sire_proposal_monthly) == {}

    # Los detalles y los archivos dependen de la propuesta.
    for nombre in CON_DEP_PROPUESTA:
        deps = _deps(CADENA[nombre])
        assert set(deps) == {"sire_proposal_monthly"}, nombre
        assert _es_identidad(deps["sire_proposal_monthly"]), nombre

    # Los cost centers dependen SOLO de los archivos (la propuesta es transitiva): así
    # el run garantiza que los ZIP del mes ya están descargados al extraer las aeronaves.
    for nombre in CADENA.keys() - CON_DEP_PROPUESTA - {"sire_proposal_monthly"}:
        deps = _deps(CADENA[nombre])
        assert set(deps) == {"sire_files_monthly"}, nombre
        assert _es_identidad(deps["sire_files_monthly"]), nombre


def test_partition_months_con_claves_mensuales():
    assert partition_months(_Contexto("2026-09-01")) == ["2026-09"]
    # El cron pide mes anterior + mes actual en el mismo run.
    assert partition_months(
        _Contexto(partition_keys=["2026-08-01", "2026-09-01"])
    ) == ["2026-08", "2026-09"]


def test_partition_days_devuelve_las_claves_del_run():
    assert partition_days(_Contexto("2026-09-01")) == ["2026-09-01"]
    assert partition_days(
        _Contexto(partition_keys=["2026-08-01", "2026-09-01"])
    ) == ["2026-08-01", "2026-09-01"]
