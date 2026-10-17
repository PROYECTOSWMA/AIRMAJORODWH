"""Resource de BD para los tickets Terpel (agnóstico del motor).

Lee los correos/adjuntos **del día** del remitente ``ticketslima@exolum.com`` y hace el
upsert total del día en ``from_email_terpel_tickets_tickets`` (heredando de
``AbstractDbResource``).
"""

from __future__ import annotations

from typing import Any

from assets._common.abstract_resource import AbstractDbResource
from assets.mail_asset.model import Email, EmailAttachments
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.models.model import TerpelTicket

# Remitente de los correos con tickets de entrega de combustible Terpel.
TICKETS_SENDER = "ticketslima@exolum.com"


class TerpelSqliteResource(AbstractDbResource):
    """Resource que lee los correos/adjuntos del día y upserta los tickets."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, EmailAttachments, TerpelTicket)

    def select_terpel_emails(self, period: str) -> list[dict[str, Any]]:
        """Correos del día (partición diaria) del remitente de tickets Terpel.

        ``period`` es la clave de la partición diaria (``"YYYY-MM-DD"``) y se compara
        contra ``emails.partition_date`` exacta.
        """
        self._ensure_db()
        rows = Email.select(Email.id, Email.subject, Email.header_date).where(
            (Email.partition_date == period)
            & (Email.sender == TICKETS_SENDER)
        )
        return [
            {
                "id": row.id,
                "subject": row.subject or "",
                "header_date": row.header_date or "",
            }
            for row in rows
        ]

    def select_terpel_attachments(self, email_ids: list[str]) -> list[dict[str, Any]]:
        """Adjuntos de ``email_attachments`` para los correos dados."""
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
                "email_id": row.email_id,
                "id_attachment": row.id,
                "filename": row.filename,
                "data": row.data,
            }
            for row in rows
        ]

    def upsert_day(self, period: str, rows: list[dict]) -> int:
        """Reemplaza los tickets del **día** ``period`` por los dados."""
        return self._replace(
            TerpelTicket,
            TerpelTicket.partition_date == period,
            rows,
            {"partition_date": period},
        )
