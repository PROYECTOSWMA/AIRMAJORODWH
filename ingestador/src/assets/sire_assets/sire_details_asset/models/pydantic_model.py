"""Réplica pydantic de un ítem de detalle de comprobante CPE.

``CpeDetailsResource.get_items`` devuelve los ítems con claves snake_case (ya
normalizadas desde ``informacionItems`` de la API). Antes del upsert se validan con
este modelo para que los errores de tipo/monto salten en el programa y no en la BD.

A diferencia de las filas de la propuesta (que toleran celdas vacías de SUNAT),
aquí todos los campos son obligatorios; un monto que la API manda como ``None``
se registra como ``0.00``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator


def _parse_decimal(value: Any) -> Decimal:
    """Convierte a Decimal de 2 decimales.

    ``json.loads`` devuelve floats (p. ej. ``36.53``) y ``Decimal(36.53)`` arrastra
    ruido binario; se pasa por ``str`` y se redondea a 2 decimales. Un ``None``
    (la API a veces no manda el monto, p. ej. ``mto_imp_total``) se registra
    como ``0.00``.
    """
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, BeforeValidator(_parse_decimal)]


class SireDetailsItem(BaseModel):
    """Un ítem de línea de un comprobante (informacionItems).

    Réplica de las tablas ``sire_sales_details``/``sire_purchs_details`` (sin el
    FK ni ``period``/``empresa``, que inyecta el asset al hacer el upsert).
    """

    cnt_items: Money
    cod_unidad_medida: str
    des_unidad_medida: str
    des_codigo: str
    des_item: str
    mto_val_unitario: Money
    mto_icbper: Money
    mto_desc: Money
    mto_imp_total: Money
