"""Tests del parser del PDF CORPAC de servicios (cabecera + detalle).

Se usan PDFs **reales** extraídos de ``from_email_corpac_files`` (fixtures en base64)
con sus valores esperados verificados contra el contenido de cada PDF:
- ``f025_29006``: 1 detalle, moneda ``S/``, VUELO SALIDA poblado.
- ``f056_3893``: 2 detalles, moneda ``US$``, LLEGADA/SALIDA alternados.
- ``f051_2816``: ruta pegada al km (``UT332/UT323123.32``) partida por posición.
- ``f024_711``: rutas con waypoints (``ATATU UV1`` / ``UV1 ATATU``).
- ``f030_65498``: multipágina (2 páginas, decenas de filas, ``1 de 2``).
- ``f001_150472``: una factura con **3 aeronaves** -> 3 cabeceras de sección.
"""

import base64
from decimal import Decimal
from pathlib import Path

import pytest

from assets.from_email_assets.corpac_assets.corpac_data_asset.parser import (
    CorpacDataParseError,
    _as_decimal,
    _column_name,
    _split_route_km,
    parse_invoice_pdf,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "corpac"


def _pdf(nombre):
    with open(_FIXTURES / f"{nombre}.pdf.b64", encoding="ascii") as f:
        return base64.b64decode(f.read())


# ---------------------------------------------------------------------------
# parse_invoice_pdf contra PDFs reales
# ---------------------------------------------------------------------------


def test_parse_f025_cabecera_y_un_detalle():
    out = parse_invoice_pdf(_pdf("f025_29006"))

    # Una sola sección (una aeronave) -> una cabecera.
    assert len(out["headers"]) == 1
    assert out["headers"][0] == {
        "factura": "F0250029006",
        "fecha_doc": "11/08/2026",
        "fch_impresion": "12/08/2026",
        "hora": "00:19:46",
        "pagina": "1 de 1",
        "cliente": "306390 AIR MAJORO SOCIEDAD ANONIMA",
        "matricula": "OB-2200",
        "tipo_aeronave": "CESSNA C-208",
        "pmd": "3.10",
    }

    assert len(out["details"]) == 1
    d = out["details"][0]
    assert d["_section"] == 0
    assert d["servicio"] == "SNAR NACIONAL SOLES"
    assert d["aeropuerto_origen"] == "SPCL"
    assert d["aeropuerto_destino"] == "SPAY"
    assert d["vuelo_llegada"] == ""
    assert d["vuelo_salida"] == "ESP01"
    assert d["ruta_aerea"] == "SPCL DCT SPAY"
    assert d["total_km"] == Decimal("274.72")
    assert d["fecha_llegada"] == "11/08/2026 15:12"
    assert d["fecha_salida"] == "11/08/2026 14:12"
    assert d["total_min"] == ""
    assert d["moneda"] == "S/"
    assert d["precio_unitario"] == Decimal("35.66")


def test_parse_f056_dos_detalles_en_usd_con_vuelos_alternados():
    out = parse_invoice_pdf(_pdf("f056_3893"))

    assert len(out["headers"]) == 1
    assert out["headers"][0]["factura"] == "F0560003893"
    assert out["headers"][0]["tipo_aeronave"] == "B-200"
    assert out["headers"][0]["pmd"] == "5.67"

    assert len(out["details"]) == 2
    aterrizaje, despegue = out["details"]
    assert aterrizaje["_section"] == despegue["_section"] == 0

    # Aterrizaje: solo VUELO LLEGADA.
    assert aterrizaje["servicio"] == "Aterrizaje Nacional"
    assert aterrizaje["vuelo_llegada"] == "FEB0005"
    assert aterrizaje["vuelo_salida"] == ""
    assert aterrizaje["ruta_aerea"] == "DCT MULAN AMVEX V18"
    assert aterrizaje["total_km"] == Decimal("300.04")
    assert aterrizaje["moneda"] == "US$"
    assert aterrizaje["precio_unitario"] == Decimal("1.62")

    # Despegue: solo VUELO SALIDA.
    assert despegue["servicio"] == "Despegue Nacional"
    assert despegue["vuelo_llegada"] == ""
    assert despegue["vuelo_salida"] == "FEB0006"
    assert despegue["ruta_aerea"] == "SPNC T327 SPIM"
    assert despegue["total_km"] == Decimal("315.41")
    assert despegue["fecha_llegada"] == "25/02/2026 17:39"
    assert despegue["fecha_salida"] == "25/02/2026 16:55"


def test_parse_f051_ruta_pegada_al_km():
    out = parse_invoice_pdf(_pdf("f051_2816"))

    assert len(out["details"]) == 2
    aprox, snar = out["details"]

    # Ruta "RUTA KM VARIABLE" (texto variable que llena la columna de ruta).
    assert aprox["servicio"] == "APROX. NACIONAL SOLES"
    assert aprox["vuelo_llegada"] == "VLO001"
    assert aprox["ruta_aerea"] == "RUTA KM VARIABLE"
    assert aprox["total_km"] == Decimal("344.59")

    # El token pegado "UT332/UT323123.32" se parte por posición de caracteres.
    assert snar["vuelo_salida"] == "VLO002"
    assert snar["ruta_aerea"] == "AYA DCT UDENI UT332/UT32"
    assert snar["total_km"] == Decimal("3123.32")


def test_parse_f024_rutas_con_waypoints():
    out = parse_invoice_pdf(_pdf("f024_711"))

    assert len(out["details"]) == 2
    aprox, snar = out["details"]

    assert aprox["vuelo_llegada"] == "PVN223"
    assert aprox["ruta_aerea"] == "ATATU UV1"
    assert aprox["total_km"] == Decimal("946.50")

    assert snar["vuelo_salida"] == "PVN224"
    assert snar["ruta_aerea"] == "UV1 ATATU"
    assert snar["total_km"] == Decimal("831.57")
def test_parse_f030_multipagina():
    out = parse_invoice_pdf(_pdf("f030_65498"))

    # Cabecera de la página 1 (se repite en la 2) + total de páginas.
    # La repetición de MATRICULA de la página 2 no abre una sección nueva.
    assert len(out["headers"]) == 1
    assert out["headers"][0]["factura"] == "F0300065498"
    assert out["headers"][0]["pagina"] == "1 de 2"
    assert out["headers"][0]["matricula"] == "OB-1919P"
    assert out["headers"][0]["tipo_aeronave"] == "CESSNA C-207"
    assert out["headers"][0]["pmd"] == "2.00"

    # Decenas de filas juntadas de las 2 páginas, todas en dólares.
    assert len(out["details"]) > 20
    assert all(d["moneda"] == "US$" for d in out["details"])
    assert all(d["aeropuerto_origen"] == "SPZA" for d in out["details"])
    # Las filas son pares Aterrizaje/Despegue con número de tramo en SALIDA.
    assert out["details"][0]["servicio"] == "Aterrizaje Nacional"
    assert out["details"][0]["vuelo_salida"] == "1"
    assert out["details"][1]["servicio"] == "Despegue Nacional"


def test_parse_f001_multiaeronave_tres_secciones():
    """Una factura puede tener varias aeronaves: una cabecera por sección."""
    out = parse_invoice_pdf(_pdf("f001_150472"))

    assert out["headers"][0]["factura"] == "F0010150472"

    # 3 aeronaves -> 3 cabeceras (misma factura, distinta matrícula).
    assert [h["matricula"] for h in out["headers"]] == [
        "OB-2092P",
        "OB-2209",
        "OB-2221P",
    ]
    assert [h["tipo_aeronave"] for h in out["headers"]] == [
        "B-200",
        "BEECHCRAFT 200",
        "BE-9L",
    ]
    assert [h["pmd"] for h in out["headers"]] == ["5.67", "5.68", "4.30"]

    # Todos los detalles de la misma factura, cada uno en su sección.
    assert len(out["details"]) == 11
    assert [d["_section"] for d in out["details"]] == [
        0, 0, 0, 0, 0, 0, 0,  # OB-2092P
        1,                     # OB-2209
        2, 2, 2,              # OB-2221P
    ]
    # Cada detalle conserva la fila de su sección (matrícula correcta).
    det_seccion1 = [d for d in out["details"] if d["_section"] == 1]
    assert det_seccion1[0]["aeropuerto_destino"] == "SPCL"
    assert det_seccion1[0]["ruta_aerea"] == "UT315"

    # Las líneas MATRICULA intercaladas no generan filas fantasma.
    assert all(not d["servicio"].startswith("MATRICULA") for d in out["details"])


def test_parse_pdf_invalido_lanza_corpac_parse_error():
    with pytest.raises(CorpacDataParseError):
        parse_invoice_pdf(b"%PDF-1.4 basura sin estructura")
    with pytest.raises(CorpacDataParseError):
        parse_invoice_pdf(b"no soy un pdf")


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


def test_column_name_clasifica_por_centro():
    # Servicio multi-palabra: todo con centro < 176.5.
    assert _column_name(21.2) == "servicio"
    assert _column_name(96.5) == "servicio"
    assert _column_name(100.0) == "servicio"
    # Origen/destino.
    assert _column_name(186.0) == "origen"
    assert _column_name(224.0) == "destino"
    # Vuelos.
    assert _column_name(266.0) == "vuelo_llegada"
    assert _column_name(315.0) == "vuelo_salida"
    # Ruta (incluso arrancando en x≈355.9, centro ~365).
    assert _column_name(365.0) == "ruta"
    assert _column_name(383.0) == "ruta"
    assert _column_name(410.0) == "ruta"
    # KM, fechas, min y precio.
    assert _column_name(466.0) == "km"
    assert _column_name(541.0) == "fecha_llegada"
    assert _column_name(639.0) == "fecha_salida"
    assert _column_name(700.0) == "min"
    assert _column_name(762.0) == "precio"


def test_split_route_km_fallback_regex():
    assert _split_route_km("1,039.70") is None  # km puro, sin ruta
    assert _split_route_km("DCT MULAN") is None  # sin número decimal
    # El regex es ambiguo en tokens pegados: no se usa como fuente principal.
    ruta, km = _split_route_km("UT332/UT323123.32")
    assert km == "323123.32"


def test_as_decimal():
    assert _as_decimal("1,039.70") == Decimal("1039.70")
    assert _as_decimal("35.66") == Decimal("35.66")
    assert _as_decimal("") is None
    assert _as_decimal("  ") is None
    assert _as_decimal("ABC") is None