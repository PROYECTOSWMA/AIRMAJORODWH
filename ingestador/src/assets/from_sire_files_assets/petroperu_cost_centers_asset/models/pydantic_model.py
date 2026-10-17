"""Réplica pydantic de una fila de ``from_sire_petroperu_cost_centers`` (sin ``period``).

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
    # DatoAdicional de código 31 del comprobante (última palabra y texto completo).
    aeropuerto: str | None = None
    aeropuerto_completo: str | None = None
