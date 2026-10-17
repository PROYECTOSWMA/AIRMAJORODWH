"""Resource de BD para los documentos CEP del correo (agnóstico del motor).

Lee los PDF adjuntos **del día** de los correos de ``fe.corporacion.energetico@gmail.com``
(tabla ``email_attachments``, alimentada por ``ingest_emails``) y hace el upsert total
del día en ``from_email_cep_docs_headers`` / ``from_email_cep_docs_details`` (heredando
de ``AbstractDbResource``; el upsert de cabecera + detalle con FK es propio).
"""

from __future__ import annotations

from typing import Any

from peewee import fn

from assets._common.abstract_resource import AbstractDbResource
from assets._common.db import chunked, db
from assets.from_email_assets.cep_docs_asset.models.model import (
    CepDocDetail,
    CepDocHeader,
)
from assets.mail_asset.model import Email, EmailAttachments

# Remitente de los correos con la factura de combustible de CEP.
CEP_SENDER = "fe.corporacion.energetico@gmail.com"

# Adjuntos que se procesan: solo el PDF de la factura (el correo trae también el XML).
_CEP_EXTENSIONS = (".pdf",)


class CepDocsSqliteResource(AbstractDbResource):
    """Resource que lee los PDF de CEP del día y upserta cabeceras y detalles."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, EmailAttachments, CepDocHeader, CepDocDetail)

    def select_cep_pdf_attachments(self, period: str) -> list[dict[str, Any]]:
        """PDF adjuntos del día de los correos de CEP, **sin repetir** por nombre.

        ``period`` es la clave de la partición diaria (``"YYYY-MM-DD"``) y se compara
        contra ``emails.partition_date`` exacta. El remitente se compara sin distinguir
        mayúsculas/minúsculas ni espacios. El mismo PDF llega a las dos bandejas
        (``jorge.paredes@airmajoro.com`` y ``contabilidad@airmajoro.com``), así que se
        procesa **una sola vez por nombre de archivo**.
        """
        self._ensure_db()
        sender_norm = CEP_SENDER.strip().lower()
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
        vistos: set[str] = set()
        adjuntos: list[dict[str, Any]] = []
        for row in rows:
            filename = row["filename"] or ""
            if not filename.lower().endswith(_CEP_EXTENSIONS) or filename in vistos:
                continue
            vistos.add(filename)
            adjuntos.append(
                {
                    "email_id": row["id"],
                    "id_attachment": row["id_attachment"],
                    "filename": filename,
                    "data": row["data"],
                }
            )
        return adjuntos

    def upsert_day(
        self, period: str, headers: list[dict], details: list[dict]
    ) -> tuple[int, int]:
        """Reemplaza las cabeceras y detalles de ``period`` por los dados.

        Upsert total del día: dentro de una transacción borra **todos** los detalles del
        día y después sus cabeceras, e inserta las nuevas. Cada fila de ``details`` trae
        ``filename`` (la cabecera padre) y aquí se inyecta el FK ``header``;
        ``partition_date`` se inyecta en ambas tablas. Devuelve
        ``(cabeceras, detalles)`` insertados.
        """
        self._ensure_db()
        # Los FKs no tienen pragma de cascade garantizado: se borran primero los
        # detalles del día y después las cabeceras.
        with db.atomic():
            CepDocDetail.delete().where(
                CepDocDetail.partition_date == period
            ).execute()
            CepDocHeader.delete().where(
                CepDocHeader.partition_date == period
            ).execute()

            header_ids: dict[str, int] = {}
            for h in headers:
                row = CepDocHeader.create(**h, partition_date=period)
                header_ids[h["filename"]] = row.id

            if details:
                batch_size = max(
                    1, self._max_variables() // len(CepDocDetail._meta.fields)
                )
                rows_with_fk = [
                    {
                        **{k: v for k, v in d.items() if k != "filename"},
                        "header": header_ids[d["filename"]],
                        "partition_date": period,
                    }
                    for d in details
                ]
                for batch in chunked(rows_with_fk, batch_size):
                    CepDocDetail.insert_many(batch).execute()

        return len(headers), len(details)
