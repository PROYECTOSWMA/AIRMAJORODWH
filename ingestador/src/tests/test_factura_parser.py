"""Tests del parseo de facturas de ambulancia (hoja "VUELOS B200 2026").

``parse_factura`` convierte el campo crudo ``factura`` (que trae 1 o 2 documentos
escritos de formas muy irregulares) en ``(primera, otras)``; ``parse_factura_list``
devuelve la lista completa de facturas y ``parse_factura_fields`` la columna que se
guarda en ``ambulancia_ventas_reports`` (``agregado_factura``, array JSON).
"""
from assets.static_data_asset.parsers.ambulance_sales.doc_parser import (
    parse_factura,
    parse_factura_fields,
    parse_factura_list,
    split_documento,
)


def test_un_solo_documento():
    assert parse_factura("F001-4791") == ("F001-4791", None)


def test_dos_documentos_separados_por_espacios():
    assert parse_factura("F001-4791    F001-4792") == ("F001-4791", "F001-4792")


def test_dos_documentos_separados_por_y():
    assert parse_factura("F001-4884 y F001-4885") == ("F001-4884", "F001-4885")


def test_separador_guion_espacio():
    assert parse_factura("F001-4941- F001-4983") == ("F001-4941", "F001-4983")


def test_serie_compartida():
    assert parse_factura("F001-5102-5103") == ("F001-5102", "F001-5103")


def test_serie_y_numero_partidos_por_espacio():
    assert parse_factura("F001 4880 Y F001-4881") == ("F001-4880", "F001-4881")


def test_serie_numero_concatenados_sin_guion():
    assert parse_factura("F0014897") == ("F001-4897", None)


def test_blanco_o_none_no_tiene_factura():
    assert parse_factura(None) == ("", None)
    assert parse_factura("") == ("", None)
    assert parse_factura("   ") == ("", None)


def test_split_documento():
    assert split_documento("F001-4791") == ("F001", 4791)
    assert split_documento("B001-97") == ("B001", 97)
    # Sin guion (o vacio) no hay serie ni numero.
    assert split_documento("F001") == (None, None)
    assert split_documento("") == (None, None)
    assert split_documento(None) == (None, None)


def test_parse_factura_list_un_solo_documento():
    assert parse_factura_list("F001-4791") == ["F001-4791"]


def test_parse_factura_list_dos_documentos():
    assert parse_factura_list("F001-4791    F001-4792") == ["F001-4791", "F001-4792"]


def test_parse_factura_list_separadores_y_minusculas():
    assert parse_factura_list("F001-4884 y f001-4885") == ["F001-4884", "F001-4885"]
    assert parse_factura_list("F001-4941- F001-4983") == ["F001-4941", "F001-4983"]


def test_parse_factura_list_serie_compartida():
    assert parse_factura_list("F001-5102-5103") == ["F001-5102", "F001-5103"]


def test_parse_factura_list_serie_y_numero_partidos_por_espacio():
    assert parse_factura_list("F001 4880 Y F001-4881") == ["F001-4880", "F001-4881"]


def test_parse_factura_list_serie_numero_concatenados_sin_guion():
    assert parse_factura_list("F0014897") == ["F001-4897"]


def test_parse_factura_list_sin_factura_es_lista_vacia():
    assert parse_factura_list(None) == []
    assert parse_factura_list("") == []
    assert parse_factura_list("   ") == []


def test_parse_factura_fields_una_factura():
    assert parse_factura_fields("F001-4684") == {"agregado_factura": ["F001-4684"]}


def test_parse_factura_fields_dos_facturas():
    assert parse_factura_fields("F001-4791    F001-4792") == {
        "agregado_factura": ["F001-4791", "F001-4792"]
    }


def test_parse_factura_fields_sin_factura():
    assert parse_factura_fields("") == {"agregado_factura": []}
