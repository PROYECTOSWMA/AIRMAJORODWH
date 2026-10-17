"""Tests de FlightReportsResource (SQL, POST al endpoint /query, parseo y deadline)."""

import time

import pytest

import assets.from_sql_majoro_assets.flight_reports_asset.resources.api_resource.flight_reports_resource as mod
from assets.from_sql_majoro_assets.flight_reports_asset.resources.api_resource.flight_reports_resource import (
    FlightReportsQueryError,
    FlightReportsResource,
    _mes_ventana,
)


def test_mes_ventana():
    assert _mes_ventana("2026-08-01") == ("01/08/2026", "31/08/2026")
    assert _mes_ventana("2026-07-01") == ("01/07/2026", "31/07/2026")
    assert _mes_ventana("2026-02-01") == ("01/02/2026", "28/02/2026")
    assert _mes_ventana("2028-02-01") == ("01/02/2028", "29/02/2028")


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", json_error=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


PAYLOAD = {
    "ok": True,
    "error": None,
    "columns": [
        "Fecha_Vuelo",
        "Sede_Operacion",
        "Matricula",
        "Horas_Vuelo",
        "Total_Pasajeros",
    ],
    "rows": [
        ["2026-08-01T00:00:00.0000000", "MEDEVAC", "OB2092         ", 3.5, 8],
        ["2026-08-02T00:00:00.0000000", "  NASCA  ", "OB-1919-P", "1.50", 17],
    ],
    "rowCount": 2,
    "truncated": False,
}


def test_get_report_arma_sql_y_parsea(monkeypatch):
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append((url, kwargs))
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    rows = FlightReportsResource().get_report("2026-08-01")

    url, kwargs = llamadas[0]
    assert url == "http://38.187.7.111:5500/query"
    assert kwargs == {
        "json": {
            "sql": (
                "EXECUTE [db_mantenimiento].[dbo].[USP_ESTADISTICAS_VUELOS_PERIODO] "
                "@FechaInicio='01/08/2026', "
                "@FechaFin='31/08/2026', "
                "@OpcionReporte=4"
            )
        },
        "timeout": 30,
    }

    # Los valores str se limpian (strip) y las claves se normalizan a snake_case.
    assert rows == [
        {
            "fecha_vuelo": "2026-08-01T00:00:00.0000000",
            "sede_operacion": "MEDEVAC",
            "matricula": "OB2092",
            "horas_vuelo": 3.5,
            "total_pasajeros": 8,
        },
        {
            "fecha_vuelo": "2026-08-02T00:00:00.0000000",
            "sede_operacion": "NASCA",
            "matricula": "OB-1919-P",
            "horas_vuelo": "1.50",
            "total_pasajeros": 17,
        },
    ]


def test_get_report_status_no_200(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(status_code=500, text="server error")

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(FlightReportsQueryError, match="500"):
        FlightReportsResource().get_report("2026-08-01")


def test_get_report_respuesta_no_json(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(json_error=True)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(FlightReportsQueryError, match="no es JSON"):
        FlightReportsResource().get_report("2026-08-01")


def test_get_report_ok_falso(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(payload={**PAYLOAD, "ok": False})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(FlightReportsQueryError, match="ok=True"):
        FlightReportsResource().get_report("2026-08-01")


def test_get_report_error_no_nulo(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(payload={**PAYLOAD, "error": "query failed"})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(FlightReportsQueryError, match="devolvió error"):
        FlightReportsResource().get_report("2026-08-01")


def test_get_report_deadline_duro(monkeypatch):
    """Si el endpoint no responde en el deadline, se reintenta y tras 3 veces falla."""

    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(1)
        time.sleep(1.5)
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setattr(mod, "FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS", 0.3)

    with pytest.raises(
        FlightReportsQueryError, match="no respondió en 0.3s tras 3 intentos"
    ):
        FlightReportsResource().get_report("2026-07-01")

    assert len(llamadas) == 3  # se reintentó 3 veces

    # Los hilos de los intentos fallidos quedaron durmiendo en segundo plano; se
    # espera a que terminen para no dejar hilos vivos en la suite.
    time.sleep(1.5)
