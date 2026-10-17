"""Resource de BD del remitente invoicem.lubes@terpel.com (agnóstico del motor).

Lee los correos/adjuntos **del día** del remitente ``invoicem.lubes@terpel.com`` y hace
el upsert total del día de sus 3 tablas (``from_email_terpel_invoicem_docs``,
``..._tickets`` y ``..._reports``), heredando de ``AbstractDbResource``.
"""

from __future__ import annotations

from typing import Any

from assets._common.abstract_resource import AbstractDbResource
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.models.model import (
    InvoicemDoc,
    InvoicemReport,
    InvoicemTicket,
)
from assets.mail_asset.model import Email, EmailAttachments

# Remitente de los correos con facturas, tickets y reportes de abastecimiento Terpel.
SENDER_INVOICE_LUBES = "invoicem.lubes@terpel.com"


class TerpelInvoicemSqliteResource(AbstractDbResource):
    """Resource que lee los correos/adjuntos del día y upserta docs/tickets/reportes."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, EmailAttachments, InvoicemDoc, InvoicemTicket, InvoicemReport)

    def select_invoicem_emails(self, period: str) -> list[dict[str, Any]]:
        """Correos del día (partición diaria) del remitente de invoicelubes.

        ``period`` es la clave de la partición diaria (``"YYYY-MM-DD"``) y se compara
        contra ``emails.partition_date`` exacta.
        """
        self._ensure_db()
        rows = Email.select(Email.id, Email.subject, Email.header_date).where(
            (Email.partition_date == period)
            & (Email.sender == SENDER_INVOICE_LUBES)
        )
        return [
            {
                "id": row.id,
                "subject": row.subject or "",
                "header_date": row.header_date or "",
            }
            for row in rows
        ]

    def select_invoicem_attachments(
        self, email_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Adjuntos de ``email_attachments`` para los correos dados (con su ``id``)."""
        self._ensure_db()
        if not email_ids:
            return []
        rows = EmailAttachments.select(
            EmailAttachments.id,
            EmailAttachments.email_id,
            EmailAttachments.filename,
            EmailAttachments.data,
        ).where(EmailAttachments.email.in_(email_ids))
        return [
            {
                "id_attachment": row.id,
                "email_id": row.email_id,
                "filename": row.filename,
                "data": row.data,
            }
            for row in rows
        ]

    def upsert_docs_day(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las facturas (docs) del **día** ``period`` por las dadas."""
        return self._replace(
            InvoicemDoc,
            InvoicemDoc.partition_date == period,
            rows,
            {"partition_date": period},
        )

    def upsert_tickets_day(self, period: str, rows: list[dict]) -> int:
        """Reemplaza los tickets del **día** ``period`` por los dados."""
        return self._replace(
            InvoicemTicket,
            InvoicemTicket.partition_date == period,
            rows,
            {"partition_date": period},
        )

    def upsert_reports_day(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las filas de reporte de abastecimiento del **día** ``period``."""
        return self._replace(
            InvoicemReport,
            InvoicemReport.partition_date == period,
            rows,
            {"partition_date": period},
        )
