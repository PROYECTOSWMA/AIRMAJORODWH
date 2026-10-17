"""Resource de BD para los archivos (PDF/ZIP) de comprobantes CPE (agnóstico del motor).

Lee los documentos de ``sire_sales``/``sire_purchs`` e inserta los archivos en
``sire_sales_files``/``sire_purchs_files`` por ``(period, empresa)`` (hereda de
``AbstractDbResource``; el select de faltantes y el insert sin delete son propios).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from peewee import JOIN

from assets._common.abstract_resource import AbstractDbResource
from assets._common.db import chunked, db
from assets.sire_assets.sire_files_asset.models.model import SirePurchsFiles, SireSalesFiles
from assets.sire_assets.sire_proposal_asset.models.model import SirePurchs, SireSales
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)


def _rango_documentos(model, start_date, end_date):
    """Filtro de ``fecha_de_emision`` para la ventana ``[start_date, end_date)``.

    El primer día del mes incluye además los emitidos antes del mes: la propuesta
    mensual puede traer comprobantes con fecha de emisión anterior al periodo que,
    sin este ajuste, nunca caerían en ninguna partición diaria.
    """
    en_ventana = (model.fecha_de_emision >= start_date) & (
        model.fecha_de_emision < end_date
    )
    if start_date.day == 1:
        return en_ventana | (model.fecha_de_emision < start_date)
    return en_ventana


class SireFilesSqliteResource(AbstractDbResource):
    """Resource que lee documentos SIRE e inserta sus archivos por período."""

    def _tables(self) -> tuple[type, ...]:
        return (SireSales, SirePurchs, SireSalesFiles, SirePurchsFiles)

    def select_missing_files(
        self,
        start_date: date,
        end_date: date,
        empresa: str,
        tipo_documento: str,
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> list[dict[str, Any]]:

        self._ensure_db()
        doc_model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        file_model = (
            SireSalesFiles if book_code == BOOK_CODE_SALES else SirePurchsFiles
        )
        fk_field = (
            file_model.sire_sale
            if book_code == BOOK_CODE_SALES
            else file_model.sire_purch
        )
        periodo = start_date.strftime("%Y%m")
        rows = (
            doc_model.select()
            .join(
                file_model,
                JOIN.LEFT_OUTER,
                on=(
                    (fk_field == doc_model.id)
                    & (file_model.tipo_documento == tipo_documento)
                ),
            )
            .where(
                (doc_model.empresa == empresa)
                & (doc_model.period == periodo)
                & _rango_documentos(doc_model, start_date, end_date)
                & (file_model.id.is_null(True))
            )
        )
        return [
            {
                "id": row.id,
                "tipo_cp_doc": row.tipo_cp_doc,
                "tipo_cp_modificado": row.tipo_cp_modificado,
                "serie": row.serie_del_cdp,
                "numero": row.nro_cp_o_doc_nro_inicial_rango,
                "nro_doc_identidad": row.nro_doc_identidad,
            }
            for row in rows
        ]

    def insert_files(
        self,
        period: str,
        empresa: str,
        rows: list[dict],
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> int:
        self._ensure_db()
        model = SireSalesFiles if book_code == BOOK_CODE_SALES else SirePurchsFiles
        batch_size = max(1, self._max_variables() // len(model._meta.fields))
        if rows:
            rows_with_meta = [
                {**row, "period": period, "empresa": empresa} for row in rows
            ]
            with db.atomic():
                for batch in chunked(rows_with_meta, batch_size):
                    model.insert_many(batch).execute()
        return len(rows)

    def delete_orphan_files(
        self,
        period: str,
        empresa: str,
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> int:

        self._ensure_db()
        doc_model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        file_model = (
            SireSalesFiles if book_code == BOOK_CODE_SALES else SirePurchsFiles
        )
        fk_field = (
            file_model.sire_sale
            if book_code == BOOK_CODE_SALES
            else file_model.sire_purch
        )
        return (
            file_model.delete()
            .where(
                (file_model.period == period)
                & (file_model.empresa == empresa)
                & fk_field.not_in(doc_model.select(doc_model.id))
            )
            .execute()
        )
