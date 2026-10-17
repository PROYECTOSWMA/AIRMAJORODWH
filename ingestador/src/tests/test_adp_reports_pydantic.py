"""Tests del modelo pydantic de servicios ADP (tipos y validación fail-fast)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from assets.from_email_assets.adp_reports_asset.models.pydantic_model import AdpReport


def _fila(**overrides):
    """Fila tipo del Excel de ADP (valores tal cual llegan del parser: texto)."""
    row = {
        "servicio": "3300000013",
        "nro_operacion": "1000787656",
        "operacion": "AP02",
        "apto": "TRUJILLO",
        "origen": "SPJC",
        "destino": "",
        "vuelo_llegada": "OB-2092",
        "vuelo_salida": "",
        "fec_hora_llegada": "30.01.2026 20:11:00",
        "fec_hora_salida": "30.01.2026 15:26:01",
        "total_horas": "0",
        "num_pasajeros": "3",
        "imp_unitario": "6.93",
        "peso_carga": "0",
        "descripcion_servicio": "ATERRIZAJE NACIONAL DIURNO",
        "matricula": "OB-2092",
        "tipo_aero": "BEECHCRAFT-BEEC",
        "pmd": "5.675",
        "oaci": "SPRU",
        "vuelo": "",
        "imp_igv": "1.25",
        "factura_sd": "953016366",
        "referencia": "01-0F020-0004638",
        "cliente": "20003659",
        "nom_cliente": "AIR MAJORO S.A.",
        "fecha": "31.01.2026",
        "moneda": "USD",
        "cliente_o": "20003659",
        "cliente_origen": "AIR MAJORO S.A.",
        "estado_operac": "FACTURA",
    }
    row.update(overrides)
    return row


def test_valida_y_convierte_tipos():
    d = AdpReport.model_validate(_fila()).model_dump()
    assert d["servicio"] == "3300000013"
    assert d["descripcion_servicio"] == "ATERRIZAJE NACIONAL DIURNO"
    assert d["num_pasajeros"] == 3 and isinstance(d["num_pasajeros"], int)
    assert d["total_horas"] == Decimal("0.000")
    assert d["imp_unitario"] == Decimal("6.930")
    assert d["peso_carga"] == Decimal("0.000")
    assert d["pmd"] == Decimal("5.675")
    assert d["imp_igv"] == Decimal("1.250")
    assert isinstance(d["pmd"], Decimal)
    assert d["fecha"] == date(2026, 1, 31)
    assert d["fec_hora_llegada"] == datetime(2026, 1, 30, 20, 11, 0)
    assert d["fec_hora_salida"] == datetime(2026, 1, 30, 15, 26, 1)


def test_celdas_vacias_van_a_none_y_no_rompen():
    d = AdpReport.model_validate(
        _fila(
            fecha="",
            pmd="",
            num_pasajeros="",
            fec_hora_llegada="",
            imp_igv=None,
            vuelo_salida="",
        )
    ).model_dump()
    assert d["fecha"] is None
    assert d["pmd"] is None
    assert d["num_pasajeros"] is None
    assert d["fec_hora_llegada"] is None
    assert d["imp_igv"] is None
    assert d["vuelo_salida"] == ""


def test_decimales_sin_ruido_binario():
    d = AdpReport.model_validate(_fila(pmd=5.675, imp_unitario=6.93)).model_dump()
    assert d["pmd"] == Decimal("5.675")
    assert d["imp_unitario"] == Decimal("6.930")


def test_timestamp_cero_de_adp_va_a_none():
    """ADP rellena fechas vacías con ``00.00.0000``; debe cargar ``None``."""
    d = AdpReport.model_validate(
        _fila(
            fec_hora_llegada="00.00.0000 00:00:00",
            fec_hora_salida="00.00.0000 00:00:00",
            fecha="00.00.0000",
        )
    ).model_dump()
    assert d["fec_hora_llegada"] is None
    assert d["fec_hora_salida"] is None
    assert d["fecha"] is None


def test_fecha_invalida_levanta():
    with pytest.raises(ValidationError):
        AdpReport.model_validate(_fila(fecha="no-es-fecha"))


def test_timestamp_invalido_levanta():
    with pytest.raises(ValidationError):
        AdpReport.model_validate(_fila(fec_hora_llegada="30/13/2026 20:11:00"))


def test_int_invalido_levanta():
    with pytest.raises(ValidationError):
        AdpReport.model_validate(_fila(num_pasajeros="tres"))


def test_decimal_mas_de_10_digitos_levanta():
    with pytest.raises(ValidationError):
        AdpReport.model_validate(_fila(pmd="1234567890.123"))


def test_claves_extra_se_ignoran():
    d = AdpReport.model_validate(_fila(otra_cosa=1)).model_dump()
    assert "otra_cosa" not in d
