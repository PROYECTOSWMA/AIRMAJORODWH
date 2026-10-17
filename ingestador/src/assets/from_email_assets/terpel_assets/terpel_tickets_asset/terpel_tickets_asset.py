"""Asset diario de tickets Terpel (remitente ticketslima@exolum.com).

Para la partición diaria lee de ``emails`` los correos del remitente
``ticketslima@exolum.com`` recibidos **ese día**, toma sus adjuntos de
``email_attachments``, parsea cada PDF de ticket y upserta una fila por ticket en
``from_email_terpel_tickets_tickets``.

Es un **upsert total del día y fail-fast** (igual que ``corpac_files_daily``): si un
PDF no permite identificar los campos requeridos (O. ENTREGA, ESTACIÓN, MATRÍCULA...)
se lanza ``TerpelProcessingError`` y cae la partición sin insertar nada (el upsert del
día es todo-o-nada).

Declara ``BackfillPolicy.single_run()``: al materializar un **rango** de días Dagster
hace un único run y la función se invoca **una vez** con todos los días
(``partition_days(context)``), reemplazando los tickets de cada día por separado.
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
from assets.from_email_assets.terpel_assets._common.tickets_model import (
    TerpelTicket,
)
from assets.from_email_assets.terpel_assets._common.tickets_parser import (
    parse_ticket_pdf,
)
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.resources.db_resource import (
    TerpelSqliteResource,
)
from assets.mail_asset.mail_asset import ingest_emails

_LOG_AVANCE_CADA = 50


class TerpelProcessingError(Exception):
    """Falla al procesar un ticket Terpel: derrumba la materialización de la partición."""


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(ingest_emails)],
    backfill_policy=BackfillPolicy.single_run(),
)
def terpel_tickets_daily(
    context: AssetExecutionContext,
    terpel_db: TerpelSqliteResource,
) -> None:
    """Alimenta ``from_email_terpel_tickets_tickets`` con los tickets de los correos del día.

    ``partition_days(context)`` devuelve el día de la partición o todos los días del
    rango en un backfill ``single_run``. Por cada día se parsean los PDFs de los correos
    del remitente de tickets. Si un PDF no permite identificar los campos requeridos se
    lanza ``TerpelProcessingError``: la partición cae y ese día no se toca.
    """
    total_tickets = 0
    total_adjuntos = 0
    total_correos = 0

    for period in partition_days(context):
        emails = terpel_db.select_terpel_emails(period)
        email_ids = [email["id"] for email in emails]
        attachments = terpel_db.select_terpel_attachments(email_ids)
        context.log.info(
            "Día %s: %d correos de ticketslima@exolum.com y %d adjuntos por procesar",
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
                ticket = parse_ticket_pdf(base64.b64decode(adjunto["data"]))
            except Exception as exc:
                raise TerpelProcessingError(
                    f"Correo {adjunto['email_id']}, adjunto {adjunto['filename']}: "
                    f"no se pudo identificar el ticket: {exc}"
                ) from exc

            fila = TerpelTicket.model_validate(ticket).model_dump()
            filas.append(
                {
                    **fila,
                    "id_attachment": adjunto["id_attachment"],
                    "filename": adjunto["filename"],
                }
            )

        total_tickets += terpel_db.upsert_day(period, filas)
        total_adjuntos += len(attachments)
        total_correos += len(emails)

    context.log.info(
        "Listo: %d tickets insertados de %d adjuntos (%d correos)",
        total_tickets,
        total_adjuntos,
        total_correos,
    )
