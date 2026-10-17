"""Base abstracta de los ``db_resource`` de Dagster, agnóstica al motor.

Los ``resources/db_resource.py`` de cada asset heredan de ``AbstractDbResource``
en vez de repetir ``ConfigurableResource`` + ``database_path`` + ``_ensure_db`` +
el troceado de inserts. La base resuelve el motor por configuración:
``engine="sqlite"`` (por defecto, apuntando a ``db.sqlite``) o
``engine="postgres"`` (más ``host``/``port``/``user``/``password``).

El hijo solo declara sus tablas (``_tables``) y sus métodos de lectura/upsert,
normalmente apoyados en ``_replace`` (borra la partición e inserta en lotes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal, Sequence

from dagster import ConfigurableResource
from pydantic import Field, PrivateAttr

from assets._common.db import (
    DEFAULT_SQLITE_PATH,
    bind,
    chunked,
    db,
    get_database,
    max_variables,
)


class AbstractDbResource(ConfigurableResource, ABC):
    """Resource de BD de Dagster independiente del motor (SQLite/PostgreSQL)."""

    engine: Literal["sqlite", "postgres"] = "sqlite"
    database_path: str = Field(
        default=DEFAULT_SQLITE_PATH,
        description=(
            "Ruta del archivo de la SQLite o nombre de la base en PostgreSQL"
        ),
    )
    # Solo aplican con engine="postgres".
    host: str | None = None
    port: int | None = None
    user: str | None = None
    password: str | None = None
    prefer_psycopg3: bool = True

    _already_init: bool = PrivateAttr(default=False)

    @abstractmethod
    def _tables(self) -> Sequence[type]:
        """Modelos peewee cuyas tablas necesita (y crea) este recurso."""

    def _connect_db(self) -> None:
        """Enlaza el proxy compartido al motor/destino de este recurso."""
        bind(
            db,
            get_database(
                self.engine,
                self.database_path,
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                prefer_psycopg3=self.prefer_psycopg3,
            ),
        )

    def _ensure_db(self) -> None:
        """Inicializa la conexión y crea las tablas (idempotente por instancia)."""
        if self._already_init:
            return
        self._connect_db()
        db.connect(reuse_if_open=True)
        db.create_tables(list(self._tables()))
        self._already_init = True

    def _max_variables(self) -> int:
        """Máximo de variables por sentencia SQL del motor configurado."""
        return max_variables(self.engine)

    def _replace(
        self,
        model,
        where,
        rows: list[dict],
        inject: dict | None = None,
    ) -> int:
        """Upsert total portable: borra la partición e inserta las filas dadas.

        Dentro de una transacción borra las filas que cumplen ``where`` e inserta
        ``rows`` (con ``inject`` mezclado en cada fila, p. ej. ``period``) en lotes
        para no superar el límite de variables del motor. Devuelve el número de
        filas insertadas.

        ``where=None`` significa **tabla completa** (borra todo): lo usan las tablas
        de referencia que se reemplazan enteras (los CSV estáticos).
        """
        self._ensure_db()
        n_cols = len(model._meta.fields)
        batch_size = max(1, self._max_variables() // n_cols)
        with db.atomic():
            if where is None:
                model.delete().execute()
            else:
                model.delete().where(where).execute()
            if rows:
                rows_with_meta = [{**row, **(inject or {})} for row in rows]
                for batch in chunked(rows_with_meta, batch_size):
                    model.insert_many(batch).execute()
        return len(rows)

    def _existing_keys(
        self,
        model,
        lookup_field: str,
        values: list,
        key_fields: tuple[str, ...],
    ) -> set[tuple]:
        """Claves ``key_fields`` ya presentes para ``lookup_field IN values``.

        Acota la consulta por ``lookup_field`` (p. ej. ``"id"`` o ``"email"``) y
        consulta en lotes por el límite de variables del motor. ``key_fields`` usa
        los **nombres de atributo del modelo** (p. ej. ``("id",)`` o
        ``("email_id", "filename")``).
        """
        self._ensure_db()
        where_field = getattr(model, lookup_field)
        columns = [getattr(model, f) for f in key_fields]
        existing: set[tuple] = set()
        for batch in chunked(list(dict.fromkeys(values)), self._max_variables()):
            existing.update(
                tuple(getattr(row, f) for f in key_fields)
                for row in model.select(*columns).where(where_field.in_(batch))
            )
        return existing

    def _insert_new(
        self,
        model,
        rows: list[dict],
        key_fields: tuple[str, ...],
        existing: set[tuple] | None = None,
    ) -> int:
        """Inserta **solo** las filas cuya ``key_fields`` no exista (append-only).

        Es el upsert idempotente: no borra ni actualiza lo ya presente, solo agrega
        las filas nuevas. Descarta además duplicados dentro de la misma corrida y
        trocea el insert según el límite de variables del motor. ``key_fields`` usa
        las **claves del dict** de cada fila (p. ej. ``("id",)``). ``existing`` es
        el resultado de ``_existing_keys`` (si no se pasa, se asume vacío).
        Devuelve el número de filas insertadas.
        """
        self._ensure_db()
        if not rows:
            return 0
        existing = existing or set()
        seen: set[tuple] = set()
        new_rows: list[dict] = []
        for row in rows:
            key = tuple(row[f] for f in key_fields)
            if key in existing or key in seen:
                continue
            seen.add(key)
            new_rows.append(row)
        if new_rows:
            batch_size = max(1, self._max_variables() // len(model._meta.fields))
            with db.atomic():
                for batch in chunked(new_rows, batch_size):
                    model.insert_many(batch).execute()
        return len(new_rows)
