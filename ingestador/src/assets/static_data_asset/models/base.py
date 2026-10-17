"""``BaseModel`` compartido de los modelos de las fuentes estáticas.

Todos los modelos del asset ``static_data_asset`` comparten el ``db`` de
``assets._common.db`` (un ``DatabaseProxy``), así que el motor es intercambiable
(SQLite/PostgreSQL) sin tocar los modelos.
"""
from __future__ import annotations

from peewee import Model

from assets._common.db import db


class BaseModel(Model):
    """Modelo peewee enlazado al ``db`` compartido del repo."""

    class Meta:
        database = db
