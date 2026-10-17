"""Resource de BD para los reportes ADP (agnóstico del motor).

Lee los correos/adjuntos **del día** de la remitente ``ladyliz.moreno@adp.com.pe`` y
hace upsert total del día en ``from_email_adp_reports``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from peewee import fn

from assets._common.abstract_resource import AbstractDbResource
from assets.from_email_assets.adp_reports_asset.models.model import AdpReport
from assets.mail_asset.model import Email, EmailAttachments

# Remitente de los correos con el Excel de servicios ADP.
ADP_SENDER = "ladyliz.moreno@adp.com.pe"

# Adjuntos que se procesan: libros de Excel (.xlsx/.xlsm) y los .xls que envía
# ADP (en realidad texto delimitado por tab).
_ADP_EXTENSIONS = (".xlsx", ".xlsm", ".xls")


class AdpReportSqliteResource(AbstractDbResource):
    """Resource que lee los correos/adjuntos del día y upserta los registros."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, EmailAttachments, AdpReport)

    def get_adp_attachments(self, period: str) -> list[dict[str, Any]]:
        """Adjuntos Excel del día de la remitente ADP (lista aplanada).

        ``period`` es la clave de la partición diaria (``"YYYY-MM-DD"``) y se compara
        contra ``emails.partition_date`` exacta. El remitente se compara sin distinguir
        mayúsculas/minúsculas ni espacios.
        """
        self._ensure_db()
        sender_norm = ADP_SENDER.strip().lower()
        rows = (
            Email.select(
                Email.id,
                EmailAttachments.id.alias("id_attachment"),
                EmailAttachments.filename,
                EmailAttachments.data,
            )
            .join(EmailAttachments, on=(EmailAttachments.email == Email.id))
            .where(
                (Email.partition_date == period)
                & (fn.Lower(fn.Trim(Email.sender)) == sender_norm)
            )
            .order_by(Email.id, EmailAttachments.id)
            .dicts()
        )
        return [
            {
                "email_id": row["id"],
                "id_attachment": row["id_attachment"],
                "filename": row["filename"],
                "data": row["data"],
            }
            for row in rows
            if row["filename"] and row["filename"].lower().endswith(_ADP_EXTENSIONS)
        ]

    def upsert_day(self, period: str, rows: list[dict]) -> int:
        """Reemplaza las filas del **día** ``period`` por las dadas.

        ``from_email_adp_reports.partition_date`` es ``DATE``, así que la clave de
        partición (``"YYYY-MM-DD"``) se convierte a ``date`` antes de guardarla.
        """
        period_date = date.fromisoformat(period[:10])
        return self._replace(
            AdpReport,
            AdpReport.partition_date == period_date,
            rows,
            {"partition_date": period_date},
        )
