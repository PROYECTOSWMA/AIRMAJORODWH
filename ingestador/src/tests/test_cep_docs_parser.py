"""Tests del parser del PDF de CEP (``parse_invoice_pdf``).

Se construyen PDFs sintéticos (fixture ``make_pdf``) que reproducen la cabecera y la
tabla de las facturas de combustible de ``fe.corporacion.energetico@gmail.com``,
incluida la variante de **nota de crédito** (sin PLACA y con 3 importes). El texto va
sin acentos a propósito: la fixture compone el PDF en latin-1/Helvetica.
"""

from decimal import Decimal

import pytest

from assets.from_email_assets.cep_docs_asset.parser import (
    CepDocsParseError,
    parse_invoice_pdf,
)

FACTURA_LINES = [
    "AV. REDUCTO NRO. 861 R.U.C. 20613566881",
    "LIMA - LIMA - MIRAFLORES FACTURA ELECTRONICA",
    "Web : http://fe.energetico.sistemfac.com/ F002-009674",
    "SENOR (ES) : AIR MAJORO S.A. FECHA DE EMISION : 31/12/2025",
    "DIRECCION : AV ARGENTINA NRO 4065 ZI CALLAO R.U.C. : 20494626978",
    "COD DEL CLIENTE N DE GUIA COD VENDEDOR COND. PAGO MONEDA O/C",
    "NZA/SPZA 2 115984 OFI Contado DOLARES 2009689",
    "CODIGO CANT. DESCRIPCION U.M. VALOR UNIT. PRECIO UNIT. VALOR VENTA",
    "AV 20.00 AV GAS 100LL GLL 11.2200 13.2396 224.40",
    "TRANSPORTISTA : AIR MAJORO S.A. CHOFER :PILMER D. CESPEDES LOZANO",
    "SON :DOSCIENTOS SESENTA Y CUATRO Y 79/100 DOLARES AMERICANOS",
    "PLACA OP GRAVADAS OP EXONERADAS IGV (18%) IMPORTE TOTAL",
    "OB-1919 $ 224.40 $ 0.00 $ 40.39 $ 264.79",
    "CODIGO SCOP : 12634330075",
]

NOTA_LINES = [
    "LIMA - LIMA - MIRAFLORES NOTA DE CREDITO ELECTRONICA",
    "Web : http://fe.energetico.sistemfac.com/ F001-000027",
    "SENOR (ES) : AIR MAJORO S.A FECHA DE EMISION : 7/05/2026",
    "DIRECCION : AV. AEROPUERTO C-11 LOS CEDROS DE CORPAC, UCAYALI R.U.C. : 20494626978",
    "COD DEL CLIENTE DOC REFERENCIA COD VENDEDOR COND. PAGO MONEDA O/C",
    "PCL/SPCL 2 F001-005735 OFI DOLARES",
    "CODIGO CANT. DESCRIPCION U.M. VALOR UNIT. PRECIO UNIT. VALOR VENTA",
    "AV 26.00 AV GAS 100LL GLL 11.6600 13.7588 303.16",
    "SON :TRESCIENTOS CINCUENTA Y SIETE Y 73/100 DOLARES AMERICANOS",
    "SUBTOTAL IGV (18%) IMPORTE TOTAL",
    "$ 303.16 $ 54.57 $ 357.73",
]


def test_parse_invoice_pdf_factura(make_pdf):
    parsed = parse_invoice_pdf(make_pdf(FACTURA_LINES))
    header = parsed["header"]

    assert header["factura"] == "F002-009674"
    assert header["tipo_documento"] == "FACTURA"
    assert header["fecha_emision"] == "31/12/2025"
    assert header["cliente"] == "AIR MAJORO S.A."
    assert header["ruc_cliente"] == "20494626978"
    assert header["cod_del_cliente"] == "NZA/SPZA"
    assert header["n_de_guia"] == "2"
    assert header["cod_vendedor"] == "115984"
    assert header["cond_pago"] == "Contado"
    assert header["moneda"] == "DOLARES"
    assert header["o_c"] == "2009689"
    assert header["transportista"] == "AIR MAJORO S.A."
    assert header["chofer"] == "PILMER D. CESPEDES LOZANO"
    assert header["son"] == "DOSCIENTOS SESENTA Y CUATRO Y 79/100 DOLARES AMERICANOS"
    assert header["placa"] == "OB-1919"
    assert header["op_gravadas"] == Decimal("224.40")
    assert header["op_exoneradas"] == Decimal("0.00")
    assert header["igv"] == Decimal("40.39")
    assert header["importe_total"] == Decimal("264.79")
    assert header["codigo_scop"] == "12634330075"

    assert parsed["details"] == [
        {
            "codigo": "AV",
            "cant": Decimal("20.00"),
            "descripcion": "AV GAS 100LL",
            "u_m": "GLL",
            "valor_unit": Decimal("11.2200"),
            "precio_unit": Decimal("13.2396"),
            "valor_venta": Decimal("224.40"),
        }
    ]


def test_parse_invoice_pdf_nota_de_credito(make_pdf):
    parsed = parse_invoice_pdf(make_pdf(NOTA_LINES))
    header = parsed["header"]

    assert header["factura"] == "F001-000027"
    assert header["tipo_documento"] == "NOTA DE CREDITO"
    # La nota de crédito no trae PLACA ni O/C; el 3er valor es el doc referenciado.
    assert header["cod_del_cliente"] == "PCL/SPCL"
    assert header["n_de_guia"] == "2"
    assert header["cod_vendedor"] == ""
    assert header["moneda"] == "DOLARES"
    assert header["o_c"] == ""
    assert header["placa"] == ""
    # 3 importes: gravadas + IGV + total (exoneradas no aplica -> None).
    assert header["op_gravadas"] == Decimal("303.16")
    assert header["op_exoneradas"] is None
    assert header["igv"] == Decimal("54.57")
    assert header["importe_total"] == Decimal("357.73")

    assert parsed["details"][0]["valor_venta"] == Decimal("303.16")


def test_parse_invoice_pdf_sin_cabecera_lanza_error(make_pdf):
    with pytest.raises(CepDocsParseError, match="factura"):
        parse_invoice_pdf(make_pdf(["texto sin nada reconocible"]))


def test_parse_invoice_pdf_no_es_pdf_lanza_error():
    with pytest.raises(CepDocsParseError, match="PDF"):
        parse_invoice_pdf(b"%PDF-1.4 roto")
