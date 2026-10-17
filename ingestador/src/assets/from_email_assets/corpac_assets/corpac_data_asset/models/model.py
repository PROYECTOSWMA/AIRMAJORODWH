"""Modelos peewee de los datos extraídos del PDF CORPAC de servicios.

``from_email_corpac_headers`` es 1:1 con cada PDF ``01-*.pdf`` de ``from_email_corpac_files`` (una
factura) y ``from_email_corpac_details`` es 1:N con su cabecera (un detalle por servicio
de la tabla del PDF).

Reutilizan el mismo ``db`` (SQLite) y ``BaseModel`` de ``mail_asset``. El
asset hace upsert total del día: borra las cabeceras del día (y sus detalles)
e inserta las nuevas; por eso los detalles guardan ``partition_date``
denormalizada, igual que los archivos en ``from_email_corpac_files``.
"""

from __future__ import annotations

from peewee import CharField, DecimalField, ForeignKeyField

from assets.from_email_assets.corpac_assets.corpac_files_asset.models.model import (
    CorpacFile,
)
from assets.mail_asset.model import BaseModel


class CorpacHeader(BaseModel):
    """Cabecera de la factura de servicios (1:1 con un PDF ``01-*.pdf``)."""

    class Meta:
        table_name = "from_email_corpac_headers"

    file = ForeignKeyField(
        CorpacFile,
        backref="headers",
        object_id_name="file_id",
        column_name="file_id",
    )  # PDF en ``from_email_corpac_files`` (``from_email_corpac_files.id``); acceso crudo vía ``file_id``
    partition_date = CharField()
    filename = CharField()  # 01-*.pdf

    # Réplica literal de la cabecera del PDF.
    factura = CharField(default="")        # F0250029006
    fecha_doc = CharField(default="")      # 11/08/2026
    fch_impresion = CharField(default="")  # 12/08/2026
    hora = CharField(default="")           # 00:19:46
    pagina = CharField(default="")         # "1 de 1"
    cliente = CharField(default="")        # "306390 AIR MAJORO SOCIEDAD ANONIMA"
    matricula = CharField(default="")      # OB-2200
    tipo_aeronave = CharField(default="")  # CESSNA C-208
    pmd = CharField(default="")            # 3.10


class CorpacDetail(BaseModel):
    """Detalle de servicio de la tabla del PDF (1 a N con ``from_email_corpac_headers``)."""

    class Meta:
        table_name = "from_email_corpac_details"

    header = ForeignKeyField(CorpacHeader, backref="details", on_delete="CASCADE")
    partition_date = CharField()

    servicio = CharField(default="")
    aeropuerto_origen = CharField(default="")
    aeropuerto_destino = CharField(default="")
    vuelo_llegada = CharField(default="")
    vuelo_salida = CharField(default="")
    ruta_aerea = CharField(default="")
    total_km = DecimalField(max_digits=18, decimal_places=2, null=True)
    fecha_llegada = CharField(default="")  # "11/08/2026 15:12" (UTC)
    fecha_salida = CharField(default="")   # "11/08/2026 14:12" (UTC)
    total_min = CharField(default="")
    moneda = CharField(default="")  # "S/" o "US$"
    precio_unitario = DecimalField(max_digits=18, decimal_places=2, null=True)
