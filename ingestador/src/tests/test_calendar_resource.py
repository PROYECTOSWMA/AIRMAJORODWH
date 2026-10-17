"""Tests de CalendarApiResource (tipo de cambio SUNAT con HTTP mockeado).

Cubren sobre todo el HTTP **429** (rate limit de apis.net.pe): se reintenta con una
pausa propia (respetando ``Retry-After``) y, agotados los intentos, se lanza
``CalendarApiError`` para que el asset decida degradar sin tumbar el run.
"""

import pytest

import assets.calendar_asset.resources.api_resource.calendar_resource as calendar_mod
from assets.calendar_asset.resources.api_resource.calendar_resource import (
    CalendarApiError,
    CalendarApiResource,
)
from assets.calendar_asset.resources.api_resource.constants import (
    CALENDAR_RATE_LIMIT_SLEEP_SECONDS,
    CALENDAR_RETRY_SLEEP_SECONDS,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("respuesta sin JSON")
        return self._json


def _resource(max_attempts=3):
    """Resource con pocos intentos para que los tests sean instantáneos."""
    return CalendarApiResource(max_attempts=max_attempts)


def _item(fecha="2025-10-01", compra="3.7", venta="3.8"):
    return {"fecha": fecha, "compra": compra, "venta": venta}


def test_429_reintenta_y_termina_bien(monkeypatch):
    sleeps = []
    monkeypatch.setattr(calendar_mod.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            return FakeResponse(status_code=429, text="too many")
        return FakeResponse(json_data=[_item()])

    monkeypatch.setattr(calendar_mod.requests, "get", flaky)

    out = _resource().get_month(2025, 10)

    assert out == {"2025-10-01": {"compra": "3.7", "venta": "3.8"}}
    assert len(calls) == 3
    # El 429 espera la pausa larga, no la genérica.
    assert sleeps == [CALENDAR_RATE_LIMIT_SLEEP_SECONDS] * 2


def test_429_agota_intentos_y_lanza(monkeypatch):
    monkeypatch.setattr(calendar_mod.time, "sleep", lambda _s: None)
    calls = []

    def always_429(*a, **k):
        calls.append(1)
        return FakeResponse(status_code=429, text="too many")

    monkeypatch.setattr(calendar_mod.requests, "get", always_429)

    with pytest.raises(CalendarApiError) as excinfo:
        _resource().get_month(2025, 10)

    assert "429" in str(excinfo.value)
    assert len(calls) == 3


def test_429_respeta_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(calendar_mod.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(status_code=429, headers={"Retry-After": "12"})
        return FakeResponse(json_data=[_item()])

    monkeypatch.setattr(calendar_mod.requests, "get", flaky)

    _resource().get_month(2025, 10)

    assert sleeps == [12.0]


def test_retry_after_invalido_usa_el_defecto(monkeypatch):
    sleeps = []
    monkeypatch.setattr(calendar_mod.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            # ``Retry-After`` como fecha HTTP (no soportado): se usa el valor defecto.
            return FakeResponse(status_code=429, headers={"Retry-After": "Wed, 21 Oct"})
        return FakeResponse(json_data=[_item()])

    monkeypatch.setattr(calendar_mod.requests, "get", flaky)

    _resource().get_month(2025, 10)

    assert sleeps == [CALENDAR_RATE_LIMIT_SLEEP_SECONDS]


def test_5xx_usa_la_pausa_generica(monkeypatch):
    sleeps = []
    monkeypatch.setattr(calendar_mod.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(status_code=500, text="boom")
        return FakeResponse(json_data=[_item()])

    monkeypatch.setattr(calendar_mod.requests, "get", flaky)

    _resource().get_month(2025, 10)

    assert sleeps == [CALENDAR_RETRY_SLEEP_SECONDS]
