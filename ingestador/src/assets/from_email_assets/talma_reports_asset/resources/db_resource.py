"""Resource de BD para los reportes Talma (agnóstico del motor).

Lee los correos **del día** de los remitentes de Talma (``facturacion.centralizada
@talma.com.pe``, ``shirley.guerra@talma.com.pe`` y ``facturacion.gestion
@talma.com.pe``) de la tabla ``emails`` (los correos se guardan con partición diaria,
así que la partición diaria filtra por ``partition_date`` exacta), sus adjuntos de
``email_attachments`` (solo los Excel ``.xlsx`` / ``.xls``) y hace **upsert total del
día** en ``from_email_talma_reports``: borra todas las filas del día e inserta las
nuevas. El asset junta las filas de todos los adjuntos del día y hace una sola llamada
por día (todo-o-nada: si algo falla a mitad del día no se toca nada de ese día).
"""

from __future__ import annotations

from typing import Any

from peewee import fn

from assets._common.abstract_resource import AbstractDbResource
from assets.from_email_assets.talma_reports_asset.models.model import TalmaReport
from assets.mail_asset.model import Email, EmailAttachments

# Remitentes de los correos con el Excel de reportes Talma.
TALMA_SENDERS = (
    "facturacion.centralizada@talma.com.pe",
    "shirley.guerra@talma.com.pe",
    "facturacion.gestion@talma.com.pe",
)

# Adjuntos que se procesan: libros de Excel (.xlsx) y los .xls que envía Talma
# (en realidad texto delimitado por tab).
_TALMA_EXTENSIONS = (".xlsx", ".xls")


class TalmaReportSqliteResource(AbstractDbResource):
    """Resource que lee los correos/adjuntos del día y upserta los registros."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, EmailAttachments, TalmaReport)

    def select_talma_emails(self, period: str) -> list[dict[str, Any]]:
        """Correos del día (partición diaria) de los remitentes de Talma.

        ``period`` es la clave de la partición diaria (``"YYYY-MM-DD"``) y se compara
        contra ``emails.partition_date`` exacta. El remitente se compara **sin
distinguir mayúsculas/minúsculas ni espacios**: ``ingest_emails`` guarda el ``From``
        tal cual lo devuelve Gmail (``parseaddr`` conserva el case), así que un match
        exacto dejaría fuera variaciones.
        """
        self._ensure_db()
        senders_norm = [s.strip().lower() for s in TALMA_SENDERS]
        rows = Email.select(Email.id, Email.subject, Email.header_date).where(
            (Email.partition_date == period)
            & (fn.Lower(fn.Trim(Email.sender)).in_(senders_norm))
        )
        return [
            {
                "id": row.id,
                "subject": row.subject or "",
                "header_date": row.header_date or "",
            }
            for row in rows
        ]

    def select_talma_attachments(self, email_ids: list[str]) -> list[dict[str, Any]]:
        """Adjuntos Excel de ``email_attachments`` para los correos dados."""
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
            if row.filename and row.filename.lower().endswith(_TALMA_EXTENSIONS)
        ]

    def upsert_day(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las filas del **día** ``period`` por las dadas.

        Upsert total del día: dentro de una transacción borra todas las filas del día e
        inserta las nuevas (particionado en lotes para no superar el límite de variables
        SQL de SQLite). Devuelve el número de filas insertadas. ``period`` se guarda tal
        cual en ``from_email_talma_reports.partition_date`` (p. ej. ``"2026-08-14"``).
        """
        return self._replace(
            TalmaReport,
            TalmaReport.partition_date == period,
            rows,
            {"partition_date": period},
        )
