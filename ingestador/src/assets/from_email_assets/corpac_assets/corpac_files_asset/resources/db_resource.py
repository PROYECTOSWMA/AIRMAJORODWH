"""Resource de BD para los archivos CORPAC (agnóstico del motor).

Lee los correos del día del remitente CORPAC de la tabla ``emails`` y alimenta
``from_email_corpac_files`` de forma **append-only**: ``select_corpac_emails`` **salta
los correos que ya tienen al menos un archivo** en la tabla (el asset ni los vuelve a
descargar) y ``upsert_files`` inserta solo los archivos nuevos, deduplicados por
``filename`` —el mismo PDF/XML llega en los 2 buzones y en las respuestas del hilo, y es
el mismo documento— y por ``(id_email, filename)``, para que el ``id`` (``file_id`` que
referencia ``corpac_header``) sea estable entre corridas (hereda de
``AbstractDbResource``).
"""

from __future__ import annotations

from typing import Any

from assets._common.abstract_resource import AbstractDbResource
from assets.from_email_assets.corpac_assets.corpac_files_asset.models.model import CorpacFile
from assets.mail_asset.model import Email

# Remitente de los correos de comunicaciones CORPAC (portal Mercurio de Pegasus).
CORPAC_SENDER = "servicio.facturacion@pegasus.com.pe"


class CorpacSqliteResource(AbstractDbResource):
    """Resource que lee los correos CORPAC pendientes del día y agrega sus archivos."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, CorpacFile)

    def select_corpac_emails(self, partition_date: str) -> list[dict[str, Any]]:
        """Correos del día del remitente CORPAC que **aún no tienen archivos**.

        Se excluyen los correos que ya tengan **al menos una** fila en
        ``from_email_corpac_files`` (subconsulta por ``id_email``): al ser
        append-only, re-pasar el día solo mira lo nuevo y ni siquiera se vuelve a
        descargar el ZIP de un correo ya procesado.
        """
        self._ensure_db()
        ya_procesados = CorpacFile.select(CorpacFile.padre)
        rows = Email.select(Email.id, Email.sender, Email.body).where(
            (Email.partition_date == partition_date)
            & (Email.sender == CORPAC_SENDER)
            & (Email.id.not_in(ya_procesados))
        )
        return [
            {
                "id": row.id,
                "sender": row.sender or "",
                "body": row.body or "",
            }
            for row in rows
        ]

    def upsert_files(self, partition_date: str, rows: list[dict]) -> int:
        """Inserta **solo** los archivos nuevos (por ``filename`` y por ``(id_email, filename)``).

        Append-only: no borra ni actualiza lo ya presente, de modo que el ``id``
        (``file_id`` de ``corpac_header``) queda estable entre corridas. El
        ``select_corpac_emails`` ya descarta los correos con archivos, así que en el
        flujo normal esto es un insert directo; el dedupe es la red de seguridad del
        re-run. Devuelve el número de archivos insertados.

        **Un documento = una fila**: el mismo PDF/XML llega en varios correos (los 2
        buzones del remitente + las respuestas del hilo), así que un ``filename`` ya
        presente se salta y no se guarda otra copia de su payload (~250 MB de copias
        repetidas del mismo PDF). El correo que lo traía se queda sin filas propias, de
        modo que un re-run de esa partición lo vuelve a descargar y lo vuelve a saltar
        aquí: es el precio de no guardar el documento dos veces y no reintroduce
        duplicados (``corpac_data_daily`` lee una copia por documento).
        """
        self._ensure_db()
        if not rows:
            return 0
        to_insert = [{**row, "partition_date": partition_date} for row in rows]
        ya_presentes = self._existing_keys(
            CorpacFile,
            "filename",
            [row["filename"] for row in to_insert],
            ("filename",),
        )
        # Dedupe por documento también dentro de la misma corrida (dos correos del
        # día con el mismo adjunto).
        vistos: set[tuple] = set()
        nuevos: list[dict] = []
        for row in to_insert:
            clave = (row["filename"],)
            if clave in ya_presentes or clave in vistos:
                continue
            vistos.add(clave)
            nuevos.append(row)
        existing = self._existing_keys(
            CorpacFile,
            "id_email",
            [row["id_email"] for row in nuevos],
            ("id_email", "filename"),
        )
        return self._insert_new(CorpacFile, nuevos, ("id_email", "filename"), existing)
