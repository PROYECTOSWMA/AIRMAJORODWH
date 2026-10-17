"""Tests de las utilidades compartidas a nivel de assets (assets/utils.py)."""

from assets.utils import normalize_matricula, normalize_rows, to_db_field


def test_to_db_field_snake_case():
    assert to_db_field("CAR SUNAT") == "car_sunat"
    assert to_db_field("FECHAEMISIO") == "fechaemisio"
    assert to_db_field("ruc_cliente20") == "ruc_cliente20"
    assert to_db_field("DOREFSUBTOT") == "dorefsubtot"


def test_to_db_field_strips_accents():
    assert to_db_field("Razón Social") == "razon_social"


def test_normalize_matricula_corrige_los_tecleos():
    """La matrícula debe quedar SIEMPRE 'OB-1234': de ella sale el CC en dbt.

    ``extract_cost_center`` toma los 4 caracteres siguientes al primer dígito, así que
    un valor que empieza por dígito ('0B-2180') producía el CC basura '0B-2'.
    """
    assert normalize_matricula("0B-2180") == "OB-2180"
    assert normalize_matricula("0b2200") == "OB-2200"
    assert normalize_matricula("ob.2209") == "OB-2209"
    assert normalize_matricula("OB2221") == "OB-2221"
    assert normalize_matricula("  OB-2104 ") == "OB-2104"
    assert normalize_matricula("OB 1919") == "OB-1919"


def test_normalize_matricula_vacia_los_numeros_de_documento():
    """Si la celda trae un nº de documento (no una aeronave) no se inventa CC."""
    assert normalize_matricula("003-4560") is None
    assert normalize_matricula("007-1731") is None


def test_normalize_matricula_deja_lo_que_no_es_matricula():
    """Valores que no son matrículas se dejan igual (y los no-texto, intactos)."""
    assert normalize_matricula("SAETA") == "SAETA"
    assert normalize_matricula("OIB-2200") == "OIB-2200"
    assert normalize_matricula(None) is None
    assert normalize_matricula(15012026) == 15012026


def test_normalize_rows_maps_columns_to_snake_case():
    columns = ["NUMEROFILA", "RAZONSOCIAL", "DOREFTOTNUM", "FECHAVUELO"]
    rows = [
        [1, "PENSION 65", 30.0, None],
        [2, "  CONSORCIO CG  ", "60.00", ""],
    ]
    assert normalize_rows(columns, rows) == [
        {
            "numerofila": 1,
            "razonsocial": "PENSION 65",
            "doreftotnum": 30.0,
            "fechavuelo": None,
        },
        {
            "numerofila": 2,
            "razonsocial": "CONSORCIO CG",
            "doreftotnum": "60.00",
            "fechavuelo": None,
        },
    ]


def test_normalize_rows_empty_values_become_none():
    assert normalize_rows(["A", "B"], [["1", ""], ["", None], [], ["3", "x"]]) == [
        {"a": "1", "b": None},
        {"a": None, "b": None},
        {"a": "3", "b": "x"},
    ]


def test_normalize_rows_sin_filas():
    assert normalize_rows(["A", "B"], []) == []
