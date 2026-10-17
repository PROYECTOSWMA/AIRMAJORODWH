"""Resource de BD para los detalles de comprobantes CPE (agnóstico del motor).

Lee los documentos de ``sire_sales``/``sire_purchs`` e inserta los ítems en
``sire_sales_details``/``sire_purchs_details`` por ``(period, empresa)`` **sin
borrar** lo ya materializado (append-only, igual que los archivos; hereda de
``AbstractDbResource``; los selects y el insert sin delete son propios).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from peewee import JOIN

from assets._common.abstract_resource import AbstractDbResource
from assets._common.db import chunked, db
from assets.sire_assets.sire_details_asset.models.model import (
    SirePurchsDetails,
    SireSalesDetails,
)
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


class SireDetailsSqliteResource(AbstractDbResource):
    """Resource que lee documentos SIRE e inserta (append-only) sus detalles."""

    def _tables(self) -> tuple[type, ...]:
        return (SireSales, SirePurchs, SireSalesDetails, SirePurchsDetails)

    def select_documents(
        self,
        start_date: date,
        end_date: date,
        empresa: str,
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> list[dict[str, Any]]:
        """Filas de ``sire_sales``/``sire_purchs`` de ``empresa`` del periodo mensual
        de la partición (``period``) cuya ``fecha_de_emision`` cae en la ventana
        ``[start_date, end_date)`` (el primer día del mes también las emitidas antes).

        Devuelve los datos mínimos para consultar la API y enlazar el detalle:
        ``id`` (FK del detalle), ``tipo_cp_doc``, ``tipo_cp_modificado``,
        ``serie``, ``numero`` y ``nro_doc_identidad`` (RUC del proveedor).
        """
        self._ensure_db()
        model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        periodo = start_date.strftime("%Y%m")
        rows = model.select().where(
            (model.empresa == empresa)
            & (model.period == periodo)
            & _rango_documentos(model, start_date, end_date)
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

    def select_missing_documents(
        self,
        start_date: date,
        end_date: date,
        empresa: str,
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> list[dict[str, Any]]:
        """Documentos de ``empresa`` del periodo mensual de la partición (``period``)
        en ``[start_date, end_date)`` sin ningún detalle (el primer día del mes
        también los emitidos antes).

        Igual que ``select_documents`` pero solo devuelve los que faltan en la tabla
        de detalles: ``LEFT JOIN`` con la tabla de ítems por el FK
        (``sire_sale``/``sire_purch``) y filtro ``detalles.id IS NULL`` dentro de la
        ventana.
        """
        self._ensure_db()
        doc_model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        detail_model = (
            SireSalesDetails if book_code == BOOK_CODE_SALES else SirePurchsDetails
        )
        fk_field = (
            detail_model.sire_sale
            if book_code == BOOK_CODE_SALES
            else detail_model.sire_purch
        )
        periodo = start_date.strftime("%Y%m")
        rows = (
            doc_model.select()
            .join(detail_model, JOIN.LEFT_OUTER, on=(fk_field == doc_model.id))
            .where(
                (doc_model.empresa == empresa)
                & (doc_model.period == periodo)
                & _rango_documentos(doc_model, start_date, end_date)
                & (detail_model.id.is_null(True))
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

    def count_documents(
        self,
        start_date: date,
        end_date: date,
        empresa: str,
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> int:
        """Número de documentos de ``empresa`` del periodo mensual de la partición
        (``period``) en ``[start_date, end_date)`` (el primer día del mes también
        los emitidos antes).

        Se usa para loguear el total al inicio de la materialización.
        """
        self._ensure_db()
        model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        periodo = start_date.strftime("%Y%m")
        return model.select().where(
            (model.empresa == empresa)
            & (model.period == periodo)
            & _rango_documentos(model, start_date, end_date)
        ).count()

    def insert_details(
        self,
        period: str,
        empresa: str,
        rows: list[dict],
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> int:
        """Inserta los ítems dados **sin borrar** los detalles ya existentes.

        Append-only (igual que ``insert_files``): solo agrega los ítems nuevos, los
        ya materializados de ese periodo se respetan y el padre conserva su id
        (``insert_proposal_new`` nunca borra), así que no quedan huérfanos. Cada
        fila de ``rows`` trae el FK del documento padre (``sire_sale``/
        ``sire_purch``) más los campos del ítem; ``period`` y ``empresa`` se inyectan
        aquí. El insert se particiona en lotes para no superar el límite de variables
        SQL de SQLite. Devuelve el número de ítems insertados.
        """
        self._ensure_db()
        model = SireSalesDetails if book_code == BOOK_CODE_SALES else SirePurchsDetails
        batch_size = max(1, self._max_variables() // len(model._meta.fields))
        if rows:
            rows_with_meta = [
                {**row, "period": period, "empresa": empresa} for row in rows
            ]
            with db.atomic():
                for batch in chunked(rows_with_meta, batch_size):
                    model.insert_many(batch).execute()
        return len(rows)

    def delete_orphan_details(
        self,
        period: str,
        empresa: str,
        book_code: str = BOOK_CODE_PURCHASES,
    ) -> int:
        """Borra los detalles de ``(period, empresa)`` cuyo padre ya no existe.

        La propuesta mensual re-upserta los padres con ids nuevos cada corrida, así
        que los detalles de corridas anteriores quedan huérfanos (FK a un padre
        borrado). Se eliminan para que los detalles queden consistentes con los
        padres. Devuelve el número de filas eliminadas.
        """
        self._ensure_db()
        doc_model = SireSales if book_code == BOOK_CODE_SALES else SirePurchs
        detail_model = (
            SireSalesDetails if book_code == BOOK_CODE_SALES else SirePurchsDetails
        )
        fk_field = (
            detail_model.sire_sale
            if book_code == BOOK_CODE_SALES
            else detail_model.sire_purch
        )
        return (
            detail_model.delete()
            .where(
                (detail_model.period == period)
                & (detail_model.empresa == empresa)
                & fk_field.not_in(doc_model.select(doc_model.id))
            )
            .execute()
        )
