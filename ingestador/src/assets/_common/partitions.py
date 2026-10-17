from __future__ import annotations

from dagster import (
    AssetExecutionContext,
    DailyPartitionsDefinition,
    MonthlyPartitionsDefinition,
)

from assets.constants import START_DATE

# Definición diaria compartida por los assets de la cadena de correo. Compartir el
# MISMO objeto (mismo ``start_date``/``end_offset``) es requisito para que padre e
# hijo puedan materializarse en un mismo run.
daily_partitions_def = DailyPartitionsDefinition(start_date=START_DATE)

# Alias con el nombre histórico de la cadena de correo.
correos_daily_partitions_def = daily_partitions_def

# Definición mensual compartida por los 6 assets de SIRE (clave = primer día del
# mes, p. ej. "2026-09-01"). ``end_offset=1`` incluye el mes en curso: el cron
# materializa siempre **mes anterior + mes actual** en un único run.
monthly_partitions_def = MonthlyPartitionsDefinition(
    start_date=START_DATE,
    end_offset=1,
)

# Mismo objeto con el nombre histórico de la cadena SIRE (Dagster exige compartir
# la definición para que padre e hijo se materialicen en el mismo run).
sire_monthly_partitions_def = monthly_partitions_def

# Alias del reporte RH del SEE-SOL (``seesol_rh_monthly``): es un asset
# independiente (sin padres) con la misma mensual y el mismo uso de
# ``single_run()`` (el cron pide mes anterior + mes actual).
seesol_rh_monthly_partitions_def = monthly_partitions_def


def partition_days(context: AssetExecutionContext) -> list[str]:
    """Claves de partición que cubre esta materialización, sin normalizar.

    Devuelve la lista de claves cuando el run cubre varias particiones (backfill con
    ``BackfillPolicy.single_run()`` o con ``multi_run(max_partitions_per_run=N)``, que
    llega troceado en runs de hasta N días) o una lista de un solo elemento en una
    materialización normal. Tolerante a contextos parciales (tests).
    """
    keys = getattr(context, "partition_keys", None)
    if keys:
        return list(keys)
    return [context.partition_key]


def partition_months(context: AssetExecutionContext) -> list[str]:
    """Meses (``"2026-08"``) que cubre esta materialización, sin repetir y en orden.

    Sirve para las dos cadenas: en SIRE (particiones **mensuales**) la clave ya es
    el mes (``"2026-08-01"`` -> ``"2026-08"``) y en la diaria agrupa los días del
    run. La propuesta es un **libro por periodo** (``per_tributario=yyyymm``), así
    que se pide una sola vez por mes: un mes -> ``["2026-08"]``; dos meses ->
    ``["2026-08", "2026-09"]``.
    """
    return sorted({key[:7] for key in partition_days(context)})
