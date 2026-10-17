
from __future__ import annotations

from pydantic import BaseModel


class TalmaReport(BaseModel):
    fecha: str = ""
    estacion: str = ""
    aerolinea: str = ""
    rsir: str = ""
    aeronave: str = ""
    matricula: str = ""
    vuelo_l: str = ""
    vuelo_s: str = ""
    hora_l: str = ""
    hora_s: str = ""
    diferencia: str = ""
    pea_origen: str = ""
    pea_destino: str = ""
    cantidad: str = ""
    equipo: str = ""
    peso_kg: str = ""
    servicio: str = ""
    tarifa: str = ""
    moneda: str = ""
    estado: str = ""
    tipo_rsir: str = ""
