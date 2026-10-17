"""Parsing del PDF del ticket Terpel (sin I/O, compartido por los assets de tickets).

Lo comparten los dos assets de tickets de Terpel, que usan el mismo layout:

- ``terpel_tickets_daily`` (remitente ``ticketslima@exolum.com``): cada correo trae
  un PDF adjunto con el tiquete de suministro (los asuntos son ``Tiquete Exolum``,
  ``CREACIËN de Suministro`` y ``MODIFICACIËN de Suministro``).
- ``terpel_invoicem_daily`` (remitente ``invoicem.lubes@terpel.com``): los tickets
  llegan como ``Reimpresion_<o_entrega>.pdf`` / ``ORDEN(ES) DE ENTREGA*.pdf``,
  sueltos o dentro de un ZIP ``ORDENES DE ENTREGA*.zip``.

El ticket es **solo
cabecera**: ``O.Entrega``, ``Estacion``, ``Matricula``, ``Fecha``, ``Equipo``,
``Operacion``, ``Producto``, ``Operador``, ``Cliente``/``Aerolinea``,
``Comercializador``, ``Forma de Pago``, ``No. Vuelo``, ``Destino``,
``Aeronave``, horas y lecturas de ``Llegada/Conexion/Final/Inicial``,
``GALONES``, ``Temp.``, ``FLOW RATE``, ``API Corregido``, ``Densidad``,
``Presion Dif. Observada`` y pruebas de calidad.

El parseo es table-driven: cada campo se busca por **label** (regex) en el
texto plano extraído del PDF (``pdfplumber``). Casos reales que maneja:

- **Varios campos por línea** (``Estacion: LIM Fecha: ...``): el valor se corta
  en el siguiente label conocido.
- **Layout de 2 columnas duplicadas** (los PDFs de Suministro imprimen el
  tiquete dos veces por página): los labels de la segunda columna acotan los
  valores de la primera.
- **Secciones repetidas** (``CLIENTE:`` como cabecera y ``Cliente:``/
  ``Aerolinea:`` como campo): se itera sobre las ocurrencias del label hasta
  dar con un valor.
- **``Final:``/``Inicial:`` con dos valores** (hora + lectura de contador):
  se parten en ``hora_final``/``lectura_final`` y ``hora_inicial``/
  ``lectura_inicial``.

Si un campo **requerido** (``o_entrega``, ``estacion``, ``matricula``) no se
identifica se lanza ``TerpelParseError`` y el asset derrumba la partición
(fail-fast, sin insertar nada del día).
"""

from __future__ import annotations

import io
import re

import pdfplumber


class TerpelParseError(Exception):
    """El PDF del ticket Terpel no se pudo parsear (campo requerido ausente)."""


# Campos del ticket: nombre de columna -> variantes de regex del label (en
# orden de búsqueda). IGNORECASE: da igual mayúsculas/minúsculas y acentos.
# Los paréntesis del label (``Temp. (░F)``, ``API Corregido (60 ░F)``,
# ``Densidad (Kg/Gal)``, ``FLOW RATE (GPM)``) se consumen en el propio label
# para que el valor empiece después del ``:``.
_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "o_entrega": (r"O\s*\.\s*ENTREGA",),
    "estacion": (r"ESTACI[OÓ]N",),
    "fecha": (r"FECHA",),
    "equipo": (r"EQUIPO",),
    "operacion": (r"OPERACI[OÓ]N",),
    "producto": (r"PRODUCTO",),
    "p_abastecimiento": (r"P\s*\.?\s*ABASTECIMIENTO",),
    "operador": (r"OPERADOR",),
    "cliente": (r"CLIENTE|AEROL[IÍ]NEA",),
    "comercializador": (r"COMERCIALIZADOR",),
    "forma_pago": (r"FORMA\s+DE\s+PAGO",),
    "nro_vuelo": (r"NO\.?\s*VUELO",),
    "destino": (r"DESTINO",),
    "matricula": (r"MATR[IÍ]CULA",),
    "aeronave": (r"AERONAVE",),
    "hora_llegada": (r"LLEGADA",),
    "hora_conexion": (r"CONEXI[OÓ]N",),
    "galones": (r"GALONES",),
    "temperatura": (r"TEMP\.?\s*\([^)]*\)",),
    "flow_rate": (r"FLOW\s+RATE\s*\([^)]*\)",),
    "api_corregido": (r"API\s+CORREGIDO\s*\([^)]*\)",),
    "densidad": (r"DENSIDAD\s*\([^)]*\)",),
    "presion_dif": (r"PRESION\s+DIF\.?\s*OBSERVADA",),
    "prueba_apariencia": (r"CLARO\s*/\s*BRILLANTE",),
    "prueba_agua": (
        r"PRUEBA\s+(?:QUIMICA\s+DE\s+)?DETECCION\s+DE\s+AGUA"
        r"(?:\s+SHELL\s+WATER\s*\(R\))?",
    ),
}

# Campos sin los que el ticket no se considera identificado.
_REQUIRED_FIELDS = ("o_entrega", "estacion", "matricula")

# Labels de las líneas con dos valores (hora + lectura del contador).
_COMPOSITE_LABELS = (r"FINAL", r"INICIAL")

# Separa el valor del label: "Estacion: LIM" -> "LIM".
_SEP = re.compile(r"^[\s:#\-]+")

# Cualquier label conocido: corta el valor en cuanto aparece otro campo en la
# misma línea (layout de varios campos por línea y de 2 columnas).
_ANY_LABEL = re.compile(
    "|".join(
        f"(?:{p})"
        for ps in tuple(_FIELD_LABELS.values())
        + tuple((p,) for p in _COMPOSITE_LABELS)
        for p in ps
    ),
    re.IGNORECASE,
)


def _normalize_text(text: str) -> str:
    """Colapsa el whitespace horizontal pero conserva las líneas del PDF."""
    return "\n".join(
        " ".join(line.split()) for line in text.splitlines() if line.strip()
    )


def _extract_value(resto: str) -> str:
    """Valor a partir del resto del texto tras un label.

    Recorta los separadores (``:``, ``#``, espacios, saltos de línea) y corta
    en el siguiente label conocido o al final de la línea.
    """
    resto = _SEP.sub("", resto)
    linea = resto.splitlines()[0] if resto else ""
    match = _ANY_LABEL.search(linea)
    if match:
        linea = linea[: match.start()]
    return linea.strip()


def _extract_hora_lectura(normalized: str, label: str) -> tuple[str, str]:
    """Hora y lectura de las líneas ``Final:``/``Inicial:`` (dos valores)."""
    for match in re.finditer(label, normalized, flags=re.IGNORECASE):
        valor = _extract_value(normalized[match.end() :])
        if not valor:
            continue
        tokens = valor.split(None, 1)
        if not tokens:
            continue
        hora = tokens[0]
        lectura = tokens[1].strip() if len(tokens) > 1 else ""
        return hora, lectura
    return "", ""


def parse_ticket_text(text: str) -> dict[str, str]:
    """Extrae los campos del ticket desde el texto plano del PDF.

    Cada campo se busca por label en todo el texto: se itera sobre las
    ocurrencias hasta encontrar una con valor (las cabeceras de sección como
    ``CLIENTE:`` solas no dan valor y se saltan). Un campo requerido sin valor
    lanza ``TerpelParseError``.
    """
    normalized = _normalize_text(text)
    result: dict[str, str] = {}
    for field, patterns in _FIELD_LABELS.items():
        valor = ""
        for pattern in patterns:
            for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
                valor = _extract_value(normalized[match.end() :])
                if valor:
                    break
            if valor:
                break
        result[field] = valor

    hora_final, lectura_final = _extract_hora_lectura(
        normalized, _COMPOSITE_LABELS[0]
    )
    hora_inicial, lectura_inicial = _extract_hora_lectura(
        normalized, _COMPOSITE_LABELS[1]
    )
    result["hora_final"] = hora_final
    result["lectura_final"] = lectura_final
    result["hora_inicial"] = hora_inicial
    result["lectura_inicial"] = lectura_inicial

    for required in _REQUIRED_FIELDS:
        if not result[required]:
            raise TerpelParseError(
                f"no se pudo identificar el campo requerido '{required}' "
                f"(labels identificados: {[k for k, v in result.items() if v]})"
            )
    return result


def extract_ticket_text(pdf_bytes: bytes) -> str:
    """Extrae el texto de todas las páginas del PDF del ticket."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if not pdf.pages:
                raise TerpelParseError("PDF sin páginas")
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except TerpelParseError:
        raise
    except Exception as exc:
        raise TerpelParseError(f"no se pudo abrir el PDF: {exc}") from exc


def parse_ticket_pdf(pdf_bytes: bytes) -> dict[str, str]:
    """Parsea un PDF de ticket Terpel y devuelve los campos del ticket."""
    return parse_ticket_text(extract_ticket_text(pdf_bytes))
