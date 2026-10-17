"""Réplica pydantic de una fila de ``sisa_sales`` para validar antes del insert.

``SisaSalesResource.get_sales`` devuelve las filas con claves normalizadas con
``assets.utils.to_db_field`` (snake_case literal de las columnas del endpoint,
p. ej. ``"FECHAEMISIO"`` -> ``fechaemisio``). Antes del upsert se validan con
este modelo para que los errores de tipo/fecha/decimal salten en el programa y
no en la BD. Las columnas extra que el modelo no tiene se descartan al volcar el
modelo validado.

Todos los campos son opcionales a propósito: el endpoint puede devolver celdas
vacías/null en cualquier columna y eso no debe romper la ingesta.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator


def _parse_date(value: Any) -> date | None:
    """Acepta fechas del endpoint ('01/08/2026') o ISO ('2026-08-01'); vacío -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {value!r}")


SisaDate = Annotated[date | None, BeforeValidator(_parse_date)]


def _parse_decimal(value: Any, places: int) -> Decimal | None:
    """Convierte a Decimal de ``places`` decimales; vacío/None -> None.

    ``json.loads`` devuelve floats (p. ej. ``30.0``) y ``Decimal(30.0)`` arrastra
    ruido binario; se pasa por ``str`` y se redondea.
    """
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(
        Decimal("1").scaleb(-places), rounding=ROUND_HALF_UP
    )


def _money(value: Any) -> Decimal | None:
    return _parse_decimal(value, 2)


def _decimal4(value: Any) -> Decimal | None:
    return _parse_decimal(value, 4)


Money = Annotated[Decimal | None, BeforeValidator(_money)]
Decimal4 = Annotated[Decimal | None, BeforeValidator(_decimal4)]


class SisaSalesRow(BaseModel):
    """Fila de la liquidación contable SISA.

    Réplica de ``SisaSales`` (sin ``period``, ``nombre_empresa`` y
    ``nombre_sede``, que inyecta el asset al hacer el upsert).
    """

    numerofila: int | None = None
    codorgdoref: str | None = None
    codperdoref: str | None = None
    codseddoref: str | None = None
    codempdoref: str | None = None
    codregdoref: str | None = None
    codnvedoref: str | None = None
    nomtipmoned: str | None = None
    t01tipdoref: str | None = None
    nro_documento: str | None = None
    fechaemisio: SisaDate = None
    fechavuelo: SisaDate = None
    numeroderuc: str | None = None
    ruc_cliente20: str | None = None
    razonsocial: str | None = None
    dorefsubtot: Money = None
    dorefimpimp: Money = None
    doreftotnum: Money = None
    cuenta_contable: str | None = None
    nomtipopago: str | None = None
    aenavmatric: str | None = None
    nomsitdoref: str | None = None
    t01lugorige: str | None = None
    desorigen: str | None = None
    t01lugdesti: str | None = None
    desdestino: str | None = None
    tipcammoned: Decimal4 = None
    cantidad: Decimal4 = None
    observacion: str | None = None


class SisaCreditNoteRow(BaseModel):
    """Fila de una **nota de crédito** de SISA.

    Réplica de ``SisaCreditNote`` (sin ``period``, ``nombre_empresa`` y
    ``nombre_sede``, que inyecta el asset al hacer el upsert). Columnas del
    procedure ``USP_UVW_LIQUIDACION_NOTACREDITO`` normalizadas.
    """

    numerofila: int | None = None
    codorgdoref: str | None = None
    codempdoref: str | None = None
    codseddoref: str | None = None
    codperdoref: str | None = None
    codregdoref: str | None = None
    codnvedoref: str | None = None
    nomtipdoref: str | None = None
    razonsocial: str | None = None
    numeroderuc: str | None = None
    sunatnserie: str | None = None
    sunatnforma: str | None = None
    fechaemisio: SisaDate = None
    fechavuelo: SisaDate = None
    t01tipopago: str | None = None
    t01tipmoned: str | None = None
    nomtipmoned: str | None = None
    nomtipopago: str | None = None
    dorefsubtot: Money = None
    dorefdespor: Money = None
    dorefdesimp: Money = None
    dorefimppor: Money = None
    dorefimpimp: Money = None
    doreftotnum: Money = None
    doreftotlet: str | None = None
    t01sitdoref: str | None = None
    swestadoreg: str | None = None
    sunatnfodve: str | None = None
    nomsitdoref: str | None = None
