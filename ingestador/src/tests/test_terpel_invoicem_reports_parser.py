"""Tests del parser del Excel ``Reporte abastecimiento`` (remitente invoicem).

El parser localiza la fila de cabecera (``TICKET``/``GALONES``) y emite una fila por
vuelo con las columnas del reporte, todas como texto. Se construyen Excel en memoria
con ``openpyxl`` reproduciendo el layout real (cabecera en la fila 3 y columna A de
índice sin cabecera).
"""

import datetime as dt
import io

import openpyxl
import pytest

from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.parser_reports import (
    TerpelReportParseError,
    parse_reporte_xlsx,
)

_HEADER = [
    None,
    "FECHA",
    "TICKET",
    "PRODUCTO",
    "AEROLINEA",
    "VUELO",
    "GALONES",
    "SCOP",
    "PRECIO",
    "MONTO",
    "N°FACTURA",
]


def _xlsx(rows) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _reporte_con_cabecera(filas) -> bytes:
    return _xlsx(
        [
            [None, "VENTA DEL 06.01.2026 - AIR MAJORO S.A.C"],
            [],
            _HEADER,
            *filas,
        ]
    )


def test_parse_reporte_un_vuelo():
    data = _reporte_con_cabecera(
        [[1, dt.datetime(2026, 1, 6), 2600603901, "JET", "AIR MAJORO S.A.C",
          2092, 67, 12636963345, 2.53, 169.51, "FV02-00031982"]]
    )

    filas = parse_reporte_xlsx(data)

    assert filas == [
        {
            "fecha": "2026-01-06",
            "ticket": "2600603901",
            "producto": "JET",
            "aerolinea": "AIR MAJORO S.A.C",
            "vuelo": "2092",
            "galones": "67",
            "scop": "12636963345",
            "precio": "2.53",
            "monto": "169.51",
            "n_factura": "FV02-00031982",
        }
    ]


def test_parse_reporte_varias_filas():
    data = _reporte_con_cabecera(
        [
            [1, dt.datetime(2026, 1, 6), 2600603901, "JET", "AIR MAJORO S.A.C",
             2092, 67, 1, 2.5, 167.5, "FV02-1"],
            [2, dt.datetime(2026, 1, 6), 2600603904, "JET", "AIR MAJORO S.A.C",
             2221, 117, 2, 2.5, 292.5, "FV02-2"],
        ]
    )

    filas = parse_reporte_xlsx(data)

    assert [f["ticket"] for f in filas] == ["2600603901", "2600603904"]
    assert [f["n_factura"] for f in filas] == ["FV02-1", "FV02-2"]


def test_parse_reporte_descarta_filas_sin_ticket():
    # Fila de totales (solo GALONES, sin TICKET): no es un vuelo.
    data = _reporte_con_cabecera(
        [
            [1, dt.datetime(2026, 1, 5), 2600504502, "JET", "AIR MAJORO S.A.C",
             2092, 61, 1, 2.5, 152.5, "FV02-1"],
            [None, None, None, None, None, None, 256, None, None, None, None],
        ]
    )

    filas = parse_reporte_xlsx(data)

    assert [f["ticket"] for f in filas] == ["2600504502"]


def test_parse_reporte_sin_cabecera_levanta():
    data = _xlsx([["sin", "cabecera"], ["nada", "aqui"]])

    with pytest.raises(TerpelReportParseError, match="cabecera"):
        parse_reporte_xlsx(data)


def test_parse_reporte_archivo_invalido_levanta():
    with pytest.raises(TerpelReportParseError, match="abrir el Excel"):
        parse_reporte_xlsx(b"no soy un xlsx")
