"""Resource de BD para los datos del PDF CORPAC (agnóstico del motor).

Lee de ``from_email_corpac_files`` los PDFs ``01-*.pdf`` de la partición del día
(**una copia por documento**: el mismo PDF puede estar ingerido hasta 16 veces porque el
correo CORPAC llega a los 2 buzones y se repite dentro del hilo) y hace el
upsert total del día en ``from_email_corpac_headers`` / ``from_email_corpac_details`` (heredando de
``AbstractDbResource``; el upsert de cabecera + detalle con FK es propio).
"""

from __future__ import annotations

from typing import Any

from peewee import fn

from assets._common.abstract_resource import AbstractDbResource
from assets._common.db import chunked, db
from assets.from_email_assets.corpac_assets.corpac_data_asset.models.model import CorpacDetail, CorpacHeader
from assets.from_email_assets.corpac_assets.corpac_files_asset.models.model import CorpacFile
from assets.mail_asset.model import Email


class CorpacDataSqliteResource(AbstractDbResource):
    """Resource que lee los PDFs CORPAC del día y upserta cabeceras y detalles."""

    def _tables(self) -> tuple[type, ...]:
        return (Email, CorpacFile, CorpacHeader, CorpacDetail)

    def select_corpac_pdfs(self, partition_date: str) -> list[dict[str, Any]]:
        """Un PDF ``01-*.pdf`` **por documento** (``filename``) de la partición del día.

        El asset solo procesa la factura de detalle de servicios: los archivos
        cuyo nombre empieza por ``01-`` y termina en ``.pdf``.

        ``filename`` es la **identidad del documento**: el mismo PDF entra varias
        veces en ``from_email_corpac_files`` (el correo CORPAC llega a los 2
        buzones y se repite dentro del hilo, así que hay hasta 16 copias idénticas
        del mismo archivo), así que aquí se devuelve **solo la copia canónica de
        cada ``filename``** —la de menor ``id`` en toda la tabla, no solo en el
        día: ``corpac_purchs_std`` cruza las cabeceras por ``factura``, así que una
        cabecera repetida multiplica ``moves`` también entre días— y cada fila trae
        ``copies`` (nº de copias del documento) para que el asset reporte las
        omitidas.

        Sin esto el PDF se parseaba N veces, se creaba una cabecera por copia y sus
        detalles se multiplicaban por N en ``moves`` (el gasto CORPAC salía ×2,15).
        """
        self._ensure_db()
        candidatos = list(
            CorpacFile.select(CorpacFile.id, CorpacFile.filename)
            .where(
                (CorpacFile.partition_date == partition_date)
                & self._es_pdf_servicios()
            )
            .order_by(CorpacFile.id)
        )
        if not candidatos:
            return []

        # Copia canónica (menor ``id``) y nº de copias de cada ``filename`` del día.
        copias = {
            row.filename: (row.canonica, row.copies)
            for row in CorpacFile.select(
                CorpacFile.filename,
                fn.MIN(CorpacFile.id).alias("canonica"),
                fn.COUNT(CorpacFile.id).alias("copies"),
            )
            .where(CorpacFile.filename.in_([c.filename for c in candidatos]))
            .group_by(CorpacFile.filename)
        }

        canonicos = [c for c in candidatos if copias[c.filename][0] == c.id]
        if not canonicos:
            return []

        # El payload se lee solo de las copias canónicas: los días con correos
        # repetidos traen el mismo PDF hasta 16 veces y no se cargan en memoria.
        payload = {
            row.id: row.data
            for row in CorpacFile.select(CorpacFile.id, CorpacFile.data).where(
                CorpacFile.id.in_([c.id for c in canonicos])
            )
        }
        return [
            {
                "id": c.id,
                "filename": c.filename,
                "data": payload[c.id],
                "copies": copias[c.filename][1],
            }
            for c in canonicos
        ]

    @staticmethod
    def _es_pdf_servicios():
        """Filtro de los archivos que parsea el asset: ``01-*.pdf``."""
        return CorpacFile.filename.startswith("01-") & CorpacFile.filename.endswith(
            ".pdf"
        )

    def upsert_day(
        self,
        partition_date: str,
        headers: list[dict],
        details: list[dict],
    ) -> tuple[int, int]:
        """Reemplaza las cabeceras y detalles de ``partition_date`` por los dados.

        Upsert total del día: dentro de una transacción borra **todas** las
        cabeceras del día (y sus detalles) e inserta las nuevas. Cada fila de
        ``details`` trae ``filename`` (la cabecera padre) y aquí se inyecta el
        FK ``header``; ``partition_date`` se inyecta en ambas tablas. Devuelve
        ``(cabeceras, detalles)`` insertados.

        La clave de cabecera es ``(filename, _section)`` (una factura puede tener
        varias secciones, una por aeronave) y la **primera** fila de cada clave es
        la que se inserta: si el mismo PDF llegara dos veces, la segunda no crea
        otra cabecera y la tabla mantiene su contrato (una cabecera por documento).
        Quien evita de verdad la duplicación es ``select_corpac_pdfs``, que entrega
        una sola copia por ``filename``.
        """
        self._ensure_db()
        # Los FKs no tienen pragma de cascade garantizado: se borran primero
        # los detalles del día y después las cabeceras.
        with db.atomic():
            CorpacDetail.delete().where(
                CorpacDetail.partition_date == partition_date
            ).execute()
            CorpacHeader.delete().where(
                CorpacHeader.partition_date == partition_date
            ).execute()

            header_ids: dict[tuple[str, int], int] = {}
            for h in headers:
                clave = (h["filename"], h["_section"])
                if clave in header_ids:
                    continue  # mismo PDF/sección dos veces: una sola cabecera
                fila = {k: v for k, v in h.items() if k != "_section"}
                row = CorpacHeader.create(**fila, partition_date=partition_date)
                header_ids[clave] = row.id

            if details:
                batch_size = max(1, self._max_variables() // len(CorpacDetail._meta.fields))
                rows_with_fk = [
                    {
                        **{k: v for k, v in d.items() if k not in ("_section", "filename")},
                        "header": header_ids[(d["filename"], d["_section"])],
                        "partition_date": partition_date,
                    }
                    for d in details
                ]
                for batch in chunked(rows_with_fk, batch_size):
                    CorpacDetail.insert_many(batch).execute()

        return len(header_ids), len(details)
