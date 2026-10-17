"""Tests del parser **propio** de ICARO (ticket en la línea del comprobante).

El XML real de ICARO (UBL) trae el ticket en ``cbc:ID schemeID="txt"`` (CDATA) de
``cac:BillingReference/cac:AdditionalDocumentReference``, dentro de la única línea:
``Invoice`` → ``cac:InvoiceLine`` y ``CreditNote`` → ``cac:CreditNoteLine``.
"""

import pytest

from assets.from_sire_files_assets.icaro_cost_centers_asset.parser import (
    IcaroParseError,
    parse_credit_note_ticket,
    parse_invoice_ticket,
    parse_ticket,
)

_CAC = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_CBC = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"

# Textos reales verificados en BD (CHICLAYO lleva un espacio antes del guion).
TEXTO_CHICLAYO = "Ticket 1338-PLANTA CHICLAYO -Matricula:OB2092/12699199932"
TEXTO_TRUJILLO = "Ticket 12282-PLANTA TRUJILLO-Matricula:OB2104P/12699567071"
# PUCALLPA trae un espacio dentro de la matrícula (``OB 2180``).
TEXTO_PUCALLPA = "Ticket 517-PLANTA PUCALLPA-Matricula:OB 2180/12722986319"
# Nota de crédito real (mismo formato de ticket).
TEXTO_NOTA_CREDITO = "Ticket 13189-PLANTA PISCO-Matricula:OB2009/12714050648"


def _linea(texto: str, etiqueta: str, indice: int = 1) -> str:
    return (
        f"<cac:{etiqueta}><cbc:ID>{indice}</cbc:ID>"
        "<cac:BillingReference><cac:AdditionalDocumentReference>"
        f'<cbc:ID schemeID="txt"><![CDATA[{texto}]]></cbc:ID>'
        "</cac:AdditionalDocumentReference></cac:BillingReference>"
        f"</cac:{etiqueta}>"
    )


def _xml(
    textos: list[str],
    raiz: str = "Invoice",
    etiqueta_linea: str = "InvoiceLine",
    extra: str = "",
) -> str:
    """XML de ICARO mínimo: ``raiz`` con una línea por texto de ticket dado."""
    lineas = "".join(
        _linea(texto, etiqueta_linea, i) for i, texto in enumerate(textos, start=1)
    )
    return (
        '<?xml version="1.0" encoding="utf-8" standalone="yes"?>'
        f'<cac:{raiz} xmlns:cac="{_CAC}" xmlns:cbc="{_CBC}">{extra}{lineas}</cac:{raiz}>'
    )



def test_parse_ticket_chiclayo_con_espacio_antes_del_guion():
    ticket = parse_ticket(_xml([TEXTO_CHICLAYO]))

    assert ticket == {
        "nro_ticket": "1338",
        "texto_planta": "CHICLAYO",
        "texto_matricula": "OB2092",
        "matricula": "2092",
        "schema_info": TEXTO_CHICLAYO,
    }


def test_parse_ticket_trujillo_sin_espacio_y_matricula_con_letra():
    ticket = parse_ticket(_xml([TEXTO_TRUJILLO]))

    assert ticket["nro_ticket"] == "12282"
    assert ticket["texto_planta"] == "TRUJILLO"
    assert ticket["texto_matricula"] == "OB2104P"
    assert ticket["matricula"] == "2104"
    assert ticket["schema_info"] == TEXTO_TRUJILLO


def test_parse_ticket_matricula_con_espacio_lee_hasta_la_barra():
    # Caso real: ``Matricula:OB 2180`` → ``texto_matricula`` lee todo hasta la ``/``.
    ticket = parse_ticket(_xml([TEXTO_PUCALLPA]))

    assert ticket["texto_planta"] == "PUCALLPA"
    assert ticket["texto_matricula"] == "OB 2180"
    assert ticket["matricula"] == "2180"
    assert ticket["schema_info"] == TEXTO_PUCALLPA


def test_parse_ticket_admite_bom_al_inicio():
    # El XML de SUNAT viene con BOM (``\ufeff``) al decodificar el ZIP.
    xml = "\ufeff" + _xml([TEXTO_CHICLAYO])

    assert parse_ticket(xml)["matricula"] == "2092"


def test_parse_invoice_ticket_directo():
    assert parse_invoice_ticket(_xml([TEXTO_CHICLAYO]))["nro_ticket"] == "1338"


def test_parse_ticket_nota_de_credito():
    # El dispatcher detecta la raíz ``CreditNote`` y entra a ``cac:CreditNoteLine``.
    xml = _xml([TEXTO_NOTA_CREDITO], raiz="CreditNote", etiqueta_linea="CreditNoteLine")

    ticket = parse_ticket(xml)

    assert ticket["nro_ticket"] == "13189"
    assert ticket["texto_planta"] == "PISCO"
    assert ticket["texto_matricula"] == "OB2009"
    assert ticket["matricula"] == "2009"
    assert ticket["schema_info"] == TEXTO_NOTA_CREDITO


def test_parse_credit_note_ticket_directo():
    xml = _xml([TEXTO_NOTA_CREDITO], raiz="CreditNote", etiqueta_linea="CreditNoteLine")

    assert parse_credit_note_ticket(xml)["matricula"] == "2009"


def test_nota_de_credito_ignora_el_billing_reference_de_cabecera():
    # La nota de crédito trae otro ``cac:BillingReference`` en la cabecera
    # (``cac:InvoiceDocumentReference``): el ticket se busca dentro de la línea.
    cabecera = (
        "<cac:BillingReference><cac:InvoiceDocumentReference>"
        "<cbc:ID><![CDATA[F001-0027967]]></cbc:ID>"
        "</cac:InvoiceDocumentReference></cac:BillingReference>"
    )
    xml = _xml(
        [TEXTO_NOTA_CREDITO],
        raiz="CreditNote",
        etiqueta_linea="CreditNoteLine",
        extra=cabecera,
    )

    assert parse_ticket(xml)["nro_ticket"] == "13189"


def test_nota_de_credito_con_varias_lineas_lanza_error():
    xml = _xml(
        [TEXTO_NOTA_CREDITO, TEXTO_NOTA_CREDITO],
        raiz="CreditNote",
        etiqueta_linea="CreditNoteLine",
    )

    with pytest.raises(IcaroParseError, match="CreditNoteLine"):
        parse_ticket(xml)


def test_parse_ticket_raiz_no_soportada_lanza_error():
    xml = _xml([TEXTO_CHICLAYO], raiz="DebitNote", etiqueta_linea="DebitNoteLine")

    with pytest.raises(IcaroParseError, match="raíz"):
        parse_ticket(xml)


def test_parse_ticket_sin_invoice_line_lanza_error():
    with pytest.raises(IcaroParseError, match="InvoiceLine"):
        parse_ticket(_xml([]))


def test_parse_ticket_con_varias_invoice_line_lanza_error():
    with pytest.raises(IcaroParseError, match="InvoiceLine"):
        parse_ticket(_xml([TEXTO_CHICLAYO, TEXTO_TRUJILLO]))


def test_parse_ticket_sin_el_nodo_schemeID_txt_lanza_error():
    xml = _xml([TEXTO_CHICLAYO]).replace(' schemeID="txt"', "")

    with pytest.raises(IcaroParseError, match="schemeID"):
        parse_ticket(xml)


def test_parse_ticket_texto_fuera_de_formato_lanza_error():
    with pytest.raises(IcaroParseError, match="formato"):
        parse_ticket(_xml(["Ticket 1338 PLANTA CHICLAYO OB2092"]))


def test_parse_ticket_texto_matricula_sin_cuatro_digitos_lanza_error():
    with pytest.raises(IcaroParseError, match="dígitos"):
        parse_ticket(_xml(["Ticket 1-PLANTA PISCO-Matricula:OBX/123"]))


def test_parse_ticket_xml_ilegible_lanza_error():
    with pytest.raises(IcaroParseError, match="ilegible"):
        parse_ticket("no soy un xml")
