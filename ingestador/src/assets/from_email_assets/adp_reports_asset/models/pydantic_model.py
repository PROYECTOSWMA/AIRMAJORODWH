"""Réplica pydantic de un registro de servicio ADP extraído del Excel.

``parse_report_data`` devuelve los campos de cada fila como texto y antes del
upsert se validan con este modelo para que los errores de tipo salten en el
programa y no en la BD (fail-fast: si un valor **no vacío** no se puede convertir
al tipo declarado se lanza ``ValidationError`` y cae la partición del mes).

Tipos declarados según la estructura esperada de ``from_email_adp_reports``:

- ``text``      -> ``str``
- ``date``      -> ``datetime.date``   (parseo de ``"31.01.2026"``)
- ``timestamp`` -> ``datetime.datetime`` (parseo de ``"30.01.2026 20:11:00"``)
- ``int``       -> ``int``             (parseo de ``"3"``)
- ``float``     -> ``Decimal`` de máximo 10 dígitos; se pasa por ``str`` para no
  arrastrar ruido binario y se cuantiza a 3 decimales.

Los campos numéricos/fecha/decimal aceptan celdas vacías (``None``/``""``): una
fila puede traer celdas en blanco y no debe romper la carga. Además, ADP rellena
fechas/timestamps vacíos con el placeholder ``00.00.0000 ...``, que también se
interpreta como ``None``. Solo un valor **poblado** y no nulo que no cumpla el
tipo declarado levanta excepción.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
import re
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator

# Máximo de dígitos significativos de los decimales (``float`` -> ``Decimal``).
_MAX_DIGITS = 10
_DECIMAL_PLACES = 3


def _es_fecha_nula(value: Any) -> bool:
    """``True`` si la fecha es el placeholder nulo de ADP (``00.00.0000``).

    ADP rellena fechas/timestamps vacíos con ``00.00.0000`` (y ``00:00:00`` de
    hora); eso no es una fecha real, así que se trata como ``None`` en vez de
    derrumbar la carga. Detecta el día, mes y año a cero en los formatos con
    separador ``.``, ``/`` o ``-`` (``00.00.0000 ...``).
    """
    if not isinstance(value, str):
        return False
    fecha = value.strip().split(" ")[0]
    partes = re.split(r"[./-]", fecha)
    if len(partes) < 3:
        return False
    dia, mes, anio = partes[:3]
    return dia in ("00", "0") and mes in ("00", "0") and anio.startswith("0")


def _parse_date(value: Any) -> date | None:
    """``"31.01.2026"`` -> ``date``; vacío/None -> ``None``."""
    if value is None or value == "" or _es_fecha_nula(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Fecha no válida: {value!r}")


def _parse_datetime(value: Any) -> datetime | None:
    """``"30.01.2026 20:11:00"`` -> ``datetime``; vacío/None -> ``None``."""
    if value is None or value == "" or _es_fecha_nula(value):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    for fmt in ("%d.%m.%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Timestamp no válido: {value!r}")


def _parse_int(value: Any) -> int | None:
    """``"3"`` (o ``"3.0"``) -> ``3``; vacío/None -> ``None``."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return int(text)


def _digit_count(d: Decimal) -> int:
    """Cantidad de dígitos significativos de un Decimal (sin punto ni signo)."""
    return len(format(d, "f").replace(".", "").replace("-", "").lstrip("0") or "0")


def _parse_decimal(value: Any) -> Decimal | None:
    """Convierte a ``Decimal`` de máx. ``_MAX_DIGITS`` dígitos; vacío/None -> None.

    ``json.loads``/Excel devuelven floats (p. ej. ``5.675``) y ``Decimal(5.675)``
    arrastraría ruido binario; se pasa por ``str`` y se cuantiza a
    ``_DECIMAL_PLACES`` decimales. Si el resultado supera ``_MAX_DIGITS`` dígitos
    se levanta ``ValueError`` (la fila no cumple la estructura y el asset falla).
    """
    if value is None or value == "":
        return None
    decimal = Decimal(str(value)).quantize(
        Decimal("1").scaleb(-_DECIMAL_PLACES), rounding=ROUND_HALF_UP
    )
    if _digit_count(decimal) > _MAX_DIGITS:
        raise ValueError(
            f"Decimal supera los {_MAX_DIGITS} dígitos máximos: {value!r}"
        )
    return decimal


# Aliases tipados para reutilizar en los campos.
Fecha = Annotated[date | None, BeforeValidator(_parse_date)]
FecHora = Annotated[datetime | None, BeforeValidator(_parse_datetime)]
Entero = Annotated[int | None, BeforeValidator(_parse_int)]
Decimal10 = Annotated[Decimal | None, BeforeValidator(_parse_decimal)]


class AdpReport(BaseModel):
    """Registro de servicio ADP (1 fila por fila de la tabla del Excel)."""

    servicio: str = ""
    nro_operacion: str = ""
    operacion: str = ""
    apto: str = ""
    origen: str = ""
    destino: str = ""
    vuelo_llegada: str = ""
    vuelo_salida: str = ""
    fec_hora_llegada: FecHora = None
    fec_hora_salida: FecHora = None
    total_horas: Decimal10 = None
    num_pasajeros: Entero = None
    imp_unitario: Decimal10 = None
    peso_carga: Decimal10 = None
    descripcion_servicio: str = ""
    matricula: str = ""
    tipo_aero: str = ""
    pmd: Decimal10 = None
    oaci: str = ""
    vuelo: str = ""
    imp_igv: Decimal10 = None
    factura_sd: str = ""
    referencia: str = ""
    cliente: str = ""
    nom_cliente: str = ""
    fecha: Fecha = None
    moneda: str = ""
    cliente_o: str = ""
    cliente_origen: str = ""
    estado_operac: str = ""
