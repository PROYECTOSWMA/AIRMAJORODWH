"""Modelos peewee de las 3 tablas del remitente ``invoicem.lubes@terpel.com``.

Reutilizan el ``db`` (SQLite) y ``BaseModel`` de ``mail_asset``: este remitente manda
tres tipos de documento en el mismo correo y se separan por el nombre del adjunto (o
de la entrada del ZIP, si viene comprimido):

- ``from_email_terpel_invoicem_docs``: facturas (PDFs ``Fact_*``), con
  ``orden_de_compra``/``observaciones`` y el ``agregado_o_entrega`` derivado (el número
  tras ``DT``, que es el índice del ticket).
- ``from_email_terpel_invoicem_tickets``: tickets de suministro (``Reimpresion_*`` u
  ``ORDEN(ES) DE ENTREGA*``), mismo esquema que ``from_email_terpel_tickets_tickets``.
- ``from_email_terpel_invoicem_reports``: filas del Excel ``Reporte abastecimiento``.

``id_attachment`` es una Foreign Key a ``email_attachments`` (el adjunto del que salió
la fila) y es segura porque ``ingest_emails`` es **append-only**: el ``id``
autoincremental de ``email_attachments`` queda estable y la referencia no queda
huérfana tras un re-upsert.
"""

from __future__ import annotations

from peewee import AutoField, CharField, ForeignKeyField, IntegerField

from assets.mail_asset.model import BaseModel, EmailAttachments


class InvoicemDoc(BaseModel):
    """Factura Terpel (1 fila por PDF ``Fact_*``, suelto o dentro de un ZIP)."""

    class Meta:
        table_name = "from_email_terpel_invoicem_docs"

    id = AutoField()              # PK autoincremental
    partition_date = CharField()  # partición diaria (p. ej. "2026-08-14")
    filename = CharField()        # nombre del PDF ``Fact_*``
    observaciones = CharField(default="")
    orden_de_compra = CharField(default="")
    # Derivado de ``orden_de_compra``/``observaciones``: el número tras 'DT' (índice del
    # ticket). Se calcula al ingerir el PDF (``parser_docs.parse_o_entrega``), no en dbt.
    agregado_o_entrega = IntegerField(null=True)
    attachment = ForeignKeyField(
        EmailAttachments, backref="invoicem_docs", object_id_name="id_attachment",
        column_name="id_attachment",
    )  # adjunto padre en email_attachments; acceso crudo vía ``id_attachment``


class InvoicemTicket(BaseModel):
    """Ticket de suministro Terpel del remitente invoicem (1 fila por PDF de ticket)."""

    class Meta:
        table_name = "from_email_terpel_invoicem_tickets"

    attachment = ForeignKeyField(
        EmailAttachments,
        backref="invoicem_tickets",
        object_id_name="id_attachment",
        column_name="id_attachment",
    )  # PDF del ticket en ``email_attachments``
    partition_date = CharField()  # partición del día (misma que la del correo)
    filename = CharField()        # PDF del que se extrajo el ticket

    # Campos requeridos del ticket (si no se identifican, se descarta con warning).
    o_entrega = CharField(default="")
    estacion = CharField(default="")
    matricula = CharField(default="")

    # Datos del suministro.
    fecha = CharField(default="")
    equipo = CharField(default="")
    operacion = CharField(default="")
    producto = CharField(default="")
    p_abastecimiento = CharField(default="")
    operador = CharField(default="")
    cliente = CharField(default="")
    comercializador = CharField(default="")
    forma_pago = CharField(default="")
    nro_vuelo = CharField(default="")
    destino = CharField(default="")
    aeronave = CharField(default="")

    # Servicio: horas y lecturas del contador.
    hora_llegada = CharField(default="")
    hora_conexion = CharField(default="")
    hora_final = CharField(default="")
    hora_inicial = CharField(default="")
    lectura_final = CharField(default="")
    lectura_inicial = CharField(default="")
    galones = CharField(default="")
    temperatura = CharField(default="")
    flow_rate = CharField(default="")

    # Características y pruebas de calidad.
    api_corregido = CharField(default="")
    densidad = CharField(default="")
    presion_dif = CharField(default="")
    prueba_apariencia = CharField(default="")
    prueba_agua = CharField(default="")


class InvoicemReport(BaseModel):
    """Fila del Excel ``Reporte abastecimiento`` (1 fila por vuelo del reporte)."""

    class Meta:
        table_name = "from_email_terpel_invoicem_reports"

    id = AutoField()              # PK autoincremental
    attachment = ForeignKeyField(
        EmailAttachments,
        backref="invoicem_reports",
        object_id_name="id_attachment",
        column_name="id_attachment",
    )  # Excel adjunto en ``email_attachments``
    partition_date = CharField()  # partición del día (misma que la del correo)
    filename = CharField()        # Excel del que salió la fila
    # Columnas del reporte (todas como texto; ver ``parser_reports``).
    fecha = CharField(default="")
    ticket = CharField(default="")
    producto = CharField(default="")
    aerolinea = CharField(default="")
    vuelo = CharField(default="")
    galones = CharField(default="")
    scop = CharField(default="")
    precio = CharField(default="")
    monto = CharField(default="")
    n_factura = CharField(default="")
