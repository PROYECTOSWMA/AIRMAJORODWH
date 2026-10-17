"""Modelo peewee de la tabla ``from_email_terpel_tickets_tickets`` (tickets de suministro Terpel).

Reutiliza el ``db`` (SQLite) y ``BaseModel`` de ``mail_asset``: cada fila es un
ticket extraído del PDF adjunto a un correo de ``ticketslima@exolum.com``.
``id_attachment`` es una Foreign Key al PDF de ``email_attachments`` (el ticket
del que salió la fila): es segura porque ``ingest_emails`` es **append-only**
(nunca borra adjuntos ya insertados), así que un re-upsert no borra en cascada lo
ya materializado.

Los valores numéricos del ticket se guardan como texto: los PDFs mezclan
decimales con coma (``3,033``, ``24,99``) y separadores de miles (``61,188,092``
en las lecturas), así que pasarlos a Decimal aquí sería ambiguo.
"""

from __future__ import annotations

from peewee import CharField, ForeignKeyField

from assets.mail_asset.model import BaseModel, EmailAttachments


class TerpelTicket(BaseModel):
    """Ticket de suministro Terpel (1 fila por PDF adjunto)."""

    class Meta:
        table_name = "from_email_terpel_tickets_tickets"

    attachment = ForeignKeyField(
        EmailAttachments,
        backref="terpel_tickets",
        object_id_name="id_attachment",
        column_name="id_attachment",
    )  # PDF del ticket en ``email_attachments``; acceso crudo vía ``id_attachment``
    partition_date = CharField()  # partición del día (misma que la del correo)
    filename = CharField()        # adjunto PDF del que se extrajo el ticket

    # Campos requeridos del ticket (si no se identifican, falla la partición).
    o_entrega = CharField(default="")
    estacion = CharField(default="")
    matricula = CharField(default="")

    # Datos del suministro.
    fecha = CharField(default="")               # "01/01/2026 18:22" (la hora en el mismo campo)
    equipo = CharField(default="")              # "RF05 - Refueller"
    operacion = CharField(default="")           # SUMINISTRO
    producto = CharField(default="")            # JET A-1
    p_abastecimiento = CharField(default="")    # "14"
    operador = CharField(default="")            # "76535989-... NOMBRE"
    cliente = CharField(default="")             # "AIR MAJORO S.A.C" (label Cliente/Aerolinea)
    comercializador = CharField(default="")     # TER/TERPEL COMERCIAL
    forma_pago = CharField(default="")          # CREDITO
    nro_vuelo = CharField(default="")           # "2221"
    destino = CharField(default="")             # PCL
    aeronave = CharField(default="")            # B 200

    # Servicio: horas y lecturas del contador.
    hora_llegada = CharField(default="")
    hora_conexion = CharField(default="")
    hora_final = CharField(default="")
    hora_inicial = CharField(default="")
    lectura_final = CharField(default="")
    lectura_inicial = CharField(default="")
    galones = CharField(default="")
    temperatura = CharField(default="")         # Temp. (░F)
    flow_rate = CharField(default="")           # FLOW RATE (GPM)

    # Características y pruebas de calidad.
    api_corregido = CharField(default="")       # API Corregido (60 ░F)
    densidad = CharField(default="")            # Densidad (Kg/Gal)
    presion_dif = CharField(default="")         # Presion Dif. Observada
    prueba_apariencia = CharField(default="")   # Claro/Brillante
    prueba_agua = CharField(default="")         # Prueba deteccion de Agua

