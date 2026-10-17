"""Tests de SisaSalesResource (SQL, POST al endpoint /query, parseo, deadline y serialización)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import assets.sisa_sales_asset.resources.api_resource.sisa_sales_resource as mod
from assets.sisa_sales_asset.resources.api_resource.sisa_sales_resource import (
    SisaSalesQueryError,
    SisaSalesResource,
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
        "NUMEROFILA",
        "CODEMPDOREF",
        "CODSEDDOREF",
        "RAZONSOCIAL",
        "DOREFTOTNUM",
        "FECHAVUELO",
    ],
    "rows": [
        [1, "02", "06", "PENSION 65", 30.0000, "01/08/2026"],
        [2, "02", "06", "  CONSORCIO CG  ", "60.00", None],
    ],
    "rowCount": 2,
    "truncated": False,
}


def test_get_sales_arma_sql_y_parsea(monkeypatch):
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append((url, kwargs))
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    rows = SisaSalesResource().get_sales("2026-08-01", "02", "06")

    url, kwargs = llamadas[0]
    assert url == "http://38.187.7.111:5500/query"
    assert kwargs == {
        "json": {
            "sql": (
                "EXECUTE [dbo].[USP_UVW_LIQUIDACION_CONTA] "
                "@CODORGDOREF='01', "
                "@CODEMPDOREF='02', "
                "@CODSEDDOREF='06', "
                "@RAZONSOCIAL=NULL, "
                "@CODNVEDOREF=NULL, "
                "@T01TIPOPAGO=NULL, "
                "@NUMERODERUC=NULL, "
                "@FECHAINICIO='01/08/2026', "
                "@FECHATERMIN='31/08/2026'"
            )
        },
        "timeout": 30,
    }

    assert rows == [
        {
            "numerofila": 1,
            "codempdoref": "02",
            "codseddoref": "06",
            "razonsocial": "PENSION 65",
            "doreftotnum": 30.0,
            "fechavuelo": "01/08/2026",
        },
        {
            "numerofila": 2,
            "codempdoref": "02",
            "codseddoref": "06",
            "razonsocial": "CONSORCIO CG",
            "doreftotnum": "60.00",
            "fechavuelo": None,
        },
    ]


def test_get_credit_notes_arma_el_sql_del_procedure(monkeypatch):
    """``get_credit_notes`` usa el procedure de NC con los mismos parámetros."""
    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append((url, kwargs))
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    rows = SisaSalesResource().get_credit_notes("2026-08-01", "02", "06")

    _, kwargs = llamadas[0]
    assert kwargs["json"] == {
        "sql": (
            "EXECUTE [dbo].[USP_UVW_LIQUIDACION_NOTACREDITO] "
            "@CODORGDOREF='01', "
            "@CODEMPDOREF='02', "
            "@CODSEDDOREF='06', "
            "@RAZONSOCIAL='', "
            "@CODNVEDOREF='00', "
            "@T01TIPOPAGO='', "
            "@NUMERODERUC='', "
            "@FECHAINICIO='01/08/2026', "
            "@FECHATERMIN='31/08/2026'"
        )
    }
    assert len(rows) == 2


def test_get_sales_status_no_200(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(status_code=500, text="server error")

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(SisaSalesQueryError, match="500"):
        SisaSalesResource().get_sales("2026-08-01", "02", "06")


def test_get_sales_error_http(monkeypatch):
    def fake_post(url, **kwargs):
        raise mod.requests.ConnectionError("sin conexión")

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(SisaSalesQueryError, match="No hubo respuesta"):
        SisaSalesResource().get_sales("2026-08-01", "02", "06")


def test_get_sales_no_json(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(payload=None, text="not json", json_error=True)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(SisaSalesQueryError, match="no es JSON"):
        SisaSalesResource().get_sales("2026-08-01", "02", "06")


def test_get_sales_ok_false(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(payload={**PAYLOAD, "ok": False, "error": "boom"})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(SisaSalesQueryError, match="ok=True"):
        SisaSalesResource().get_sales("2026-08-01", "02", "06")


def test_get_sales_error_no_nulo(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse(payload={**PAYLOAD, "error": "query failed"})

    monkeypatch.setattr(mod.requests, "post", fake_post)

    with pytest.raises(SisaSalesQueryError, match="devolvió error"):
        SisaSalesResource().get_sales("2026-08-01", "02", "06")


def test_get_sales_deadline_duro(monkeypatch):
    """Si el endpoint no responde en el deadline, se reintenta y tras 3 veces falla.

    Aunque el servidor "avance" (aquí un POST que tarda más que el deadline),
    el deadline de reloj corta cada intento; no se depende del read timeout de
    requests (que no dispara si llegan datos poco a poco).
    """

    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(1)
        time.sleep(1.5)
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setattr(mod, "SISA_QUERY_TIMEOUT_SECONDS", 0.3)

    t0 = time.time()
    with pytest.raises(SisaSalesQueryError, match="no respondió en 0.3s tras 3 intentos"):
        SisaSalesResource().get_sales("2026-07-01", "02", "06")
    elapsed = time.time() - t0

    assert len(llamadas) == 3  # se reintentó 3 veces
    assert 0.5 < elapsed < 1.5  # 3 intentos de 0.3s aprox

    # Los hilos de los intentos fallidos quedaron durmiendo en segundo plano; se
    # espera a que terminen para no dejar hilos vivos en la suite.
    time.sleep(1.5)


def test_get_sales_reintenta_y_se_recupera(monkeypatch):
    """Si el primer intento no responde pero el segundo sí, devuelve las filas."""

    llamadas = []

    def fake_post(url, **kwargs):
        llamadas.append(1)
        if len(llamadas) == 1:  # el primer intento no responde; el segundo sí
            time.sleep(1.5)
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)
    monkeypatch.setattr(mod, "SISA_QUERY_TIMEOUT_SECONDS", 0.3)

    rows = SisaSalesResource().get_sales("2026-07-01", "02", "06")

    assert len(llamadas) == 2  # 1 timeout + 1 éxito
    assert len(rows) == 2

    # Espera al hilo del primer intento (quedó durmiendo en segundo plano).
    time.sleep(1.5)


def test_get_sales_se_serializan(monkeypatch):
    """Dos llamadas concurrentes nunca se solapan: cada una espera a la anterior."""
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_post(url, **kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.2)
        with lock:
            active -= 1
        return FakeResponse(payload=PAYLOAD)

    monkeypatch.setattr(mod.requests, "post", fake_post)

    res = SisaSalesResource()

    def llamada():
        return res.get_sales("2026-07-01", "01", "01")

    with ThreadPoolExecutor(max_workers=2) as pool:
        fut1 = pool.submit(llamada)
        time.sleep(0.05)  # deja que la primera arranque
        fut2 = pool.submit(llamada)
        r1 = fut1.result()
        r2 = fut2.result()

    assert max_active == 1  # los POST nunca se ejecutaron en paralelo
    assert len(r1) == 2
    assert len(r2) == 2
