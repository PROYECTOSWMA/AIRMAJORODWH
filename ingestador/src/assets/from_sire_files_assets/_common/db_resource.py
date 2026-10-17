
from __future__ import annotations

from functools import reduce
from operator import or_
from typing import Any, ClassVar

from assets._common.abstract_resource import AbstractDbResource
from assets._common.db import db
from assets.sire_assets.sire_files_asset.models.model import SirePurchsFiles
from assets.sire_assets.sire_files_asset.resources.api_resource.constants import (
    FILE_KIND_ZIP,
)
from assets.sire_assets.sire_proposal_asset.models.model import SirePurchs

# Clave natural de una fila: el ZIP del que salió el XML + la matrícula.
NATURAL_KEY = ("id_file", "aeronave")

# Campos que, cuando el modelo los tiene, se rellenan por ``UPDATE`` en las filas ya
# existentes (backfill): antes de su incorporación la tabla se migró con el ``ALTER
# TABLE`` de ``_ensure_db`` y las filas quedaron en NULL.
BACKFILL_FIELDS = ("aeropuerto", "aeropuerto_completo")


def _tiene_columna(model: type, nombre: str) -> bool:
    """¿El modelo peewee tiene el campo ``nombre``?"""
    return hasattr(model, nombre)


class AeronaveSireSqliteResource(AbstractDbResource):
    """Lee los ZIP de compras del proveedor y añade sus aeronaves (append-only)."""

    # Subclases: modelo peewee de la tabla destino y RUC del proveedor.
    _model: ClassVar[type]
    _ruc: ClassVar[str]

    def _tables(self) -> tuple[type, ...]:
        # ``SirePurchs`` solo se declara para que exista la tabla padre de la FK
        # ``sire_purchs_files.sire_purch`` (``create_tables``); el select de ZIPs
        # **no** la consulta.
        return (SirePurchs, SirePurchsFiles, self._model)

    def _ensure_db(self) -> None:
        """Base + migración blanda de columnas nuevas.

        ``create_tables`` crea las tablas que falten pero **no** añade columnas a las
        que ya existen; cuando un modelo gana columnas (p. ej. el aeropuerto de
        petroperú) la tabla vieja se queda sin ellas. Aquí se añaden por ``ALTER
        TABLE`` las que falten (idempotente: solo actúa la primera vez por instancia).
        """
        if self._already_init:
            return
        super()._ensure_db()
        self._add_missing_columns(self._model)

    def _add_missing_columns(self, model: type) -> None:
        """Añade por ``ALTER TABLE`` las columnas del modelo que falten en la tabla."""
        tabla = model._meta.table_name
        existentes = {columna.name for columna in db.get_columns(tabla)}
        for campo in model._meta.sorted_fields:
            if campo.column_name in existentes:
                continue
            db.execute_sql(
                f'ALTER TABLE "{tabla}" ADD COLUMN '
                f'"{campo.column_name}" {campo.field_type}'
            )

    def select_zip_files(self, months: list[str]) -> list[dict[str, Any]]:
        """ZIPs de compras del proveedor de esos meses que **aún no están completos**.

        ``months`` son los meses de la materialización (``["2026-08", "2026-09"]``);
        los ZIP se guardan en ``sire_purchs_files.period`` con la **fecha de emisión**
        del comprobante, así que se filtra por el prefijo ``YYYY-MM``. El proveedor se
        identifica por el RUC que SUNAT pone al principio del nombre del ZIP
        (``nom_archivo LIKE '<RUC>%'``): **no** hay JOIN a ``sire_purchs``, la
        pertenencia al comprobante la garantiza la FK de ``sire_purchs_files``.

        Un ZIP se considera ya procesado (y se omite) cuando tiene filas en la tabla
        y, si el modelo tiene aeropuerto (``BACKFILL_FIELDS``), esas filas ya lo
        traen relleno: así los ZIP que se insertaron antes de la columna vuelven a
        mirarse una vez para **rellenar** su aeropuerto (ver
        ``insert_aeronaves_new``). Al ser append-only, re-pasar el mes solo mira lo
        nuevo. Se devuelve ``period`` para etiquetar cada fila con el día de su ZIP.
        """
        if not months:
            return []
        self._ensure_db()
        en_los_meses = reduce(
            or_, [SirePurchsFiles.period.startswith(month) for month in months]
        )
        ya_procesados = self._zip_files_completos()
        rows = (
            SirePurchsFiles.select(
                SirePurchsFiles.id,
                SirePurchsFiles.period,
                SirePurchsFiles.nom_archivo,
                SirePurchsFiles.val_archivo,
            )
            .where(
                (SirePurchsFiles.nom_archivo.startswith(self._ruc))
                & (SirePurchsFiles.tipo_documento == FILE_KIND_ZIP)
                & en_los_meses
                & (SirePurchsFiles.id.not_in(ya_procesados))
            )
        )
        return [
            {
                "id": row.id,
                "period": row.period,
                "nom_archivo": row.nom_archivo,
                "val_archivo": row.val_archivo,
            }
            for row in rows
        ]

    def _zip_files_completos(self):
        """ZIPs que ya no hay que mirar.

        Sin aeropuerto en el modelo, cualquiera con filas. Con aeropuerto, solo los
        que tienen **alguna** fila con el aeropuerto no nulo: los ZIP cuyas filas
        quedaron todas en NULL (insertadas antes de la columna) se devuelven para
        rellenarlas.
        """
        if not _tiene_columna(self._model, "aeropuerto"):
            return self._model.select(self._model.file)
        return self._model.select(self._model.file).where(
            ~self._model.aeropuerto.is_null(True)
        )

    def insert_aeronaves_new(self, rows: list[dict]) -> int:
        """Inserta las aeronaves que aún no están en la tabla (append-only).

        La identidad es ``(id_file, aeronave)``: re-materializar un mes (o el rango
        de dos meses del cron) solo añade lo nuevo y no rota ids. Cada fila debe
        traer ya su ``period`` (el día del ZIP). Devuelve el número de filas
        insertadas.
        """
        if not rows:
            return 0
        existing = self._existing_keys(
            self._model, "id_file", [row["id_file"] for row in rows], NATURAL_KEY
        )
        insertados = self._insert_new(self._model, rows, NATURAL_KEY, existing)
        self._backfill_aeropuertos(rows)
        return insertados

    def _backfill_aeropuertos(self, rows: list[dict]) -> None:
        """Rellena (por ``UPDATE``) el aeropuerto de las filas que ya existían en NULL.

        El ``INSERT`` es append-only, así que las filas insertadas antes de la
        columna del aeropuerto no se tocan al volver a pasar su ZIP; aquí se
        actualizan solo las que aún lo tienen NULL y la fila nueva sí lo trae.
        """
        if not _tiene_columna(self._model, "aeropuerto"):
            return
        for row in rows:
            valores = {
                campo: row[campo]
                for campo in BACKFILL_FIELDS
                if row.get(campo)
            }
            if not valores:
                continue
            (
                self._model.update(**valores)
                .where(
                    (self._model.id_file == row["id_file"])
                    & (self._model.aeronave == row["aeronave"])
                    & self._model.aeropuerto.is_null(True)
                )
                .execute()
            )
