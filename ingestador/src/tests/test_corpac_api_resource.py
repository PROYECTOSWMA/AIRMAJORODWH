"""Tests de CorpacResource (GET al portal, hidden inputs y POST del ZIP) con HTTP mockeado."""

import pytest

import assets.from_email_assets.corpac_assets.corpac_files_asset.resources.api_resource as mod
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.api_resource import (
    CORPAC_GET_TIMEOUT_SECONDS,
    CORPAC_POST_TIMEOUT_SECONDS,
    CORPAC_USER_AGENT,
    CorpacResource,
    CorpacZipError,
    extract_hidden_inputs,
)

PORTAL_HTML = """
<html><body>
<form method="post">
<input type="hidden" name="__VIEWSTATE" value="abc123" />
<input type="hidden" id="h1" name="hf_token" value="tok" />
<input type="text" name="usuario" value="x" />
<input type="submit" name="btnAdjuntos" value="Descargar Documentos" id="btnAdjuntos" />
</form>
</body></html>
"""

URL = (
    "https://www.fedtt-peru.com/MercurioCorpacPortal/Paginas/Comunicaciones"
    "?accessCode=bWZ1dzFsczErY2s90&action=1"
)


def requests_exception():
    return mod.requests.exceptions.ConnectionError("timeout")


class FakeResponse:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content


class FakeSession:
    """Registra GET/POST y responde con lo configurado (imita requests.Session)."""

    def __init__(self, get_resp, post_resp, get_error=None, post_error=None):
        self.get_resp = get_resp
        self.post_resp = post_resp
        self.get_error = get_error
        self.post_error = post_error
        self.headers = {}
        self.calls = []  # (método, url, kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if self.get_error is not None:
            raise self.get_error
        return self.get_resp

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if self.post_error is not None:
            raise self.post_error
        return self.post_resp


def _zip_resp(content=b"PK\x03\x04contenido-del-zip"):
    return FakeResponse(status_code=200, content=content)


def test_download_zip_flujo_completo(monkeypatch):
    session = FakeSession(
        get_resp=FakeResponse(status_code=200, text=PORTAL_HTML),
        post_resp=_zip_resp(),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    zip_bytes = CorpacResource().download_zip(URL)

    assert zip_bytes == b"PK\x03\x04contenido-del-zip"

    metodo_get, url_get, kwargs_get = session.calls[0]
    assert metodo_get == "GET"
    assert url_get == URL
    assert kwargs_get["timeout"] == CORPAC_GET_TIMEOUT_SECONDS
    assert session.headers["User-Agent"] == CORPAC_USER_AGENT

    metodo_post, url_post, kwargs_post = session.calls[1]
    assert metodo_post == "POST"
    assert url_post == URL
    assert kwargs_post["timeout"] == CORPAC_POST_TIMEOUT_SECONDS
    assert kwargs_post["headers"] == {"Referer": URL}
    assert kwargs_post["data"] == {
        "__VIEWSTATE": "abc123",
        "hf_token": "tok",
        "btnAdjuntos": "Descargar Documentos",
    }


def test_download_zip_sin_campos_ocultos_usa_solo_btn(monkeypatch):
    session = FakeSession(
        get_resp=FakeResponse(status_code=200, text="<html>sin form</html>"),
        post_resp=_zip_resp(),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    zip_bytes = CorpacResource().download_zip(URL)

    assert zip_bytes[:2] == b"PK"
    assert session.calls[1][2]["data"] == {"btnAdjuntos": "Descargar Documentos"}


def test_download_zip_respuesta_no_zip_levanta_error(monkeypatch):
    session = FakeSession(
        get_resp=FakeResponse(status_code=200, text=PORTAL_HTML),
        post_resp=FakeResponse(status_code=200, text="<html>error</html>", content=b"<html>"),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    with pytest.raises(CorpacZipError, match="no es un ZIP"):
        CorpacResource().download_zip(URL)


def test_download_zip_get_status_no_200(monkeypatch):
    session = FakeSession(
        get_resp=FakeResponse(status_code=500, text="server error"),
        post_resp=_zip_resp(),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    with pytest.raises(CorpacZipError, match="HTTP 500"):
        CorpacResource().download_zip(URL)


def test_download_zip_post_status_no_200(monkeypatch):
    session = FakeSession(
        get_resp=FakeResponse(status_code=200, text=PORTAL_HTML),
        post_resp=FakeResponse(status_code=500, text="boom"),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    with pytest.raises(CorpacZipError, match="HTTP 500"):
        CorpacResource().download_zip(URL)


def test_download_zip_error_de_red_en_get(monkeypatch):
    session = FakeSession(
        get_resp=None,
        post_resp=_zip_resp(),
        get_error=requests_exception(),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    with pytest.raises(CorpacZipError, match="No hubo respuesta"):
        CorpacResource().download_zip(URL)


def test_download_zip_error_de_red_en_post(monkeypatch):
    session = FakeSession(
        get_resp=FakeResponse(status_code=200, text=PORTAL_HTML),
        post_resp=None,
        post_error=requests_exception(),
    )
    monkeypatch.setattr(mod.requests, "Session", lambda: session)

    with pytest.raises(CorpacZipError, match="No hubo respuesta"):
        CorpacResource().download_zip(URL)


def test_extract_hidden_inputs_maneja_orden_y_comillas():
    html = (
        '<input value="v1" name="a" type="hidden">'
        "<input type='hidden' name='b' value='v2' />"
        "<input name='no_hidden' type='text' value='x'>"
        "<input name='sin_type' value='y'>"
        "<input TYPE='HIDDEN' name='c'>"
    )
    assert extract_hidden_inputs(html) == {"a": "v1", "b": "v2", "c": ""}


def test_extract_hidden_inputs_sin_hidden():
    assert extract_hidden_inputs("<input name='a' value='1'>") == {}
    assert extract_hidden_inputs("<input type='submit' value='Descargar'>") == {}
    assert extract_hidden_inputs("") == {}
