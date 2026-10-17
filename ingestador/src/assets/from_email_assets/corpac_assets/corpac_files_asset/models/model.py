"""Modelo peewee de la tabla ``from_email_corpac_files`` (archivos hijos de correos CORPAC).

Reutiliza el ``db`` (SQLite) y ``BaseModel`` de ``mail_asset``: los archivos son
hijos de ``emails`` (``id_email`` es el ``id`` del correo) mediante una Foreign
Key. Es segura porque ``ingest_emails`` ahora es **append-only** (nunca borra
correos ya insertados), así que re-materializar no borra en cascada los archivos
ya descargados.

No hay ``empresa``: el padre es el correo y la partición es ``partition_date``.
"""

from __future__ import annotations

from peewee import CharField, ForeignKeyField, TextField

from assets.mail_asset.model import BaseModel, Email


class CorpacFile(BaseModel):
    """Archivo (PDF/XML/OC...) descargado del portal CORPAC (1 a N con ``emails``)."""

    class Meta:
        table_name = "from_email_corpac_files"

    padre = ForeignKeyField(
        Email, backref="corpac_files", object_id_name="id_email",
        column_name="id_email",
    )  # correo del que proviene el archivo (emails.id); crudo vía ``id_email``
    partition_date = CharField()  # partición del día (misma que la del correo)
    filename = CharField()
    data = TextField()            # contenido del archivo en base64
