

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# Namespaces UBL 2.1 del comprobante de SUNAT.
_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

# Texto del ticket: ``Ticket 1338-PLANTA CHICLAYO -Matricula:OB2092/12699199932``.
# ``texto_matricula`` lee todo hasta la ``/`` (admite espacios, p. ej. ``OB 2180``).
TICKET_RE = re.compile(
    r"^Ticket (?P<nro_ticket>\d+)-PLANTA (?P<texto_planta>.+?)"
    r"\s*-Matricula:(?P<texto_matricula>[^/]+)/(?P<numero>\d+)$"
)

# Matrícula: los 4 primeros dígitos consecutivos del texto de matrícula.
MATRICULA_RE = re.compile(r"\d{4}")

# Etiqueta raíz (UBL) del comprobante -> etiqueta de su línea de detalle.
_LINEA_POR_RAIZ = {
    "Invoice": "InvoiceLine",
    "CreditNote": "CreditNoteLine",
}


class IcaroParseError(Exception):
    """El XML de ICARO no trae el ticket esperado en su línea de detalle."""


def parse_ticket(xml: str) -> dict[str, str]:
    """Parsea el ticket de ICARO sea factura (``Invoice``) o nota de crédito.

    Detecta la etiqueta raíz y usa el parser correspondiente
    (``parse_invoice_ticket`` / ``parse_credit_note_ticket``).
    """
    root = _parse_xml(xml)
    raiz = root.tag.split("}")[-1]
    linea = _LINEA_POR_RAIZ.get(raiz)
    if linea is None:
        raise IcaroParseError(f"XML de ICARO con raíz no soportada: <{raiz}>")
    return _parse_linea(root, raiz, linea)


def parse_invoice_ticket(xml: str) -> dict[str, str]:
    """Factura (``Invoice``): ticket de la ``cac:InvoiceLine``."""
    return _parse_linea(_parse_xml(xml), "Invoice", "InvoiceLine")


def parse_credit_note_ticket(xml: str) -> dict[str, str]:
    """Nota de crédito (``CreditNote``): ticket de la ``cac:CreditNoteLine``."""
    return _parse_linea(_parse_xml(xml), "CreditNote", "CreditNoteLine")


def _parse_xml(xml: str) -> ET.Element:
    """``fromstring`` sin el BOM (el XML de SUNAT lo trae al decodificar el ZIP)."""
    try:
        return ET.fromstring(xml.lstrip("\ufeff"))
    except ET.ParseError as exc:
        raise IcaroParseError(f"XML de ICARO ilegible: {exc}") from exc


def _parse_linea(root: ET.Element, raiz: str, linea: str) -> dict[str, str]:
    """Extrae el ticket de la única ``cac:<linea>`` del comprobante ``<raiz>``."""
    lineas = root.findall(f"{{{_CAC}}}{linea}")
    if len(lineas) != 1:
        raise IcaroParseError(
            f"Se esperaba 1 cac:{linea} en el <{raiz}> de ICARO, hay {len(lineas)}"
        )

    nodo = lineas[0].find(
        f"{{{_CAC}}}BillingReference/{{{_CAC}}}AdditionalDocumentReference/"
        f"{{{_CBC}}}ID[@schemeID='txt']"
    )
    texto = (nodo.text or "").strip() if nodo is not None else ""
    if not texto:
        raise IcaroParseError(
            f"El cac:{linea} no trae cbc:ID schemeID='txt' con el ticket"
        )

    match = TICKET_RE.match(texto)
    if not match:
        raise IcaroParseError(f"Ticket de ICARO fuera de formato: {texto!r}")

    grupos = match.groupdict()
    matricula = MATRICULA_RE.search(grupos["texto_matricula"])
    if not matricula:
        raise IcaroParseError(
            f"Texto de matrícula sin 4 dígitos: {grupos['texto_matricula']!r}"
        )

    return {
        "nro_ticket": grupos["nro_ticket"],
        "texto_planta": grupos["texto_planta"].strip(),
        "texto_matricula": grupos["texto_matricula"].strip(),
        "matricula": matricula.group(0),
        "schema_info": texto,
    }

