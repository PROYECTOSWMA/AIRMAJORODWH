"""Asset mensual del reporte de estadísticas de vuelos (SISA).

Para el mes de la partición consulta ``FlightReportsResource.get_report`` (el
``EXECUTE`` de ``USP_ESTADISTICAS_VUELOS_PERIODO`` con ``@OpcionReporte=4``),
valida las filas contra el modelo pydantic (réplica de la tabla) y hace un
**upsert total** de la partición vía ``FlightReportsSqliteResource.upsert_report``:
borra todas las filas del mes e inserta las nuevas. El asset no tiene padre y la
tabla ``flight_reports`` no tiene relación con ningún otro dato del proyecto.

Declara ``BackfillPolicy.single_run()``: el rango completo de un backfill se
materializa en **un único run** (``context.partition_keys`` trae todos los meses)
y la función lo recorre mes a mes con ``partition_days``.
"""

from typing import Any

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    MonthlyPartitionsDefinition,
    asset,
)

from assets._common.partitions import partition_days
from assets.from_sql_majoro_assets.flight_reports_asset.models.pydantic_model import (
    FlightReportRow,
)
from assets.from_sql_majoro_assets.flight_reports_asset.resources.api_resource.flight_reports_resource import (
    FlightReportsResource,
)
from assets.from_sql_majoro_assets.flight_reports_asset.resources.db_resource import (
    FlightReportsSqliteResource,
)

monthly_partitions_def = MonthlyPartitionsDefinition(
    start_date="2026-01-01",
    end_offset=1,  # incluye el mes en curso (p. ej. 2026-08-01 aunque no haya terminado)
)


def procesar_mes(
    context: AssetExecutionContext,
    flight_reports: FlightReportsResource,
    flight_reports_db: FlightReportsSqliteResource,
    period: str,
) -> dict[str, Any]:
    """Consulta el reporte de **un** mes y hace el upsert total de esa partición.

    ``period`` es la clave de la partición mensual (``"2026-08-01"``). Devuelve el
    resumen del mes (período y filas upserteadas) para la metadata del
    materialization event.
    """
    rows = flight_reports.get_report(period)
    filas = [FlightReportRow.model_validate(r).model_dump() for r in rows]
    count = flight_reports_db.upsert_report(period, filas)
    context.log.info("Reporte de vuelos %s: %d filas upserteadas", period, count)
    return {"period": period, "rows_upserted": count}


@asset(
    name="flight_reports_asset",
    group_name="from_sql_majoro",
    partitions_def=monthly_partitions_def,
    backfill_policy=BackfillPolicy.single_run(),
    description=(
        "Reporte de estadísticas de vuelos de SISA (USP_ESTADISTICAS_VUELOS_PERIODO, "
        "OpcionReporte=4) -> tabla `flight_reports` de db.sqlite (partición mensual)."
    ),
)
def flight_reports_asset(
    context: AssetExecutionContext,
    flight_reports: FlightReportsResource,
    flight_reports_db: FlightReportsSqliteResource,
) -> MaterializeResult:
    """Alimenta ``flight_reports`` con el reporte de vuelos de los meses del run.

    Con ``BackfillPolicy.single_run()`` un backfill de un rango va en **un único run**
    y esta función se invoca **una vez** con todos los meses de
    ``partition_days(context)``; en una materialización normal el run trae un solo mes.
    Cada mes se consulta y se upsertea por separado (todo-o-nada por mes).

    Devuelve ``MaterializeResult`` **sin valor**: un ``Output`` con valor pasaría por el
    IO manager por defecto, que no sabe persistir un output asociado a varias
    particiones y tumbaría el run del backfill (después de escribir los datos).
    """
    meses = partition_days(context)

    resumenes = [procesar_mes(context, flight_reports, flight_reports_db, mes) for mes in meses]

    # Agregado del run: ``rows_upserted`` y las filas por mes (``rows_by_month``).
    totales: dict[str, Any] = {}
    for resumen in resumenes:
        for clave, valor in resumen.items():
            if clave == "period":
                continue
            totales[clave] = totales.get(clave, 0) + valor

    context.log.info(
        "Listo: %d mes(es) (%s), %d filas upserteadas",
        len(meses),
        ", ".join(meses),
        totales["rows_upserted"],
    )

    return MaterializeResult(
        metadata={
            **totales,
            "months": MetadataValue.json(meses),
            "months_processed": len(meses),
            "rows_by_month": MetadataValue.json(
                {resumen["period"]: resumen["rows_upserted"] for resumen in resumenes}
            ),
        }
    )
