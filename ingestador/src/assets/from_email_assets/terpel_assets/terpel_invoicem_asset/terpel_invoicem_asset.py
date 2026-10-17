"""Asset diario del remitente ``invoicem.lubes@terpel.com`` (docs, tickets y reportes).

Para la partición diaria lee de ``emails`` los correos del remitente
``invoicem.lubes@terpel.com`` recibidos **ese día**, toma sus adjuntos de
``email_attachments`` y los reparte por tipo según el nombre del adjunto (o de la
entrada del ZIP, si viene comprimido):

- ``.xlsx`` -> ``from_email_terpel_invoicem_reports`` (Excel ``Reporte abastecimiento``).
- PDFs ``Fact_*`` (sueltos o dentro de un ZIP ``FACTURA(S) ...``) ->
  ``from_email_terpel_invoicem_docs`` (parser ``parser_docs``).
- PDFs ``Reimpresion_*`` / ``ORDEN(ES) DE ENTREGA*`` (sueltos o dentro de un ZIP
  ``ORDENES DE ENTREGA ...``) -> ``from_email_terpel_invoicem_tickets`` (parser de
  tickets **compartido** con ``terpel_tickets_daily``: ``_common.tickets_parser``).
- Imágenes inline (``image00x.png/gif``) y ``.xml`` -> se ignoran.

Es un **upsert total del día** e independiente por tabla: se procesan todos los
correos/adjuntos del día y el reemplazo de cada tabla ocurre al final, en una sola
transacción. No es fail-fast: un ZIP/PDF ilegible se registra como warning y se
continúa con el resto.

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
from assets.from_email_assets.terpel_assets._common.tickets_model import (
    TerpelTicket,
)
from assets.from_email_assets.terpel_assets._common.tickets_parser import (
    parse_ticket_pdf,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.parser_docs import (
    extract_zip_pdf_entries,
    parse_fact_pdf,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.parser_reports import (
    parse_reporte_xlsx,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.resources.db_resource import (
    TerpelInvoicemSqliteResource,
)
from assets.mail_asset.mail_asset import ingest_emails

_LOG_AVANCE_CADA = 50


def clasificar_pdf(filename: str) -> str | None:
    """Tipo de una entrada PDF por su nombre: ``"docs"``, ``"tickets"`` o ``None``.

    - ``docs``: facturas (``Fact_*``).
    - ``tickets``: ``Reimpresion_*`` u ``ORDEN(ES) DE ENTREGA*`` (basta con buscar
      ``orden`` para tolerar las erratas reales ``ORDEN DE ENTRGEA``/``OREDEN...``).
    - ``None``: cualquier otra cosa (XML/CDR de SUNAT, imágenes, notas de crédito
      ``NoCr_*``...), que se ignora.
    """
    name = filename.lower()
    if not name.endswith(".pdf"):
        return None
    if name.startswith("fact_"):
        return "docs"
    if name.startswith("reimpresion_") or "orden" in name:
        return "tickets"
    return None


def _parse_doc(
    docs: list[dict[str, Any]],
    adjunto: dict[str, Any],
    filename: str,
    data_b64: str,
    context: AssetExecutionContext,
) -> None:
    """Parsea una factura ``Fact_*`` y agrega su fila (warning si falla)."""
    try:
        campos = parse_fact_pdf(base64.b64decode(data_b64))
    except Exception as exc:
        context.log.warning(
            "Correo %s, adjunto %s, pdf %s: no se pudo parsear la factura: %s",
            adjunto["email_id"],
            adjunto["filename"],
            filename,
            exc,
        )
        return
    docs.append(
        {
            "filename": filename,
            "observaciones": campos["observaciones"],
            "orden_de_compra": campos["orden_de_compra"],
            "agregado_o_entrega": campos["agregado_o_entrega"],
            "id_attachment": adjunto["id_attachment"],
        }
    )


def _parse_ticket(
    tickets: list[dict[str, Any]],
    adjunto: dict[str, Any],
    filename: str,
    data_b64: str,
    context: AssetExecutionContext,
) -> None:
    """Parsea un PDF de ticket con el parser compartido y agrega su fila."""
    try:
        campos = parse_ticket_pdf(base64.b64decode(data_b64))
        fila = TerpelTicket.model_validate(campos).model_dump()
    except Exception as exc:
        context.log.warning(
            "Correo %s, adjunto %s, pdf %s: no se pudo identificar el ticket: %s",
            adjunto["email_id"],
            adjunto["filename"],
            filename,
            exc,
        )
        return
    tickets.append(
        {
            **fila,
            "id_attachment": adjunto["id_attachment"],
            "filename": filename,
        }
    )


def _parse_reporte(
    reports: list[dict[str, Any]],
    adjunto: dict[str, Any],
    data: bytes,
    context: AssetExecutionContext,
) -> None:
    """Parsea el Excel de abastecimiento y agrega una fila por vuelo."""
    try:
        filas = parse_reporte_xlsx(data)
    except Exception as exc:
        context.log.warning(
            "Correo %s, adjunto %s: no se pudo leer el Excel: %s",
            adjunto["email_id"],
            adjunto["filename"],
            exc,
        )
        return
    for fila in filas:
        reports.append(
            {
                **fila,
                "id_attachment": adjunto["id_attachment"],
                "filename": adjunto["filename"],
            }
        )


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(ingest_emails)],
    backfill_policy=BackfillPolicy.single_run(),
)
def terpel_invoicem_daily(
    context: AssetExecutionContext,
    terpel_invoicem_db: TerpelInvoicemSqliteResource,
) -> None:
    """Alimenta las 3 tablas ``from_email_terpel_invoicem_*`` del día.

    ``partition_days(context)`` devuelve el día de la partición o todos los días del
    rango en un backfill ``single_run``. Por cada día se clasifican los adjuntos del
    remitente invoicelubes en facturas (``docs``), tickets y reportes de abastecimiento.
    """
    total_docs = 0
    total_tickets = 0
    total_reports = 0
    total_adjuntos = 0
    total_correos = 0

    for period in partition_days(context):
        emails = terpel_invoicem_db.select_invoicem_emails(period)
        email_ids = [email["id"] for email in emails]
        attachments = terpel_invoicem_db.select_invoicem_attachments(email_ids)
        context.log.info(
            "Día %s: %d correos de invoicem.lubes@terpel.com y %d adjuntos por procesar",
            period,
            len(emails),
            len(attachments),
        )

        docs: list[dict[str, Any]] = []
        tickets: list[dict[str, Any]] = []
        reports: list[dict[str, Any]] = []

        for procesados, adjunto in enumerate(attachments, start=1):
            if procesados % _LOG_AVANCE_CADA == 0:
                context.log.info(
                    "[%s] %d/%d adjuntos procesados",
                    period,
                    procesados,
                    len(attachments),
                )

            filename = adjunto["filename"]
            low = filename.lower()

            if low.endswith(".xlsx"):
                try:
                    data = base64.b64decode(adjunto["data"])
                except Exception as exc:
                    context.log.warning(
                        "Correo %s, adjunto %s: base64 inválido: %s",
                        adjunto["email_id"],
                        filename,
                        exc,
                    )
                    continue
                _parse_reporte(reports, adjunto, data, context)
                continue

            if low.endswith(".zip"):
                try:
                    entries = extract_zip_pdf_entries(
                        base64.b64decode(adjunto["data"])
                    )
                except Exception as exc:
                    context.log.warning(
                        "Correo %s, adjunto %s: no se pudo leer el ZIP: %s",
                        adjunto["email_id"],
                        filename,
                        exc,
                    )
                    continue
                for entry in entries:
                    tipo = clasificar_pdf(entry["filename"])
                    if tipo == "docs":
                        _parse_doc(
                            docs, adjunto, entry["filename"], entry["data"], context
                        )
                    elif tipo == "tickets":
                        _parse_ticket(
                            tickets, adjunto, entry["filename"], entry["data"], context
                        )
                continue

            tipo = clasificar_pdf(filename)
            if tipo == "docs":
                _parse_doc(docs, adjunto, filename, adjunto["data"], context)
            elif tipo == "tickets":
                _parse_ticket(tickets, adjunto, filename, adjunto["data"], context)

        total_docs += terpel_invoicem_db.upsert_docs_day(period, docs)
        total_tickets += terpel_invoicem_db.upsert_tickets_day(period, tickets)
        total_reports += terpel_invoicem_db.upsert_reports_day(period, reports)
        total_adjuntos += len(attachments)
        total_correos += len(emails)

    context.log.info(
        "Listo: %d docs, %d tickets y %d filas de reporte de %d adjuntos (%d correos)",
        total_docs,
        total_tickets,
        total_reports,
        total_adjuntos,
        total_correos,
    )
