"""Tests de TicketResource (flujo de ticket con HTTP mockeado)."""

import base64
import io
import json
import time
import zipfile

import pytest

import assets.sire_assets.sire_proposal_asset.resources.api_resource.ticket_resource as ticket_mod
from assets.sire_assets.resources.token_resource import (
    AUDIENCE_SIRE,
    RECURSO_MIGEIGV,
    SireTokenResource,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    API_ORIGIN_CODE_PURCHASES,
    API_ORIGIN_CODE_SALES,
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
    HTTP_NETWORK_MAX_ATTEMPTS,
    HTTP_NETWORK_WAIT_SECONDS,
    HTTP_REQUEST_TIMEOUT_SECONDS,
    REPORT_FILE_PATH,
    TICKET_EMPTY_PERIOD_CODE,
    TICKET_EMPTY_PERIOD_MAX_ATTEMPTS,
    TICKET_EMPTY_PERIOD_WAIT_SECONDS,
    TICKET_IN_PROGRESS_CODE,
    TICKET_IN_PROGRESS_MAX_ATTEMPTS,
    TICKET_IN_PROGRESS_WAIT_SECONDS,
    TICKET_STATUS_PATH,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.ticket_resource import (
    PropuestaRceError,
    TicketResource,
    _es_periodo_sin_comprobantes,
    _es_proceso_en_curso,
    _ready_download,
)

def _b64(datos):
    return base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")


def make_jwt(aud, exp_offset=3600):
    """JWT de mentira (firma sin verificar) con la audiencia y caducidad pedidas."""
    payload = {"aud": aud, "exp": time.time() + exp_offset}
    return f"{_b64({'alg': 'HS256'})}.{_b64(payload)}.firma"


FINISHED_STATE = {
    "registros": [
        {
            "desEstadoProceso": "terminado",
            "showReporteDescarga": "1",
            "perTributario": "202607",
            "numTicket": "123456",
            "codProceso": "10",
            "archivoReporte": [
                {"nomArchivoReporte": "propuesta.zip", "codTipoAchivoReporte": "00"}
            ],
        }
    ]
}


class FakeResponse:
    def __init__(self, ok=True, status_code=200, text="", content=b"", json_data=None):
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self.content = content
        self._json_data = json_data

    def json(self):
        return self._json_data


@pytest.fixture
def token(tmp_path):
    """Credenciales con el token de libros ya cacheado (nunca se llama a SUNAT)."""
    creds = tmp_path / "sire_credentials.json"
    creds.write_text(
        json.dumps([{"name": "Air Majoro", "ruc": "20494626978"}]),
        encoding="utf-8",
    )
    cache = tmp_path / "sire_tokens.json"
    cache.write_text(
        json.dumps(
            {
                AUDIENCE_SIRE: {
                    "Air Majoro": {
                        "token": make_jwt(
                            [{"api": AUDIENCE_SIRE, "recurso": [{"id": RECURSO_MIGEIGV}]}]
                        ),
                        "recursos": [RECURSO_MIGEIGV],
                        "origen": "test",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return SireTokenResource(
        credentials_path=str(creds), tokens_cache_path=str(cache)
    )


@pytest.fixture
def ticket(token):
    return TicketResource(token_resource=token)


@pytest.fixture
def mock_requests(monkeypatch):
    """Router que simula los 3 endpoints. El test puede ajustar 'poll_states'."""

    def _install(poll_states, zip_bytes=b"ZIP"):
        calls = []

        def router(method, url, params=None, headers=None, **kwargs):
            calls.append(
                {"method": method, "url": url, "params": params, "headers": headers}
            )
            if "exportacioncomprobantepropuesta" in url or "exportapropuesta" in url:
                return FakeResponse(json_data={"numTicket": "123456"})
            if TICKET_STATUS_PATH in url:
                state = poll_states.pop(0) if poll_states else {"registros": []}
                return FakeResponse(json_data=state)
            if REPORT_FILE_PATH in url:
                return FakeResponse(content=zip_bytes)
            raise AssertionError(f"unexpected url: {url}")

        monkeypatch.setattr(ticket_mod.requests, "request", router)
        return calls

    return _install


def test_only_public_method_is_get_zip(ticket):
    for name in ["get_zip", "_request_ticket", "_wait_for_ticket", "_download_zip", "_request"]:
        assert hasattr(ticket, name), name
    for name in ["request_ticket", "wait_for_ticket", "download_zip"]:
        assert not hasattr(ticket, name), name


def test_request_ticket_purchases(ticket, mock_requests):
    calls = mock_requests(poll_states=[])
    num = ticket._request_ticket("202607", BOOK_CODE_PURCHASES, empresa="Air Majoro")
    assert num == "123456"
    call = calls[0]
    assert "exportacioncomprobantepropuesta" in call["url"]
    assert call["params"]["codTipoArchivo"] == 1
    assert call["params"]["codOrigenEnvio"] == API_ORIGIN_CODE_PURCHASES
    assert call["headers"]["Authorization"] == (
        "Bearer "
        + ticket.token_resource.token(
            "Air Majoro", audience=AUDIENCE_SIRE, recurso=RECURSO_MIGEIGV
        )
    )
    assert call["headers"]["Host"] == "api-sire.sunat.gob.pe"


def test_request_ticket_sales(ticket, mock_requests):
    calls = mock_requests(poll_states=[])
    num = ticket._request_ticket("202607", BOOK_CODE_SALES, empresa="Air Majoro")
    assert num == "123456"
    assert "exportapropuesta" in calls[0]["url"]
    assert calls[0]["params"]["codOrigenEnvio"] == API_ORIGIN_CODE_SALES


def test_request_ticket_missing_numticket_raises(ticket, mock_requests):
    mock_requests(poll_states=[])
    ticket_mod.requests.request = lambda *a, **k: FakeResponse(json_data={"msg": "x"})
    with pytest.raises(PropuestaRceError, match="numTicket"):
        ticket._request_ticket("202607", empresa="Air Majoro")


def test_wait_for_ticket_polls_until_finished(ticket, mock_requests):
    calls = mock_requests(poll_states=[{"registros": []}, FINISHED_STATE])
    archivo = ticket._wait_for_ticket(
        "202607", "123456", poll_seconds=0, empresa="Air Majoro"
    )
    assert archivo.nom_archivo_reporte == "propuesta.zip"
    assert archivo.cod_tipo_archivo_reporte == "00"
    assert archivo.per_tributario == "202607"
    assert archivo.num_ticket == "123456"
    assert archivo.cod_proceso == "10"
    poll_calls = [c for c in calls if TICKET_STATUS_PATH in c["url"]]
    assert len(poll_calls) == 2
    assert all(c["params"]["page"] == 1 and c["params"]["perPage"] == 1 for c in poll_calls)


def test_get_zip_end_to_end(ticket, mock_requests):
    zip_bytes = b"FAKE-ZIP-BYTES"
    calls = mock_requests(
        poll_states=[{"registros": []}, FINISHED_STATE], zip_bytes=zip_bytes
    )
    result = ticket.get_zip("202607", poll_seconds=0, empresa="Air Majoro")
    assert result == zip_bytes
    assert [c["url"].split("libros/")[-1].split("/")[0] for c in calls] == [
        "rce",
        "rvierce",
        "rvierce",
        "rvierce",
    ]


# Body real de SUNAT cuando el proceso masivo del ticket no ve comprobantes del
# periodo (HTTP 422 / cod 1070).
PERIODO_VACIO_BODY = json.dumps(
    {
        "cod": 422,
        "msg": "Unprocessable Entity - Se presentaron errores de validación que "
        "impidieron completar el Request",
        "errors": [
            {
                "cod": TICKET_EMPTY_PERIOD_CODE,
                "msg": "No se ha encontrado información de comprobantes de pago en "
                "Periodo Seleccionado.",
            }
        ],
    }
)


class _Log:
    """Log de mentira para capturar los warnings del resource."""

    def __init__(self):
        self.warnings = []

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        self.warnings.append(args[0])


def _error_periodo_vacio():
    return FakeResponse(ok=False, status_code=422, text=PERIODO_VACIO_BODY)


def test_es_periodo_sin_comprobantes_detecta_el_422_1070():
    exc = PropuestaRceError(
        "Error HTTP 422", status_code=422, response_body=PERIODO_VACIO_BODY
    )
    assert _es_periodo_sin_comprobantes(exc) is True


def test_es_periodo_sin_comprobantes_no_confunde_otros_errores():
    otros = [
        # Mismo body pero otro status.
        PropuestaRceError("500", status_code=500, response_body=PERIODO_VACIO_BODY),
        # 422 con otro código de error.
        PropuestaRceError(
            "422",
            status_code=422,
            response_body=json.dumps({"cod": 422, "errors": [{"cod": 999}]}),
        ),
        # 422 sin JSON (no se enmascara un fallo distinto).
        PropuestaRceError("422 html", status_code=422, response_body="<html>nope</html>"),
        PropuestaRceError("422 sin body", status_code=422),
    ]
    assert all(not _es_periodo_sin_comprobantes(exc) for exc in otros)


def _router_por_ticket(estados, tickets, zip_bytes=b"ZIP-NUEVO"):
    """Router que devuelve de ``estados`` (Response o dict) y cuenta los tickets."""

    def router(method, url, params=None, headers=None, **kwargs):
        if TICKET_STATUS_PATH in url:
            estado = estados.pop(0)
            if isinstance(estado, FakeResponse):
                return estado
            return FakeResponse(json_data=estado)
        if "exportapropuesta" in url or "exportacioncomprobantepropuesta" in url:
            tickets.append(1)
            return FakeResponse(json_data={"numTicket": f"{100000 + len(tickets)}"})
        if REPORT_FILE_PATH in url:
            return FakeResponse(content=zip_bytes)
        raise AssertionError(f"unexpected url: {url}")

    return router


def test_get_zip_422_1070_pide_ticket_nuevo_y_termina_bien(ticket, monkeypatch):
    """El 422/1070 es transitorio: con un ticket NUEVO el mismo libro baja bien."""
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda _seconds: None)
    tickets = []
    router = _router_por_ticket(
        estados=[
            _error_periodo_vacio(),  # 1er ticket: SUNAT dice "sin comprobantes"
            {"registros": []},  # 2º ticket: en proceso...
            FINISHED_STATE,  # ...y terminado
        ],
        tickets=tickets,
    )
    monkeypatch.setattr(ticket_mod.requests, "request", router)

    result = ticket.get_zip(
        "202608", BOOK_CODE_SALES, poll_seconds=0, empresa="Air Majoro"
    )

    assert result == b"ZIP-NUEVO"
    assert len(tickets) == 2  # el 422 obligó a pedir un ticket nuevo


def test_get_zip_422_1070_agota_intentos_y_trata_el_periodo_como_vacio(
    ticket, monkeypatch
):
    """Si SUNAT insiste, se devuelve None (0 filas) con un WARNING, sin tumbar el run."""
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda _seconds: None)
    log = _Log()
    ticket._log = log
    tickets = []
    router = _router_por_ticket(
        estados=[_error_periodo_vacio()] * TICKET_EMPTY_PERIOD_MAX_ATTEMPTS,
        tickets=tickets,
    )
    monkeypatch.setattr(ticket_mod.requests, "request", router)

    result = ticket.get_zip(
        "202608", BOOK_CODE_SALES, poll_seconds=0, empresa="Air Majoro"
    )

    assert result is None
    assert len(tickets) == TICKET_EMPTY_PERIOD_MAX_ATTEMPTS
    assert len(log.warnings) == 1
    assert "SIN comprobantes" in log.warnings[0]
    assert "202608" in log.warnings[0]


def test_http_error_raises(ticket, mock_requests):
    mock_requests(poll_states=[])
    ticket_mod.requests.request = lambda *a, **k: FakeResponse(
        ok=False, status_code=500, text="boom"
    )
    with pytest.raises(PropuestaRceError) as excinfo:
        ticket._request_ticket("202607", empresa="Air Majoro")
    assert excinfo.value.status_code == 500
    assert "boom" in str(excinfo.value)


def test_429_retries_then_succeeds(ticket, monkeypatch):
    """Un 429 puntual no debe tumbar la petición: reintenta y sigue."""
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda _seconds: None)
    calls = []

    def flaky(method, url, params=None, headers=None, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(ok=False, status_code=429, text="too many")
        return FakeResponse(json_data={"numTicket": "123456"})

    monkeypatch.setattr(ticket_mod.requests, "request", flaky)
    num = ticket._request_ticket("202607", empresa="Air Majoro")
    assert num == "123456"
    assert len(calls) == 2


def test_429_exhausts_retries_raises(ticket, monkeypatch):
    """Si SUNAT sigue con 429 tras todos los reintentos, lanza PropuestaRceError."""
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda _seconds: None)
    calls = []

    def always_429(*a, **k):
        calls.append(1)
        return FakeResponse(ok=False, status_code=429, text="too many")

    monkeypatch.setattr(ticket_mod.requests, "request", always_429)
    with pytest.raises(PropuestaRceError) as excinfo:
        ticket._request_ticket("202607", empresa="Air Majoro")
    assert excinfo.value.status_code == 429
    assert len(calls) == ticket_mod.HTTP_RETRY_MAX_ATTEMPTS
    assert ticket_mod.HTTP_RETRY_MAX_ATTEMPTS == 5
    assert ticket_mod.HTTP_RETRY_WAIT_SECONDS == 30


def test_ready_download_sunat_typo_key():
    archivo = _ready_download(FINISHED_STATE)
    assert archivo is not None
    assert archivo.cod_tipo_archivo_reporte == "00"


def test_ready_download_not_finished():
    estado = {
        "registros": [
            {
                "desEstadoProceso": "en proceso",
                "showReporteDescarga": "0",
                "archivoReporte": [],
            }
        ]
    }
    assert _ready_download(estado) is None


def test_ready_download_no_records():
    assert _ready_download({"registros": []}) is None


def test_request_pide_la_audiencia_de_los_libros_sire(ticket, mock_requests, monkeypatch):
    """El token del ticket se resuelve con la audiencia/recurso de SIRE."""
    capturado = {}

    def fake_token(self, name, audience=None, recurso=None):
        capturado.update(name=name, audience=audience, recurso=recurso)
        return "tok-1"

    monkeypatch.setattr(SireTokenResource, "token", fake_token)

    mock_requests(poll_states=[])
    ticket._request_ticket("202607", BOOK_CODE_PURCHASES, empresa="Air Majoro")

    assert capturado == {
        "name": "Air Majoro",
        "audience": AUDIENCE_SIRE,
        "recurso": RECURSO_MIGEIGV,
    }
    assert capturado == {
        "name": "Air Majoro",
        "audience": AUDIENCE_SIRE,
        "recurso": RECURSO_MIGEIGV,
    }


# Body real de SUNAT al pedir un ticket nuevo mientras el proceso del ticket
# anterior sigue corriendo (HTTP 422 / cod 42209). Verificado en vivo el
# 2026-09-23 (RVIE 202605 de Air Majoro, tras dos tickets con cod 1070).
PROCESO_EN_CURSO_BODY = json.dumps(
    {
        "cod": 422,
        "msg": "Unprocessable Entity - Se presentaron errores de validación que "
        "impidieron completar el Request",
        "errors": [
            {
                "cod": TICKET_IN_PROGRESS_CODE,
                "msg": 'Estimado contribuyente aún tiene un proceso de "Generar '
                "archivo exportar propuesta\" en curso con Ticket: 20260300003382 "
                "y Fecha Envío: 23/09/2026 16:01:46",
            }
        ],
    }
)


def _error_proceso_en_curso():
    return FakeResponse(ok=False, status_code=422, text=PROCESO_EN_CURSO_BODY)


def test_es_proceso_en_curso_detecta_el_422_42209():
    exc = PropuestaRceError(
        "Error HTTP 422", status_code=422, response_body=PROCESO_EN_CURSO_BODY
    )
    assert _es_proceso_en_curso(exc) is True


def test_es_proceso_en_curso_no_confunde_otros_errores():
    otros = [
        # Mismo body pero otro status.
        PropuestaRceError("500", status_code=500, response_body=PROCESO_EN_CURSO_BODY),
        # 422 con otro código de error.
        PropuestaRceError(
            "422",
            status_code=422,
            response_body=json.dumps({"cod": 422, "errors": [{"cod": 999}]}),
        ),
        # 422 sin JSON.
        PropuestaRceError("422 html", status_code=422, response_body="<html>nope</html>"),
        PropuestaRceError("422 sin body", status_code=422),
        # El 1070 ("periodo sin comprobantes") NO es un proceso en curso.
        PropuestaRceError(
            "422 1070", status_code=422, response_body=PERIODO_VACIO_BODY
        ),
    ]
    assert all(not _es_proceso_en_curso(exc) for exc in otros)


def test_es_periodo_sin_comprobantes_no_confunde_el_42209():
    """El 42209 (proceso en curso) no debe tratarse como periodo vacío."""
    exc = PropuestaRceError(
        "422", status_code=422, response_body=PROCESO_EN_CURSO_BODY
    )
    assert _es_periodo_sin_comprobantes(exc) is False


def test_request_ticket_42209_reintenta_y_sigue(ticket, monkeypatch):
    """Un 422/42209 (proceso anterior en curso) no debe tumbar la petición."""
    sleeps = []
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def router(method, url, params=None, headers=None, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return _error_proceso_en_curso()
        return FakeResponse(json_data={"numTicket": "999888"})

    monkeypatch.setattr(ticket_mod.requests, "request", router)

    num = ticket._request_ticket("202605", BOOK_CODE_SALES, empresa="Air Majoro")

    assert num == "999888"
    assert len(calls) == 2
    assert sleeps == [TICKET_IN_PROGRESS_WAIT_SECONDS]
    assert TICKET_IN_PROGRESS_WAIT_SECONDS == 30


def test_request_ticket_42209_agota_intentos_raises(ticket, monkeypatch):
    """Si SUNAT sigue con el proceso en curso tras todos los intentos, lanza."""
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda _s: None)
    calls = []

    def always_42209(*a, **k):
        calls.append(1)
        return _error_proceso_en_curso()

    monkeypatch.setattr(ticket_mod.requests, "request", always_42209)

    with pytest.raises(PropuestaRceError) as excinfo:
        ticket._request_ticket("202605", BOOK_CODE_SALES, empresa="Air Majoro")

    assert excinfo.value.status_code == 422
    assert str(TICKET_IN_PROGRESS_CODE) in str(excinfo.value)
    assert len(calls) == TICKET_IN_PROGRESS_MAX_ATTEMPTS
    assert TICKET_IN_PROGRESS_MAX_ATTEMPTS == 5


def test_get_zip_1070_y_choque_42209_termina_bien(ticket, monkeypatch):
    """Reproduce el fallo real del 2026-09-23 y comprueba que ya no muere.

    Secuencia: ticket 1 con 1070 -> ticket 2 con 1070 -> al pedir el ticket 3
    SUNAT contesta 422/42209 (el proceso del ticket 2 seguía en curso) -> se
    espera y reintenta -> ticket 3 descarga bien.
    """
    sleeps = []
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda s: sleeps.append(s))
    log = _Log()
    ticket._log = log
    estados = [_error_periodo_vacio()] * 2  # los dos primeros tickets dan 1070
    tickets = []

    def router(method, url, params=None, headers=None, **kwargs):
        if TICKET_STATUS_PATH in url:
            if estados:
                return estados.pop(0)
            return FakeResponse(json_data=FINISHED_STATE)
        if "exportapropuesta" in url:
            tickets.append(1)
            if len(tickets) == 3:  # el 3er ticket choca con el proceso del 2º
                return _error_proceso_en_curso()
            return FakeResponse(json_data={"numTicket": f"555{len(tickets)}"})
        if REPORT_FILE_PATH in url:
            return FakeResponse(content=b"ZIP-FINAL")
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(ticket_mod.requests, "request", router)

    result = ticket.get_zip(
        "202605", BOOK_CODE_SALES, poll_seconds=0, empresa="Air Majoro"
    )

    assert result == b"ZIP-FINAL"
    # 2 tickets con 1070 + 2 intentos rechazados con 42209 + 1 ticket bueno.
    assert len(tickets) == 4
    assert TICKET_EMPTY_PERIOD_WAIT_SECONDS in sleeps
    assert TICKET_IN_PROGRESS_WAIT_SECONDS in sleeps
    assert log.warnings == []


def test_red_reintenta_y_sigue(ticket, monkeypatch):
    """Un corte de red puntual no debe tumbar la petición: reintenta y sigue.

    Reproduce el fallo real del 2026-09-23 (RCE 202603 de Air Majoro), donde un
    ``OSError [Errno 101] Network is unreachable`` mató el run.
    """
    sleeps = []
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def flaky(method, url, params=None, headers=None, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise ticket_mod.requests.exceptions.ConnectionError(
                "[Errno 101] Network is unreachable"
            )
        return FakeResponse(json_data={"numTicket": "777888"})

    monkeypatch.setattr(ticket_mod.requests, "request", flaky)

    num = ticket._request_ticket("202603", BOOK_CODE_PURCHASES, empresa="Air Majoro")

    assert num == "777888"
    assert len(calls) == 2
    assert sleeps == [HTTP_NETWORK_WAIT_SECONDS]
    assert HTTP_NETWORK_WAIT_SECONDS == 30


def test_red_agota_intentos_raises(ticket, monkeypatch):
    """Si la red sigue caída tras todo el presupuesto, lanza PropuestaRceError."""
    monkeypatch.setattr(ticket_mod.time, "sleep", lambda _s: None)
    calls = []

    def sin_red(*a, **k):
        calls.append(1)
        raise ticket_mod.requests.exceptions.ConnectionError(
            "[Errno 101] Network is unreachable"
        )

    monkeypatch.setattr(ticket_mod.requests, "request", sin_red)

    with pytest.raises(PropuestaRceError, match="Error de red") as excinfo:
        ticket._request_ticket("202603", BOOK_CODE_PURCHASES, empresa="Air Majoro")

    assert len(calls) == HTTP_NETWORK_MAX_ATTEMPTS
    assert HTTP_NETWORK_MAX_ATTEMPTS == 10
    assert "Network is unreachable" in str(excinfo.value)


def test_request_lleva_timeout(ticket, monkeypatch):
    """La petición lleva timeout (como los demás resources de SIRE) para no colgarse."""
    capturado = {}

    def router(method, url, params=None, headers=None, **kwargs):
        capturado.update(kwargs)
        return FakeResponse(json_data={"numTicket": "1"})

    monkeypatch.setattr(ticket_mod.requests, "request", router)

    ticket._request_ticket("202607", BOOK_CODE_PURCHASES, empresa="Air Majoro")

    assert capturado["timeout"] == HTTP_REQUEST_TIMEOUT_SECONDS
    assert HTTP_REQUEST_TIMEOUT_SECONDS == 60

