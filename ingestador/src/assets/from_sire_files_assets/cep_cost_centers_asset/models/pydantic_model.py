"""Réplica pydantic de una fila de ``from_sire_cep_cost_centers`` (sin ``period``).

Antes del upsert el asset valida cada aeronave con este modelo para que los
errores de tipo salten en el programa y no en la BD.
"""

from __future__ import annotations

from pydantic import BaseModel


class AeronaveRow(BaseModel):
    """Una aeronave extraída de un XML de compras SIRE del proveedor."""

    id_file: int
    filename: str
    aeronave: str
