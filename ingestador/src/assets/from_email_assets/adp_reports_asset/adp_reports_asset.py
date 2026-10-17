"""Asset diario de servicios ADP (remitente ladyliz.moreno@adp.com.pe).

Para la partición diaria lee de ``emails`` los correos de la remitente
``ladyliz.moreno@adp.com.pe`` (tabla alimentada por ``ingest_emails``) recibidos
**ese día**, toma sus adjuntos de ``email_attachments`` (solo los Excel ``.xlsx`` /
``.xlsm``), parsea cada tabla y upserta una fila por registro en
``from_email_adp_reports``.

Es un **upsert total del día y fail-fast** (igual que ``talma_reports_daily``): si un
Excel no permite identificar la cabecera requerida se lanza ``AdpProcessingError`` y
cae la partición sin insertar nada (el upsert del día es todo-o-nada).

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
    asset,
)

from assets._common.partitions import correos_daily_partitions_def, partition_days
from assets.from_email_assets.adp_reports_asset.models.pydantic_model import (
    AdpReport,
)
from assets.from_email_assets.adp_reports_asset.parser import (
    parse_report_data,
)
from assets.from_email_assets.adp_reports_asset.resources.db_resource import (
    AdpReportSqliteResource,
)
from assets.mail_asset.mail_asset import ingest_emails

_LOG_AVANCE_CADA = 50


class AdpProcessingError(Exception):
    """Falla al procesar un Excel ADP: derrumba la materialización de la partición."""


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(ingest_emails)],
    backfill_policy=BackfillPolicy.single_run(),
)
def adp_reports_daily(
    context: AssetExecutionContext,
    adp_reports_db: AdpReportSqliteResource,
) -> None:
    """Alimenta ``from_email_adp_reports`` con los registros de los correos del día.

    ``partition_days(context)`` devuelve el día de la partición o todos los días del
    rango en un backfill ``single_run``. Por cada día se parsean los Excel de los
    correos de la remitente ADP. Si un Excel no permite identificar la cabecera se
    lanza ``AdpProcessingError``: la partición cae y ese día no se toca.
    """
    total_registros = 0
    total_adjuntos = 0
    total_correos = 0

    for period in partition_days(context):
        attachments = adp_reports_db.get_adp_attachments(period)
        emails_procesados = len({adjunto["email_id"] for adjunto in attachments})
        context.log.info(
            "Día %s: %d correos de ladyliz.moreno@adp.com.pe (%d adjuntos Excel)",
            period,
            emails_procesados,
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
                raise AdpProcessingError(
                    f"Correo {adjunto['email_id']}, adjunto {adjunto['filename']}: "
                    f"no se pudo leer la tabla del Excel: {exc}"
                ) from exc

            for registro in registros:
                try:
                    fila = AdpReport.model_validate(registro).model_dump()
                except Exception as exc:
                    raise AdpProcessingError(
                        f"Correo {adjunto['email_id']}, adjunto {adjunto['filename']}: "
                        f"los datos no cumplen la estructura esperada "
                        f"(fila {registro!r}): {exc}"
                    ) from exc
                filas.append(
                    {
                        **fila,
                        "id_attachment": adjunto["id_attachment"],
                        "filename": adjunto["filename"],
                    }
                )

        total_registros += adp_reports_db.upsert_day(period, filas)
        total_adjuntos += len(attachments)
        total_correos += emails_procesados

    context.log.info(
        "Listo: %d registros insertados de %d adjuntos (%d correos)",
        total_registros,
        total_adjuntos,
        total_correos,
    )
