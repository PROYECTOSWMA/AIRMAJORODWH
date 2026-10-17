"""Infraestructura de BD compartida por los resources de Dagster.

Dos ideas clave:

1. **Un único ``DatabaseProxy``** (``db``) que todos los modelos peewee
   comparten. Los módulos de modelo ya no hacen ``db = SqliteDatabase(None)``,
   sino ``from assets._common.db import db``. El proxy se enlaza en tiempo de
   ejecución al motor elegido (SQLite hoy, PostgreSQL cuando se migre) sin tocar
   los modelos.
2. **Helpers agnósticos de motor**: ``chunked``, ``max_variables``,
   ``get_database`` y ``bind``. Aquí vive todo lo que antes estaba copiado en
   cada ``db_resource.py`` (límite de variables de SQLite, troceado de inserts,
   ruta por defecto de ``db.sqlite``).
"""

from __future__ import annotations

import sqlite3
from itertools import islice
from pathlib import Path

from peewee import Database, DatabaseProxy, PostgresqlDatabase, SqliteDatabase

# db.py vive en src/assets/_common/, así que la raíz del repo está en parents[3].
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_SQLITE_PATH = str(PROJECT_ROOT / "db.sqlite")

# Proxy compartido por TODOS los modelos peewee. Se inicializa con ``bind``.
db = DatabaseProxy()

# SQLite limita las variables por sentencia SQL: 999 antes de 3.32 y 32766 desde 3.32.
_SQLITE_MAX_VARIABLES = (
    32766
    if tuple(int(x) for x in sqlite3.sqlite_version.split(".")[:2]) >= (3, 32)
    else 999
)

# PostgreSQL admite hasta 65535 parámetros por sentencia.
_POSTGRES_MAX_VARIABLES = 65535

# Cache de conexiones por (motor, destino, host, puerto, usuario): reutiliza la
# misma instancia de ``Database`` en vez de abrir una conexión por recurso.
_DATABASES: dict[tuple, Database] = {}


def chunked(rows: list, size: int):
    """Divide ``rows`` en lotes de ``size`` (``insert_many`` no particiona solo)."""
    it = iter(rows)
    while batch := tuple(islice(it, size)):
        yield batch


def max_variables(engine: str) -> int:
    """Máximo de variables por sentencia SQL según el motor."""
    if engine == "postgres":
        return _POSTGRES_MAX_VARIABLES
    return _SQLITE_MAX_VARIABLES


def get_database(
    engine: str,
    database_path: str,
    *,
    host: str | None = None,
    port: int | None = None,
    user: str | None = None,
    password: str | None = None,
    prefer_psycopg3: bool = True,
) -> Database:
    """Devuelve (y cachea) la conexión peewee del motor y destino dados.

    ``database_path`` es la ruta del archivo para SQLite y el nombre de la base
    para PostgreSQL. Con ``engine="postgres"`` y ``prefer_psycopg3=True`` peewee
    usa el adaptador de psycopg 3 (instalado en el entorno).
    """
    key = (engine, database_path, host, port, user)
    database = _DATABASES.get(key)
    if database is None:
        if engine == "postgres":
            database = PostgresqlDatabase(
                database_path,
                host=host,
                port=port,
                user=user,
                password=password,
                prefer_psycopg3=prefer_psycopg3,
            )
        else:
            database = SqliteDatabase(database_path)
        _DATABASES[key] = database
    return database


def bind(proxy: DatabaseProxy, database: Database) -> None:
    """Enlaza ``proxy`` a ``database`` (cierra la conexión previa si cambia).

    ``DatabaseProxy`` no permite reasignar su objeto con ``init``; se usa
    ``initialize``. Si el proxy ya apuntaba a otra base (p. ej. entre tests), se
    cierra la conexión anterior para no dejarla abierta.
    """
    if proxy.obj is database:
        return
    if proxy.obj is not None:
        try:
            proxy.obj.close()
        except Exception:
            pass
    proxy.initialize(database)
