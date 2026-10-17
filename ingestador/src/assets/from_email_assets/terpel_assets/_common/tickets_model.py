"""Réplica pydantic de un ticket Terpel extraído del PDF (compartida).

``parse_ticket_pdf`` devuelve los campos del ticket y antes del upsert se
validan con este modelo para que los errores de tipo salten en el programa y
no en la BD. Los tres campos principales (``o_entrega``, ``estacion``,
``matricula``) son obligatorios: si faltan, el parser ya lanzó
``TerpelParseError`` y la partición cae. El resto son opcionales (los PDFs
siempre los traen, pero un layout nuevo no debería romper la carga).
"""

from __future__ import annotations

from pydantic import BaseModel


class TerpelTicket(BaseModel):
    o_entrega: str
    estacion: str
    matricula: str

    # Datos del suministro.
    fecha: str = ""
    equipo: str = ""
    operacion: str = ""
    producto: str = ""
    p_abastecimiento: str = ""
    operador: str = ""
    cliente: str = ""
    comercializador: str = ""
    forma_pago: str = ""
    nro_vuelo: str = ""
    destino: str = ""
    aeronave: str = ""

    # Servicio: horas y lecturas del contador.
    hora_llegada: str = ""
    hora_conexion: str = ""
    hora_final: str = ""
    hora_inicial: str = ""
    lectura_final: str = ""
    lectura_inicial: str = ""
    galones: str = ""
    temperatura: str = ""
    flow_rate: str = ""

    # Características y pruebas de calidad.
    api_corregido: str = ""
    densidad: str = ""
    presion_dif: str = ""
    prueba_apariencia: str = ""
    prueba_agua: str = ""

