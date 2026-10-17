
from __future__ import annotations

from peewee import CharField, ForeignKeyField

from assets.mail_asset.model import BaseModel, EmailAttachments


class TalmaReport(BaseModel):
    """Registro de reporte Talma (1 fila por fila de la tabla del Excel).

    ``id_attachment`` es una Foreign Key al adjunto Excel de
    ``email_attachments`` (el libro del que salió la fila); es segura porque
    ``ingest_emails`` es **append-only** (nunca borra adjuntos ya insertados).
    """

    class Meta:
        table_name = "from_email_talma_reports"

    attachment = ForeignKeyField(
        EmailAttachments,
        backref="talma_reports",
        object_id_name="id_attachment",
        column_name="id_attachment",
    )  # adjunto Excel en ``email_attachments``; acceso crudo vía ``id_attachment``
    partition_date = CharField()  # partición mensual (misma que la del correo)
    filename = CharField()        # adjunto Excel del que se extrajo la fila

    # Los 21 campos de la tabla del Excel (A4:Y4), tal cual (snake_case).
    fecha = CharField(default="")          # 01/12/2025
    estacion = CharField(default="")       # CHICLAYO
    aerolinea = CharField(default="")      # AIR MAJORO SA
    rsir = CharField(default="")           # 0000048910 (columna D, marca el fin)
    aeronave = CharField(default="")       # BEECHCRAFT B-200
    matricula = CharField(default="")      # OB-2092P
    vuelo_l = CharField(default="")        # 2092
    vuelo_s = CharField(default="")        # 2092
    hora_l = CharField(default="")         # 22:08
    hora_s = CharField(default="")         # 00:03
    diferencia = CharField(default="")
    pea_origen = CharField(default="")     # --
    pea_destino = CharField(default="")    # --
    cantidad = CharField(default="")       # 1
    equipo = CharField(default="")         # 1
    peso_kg = CharField(default="")        # Peso (KG)
    servicio = CharField(default="")       # PAQUETE
    tarifa = CharField(default="")         # 70
    moneda = CharField(default="")         # DOL
    estado = CharField(default="")         # Activo
    tipo_rsir = CharField(default="")
