"""Tests del parser genérico de los CSV estáticos (``parse_csv``).

Los CSV de ``static/`` (maestros ``dwh_static_*`` y auxiliares
``static_aux_*``) son tablas de referencia: cabecera en la primera fila y todo TEXTO.
Se prueban los casos reales del repo: cabeceras ya snake_case y con acentos, celdas
vacías, valores con espacios, BOM de Excel y campos entrecomillados con comas y
saltos de línea (el ``comentario`` del maestro de cuentas).
"""
from assets.static_data_asset.parsers.csv_static import parse_csv


def _escribir(tmp_path, texto: str, nombre: str = "tabla.csv"):
    path = tmp_path / nombre
    path.write_text(texto, encoding="utf-8")
    return path


def test_parse_csv_devuelve_dicts_con_las_cabeceras_normalizadas(tmp_path):
    path = _escribir(
        tmp_path,
        "Registration,Owner,Business Unit\n"
        "1919,RIBBAN HOLDING S.A.,SERVICIO_TURISTICO\n"
        "2180,AIR PRIME EIRL,SERV_PASAJEROS_CARGA\n",
    )
    assert parse_csv(path) == [
        {
            "registration": "1919",
            "owner": "RIBBAN HOLDING S.A.",
            "business_unit": "SERVICIO_TURISTICO",
        },
        {
            "registration": "2180",
            "owner": "AIR PRIME EIRL",
            "business_unit": "SERV_PASAJEROS_CARGA",
        },
    ]


def test_parse_csv_normaliza_acentos_y_mayusculas_de_la_cabecera(tmp_path):
    path = _escribir(tmp_path, "CODE,Denominación,Departamento\n1,Aeródromo,LORETO\n")
    assert parse_csv(path) == [
        {"code": "1", "denominacion": "Aeródromo", "departamento": "LORETO"}
    ]


def test_parse_csv_limpia_espacios_y_celdas_vacias_a_none(tmp_path):
    path = _escribir(tmp_path, "icao,iata,departamento\nSPHO , AY , \n")
    assert parse_csv(path) == [{"icao": "SPHO", "iata": "AY", "departamento": None}]


def test_parse_csv_soporta_comas_y_saltos_de_linea_entrecomillados(tmp_path):
    """El ``comentario`` del maestro de cuentas trae saltos de línea y comas."""
    path = _escribir(
        tmp_path,
        'codigo_pcge,comentario\n639913,"linea1\nlinea2, con coma"\n704101,\n',
    )
    assert parse_csv(path) == [
        {"codigo_pcge": "639913", "comentario": "linea1\nlinea2, con coma"},
        {"codigo_pcge": "704101", "comentario": None},
    ]


def test_parse_csv_ignora_el_bom_de_excel(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_text("\ufeffpartner_doc,account\n20259880603,639101\n", encoding="utf-8")
    # Ojo: ``dict`` del CSV conserva el orden del archivo.
    assert parse_csv(path) == [{"partner_doc": "20259880603", "account": "639101"}]


def test_parse_csv_ignora_columnas_sin_nombre(tmp_path):
    path = _escribir(tmp_path, "icao,,departamento\na,,b\n")
    assert parse_csv(path) == [{"icao": "a", "departamento": "b"}]
