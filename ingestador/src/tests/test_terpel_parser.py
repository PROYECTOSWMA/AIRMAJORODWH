"""Tests del parser del PDF del ticket Terpel (labels reales del PDF).

El parser es table-driven sobre texto plano: se testean textos sintéticos que
reproducen el layout real (una columna, dos columnas duplicadas, cabeceras de
sección repetidas, ``Final:``/``Inicial:`` con hora + lectura) y los PDFs
reales de ``src/tests/fixtures/terpel``.
"""

import base64
from pathlib import Path

import pytest

from assets.from_email_assets.terpel_assets._common.tickets_parser import (
    TerpelParseError,
    parse_ticket_pdf,
    parse_ticket_text,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "terpel"


def _pdf(nombre):
    with open(_FIXTURES / f"{nombre}.pdf.b64", encoding="ascii") as f:
        return base64.b64decode(f.read())


# Texto de un tiquete real de una columna (labels sin acento, como en el PDF).
_TICKET = (
    "O.Entrega 2600103904\n"
    "________________________________________________________\n"
    "Estacion: LIM Fecha: 01/01/2026 18:22\n"
    "Equipo: RF05 - Refueller\n"
    "Operacion: SUMINISTRO Producto: JET A-1\n"
    "P.Abastecimiento: 14\n"
    "Operador: 76535989-CHAPONAN SIESQUEN ALEX YAMPIERS\n"
    "--------------------------------------------------------\n"
    "CLIENTE:\n"
    "Cliente: - AIR MAJORO S.A.C\n"
    "Comercializador: TER/TERPEL COMERCIAL\n"
    "Forma de Pago: CREDITO\n"
    "No. Vuelo: 2221 Destino: PCL\n"
    "Matricula: OB2221P Aeronave: B 200\n"
    "--------------------------------------------------------\n"
    "SERVICIO: HORA LECTURA\n"
    "Llegada: 18:14\n"
    "Conexion: 18:22\n"
    "Final: 18:36 61,188,092\n"
    "Inicial: 18:22 61,187,938\n"
    "GALONES: 154\n"
    "Temp. (F): 80.3\n"
    "FLOW RATE (GPM): 26\n"
    "--------------------------------------------------------\n"
    "CARACTERISTICAS:\n"
    "API Corregido (60 F): 43,1\n"
    "Densidad (Kg/Gal): 3,033\n"
    "Presion Dif. Observada: 22,901\n"
    "PRUEBAS DE CALIDAD:\n"
    "Claro/Brillante: Cumple\n"
    "Prueba deteccion de Agua Shell Water(R): Cumple\n"
    "--------------------------------------------------------\n"
    "Firma Operador____________________________________\n"
    "Firma Cliente ____________________________________\n"
    "----------- CLIENTE ----------\n"
)

_EXPECTED = {
    "o_entrega": "2600103904",
    "estacion": "LIM",
    "fecha": "01/01/2026 18:22",
    "equipo": "RF05 - Refueller",
    "operacion": "SUMINISTRO",
    "producto": "JET A-1",
    "p_abastecimiento": "14",
    "operador": "76535989-CHAPONAN SIESQUEN ALEX YAMPIERS",
    "cliente": "AIR MAJORO S.A.C",
    "comercializador": "TER/TERPEL COMERCIAL",
    "forma_pago": "CREDITO",
    "nro_vuelo": "2221",
    "destino": "PCL",
    "matricula": "OB2221P",
    "aeronave": "B 200",
    "hora_llegada": "18:14",
    "hora_conexion": "18:22",
    "galones": "154",
    "temperatura": "80.3",
    "flow_rate": "26",
    "api_corregido": "43,1",
    "densidad": "3,033",
    "presion_dif": "22,901",
    "prueba_apariencia": "Cumple",
    "prueba_agua": "Cumple",
    "hora_final": "18:36",
    "lectura_final": "61,188,092",
    "hora_inicial": "18:22",
    "lectura_inicial": "61,187,938",
}


def test_parse_ticket_text_campos_completos():
    assert parse_ticket_text(_TICKET) == _EXPECTED


# Layout de 2 columnas duplicadas (los PDFs de Suministro imprimen el tiquete
# dos veces por página): los labels de la 2ª columna acotan los valores.
_TICKET_2COL = (
    "O.Entrega 2536503903 O.Entrega 2536503903\n"
    "Estacion: LIM Fecha: 31/12/2025 06:08 Estacion: LIM Fecha: 31/12/2025 06:08\n"
    "Equipo: RF05 - Refueller Equipo: RF05 - Refueller\n"
    "Operacion: SUMINISTRO Producto: JET A-1 Operacion: SUMINISTRO Producto: JET A-1\n"
    "P.Abastecimiento: 14 P.Abastecimiento: 14\n"
    "Operador: 43854652-MAURICIO NEYRA LUIS EDUARDO Operador: 43854652-MAURICIO NEYRA LUIS EDUARDO\n"
    "CLIENTE: CLIENTE:\n"
    "Aerolinea: - AIR MAJORO S.A.C Aerolinea: - AIR MAJORO S.A.C\n"
    "Comercializador: TER/TERPEL COMERCIAL Comercializador: TER/TERPEL COMERCIAL\n"
    "Forma de Pago: CREDITO Forma de Pago: CREDITO\n"
    "No. Vuelo: 2092 Destino: CIX No. Vuelo: 2092 Destino: CIX\n"
    "Matricula: OB2092P Aeronave: B 200 Matricula: OB2092P Aeronave: B 200\n"
    "Llegada: 06:08 Llegada: 06:08\n"
    "Conexion: 06:12 Conexion: 06:12\n"
    "Final: 06:18 61,178,821.00 Final: 06:18 61,178,821.00\n"
    "Inicial: 06:13 61,178,761.00 Inicial: 06:13 61,178,761.00\n"
    "GALONES: 60.00 GALONES: 60.00\n"
    "Temp. (F): 75.3 Temp. (F): 75.3\n"
    "FLOW RATE (GPM): 65,81 FLOW RATE (GPM): 65,81\n"
    "CARACTERISTICAS: CARACTERISTICAS:\n"
    "API Corregido (60 F): 42,5 API Corregido (60 F): 42,5\n"
    "Densidad (Kg/Gal): 3,051 Densidad (Kg/Gal): 3,051\n"
    "Presion Dif. Observada: 9,117 Presion Dif. Observada: 9,117\n"
    "PRUEBAS DE CALIDAD: PRUEBAS DE CALIDAD:\n"
    "Claro/Brillante: Cumple Claro/Brillante: Cumple\n"
)


def test_parse_ticket_text_dos_columnas_duplicadas():
    out = parse_ticket_text(_TICKET_2COL)
    assert out["o_entrega"] == "2536503903"
    assert out["estacion"] == "LIM"
    assert out["fecha"] == "31/12/2025 06:08"
    assert out["cliente"] == "AIR MAJORO S.A.C"  # via Aerolinea
    assert out["nro_vuelo"] == "2092"
    assert out["destino"] == "CIX"
    assert out["matricula"] == "OB2092P"
    assert out["galones"] == "60.00"
    assert out["hora_final"] == "06:18"
    assert out["lectura_final"] == "61,178,821.00"
    assert out["hora_inicial"] == "06:13"
    assert out["lectura_inicial"] == "61,178,761.00"
    assert out["api_corregido"] == "42,5"
    assert out["prueba_apariencia"] == "Cumple"


def test_parse_ticket_text_variantes_de_label():
    # Con acentos y sin espacio tras el punto.
    texto = (
        "O.Entrega 1\n"
        "Estación: LIM\n"
        "Matrícula: ABC-123\n"
    )
    out = parse_ticket_text(texto)
    assert out["o_entrega"] == "1"
    assert out["estacion"] == "LIM"
    assert out["matricula"] == "ABC-123"


def test_parse_ticket_text_etiqueta_sola_y_valor_en_siguiente_linea():
    texto = (
        "O.Entrega\n"
        "2600103904\n"
        "Estacion\n"
        "LIM\n"
        "Matricula\n"
        "ABC-123\n"
    )
    out = parse_ticket_text(texto)
    assert out["o_entrega"] == "2600103904"
    assert out["estacion"] == "LIM"
    assert out["matricula"] == "ABC-123"


def test_parse_ticket_text_cabecera_cliente_sin_valor_se_salta():
    # La cabecera "CLIENTE:" sola no da valor; se toma el campo "Cliente:".
    texto = (
        "O.Entrega 1\n"
        "Estacion: LIM\n"
        "Matricula: ABC-123\n"
        "CLIENTE:\n"
        "Cliente: - AIR MAJORO S.A.C\n"
    )
    out = parse_ticket_text(texto)
    assert out["cliente"] == "AIR MAJORO S.A.C"


def test_parse_ticket_text_sin_seccion_de_caracteristicas():
    # Los PDFs de CREACIÓN de Suministro no imprimen las características.
    texto = (
        "O.Entrega 9849\n"
        "Estacion: LIM Fecha: 2026-01-01 13:36:00\n"
        "Matricula: OB2092P\n"
        "CARACTERISTICAS:\n"
        "PRUEBAS DE CALIDAD:\n"
    )
    out = parse_ticket_text(texto)
    assert out["o_entrega"] == "9849"
    assert out["fecha"] == "2026-01-01 13:36:00"
    assert out["api_corregido"] == ""
    assert out["prueba_apariencia"] == ""
    assert out["prueba_agua"] == ""


def test_parse_ticket_text_campo_requerido_faltante():
    texto = "O.Entrega 1\nEstacion: LIM\n"  # sin Matricula
    with pytest.raises(TerpelParseError, match="matricula"):
        parse_ticket_text(texto)


def test_parse_ticket_text_requerido_sin_valor():
    texto = (
        "O.Entrega\n"
        "Estacion: LIM\n"
        "Matricula: ABC-123\n"
    )
    with pytest.raises(TerpelParseError, match="o_entrega"):
        parse_ticket_text(texto)


def test_parse_ticket_pdf_tiquete_real():
    out = parse_ticket_pdf(_pdf("tiquete_2600104503"))
    assert out == {
        "o_entrega": "2600104503",
        "estacion": "LIM",
        "fecha": "01/01/2026 10:56",
        "equipo": "RF11 - Refueller",
        "operacion": "SUMINISTRO",
        "producto": "JET A-1",
        "p_abastecimiento": "13",
        "operador": "43675718-BAZALAR NINAMEZA LUIS ALFREDO",
        "cliente": "AIR MAJORO S.A.C",
        "comercializador": "TER/TERPEL COMERCIAL",
        "forma_pago": "CREDITO",
        "nro_vuelo": "2221",
        "destino": "AYP",
        "matricula": "OB2221P",
        "aeronave": "B 200",
        "hora_llegada": "10:55",
        "hora_conexion": "10:55",
        "galones": "166",
        "temperatura": "80.2",
        "flow_rate": "34",
        "api_corregido": "43,0",
        "densidad": "3,035",
        "presion_dif": "17,417",
        "prueba_apariencia": "Cumple",
        "prueba_agua": "Cumple",
        "hora_final": "11:04",
        "lectura_final": "29,783,940",
        "hora_inicial": "10:56",
        "lectura_inicial": "29,783,774",
    }


def test_parse_ticket_pdf_fecha_con_yyyy_literal():
    # El PDF fuente imprime "01/01/YYYY": se conserva tal cual.
    out = parse_ticket_pdf(_pdf("tiquete_2600103904"))
    assert out["o_entrega"] == "2600103904"
    assert out["fecha"] == "01/01/YYYY 18:22"
    assert out["galones"] == "154"
    assert out["prueba_agua"] == "Cumple"


def test_parse_ticket_pdf_suministro_mod_dos_columnas():
    out = parse_ticket_pdf(_pdf("suministro_mod_2536503903"))
    assert out["o_entrega"] == "2536503903"
    assert out["estacion"] == "LIM"
    assert out["fecha"] == "31/12/2025 06:08"
    assert out["cliente"] == "AIR MAJORO S.A.C"  # via Aerolinea
    assert out["nro_vuelo"] == "2092"
    assert out["destino"] == "CIX"
    assert out["matricula"] == "OB2092P"
    assert out["galones"] == "60.00"
    assert out["hora_final"] == "06:18"
    assert out["lectura_final"] == "61,178,821.00"
    assert out["hora_inicial"] == "06:13"
    assert out["lectura_inicial"] == "61,178,761.00"
    assert out["api_corregido"] == "42,5"
    assert out["prueba_apariencia"] == "Cumple"
    # Artefacto de la extracción del layout de 2 columnas: la prueba de agua
    # queda cortada ("Cumple" + fragmento "hell" de la columna derecha).
    assert out["prueba_agua"] == "Cumplehell"


def test_parse_ticket_pdf_creacion_sin_caracteristicas():
    out = parse_ticket_pdf(_pdf("suministro_creacion"))
    assert out["o_entrega"] == "9849"
    assert out["estacion"] == "LIM"
    assert out["fecha"] == "2026-01-01 13:36:00"
    assert out["matricula"] == "OB2092P"
    assert out["galones"] == "291.00"
    assert out["api_corregido"] == ""
    assert out["prueba_apariencia"] == ""


def test_parse_ticket_pdf_invalido_lanza_parse_error():
    with pytest.raises(TerpelParseError):
        parse_ticket_pdf(b"%PDF-1.4 basura sin estructura")
    with pytest.raises(TerpelParseError):
        parse_ticket_pdf(b"no soy un pdf")
