"""Asset diario de reportes Talma (remitentes facturacion.centralizada@talma.com.pe,
shirley.guerra@talma.com.pe y facturacion.gestion@talma.com.pe).

Para la partición diaria lee de ``emails`` los correos de los remitentes de Talma
recibidos **ese día** (los correos se guardan con partición diaria), toma sus adjuntos
de ``email_attachments`` (solo los Excel ``.xlsx`` / ``.xls``), parsea cada tabla
(cabecera en A4:Y4, datos hacia abajo hasta que la columna D ``RSIR`` quede en
blanco) y upserta una fila por registro en ``from_email_talma_reports``.

Es un **upsert total del día y fail-fast** (igual que ``adp_reports_daily``): si un
Excel no permite identificar la cabecera requerida se lanza ``TalmaProcessingError`` y
cae la partición sin insertar nada (el upsert del día es todo-o-nada).

Declara ``BackfillPolicy.single_run()``: al materializar un **rango** de días (carga
inicial) Dagster hace un único run y la función se invoca **una vez** con todos los
días (``partition_days(context)``), reemplazando las filas de cada día por separado.
"""

import base64
from typing import Any

from dagster import (
    AssetDep,
    AssetExecutionContext,
    BackfillPolicy,
    asset,
)

from assets._common.partitions import correos_daily_partitions_def, partition_days
from assets.from_email_assets.talma_reports_asset.models.pydantic_model import (
    TalmaReport,
)
from assets.from_email_assets.talma_reports_asset.parser import (
    parse_report_data,
)
from assets.from_email_assets.talma_reports_asset.resources.db_resource import (
    TalmaReportSqliteResource,
)
from assets.mail_asset.mail_asset import ingest_emails

_LOG_AVANCE_CADA = 50


class TalmaProcessingError(Exception):
    """Falla al procesar un Excel Talma: derrumba la materialización de la partición."""


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(ingest_emails)],
    backfill_policy=BackfillPolicy.single_run(),
)
def talma_reports_daily(
    context: AssetExecutionContext,
    talma_reports_db: TalmaReportSqliteResource,
) -> None:
    """Alimenta ``from_email_talma_reports`` con los registros de los correos del día.

    ``partition_days(context)`` devuelve el día de la partición (p. ej. ``"2026-08-14"``)
    o todos los días del rango cuando la materialización es un backfill ``single_run``.
    Por cada día se parsean los Excel de sus correos. Si un Excel no permite
    identificar la cabecera se lanza ``TalmaProcessingError``: la partición cae y ese
    día no se toca (el upsert del día es todo-o-nada).
    """
    total_registros = 0
    total_adjuntos = 0
    total_correos = 0

    for period in partition_days(context):
        emails = talma_reports_db.select_talma_emails(period)
        email_ids = [email["id"] for email in emails]
        attachments = talma_reports_db.select_talma_attachments(email_ids)
        context.log.info(
            "Día %s: %d correos de Talma y %d adjuntos Excel por procesar",
            period,
            len(emails),
            len(attachments),
        )

        filas: list[dict[str, Any]] = []

        for procesados, adjunto in enumerate(attachments, start=1):
            if procesados % _LOG_AVANCE_CADA == 0:
                context.log.info(
                    "[%s] %d/%d adjuntos procesados",
                    period,
                    procesados,
                    len(attachments),
                )

            try:
                registros = parse_report_data(base64.b64decode(adjunto["data"]))
            except Exception as exc:
                raise TalmaProcessingError(
                    f"Correo {adjunto['email_id']}, adjunto {adjunto['filename']}: "
                    f"no se pudo leer la tabla del Excel: {exc}"
                ) from exc

            for registro in registros:
                fila = TalmaReport.model_validate(registro).model_dump()
                filas.append(
                    {
                        **fila,
                        "id_attachment": adjunto["id_attachment"],
                        "filename": adjunto["filename"],
                    }
                )

        total_registros += talma_reports_db.upsert_day(period, filas)
        total_adjuntos += len(attachments)
        total_correos += len(emails)

    context.log.info(
        "Listo: %d registros insertados de %d adjuntos (%d correos)",
        total_registros,
        total_adjuntos,
        total_correos,
    )
