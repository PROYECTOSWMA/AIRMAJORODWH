"""Réplica pydantic de una fila de ``from_sire_icaro_cost_centers`` (sin ``period``).

Antes del upsert el asset valida cada fila con este modelo para que los errores de
tipo salten en el programa y no en la BD.
"""

from __future__ import annotations

from pydantic import BaseModel


class AeronaveRow(BaseModel):
    """Aeronave y ticket extraídos de un XML de compras SIRE de ICARO."""

    id_file: int
    filename: str
    aeronave: str           # 4 dígitos (lo lee el dbt)
    nro_ticket: str
    texto_planta: str
    texto_matricula: str
    matricula: str
    schema_info: str        # texto completo del ticket

