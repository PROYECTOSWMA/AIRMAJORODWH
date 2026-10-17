
from __future__ import annotations

from datetime import datetime, timezone

from email import policy, utils

from email.parser import BytesParser

import base64
from pathlib import Path
from typing import Any, Optional



from dagster import ConfigurableResource
from google.oauth2 import service_account
from googleapiclient.discovery import build as build_gmail_service
from pydantic import Field, PrivateAttr


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent.parent.parent

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_CREDENTIALS_PATH = str(REPO_ROOT / "env" / "email_credentials.json")
DEFAULT_ACCOUNTS = [
    "jorge.paredes@airmajoro.com",
    "contabilidad@airmajoro.com",
]


get_gmail_credentials = service_account.Credentials.from_service_account_file


def _iter_all_attachments(msg):
    """Recorre todo el árbol MIME y devuelve todas las partes que son adjuntos.

    ``msg.walk()`` desciende por todos los contenedores ``multipart/*``
    anidados (a cualquier profundidad) y devuelve cada parte. A diferencia de
    ``msg.iter_attachments()`` (que solo mira las partes de nivel superior),
    aquí se recogen todas las partes con nombre de archivo o con
    ``Content-Disposition: attachment``, estén donde estén.
    """
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            yield part


def _to_iso8601(value: Any) -> str:
    """Convierte una fecha a ISO 8601 con zona horaria.

    Acepta:
    - RFC 2822 (p. ej. ``Sat, 08 Aug 2026 18:13:43 -0500``) -> ``2026-08-08T18:13:43-05:00``
    - Timestamp Unix en milisegundos (p. ej. ``1786230823000``) -> ``2026-08-08T23:13:43+00:00``
    - Objetos ``datetime`` ya con zona horaria.
    """
    if value is None or value == "":
        return ""

    # Timestamp Unix en milisegundos (internalDate de Gmail).
    # Gmail lo devuelve como string de dígitos, p. ej. "1786233181000".
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and value.isdigit()
    ):
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()

    # datetime ya con zona horaria
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    # RFC 2822 (Date header)
    if isinstance(value, str):
        parsed = utils.parsedate_to_datetime(value)
        if parsed is not None:
            return parsed.isoformat()

    return str(value)



class GmailResource(ConfigurableResource):


    credentials_path: str = Field(default=DEFAULT_CREDENTIALS_PATH)
    accounts: list[str] = Field(default_factory=lambda: list(DEFAULT_ACCOUNTS))

    _services: dict[str, Any] = PrivateAttr(default_factory=dict)

    def _get_service(self, account: str) -> Any:
        """Crea (o reutiliza) el servicio Gmail delegado a una cuenta concreta."""
        service = self._services.get(account)
        if service is None:
            credentials = get_gmail_credentials(
                self.credentials_path,
                scopes=SCOPES,
                subject=account,
            )
            service = build_gmail_service(
                "gmail", "v1", credentials=credentials, cache_discovery=False
            )
            self._services[account] = service
        return service

    @property
    def service(self):
        # Cuenta por defecto (la primera) para compatibilidad.
        return self._get_service(self.accounts[0])

    def get_messages_ids(
        self, query: str = "", max_results: int = 500, account: Optional[str] = None
    ) -> list[str]:
        service = self._get_service(account or self.accounts[0])

        request = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=min(max_results, 500))
        )

        message_ids = []
        # Request is a page of messages
        while request is not None and len(message_ids) < max_results:
            response = request.execute()

            new_messages = response.get("messages", [])[:max_results - len(message_ids)]
            message_ids.extend([msg["id"] for msg in new_messages])
            
            # Get the next page of messages
            request = service.users().messages().list_next(request, response)
        return message_ids

    def get_message(
        self, message_id: str, account: Optional[str] = None
    ) -> dict[str, Any]:
        service = self._get_service(account or self.accounts[0])
        meta = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="raw")
            .execute()
        )
        raw = base64.urlsafe_b64decode(meta["raw"].encode("UTF-8"))
        msg = BytesParser(policy=policy.default).parsebytes(raw)

        body = msg.get_body(preferencelist=("plain", "html"))
        body = body.get_content() if body else ""
        body = body if isinstance(body, str) else str(body)

        attachments = []
        for att in _iter_all_attachments(msg):

            payload = att.get_payload(decode=True) or b""
            attachments.append(
                {
                    "filename": att.get_filename() or "",
                    "mime_type": att.get_content_type(),
                    "size": len(payload),
                    "data": base64.b64encode(payload).decode("ascii"),
                }
            )


        return {
            "id": meta["id"],
            "thread_id": meta.get("threadId"),
            "sender": utils.parseaddr(msg["from"] or "")[1],
            "subject": msg["subject"] or "",
            "body": body,
            "attachments": attachments,
            "header_date": _to_iso8601(msg["date"]),
            "received_date": _to_iso8601(meta.get("internalDate")),

        }

    def list_message_ids(
        self, query: str = "", max_results: int = 500
    ) -> dict[str, list[str]]:
        """IDs de los correos que cumplen ``query``, **por cuenta**.

        Es la llamada barata de Gmail (``users.messages.list``): devuelve solo ids,
        sin cuerpos ni adjuntos. El asset la usa como primer paso para saber qué hay
        en el día y decidir después qué descargar.
        """
        return {
            account: self.get_messages_ids(
                query=query, max_results=max_results, account=account
            )
            for account in self.accounts
        }

    def fetch_emails(
        self,
        query: str = "",
        max_results: int = 500,
        ids_by_account: Optional[dict[str, list[str]]] = None,
        skip_ids: Optional[set[str]] = None,
    ) -> list[dict]:
        """Descarga los correos de **todas** las cuentas configuradas.

        Cada mensaje descargado se etiqueta con su ``mailbox`` (la cuenta de la que
        proviene), así que un mismo correo queda identificado por la bandeja en la
        que fue leído.

        ``ids_by_account`` permite pasar los ids ya listados por
        ``list_message_ids`` y no repetir la llamada a ``messages.list``.
        ``skip_ids`` son ids que **no** hay que descargar porque ya están en la
        tabla ``emails``: con ellos la descarga es incremental de verdad (a Gmail
        solo se le pide el cuerpo y los adjuntos de lo nuevo, que es la parte cara:
        1 request por correo + decodificación MIME + base64 de los adjuntos).
        """
        pendientes = (
            ids_by_account
            if ids_by_account is not None
            else {
                account: self.get_messages_ids(
                    query=query, max_results=max_results, account=account
                )
                for account in self.accounts
            }
        )
        omitidos = skip_ids or set()

        emails: list[dict] = []
        for account in self.accounts:
            for message_id in pendientes.get(account, []):
                if message_id in omitidos:
                    continue
                message = self.get_message(message_id, account=account)
                message["mailbox"] = account
                emails.append(message)
        return emails


