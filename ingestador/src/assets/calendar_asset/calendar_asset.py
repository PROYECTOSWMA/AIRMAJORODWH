from datetime import date, timedelta
from typing import Any

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    WeeklyPartitionsDefinition,
    asset,
)

from assets._common.partitions import partition_days
from assets.calendar_asset.models.pydantic_model import CalendarRow
from assets.calendar_asset.resources.api_resource.calendar_resource import (
    CalendarApiError,
    CalendarApiResource,
)
from assets.calendar_asset.resources.api_resource.constants import MONTH_NAMES
from assets.calendar_asset.resources.db_resource import CalendarSqliteResource

# Partición semanal desde el 2025-10-01; ``day_offset=1`` hace que la semana
# empiece en lunes (coincide con ``week_number`` ISO) y ``end_offset=1``
# incluye la semana en curso. El asset no agrega fechas posteriores a hoy.
weekly_partitions_def = WeeklyPartitionsDefinition(
    start_date="2025-10-01",
    day_offset=1,
    end_offset=1,
)


def procesar_semana(
    context: AssetExecutionContext,
    calendar_api: CalendarApiResource,
    calendar_db: CalendarSqliteResource,
    period: str,
    cache_mes: dict[tuple[int, int], dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    start = date.fromisoformat(period)
    end = start + timedelta(days=7)
    hoy = date.today()

    fechas = [
        start + timedelta(days=i)
        for i in range(7)
        if start + timedelta(days=i) <= hoy
    ]
    context.log.info(
        "calendar %s: ventana [%s, %s), %d fechas <= hoy (%s)",
        period,
        start,
        end,
        len(fechas),
        hoy,
    )

    # Meses que toca la ventana (en orden y sin repetir): se piden una sola vez por run.
    meses = list(dict.fromkeys((f.year, f.month) for f in fechas))
    for clave_mes in meses:
        if clave_mes in cache_mes:
            continue
        try:
            cache_mes[clave_mes] = calendar_api.get_month(*clave_mes)
        except CalendarApiError as exc:
            # No tumbamos el run: el upsert es todo-o-nada por semana y reescribe la
            # ventana completa, así que con un mes sin datos se omite la semana entera.
            context.log.warning(
                "calendar %s: se omite la semana, sin tipo de cambio de %d-%02d "
                "tras los reintentos de la API (%s)",
                period,
                *clave_mes,
                exc,
            )
            return {
                "period": period,
                "rows_upserted": 0,
                "missing_api_dates": [f.isoformat() for f in fechas],
                "missing_api_dates_count": len(fechas),
                "skipped": True,
                "skip_reason": f"{clave_mes[0]}-{clave_mes[1]:02d}: {exc}",
            }
        context.log.info(
            "calendar %s: tipo de cambio de %s-%02d -> %d días",
            period,
            *clave_mes,
            len(cache_mes[clave_mes]),
        )

    filas: list[dict[str, Any]] = []
    sin_dato: list[str] = []
    for f in fechas:
        dato = cache_mes[(f.year, f.month)].get(f.isoformat())
        if not dato:
            sin_dato.append(f.isoformat())
            continue
        fila = CalendarRow.model_validate(
            {
                "date": f.isoformat(),
                "year": f.year,
                "month": f.month,
                "month_name": MONTH_NAMES[f.month - 1],
                "day": f.day,
                "week_number": f.isocalendar()[1],
                "exchange_rate_sale": dato.get("venta"),
                "exchange_rate_purchase": dato.get("compra"),
            }
        ).model_dump()
        filas.append(fila)

    count = calendar_db.upsert_week(start, end, filas)
    context.log.info(
        "calendar %s upserted: %d filas (%d días sin dato en la API)",
        period,
        count,
        len(sin_dato),
    )

    return {
        "period": period,
        "rows_upserted": count,
        "missing_api_dates": sin_dato,
        "missing_api_dates_count": len(sin_dato),
        "skipped": False,
        "skip_reason": None,
    }


@asset(
    partitions_def=weekly_partitions_def,
    backfill_policy=BackfillPolicy.single_run(),
)
def calendar_weekly(
    context: AssetExecutionContext,
    calendar_api: CalendarApiResource,
    calendar_db: CalendarSqliteResource,
) -> MaterializeResult:
    """Alimenta ``dwh_calendar`` con el tipo de cambio de las semanas del run.

    Con ``BackfillPolicy.single_run()`` un backfill de un rango va en **un único run** y esta
    función se invoca **una vez** con todas las semanas de ``partition_days(context)``; en una
    materialización normal el run trae una sola semana. Cada semana se upsertea por separado
    (todo-o-nada por semana).

    Devuelve ``MaterializeResult`` **sin valor**: un ``Output`` con valor pasaría por el IO
    manager por defecto, que no sabe persistir un output asociado a varias particiones y tumbaría
    el run del backfill (después de escribir los datos).
    """
    semanas = partition_days(context)

    # Caché de meses de la API compartida por todo el run: con varias semanas, los meses
    # repetidos se piden una sola vez.
    cache_mes: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}

    resumenes = [
        procesar_semana(context, calendar_api, calendar_db, semana, cache_mes)
        for semana in semanas
    ]

    totales = {
        clave: sum(resumen[clave] for resumen in resumenes)
        for clave in ("rows_upserted", "missing_api_dates_count")
    }
    missing = [
        fecha for resumen in resumenes for fecha in resumen["missing_api_dates"]]
    omitidas = {
        resumen["period"]: resumen["skip_reason"]
        for resumen in resumenes
        if resumen["skipped"]
    }
    context.log.info(
        "Listo: %d semana(s) (%s), %d filas upserteadas (%d fechas sin dato en la API, "
        "%d semana(s) omitida(s) por fallos de la API)",
        len(semanas),
        ", ".join(semanas),
        totales["rows_upserted"],
        len(missing),
        len(omitidas),
    )

    return MaterializeResult(
        metadata={
            **totales,
            "weeks": MetadataValue.json(semanas),
            "weeks_processed": len(semanas),
            "weeks_skipped": len(omitidas),
            "skipped_weeks": MetadataValue.json(omitidas),
            "rows_by_week": MetadataValue.json(
                {resumen["period"]: resumen["rows_upserted"]
                    for resumen in resumenes}
            ),
            "missing_api_dates": MetadataValue.json(missing),
        }
    )
