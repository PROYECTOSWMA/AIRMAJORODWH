"""Asset mensual del reporte RH (recibos por honorarios) del SEE-SOL de SUNAT.

Para cada **mes** de la materialización pide a ``RhResource`` el reporte RH de
**cada empresa** de ``EMPRESAS`` (vía HTTP pura, sin navegador: login del portal SOL
+ app "Consulta Receptor" + ``descargaConsultaReceptor``) y hace un upsert en
``seesol_rh`` **por (period, empresa)**:

* ``period`` es el primer día del mes de la partición (``"2026-08-01"``);
* ``empresa`` es la empresa a la que pertenece el reporte;
* el update solo toca esa pareja mes+empresa, así que re-materializar un mes
  reemplaza lo que SUNAT devuelve hoy (los recibos nuevos entran, los anulados
  desaparecen) sin tocar la otra empresa ni los otros meses.

``partition_months(context)`` devuelve el mes de la partición o los meses del rango
de un backfill ``single_run`` (el cron pide **mes anterior + mes actual**, que es
lo que recoge los recibos emitidos con fecha anterior al periodo). El portal solo
admite rangos de 1 mes por consulta, de ahí la partición mensual y el login por
empresa y mes; si SUNAT pide captcha (``fallas >= 3``) el login aborta y la
materialización falla sin sumar más fallos (el cron lo trata como AVISO).
"""

from typing import Any

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    asset,
)

from assets._common.partitions import (
    partition_months,
    seesol_rh_monthly_partitions_def,
)
from assets.seesol_rh_asset.resources.api_resource import EMPRESAS, RhResource
from assets.seesol_rh_asset.resources.db_resource import SeesolRhSqliteResource


@asset(
    partitions_def=seesol_rh_monthly_partitions_def,
    backfill_policy=BackfillPolicy.single_run(),
)
def seesol_rh_monthly(
    context: AssetExecutionContext,
    rh: RhResource,
    seesol_rh_db: SeesolRhSqliteResource,
) -> MaterializeResult:
    """Alimenta ``seesol_rh`` con el reporte RH del mes de la partición.

    Itera los meses del run (1 en una materialización normal, N en un backfill
    ``single_run``) y, dentro de cada mes, las empresas de ``EMPRESAS``: descarga,
    parsea y upserta por ``(period, empresa)``, avisando si el mes nuevo trae menos
    filas que el anterior (puede ser un mes todavía incompleto en SUNAT).
    """
    months = partition_months(context)
    totals: dict[str, int] = {}

    for month in months:
        period = f"{month}-01"
        for empresa in EMPRESAS:
            previas = seesol_rh_db.count_month(period, empresa)
            filas = [
                {**row, "empresa": empresa} for row in rh.get_month(empresa, period)
            ]
            count = seesol_rh_db.upsert_month(period, empresa, filas)
            totals[f"{period}|{empresa}"] = count
            if count < previas:
                context.log.warning(
                    "RH %s empresa '%s': el reporte trae %d filas y antes había %d "
                    "(¿mes todavía incompleto en SUNAT?)",
                    period,
                    empresa,
                    count,
                    previas,
                )
            context.log.info(
                "RH %s empresa '%s' upserted: %d filas (antes %d)",
                period,
                empresa,
                count,
                previas,
            )

    metadata: dict[str, Any] = {
        "months": len(months),
        "periods": ", ".join(f"{month}-01" for month in months),
        "rows_upserted": sum(totals.values()),
    }
    for clave, n in totals.items():
        metadata[clave] = n

    context.log.info(
        "seesol_rh %s: %d filas en %d meses",
        ", ".join(months),
        sum(totals.values()),
        len(months),
    )
    # MaterializeResult **sin valor**: un ``Output`` con valor pasa por el IO manager
    # por defecto, que no sabe persistir un output asociado a varias particiones y
    # revienta el run ``single_run`` del cron (mes anterior + mes actual). El resumen
    # de filas viaja igual en la metadata del materialization event.
    return MaterializeResult(metadata=metadata)
