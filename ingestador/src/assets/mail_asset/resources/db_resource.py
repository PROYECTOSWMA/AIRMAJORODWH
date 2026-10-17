"""Resource de BD para correos y adjuntos (agnóstico del motor, append-only).

Hereda de ``AbstractDbResource``: solo declara las tablas del modelo de correo y
sus métodos de lectura/append.
"""

from __future__ import annotations

from assets._common.abstract_resource import AbstractDbResource
from assets.mail_asset.model import Email, EmailAttachments


class DbResource(AbstractDbResource):
    """Resource que lee correos (Gmail) y **agrega** ``emails``/``email_attachments``.

    Es append-only puro: ``append_emails``/``append_email_attachments`` nunca borran
    ni actualizan lo ya insertado (no usan ``_replace``), solo insertan lo que tenga
    un ``id`` nuevo. ``existing_email_ids`` es lo que permite que el asset le pida a
    Gmail únicamente los correos que aún no están en ``emails``.
    """

    def _tables(self) -> tuple[type, ...]:
        return (Email, EmailAttachments)

    def existing_email_ids(self, ids: list[str]) -> set[str]:
        """Ids de ``emails`` que ya están guardados (para no volver a bajarlos).

        Consulta por lotes (``id IN (...)``) contra la clave primaria, así que es
        barata incluso con miles de ids. El asset la usa para pedirle a Gmail solo
        los correos que faltan.
        """
        self._ensure_db()
        return {k[0] for k in self._existing_keys(Email, "id", list(ids), ("id",))}

    def append_emails(self, partition_date: str, emails: list[dict]) -> int:
        """Agrega **solo** los correos cuyo ``id`` no exista (append-only).

        A diferencia de un upsert clásico, NO borra ni actualiza los correos ya
        insertados:
        una vez que un correo entra en ``emails`` permanece (aunque se vuelva a
        materializar la misma partición o el mismo correo reaparezca en otra).
        Esto es lo que permite que las tablas ``from_email`` tengan una Foreign
        Key a ``emails`` sin que un re-upsert borre en cascada lo ya
        materializado. Devuelve el número de correos insertados.

        Nota: como no se borra, un correo ya presente conserva su
        ``partition_date`` original; no se reubica a la partición de la corrida.
        """
        self._ensure_db()
        if not emails:
            return 0

        rows = [
            {
                "id": e["id"],
                "partition_date": partition_date,
                "mailbox": e.get("mailbox", ""),
                "sender": e.get("sender", ""),
                "subject": e.get("subject", ""),
                "body": e.get("body", ""),
                "thread_id": e.get("thread_id"),
                "header_date": e.get("header_date"),
                "received_date": e.get("received_date"),
            }
            for e in emails
        ]
        existing = self._existing_keys(Email, "id", [e["id"] for e in emails], ("id",))
        return self._insert_new(Email, rows, ("id",), existing)

    def read_emails(self, partition_date: str) -> list[dict]:
        self._ensure_db()
        rows = Email.select().where(Email.partition_date == partition_date)
        return [
            {
                "id": row.id,
                "partition_date": row.partition_date,
                "mailbox": row.mailbox or "",
                "sender": row.sender or "",
                "subject": row.subject or "",
                "body": row.body or "",
                "thread_id": row.thread_id,
                "header_date": row.header_date,
                "received_date": row.received_date,
            }
            for row in rows
        ]

    def append_email_attachments(
        self, partition_date: str, emails: list[dict]
    ) -> int:
        """Inserta **solo** los adjuntos que aún no existan (append-only).

        No borra los adjuntos ya guardados: el ``id`` autoincremental de
        ``email_attachments`` queda estable entre corridas, de modo que quien lo
        referencie (``from_email_terpel_invoicem_docs.id_attachment``) no queda huérfano. El dedupe
        es por ``(email_id, filename)``; dentro de una misma corrida también se
        descartan repeticiones. Devuelve el número de adjuntos insertados.

        ``partition_date`` se mantiene en la firma por compatibilidad con el
        asset; ya no se usa para borrar (los adjuntos no se borran).
        """
        self._ensure_db()
        if not emails:
            return 0

        rows = [
            {
                "email": e["id"],
                "filename": att.get("filename", ""),
                "data": att.get("data", ""),
            }
            for e in emails
            for att in (e.get("attachments") or [])
        ]
        existing = self._existing_keys(
            EmailAttachments,
            "email",
            [e["id"] for e in emails],
            ("email_id", "filename"),
        )
        return self._insert_new(
            EmailAttachments, rows, ("email", "filename"), existing
        )
