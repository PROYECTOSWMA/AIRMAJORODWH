"""Tests del parser del Excel de reportes Talma.

Se construye un ``.xlsx`` en memoria (con openpyxl) que reproduce el layout real:
la cabecera está en la fila 4 (A4:Y4, con la columna U en blanco) y los datos van
hacia abajo hasta que la columna D (``RSIR``) queda en blanco. También se prueba
el parseo de los ``.xls`` de texto delimitado (TSV).
"""

import datetime
import io

import pytest
from openpyxl import Workbook

from assets.from_email_assets.talma_reports_asset.parser import (
    TalmaParseError,
    _normalize_header,
    parse_report_data,
)

_HEADERS = [
    "Fecha",
    "Estación",
    "Aerolínea",
    "RSIR",
    "Aeronave",
    "Matrícula",
    "Vuelo L",
    "Vuelo S",
    "Hora L",
    "Hora S",
    "Diferencia",
    "PEA Origen",
    "PEA Destino",
    "Cantidad",
    "Equipo",
    "Peso (KG)",
    "Servicio",
    "Tarifa",
    "Moneda",
    "Estado",
    "",  # columna U en blanco
    "Tipo RSIR",
]

_ROW1 = [
    datetime.datetime(2025, 12, 1),   # Fecha
    "CHICLAYO",
    "AIR MAJORO SA",
    "0000048910",
    "BEECHCRAFT B-200",
    "OB-2092P",
    2092,
    2092,
    datetime.time(22, 8),
    datetime.time(0, 3),
    "",
    "--",
    "--",
    1,
    1,
    "",
    "PAQUETE",
    70,
    "DOL",
    "Activo",
    "",
    "",
]

_ROW2 = [
    datetime.datetime(2025, 12, 2),
    "CUSCO",
    "AIR MAJORO SA",
    "0000180091",
    "BEECHCRAFT B-200",
    "OB-2209P",
    2209,
    2209,
    datetime.time(10, 33),
    datetime.time(11, 50),
    "",
    "--",
    "--",
    1,
    1,
    "",
    "PAQUETE",
    70,
    "DOL",
    "Activo",
    "",
    "",
]

_EXPECTED_1 = {
    "fecha": "01/12/2025",
    "estacion": "CHICLAYO",
    "aerolinea": "AIR MAJORO SA",
    "rsir": "0000048910",
    "aeronave": "BEECHCRAFT B-200",
    "matricula": "OB-2092P",
    "vuelo_l": "2092",
    "vuelo_s": "2092",
    "hora_l": "22:08",
    "hora_s": "00:03",
    "diferencia": "",
    "pea_origen": "--",
    "pea_destino": "--",
    "cantidad": "1",
    "equipo": "1",
    "peso_kg": "",
    "servicio": "PAQUETE",
    "tarifa": "70",
    "moneda": "DOL",
    "estado": "Activo",
    "tipo_rsir": "",
}

_EXPECTED_2 = dict(_EXPECTED_1)
_EXPECTED_2.update(
    {
        "fecha": "02/12/2025",
        "estacion": "CUSCO",
        "rsir": "0000180091",
        "matricula": "OB-2209P",
        "vuelo_l": "2209",
        "vuelo_s": "2209",
        "hora_l": "10:33",
        "hora_s": "11:50",
    }
)


def _build_xlsx(data_rows, title_before=3):
    """Construye un ``.xlsx`` en memoria con la cabecera en la fila 4."""
    wb = Workbook()
    ws = wb.active
    for r in range(1, title_before + 1):
        ws.cell(row=r, column=1, value=f"TITULO {r}")
    for c, h in enumerate(_HEADERS, start=1):
        ws.cell(row=4, column=c, value=h)
    for i, row in enumerate(data_rows, start=5):
        for c, v in enumerate(row, start=1):
            ws.cell(row=i, column=c, value=v)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_normalize_header():
    assert _normalize_header("PEA Origen") == "PEAORIGEN"
    assert _normalize_header("Peso (KG)") == "PESOKG"
    assert _normalize_header("Estación") == "ESTACION"
    assert _normalize_header("Tipo RSIR") == "TIPORSIR"


def test_parse_xlsx_dos_registros_y_preserva_ceros_rsir():
    # Fila 7 con RSIR en blanco -> fin de la tabla; la fila 8 se ignora.
    data = [
        _ROW1,
        _ROW2,
        [None] * len(_HEADERS),  # RSIR en blanco marca el final
        ["deberia", "ignorarse", None, "999", None, None, None, None, None, None,
         None, None, None, None, None, None, None, None, None, None, None, None],
    ]
    out = parse_report_data(_build_xlsx(data))
    assert len(out) == 2
    assert out[0] == _EXPECTED_1
    assert out[1] == _EXPECTED_2
    # La columna RSIR conserva los ceros a la izquierda (no es un int).
    assert out[0]["rsir"] == "0000048910"


def test_parse_xlsx_cabecera_con_filas_de_titulo_arriba():
    out = parse_report_data(_build_xlsx([_ROW1], title_before=5))
    assert len(out) == 1
    assert out[0]["fecha"] == "01/12/2025"


def test_parse_xlsx_sin_cabecera_lanza_error():
    wb = Workbook()
    ws = wb.active
    ws.cell(row=1, column=1, value="sin cabecera")
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(TalmaParseError):
        parse_report_data(buf.getvalue())


def test_parse_delimited_text_tsv():
    headers = "\t".join(_HEADERS)
    line1 = (
        "01/12/2025\tCHICLAYO\tAIR MAJORO SA\t0000048910\tBEECHCRAFT B-200\t"
        "OB-2092P\t2092\t2092\t22:08\t00:03\t\t--\t--\t1\t1\t\tPAQUETE\t70\t"
        "DOL\tActivo\t\t"
    )
    line2 = (
        "02/12/2025\tCUSCO\tAIR MAJORO SA\t0000180091\tBEECHCRAFT B-200\t"
        "OB-2209P\t2209\t2209\t10:33\t11:50\t\t--\t--\t1\t1\t\tPAQUETE\t70\t"
        "DOL\tActivo\t\t"
    )
    blank = "\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t\t"  # RSIR vacío -> fin
    data = f"TITULO\n{headers}\n{line1}\n{line2}\n{blank}\nignorada\n".encode("utf-8")
    out = parse_report_data(data)
    assert len(out) == 2
    assert out[0] == _EXPECTED_1
    assert out[1] == _EXPECTED_2


def test_parse_texto_sin_cabecera_lanza_error():
    with pytest.raises(TalmaParseError):
        parse_report_data(b"algo\nsin\ncabecera\n")
