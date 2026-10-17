"""Asset diario de documentos CEP (remitente ``fe.corporacion.energetico@gmail.com``).

Para la partición diaria lee de ``emails`` los correos de
``fe.corporacion.energetico@gmail.com`` (CONSORCIO ENERGÉTICO DEL PERÚ S.A.) recibidos
**ese día**, toma sus adjuntos PDF de ``email_attachments``, parsea cada factura de
combustible (``parse_invoice_pdf``) y upserta la cabecera en
``from_email_cep_docs_headers`` y las filas de la tabla de combustible en
``from_email_cep_docs_details``.

Es un **upsert total del día y fail-fast** (igual que ``adp_reports_daily`` y
``talma_reports_daily``): si un PDF no se puede parsear se lanza
``CepDocsProcessingError`` y cae la partición sin insertar nada (el upsert del día es
todo-o-nada).

Declara ``BackfillPolicy.single_run()``: al materializar un **rango** de días Dagster
hace un único run y la función se invoca **una vez** con todos los días
(``partition_days(context)``), reemplazando las filas de cada día por separado.
"""

import base64
from typing import Any

from dagster import (
    AssetDep,
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    asset,
)

from assets._common.partitions import correos_daily_partitions_def, partition_days
from assets.from_email_assets.cep_docs_asset.parser import parse_invoice_pdf
from assets.from_email_assets.cep_docs_asset.resources.db_resource import (
    CepDocsSqliteResource,
)
from assets.mail_asset.mail_asset import ingest_emails

_LOG_AVANCE_CADA = 50


class CepDocsProcessingError(Exception):
    """Falla al procesar un PDF de CEP: derrumba la materialización de la partición."""


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(ingest_emails)],
    backfill_policy=BackfillPolicy.single_run(),
)
def cep_docs_daily(
    context: AssetExecutionContext,
    cep_docs_db: CepDocsSqliteResource,
) -> None:
    """Alimenta ``from_email_cep_docs_headers`` / ``from_email_cep_docs_details``.

    ``partition_days(context)`` devuelve el día de la partición o todos los días del
    rango en un backfill ``single_run``. Por cada día se parsean los PDF de CEP de sus
    correos. Si un PDF no se puede parsear se lanza ``CepDocsProcessingError``: la
    partición cae y ese día no se toca (el upsert del día es todo-o-nada).
    """
    total_headers = 0
    total_details = 0
    total_adjuntos = 0
    total_correos = 0

    for period in partition_days(context):
        attachments = cep_docs_db.select_cep_pdf_attachments(period)
        emails_procesados = len({a["email_id"] for a in attachments})
        context.log.info(
            "Día %s: %d correos de fe.corporacion.energetico@gmail.com (%d PDF)",
            period,
            emails_procesados,
            len(attachments),
        )

        headers: list[dict[str, Any]] = []
        details: list[dict[str, Any]] = []

        for procesados, adjunto in enumerate(attachments, start=1):
            if procesados % _LOG_AVANCE_CADA == 0:
                context.log.info(
                    "[%s] %d/%d PDF procesados", period, procesados, len(attachments)
                )
            try:
                parsed = parse_invoice_pdf(base64.b64decode(adjunto["data"]))
            except Exception as exc:
                raise CepDocsProcessingError(
                    f"Correo {adjunto['email_id']}, adjunto {adjunto['filename']}: "
                    f"no se pudo parsear el PDF: {exc}"
                ) from exc

            headers.append(
                {
                    **parsed["header"],
                    "id_attachment": adjunto["id_attachment"],
                    "filename": adjunto["filename"],
                }
            )
            for detalle in parsed["details"]:
                details.append({**detalle, "filename": adjunto["filename"]})

        n_headers, n_details = cep_docs_db.upsert_day(period, headers, details)
        total_headers += n_headers
        total_details += n_details
        total_adjuntos += len(attachments)
        total_correos += emails_procesados

    context.log.info(
        "Listo: %d cabeceras y %d detalles de %d PDF (%d correos)",
        total_headers,
        total_details,
        total_adjuntos,
        total_correos,
    )
    return MaterializeResult(
        metadata={
            "headers_inserted": total_headers,
            "details_inserted": total_details,
            "pdfs_procesados": total_adjuntos,
            "emails_procesados": total_correos,
        }
    )
