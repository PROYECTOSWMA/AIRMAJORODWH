"""Tests del modelo pydantic de flight_reports (fecha ISO con hora, decimales y nulls)."""

from decimal import Decimal

from assets.from_sql_majoro_assets.flight_reports_asset.models.pydantic_model import (
    FlightReportRow,
)


def test_valida_fila_del_ejemplo():
    fila = FlightReportRow.model_validate(
        {
            "fecha_vuelo": "2026-08-01T00:00:00.0000000",
            "sede_operacion": "MEDEVAC",
            "matricula": "OB2092",
            "horas_vuelo": 3.5,
            "total_pasajeros": 8,
        }
    ).model_dump()

    assert fila["fecha_vuelo"].isoformat() == "2026-08-01"
    assert fila["sede_operacion"] == "MEDEVAC"
    assert fila["matricula"] == "OB2092"
    assert fila["horas_vuelo"] == Decimal("3.50")
    assert fila["total_pasajeros"] == 8


def test_tolera_nulls():
    fila = FlightReportRow.model_validate(
        {
            "fecha_vuelo": None,
            "sede_operacion": None,
            "matricula": None,
            "horas_vuelo": None,
            "total_pasajeros": None,
        }
    ).model_dump()

    assert fila["fecha_vuelo"] is None
    assert fila["sede_operacion"] is None
    assert fila["matricula"] is None
    assert fila["horas_vuelo"] is None
    assert fila["total_pasajeros"] is None


def test_fecha_iso_y_dd_mm_yyyy_tambien_validan():
    assert (
        FlightReportRow.model_validate({"fecha_vuelo": "2026-08-01"})
        .fecha_vuelo.isoformat()
        == "2026-08-01"
    )
    assert (
        FlightReportRow.model_validate({"fecha_vuelo": "01/08/2026"})
        .fecha_vuelo.isoformat()
        == "2026-08-01"
    )
