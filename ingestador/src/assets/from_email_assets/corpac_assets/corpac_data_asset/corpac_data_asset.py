"""Asset diario de datos del PDF CORPAC de servicios (cabeceras + detalles).

Para cada partición diaria lee de ``from_email_corpac_files`` los archivos ``01-*.pdf``
(la factura de detalle de servicios, alimentada por ``corpac_files_daily``) **una sola
copia por documento** (el mismo PDF entra hasta 16 veces: los 2 buzones del remitente y
las respuestas del hilo), los parsea con ``parse_invoice_pdf`` y upserta el resultado en
``from_email_corpac_headers`` / ``from_email_corpac_details``.

Es un **upsert total del día y fail-fast** (igual que ``corpac_files_daily``):
si un PDF no se puede parsear se lanza ``CorpacDataProcessingError`` y cae la
partición sin insertar nada (el upsert solo ocurre al final, en una sola
transacción) para que el re-run vuelva a procesar todo el día.

Declara ``BackfillPolicy.single_run()``: al lanzar un backfill de un rango, Dagster **no** invoca
la función una vez por día, sino **una vez** con el rango completo (``context.partition_keys``).
Además, en un run de rango ``context.partition_key`` lanza ``DagsterInvariantViolationError``.

Por eso todo el trabajo de **un** día vive en ``procesar_dia`` y el asset se limita a
recorrer ``partition_days(context)``, que devuelve un solo día en una materialización
normal (el cron diario) y los N días del trozo en un run de backfill, cada uno con su
upsert total (todo-o-nada por día).
"""

import base64
from typing import Any

from dagster import (
    AssetDep,
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets._common.partitions import correos_daily_partitions_def, partition_days
from assets.from_email_assets.corpac_assets.corpac_data_asset.parser import parse_invoice_pdf
from assets.from_email_assets.corpac_assets.corpac_data_asset.resources.db_resource import CorpacDataSqliteResource
from assets.from_email_assets.corpac_assets.corpac_files_asset.corpac_files_asset import corpac_files_daily

# Misma definición diaria que ``ingest_emails``/``corpac_files_daily``.
daily_partitions_def = correos_daily_partitions_def

_LOG_AVANCE_CADA = 50


class CorpacDataProcessingError(Exception):
    """Falla al procesar un PDF CORPAC: derrumba la materialización de la partición."""


def procesar_dia(
    context: AssetExecutionContext,
    corpac_data_db: CorpacDataSqliteResource,
    period: str,
) -> dict[str, Any]:
    """Parsea los PDFs ``01-*.pdf`` de **un** día y los upsertea (todo-o-nada).

    ``period`` es la clave de la partición diaria (p. ej. ``"2026-08-12"``). Por cada PDF
    **único** del día —``select_corpac_pdfs`` entrega una sola copia por ``filename``— se
    parsea la factura de servicios (cabecera + filas de detalle, una cabecera por
    sección/aeronave). Si un PDF falla se lanza ``CorpacDataProcessingError``: ese día
    cae y no se inserta nada suyo (el upsert solo se hace al final, en una sola
    transacción). Devuelve el resumen del día para la metadata del materialization event
    (incluidas las copias del mismo documento que se omitieron).
    """
    files = corpac_data_db.select_corpac_pdfs(period)
    # Copias del mismo documento que el select ya descartó (``copies`` = nº de copias
    # que hay en ``from_email_corpac_files``): van en la metadata para que la
    # materialización muestre cuánta repetición de correo se está absorbiendo.
    omitidos = sum(max(0, int(archivo.get("copies", 1)) - 1) for archivo in files)
    context.log.info(
        "Día %s: %d PDFs 01-* por procesar (%d copias del mismo documento omitidas)",
        period,
        len(files),
        omitidos,
    )

    headers: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    for procesados, archivo in enumerate(files, start=1):
        if procesados % _LOG_AVANCE_CADA == 0:
            context.log.info(
                "[%s] %d/%d PDFs procesados",
                period,
                procesados,
                len(files),
            )

        try:
            parsed = parse_invoice_pdf(base64.b64decode(archivo["data"]))
        except Exception as exc:
            raise CorpacDataProcessingError(
                f"Archivo {archivo['filename']}: no se pudo parsear el PDF: {exc}"
            ) from exc

        # Una factura puede tener varias secciones (una por aeronave): cada
        # sección es una cabecera con su matrícula/tipo/PMD.
        for i, seccion in enumerate(parsed["headers"]):
            headers.append(
                {
                    **seccion,
                    "file_id": archivo["id"],
                    "filename": archivo["filename"],
                    "_section": i,
                }
            )
        for detalle in parsed["details"]:
            details.append({**detalle, "filename": archivo["filename"]})

    n_headers, n_details = corpac_data_db.upsert_day(period, headers, details)
    context.log.info(
        "Día %s: %d cabeceras y %d detalles insertados de %d PDFs",
        period,
        n_headers,
        n_details,
        len(files),
    )

    metadata: dict[str, Any] = {
        "period": period,
        "pdfs_procesados": len(files),
        "pdfs_duplicados_omitidos": omitidos,
        "headers_inserted": n_headers,
        "details_inserted": n_details,
    }

    return metadata


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(corpac_files_daily)],
    backfill_policy=BackfillPolicy.single_run(),
)
def corpac_data_daily(
    context: AssetExecutionContext,
    corpac_data_db: CorpacDataSqliteResource,
) -> MaterializeResult:
    """Alimenta ``from_email_corpac_headers`` y ``from_email_corpac_details``.

    Con ``BackfillPolicy.single_run()`` un backfill de un rango va en **un único run** y esta
    función se invoca **una vez** con todos los días de ``partition_days(context)``; en la
    materialización diaria del cron el run trae un solo día. Cada día se parsea y se upsertea por
    separado (todo-o-nada por día), así que re-lanzar el run no duplica nada y un PDF roto solo
    tumba el run, no los días que ya se insertaron.

    Devuelve ``MaterializeResult`` **sin valor**: un ``Output`` con valor pasaría por el IO
    manager por defecto, que no sabe persistir un output asociado a varias particiones y
    tumbaría el run del backfill (después de escribir los datos). El resumen agregado viaja
    en la metadata del materialization event.
    """

    dias = partition_days(context)

    resumenes = [procesar_dia(context, corpac_data_db, dia) for dia in dias]

    totales = {
        clave: sum(resumen[clave] for resumen in resumenes)
        for clave in (
            "pdfs_procesados",
            "pdfs_duplicados_omitidos",
            "headers_inserted",
            "details_inserted",
        )
    }
    context.log.info(
        "Listo: %d día(s) (%s), %d PDFs (%d copias omitidas), %d cabeceras y %d detalles",
        len(dias),
        ", ".join(dias),
        totales["pdfs_procesados"],
        totales["pdfs_duplicados_omitidos"],
        totales["headers_inserted"],
        totales["details_inserted"],
    )

    return MaterializeResult(
        metadata={
            **totales,
            "days": MetadataValue.json(dias),
            "days_processed": len(dias),
            "pdfs_by_day": MetadataValue.json(
                {r["period"]: r["pdfs_procesados"] for r in resumenes}
            ),
        }
    )
