"""Modelo peewee de la tabla ``from_email_adp_reports`` (servicios del Excel de ADP).

Reutiliza el ``db`` (SQLite) y ``BaseModel`` de ``mail_asset``: cada fila es un
registro de la tabla del Excel adjunto a un correo de
``ladyliz.moreno@adp.com.pe``. ``id_attachment`` es una Foreign Key al adjunto
Excel de ``email_attachments`` (el libro del que salió la fila): es segura porque
``ingest_emails`` es **append-only** (nunca borra adjuntos ya insertados), así que
el ``id`` autoincremental de ``email_attachments`` queda estable y un re-upsert no
borra en cascada lo ya materializado.

Los tipos de columna reflejan la estructura esperada del Excel de ADP:

- ``text``      -> ``CharField``
- ``date``      -> ``DateField``
- ``timestamp`` -> ``DateTimeField``
- ``int``       -> ``IntegerField``
- ``float``     -> ``DecimalField`` de máximo 10 dígitos (3 decimales)

Los campos ``date``/``timestamp``/``int``/``decimal`` son ``null=True``: una
fila puede traer celdas vacías y eso no debe romper la carga. La conversión de
los valores (que el parser entrega como texto) la hace el modelo pydantic antes
del upsert; si un valor **no vacío** no cumple el tipo declarado, la validación
lanza excepción y cae la partición.
"""

from __future__ import annotations

from peewee import (
    AutoField,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    ForeignKeyField,
    IntegerField,
)

from assets.mail_asset.model import BaseModel, EmailAttachments


class AdpReport(BaseModel):
    """Registro de servicio ADP (1 fila por fila de la tabla del Excel)."""

    class Meta:
        table_name = "from_email_adp_reports"

    id = AutoField()              # PK autoincremental (``id`` del enunciado)

    attachment = ForeignKeyField(
        EmailAttachments,
        backref="adp_reports",
        object_id_name="id_attachment",
        column_name="id_attachment",
    )  # adjunto Excel en ``email_attachments``; acceso crudo vía ``id_attachment``
    partition_date = DateField()  # partición mensual (misma que la del correo)
    filename = CharField()        # adjunto Excel del que se extrajo la fila

    # Los 30 campos de la tabla del Excel, tal cual (snake_case).
    servicio = CharField(default="")          # 3300000013
    nro_operacion = CharField(default="")     # 1000831517
    operacion = CharField(default="")         # AP11
    apto = CharField(default="")              # PISCO
    origen = CharField(default="")            # SPJC
    destino = CharField(default="")
    vuelo_llegada = CharField(default="")
    vuelo_salida = CharField(default="")      # OB-2092
    fec_hora_llegada = DateTimeField(null=True)  # 30.07.2026 13:37:00
    fec_hora_salida = DateTimeField(null=True)
    total_horas = DecimalField(max_digits=10, decimal_places=3, null=True)
    num_pasajeros = IntegerField(null=True)
    imp_unitario = DecimalField(max_digits=10, decimal_places=3, null=True)  # 1.67
    peso_carga = DecimalField(max_digits=10, decimal_places=3, null=True)
    descripcion_servicio = CharField(default="")  # ATERRIZAJE NACIONAL DIURNO
    matricula = CharField(default="")         # OB-2092
    tipo_aero = CharField(default="")         # BEECHCRAFT-BEEC
    pmd = DecimalField(max_digits=10, decimal_places=3, null=True)  # 5.675
    oaci = CharField(default="")              # SPSO
    vuelo = CharField(default="")
    imp_igv = DecimalField(max_digits=10, decimal_places=3, null=True)  # 0.3
    factura_sd = CharField(default="")        # 953102352
    referencia = CharField(default="")        # 01-0F100-0006035
    cliente = CharField(default="")           # 20003659
    nom_cliente = CharField(default="")       # AIR MAJORO S.A.
    fecha = DateField(null=True)              # 31.07.2026
    moneda = CharField(default="")            # USD
    cliente_o = CharField(default="")         # 20003659
    cliente_origen = CharField(default="")    # AIR MAJORO S.A.
    estado_operac = CharField(default="")     # FACTURA
