"""Tests de CpeFilesResource (consulta de PDF/ZIP de comprobantes CPE con HTTP mockeado)."""

import json

import pytest
import requests

import assets.sire_assets.resources.details_and_files_resource as base_mod
from assets.sire_assets.resources.token_resource import (
    AUDIENCE_CPE,
    RECURSO_CONSULTACPE,
    SireTokenResource,
)
from assets.sire_assets.sire_details_asset.resources.api_resource.constants import (
    CPE_DETAILS_BASE_URL,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.constants import (
    FILE_KIND_PDF,
    FILE_KIND_ZIP,
    FILE_SUFFIX_PDF,
    FILE_SUFFIX_ZIP,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.files_resource import (
    CpeFilesError,
    CpeFilesMissing,
    CpeFilesResource,
    CpeFilesUnauthorized,
    extract_file,
)

SAMPLE_BODY = {
    "nomArchivo": "20514513172-08-F040-399-XML.zip",
    "valArchivo": "UEsDBBQAAAAIAG62M1xEjjea7RQAAIZDAAAbAAAAMjA1MTQ1MTMxNzItMDgtRjA0MC0zOTkueG1s",
}


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON body")
        return self._json_data


@pytest.fixture
def token(tmp_path):
    """Credenciales de prueba con el token de CPE ya cacheado (no se llama a SUNAT)."""
    creds = tmp_path / "sire_credentials.json"
    creds.write_text(
        json.dumps([{"name": "Air Majoro", "ruc": "20494626978"}]),
        encoding="utf-8",
    )
    cache = tmp_path / "sire_tokens.json"
    cache.write_text(
        json.dumps(
            {
                AUDIENCE_CPE: {
                    "Air Majoro": {
                        "token": "tok-1",
                        "recursos": [RECURSO_CONSULTACPE],
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


class _SessionProxy:
    """Fake de ``requests.Session`` que delega ``get`` en ``requests.get``.

    El recurso reutiliza una session (keep-alive); los tests parchean
    ``requests.get``, así que el proxy mantiene esa forma de parcheo.
    """

    def get(self, url, headers=None, **kwargs):
        return requests.get(url, headers=headers, **kwargs)


@pytest.fixture
def resource(token, monkeypatch):
    monkeypatch.setattr(requests, "Session", _SessionProxy)
    return CpeFilesResource(token_resource=token)


def test_get_file_construye_url_con_sufijo_pdf(resource, monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append((url, headers))
        return FakeResponse(status_code=200, json_data=SAMPLE_BODY)

    monkeypatch.setattr(base_mod.requests, "get", fake_get)

    archivo = resource.get_file(
        "20494626978", "01", "F001", 123,
        tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
    )
    url, headers = calls[0]
    assert url == f"{CPE_DETAILS_BASE_URL}/20494626978-01-F001-123-1{FILE_SUFFIX_PDF}"
    assert headers["User-Agent"] == "Mozilla"
    assert headers["Authorization"] == "Bearer tok-1"
    assert archivo == {
        "nom_archivo": SAMPLE_BODY["nomArchivo"],
        "val_archivo": SAMPLE_BODY["valArchivo"],
    }


def test_get_file_usa_sufijo_zip_con_rol_receptor(resource, monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=200, json_data=SAMPLE_BODY)

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    resource.get_file(
        "20100047218", "03", "B100", 7,
        tipo_archivo=FILE_KIND_ZIP, empresa="Air Majoro", rol=2,
    )
    assert calls[0] == f"{CPE_DETAILS_BASE_URL}/20100047218-03-B100-7-2{FILE_SUFFIX_ZIP}"


def test_get_file_pide_la_audiencia_de_consulta_cpe(resource, monkeypatch):
    """El token se resuelve con la audiencia y el recurso de la API de CPE."""
    capturado = {}

    def fake_token(self, name, audience=None, recurso=None):
        capturado.update(name=name, audience=audience, recurso=recurso)
        return "tok-1"

    monkeypatch.setattr(SireTokenResource, "token", fake_token)

    def fake_get(url, headers=None, **kwargs):
        return FakeResponse(status_code=200, json_data=SAMPLE_BODY)

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    resource.get_file(
        "20494626978", "01", "F001", 1,
        tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
    )

    assert capturado == {
        "name": "Air Majoro",
        "audience": AUDIENCE_CPE,
        "recurso": RECURSO_CONSULTACPE,
    }


def test_get_file_500_reintenta_y_luego_missing(resource, monkeypatch):
    monkeypatch.setattr(base_mod.time, "sleep", lambda _: None)
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append(1)
        # 500 con body JSON válido: aplica la política de retry.
        return FakeResponse(
            status_code=500,
            json_data={"code": 500, "message": "There was an error processing your request."},
        )

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesMissing):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )
    # CpeFilesResource no define retry propio: hereda el de la base
    # ``DetailsAndFilesResource.retry_max_attempts`` (50).
    assert len(calls) == resource.retry_max_attempts


def test_get_file_500_se_recupera_en_reintento(resource, monkeypatch):
    monkeypatch.setattr(base_mod.time, "sleep", lambda _: None)
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return FakeResponse(status_code=500, json_data={"code": 500})
        return FakeResponse(status_code=200, json_data=SAMPLE_BODY)

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    archivo = resource.get_file(
        "20494626978", "01", "F001", 1,
        tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
    )
    assert archivo["nom_archivo"] == SAMPLE_BODY["nomArchivo"]
    assert len(calls) == 2


def test_get_file_500_no_json_levanta_unauthorized(resource, monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append(1)
        # 500 con body no-JSON (p.ej. HTML): se interpreta como problema de
        # autenticación y corta sin reintentar.
        return FakeResponse(status_code=500, text="<html>error page</html>")

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesUnauthorized):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )
    assert len(calls) == 1


def test_get_file_401_levanta_unauthorized(resource, monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        return FakeResponse(status_code=401, text='{"status": 401, "message": "Unauthorized"}')

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesUnauthorized):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )


def test_get_file_otro_status_levanta_caso_no_manejado(resource, monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        return FakeResponse(status_code=404, text="not found")

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesError):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )


def test_get_file_error_de_red_levanta_missing(resource, monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        raise requests.exceptions.ConnectionError("timeout")

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesMissing):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )


def test_get_file_200_no_json_levanta_error(resource, monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        return FakeResponse(status_code=200, text="not-json")

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesError):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )


def test_get_file_timeout_levanta_missing(resource, monkeypatch):
    def fake_get(url, headers=None, **kwargs):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    with pytest.raises(CpeFilesMissing):
        resource.get_file(
            "20494626978", "01", "F001", 1,
            tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
        )


def test_get_file_pasa_timeout_al_request(resource, monkeypatch):
    calls = []

    def fake_get(url, headers=None, **kwargs):
        calls.append(kwargs)
        return FakeResponse(status_code=200, json_data=SAMPLE_BODY)

    monkeypatch.setattr(base_mod.requests, "get", fake_get)
    resource.get_file(
        "20494626978", "01", "F001", 1,
        tipo_archivo=FILE_KIND_PDF, empresa="Air Majoro",
    )
    assert calls[0]["timeout"] == resource.request_timeout_seconds


def test_extract_file_devuelve_claves_snake_case():
    assert extract_file(SAMPLE_BODY) == {
        "nom_archivo": SAMPLE_BODY["nomArchivo"],
        "val_archivo": SAMPLE_BODY["valArchivo"],
    }


def test_extract_file_faltan_campos_levanta():
    with pytest.raises(CpeFilesError):
        extract_file({"nomArchivo": "a.pdf"})
    with pytest.raises(CpeFilesError):
        extract_file({})

