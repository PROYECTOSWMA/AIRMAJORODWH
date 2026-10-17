"""Tests de SireTokenResource (tokens de SUNAT por audiencia, caché y vías).

Cubre: lectura de credenciales, resolución por audiencia (caché → API de
seguridad → portal SOL por HTTP), caché en fichero multi-audiencia (el JSON de
``env/``, junto a las credenciales) y el fallo duro (``SireTokenError``) cuando no
hay forma de obtener el token.
"""

import base64
import json
import os
import time

import pytest

import assets.sire_assets.resources.token_resource as token_mod
from assets.sire_assets.resources.token_resource import (
    AUDIENCE_CPE,
    AUDIENCE_SIRE,
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKENS_CACHE_PATH,
    RECURSO_CONSULTACPE,
    RECURSO_MIGEIGV,
    SECURITY_TOKEN_URL_TEMPLATE,
    SireTokenError,
    SireTokenResource,
    decode_jwt_claims,
    escribir_cache,
    guardar_token,
    leer_cache,
    probar_consultacpe,
    token_coverage,
    token_en_cache,
    token_expiry,
    token_has_audience,
    token_is_expired,
)
from assets.sire_assets.resources.sol_portal import SolPortalError


def _b64(datos):
    return base64.urlsafe_b64encode(json.dumps(datos).encode()).decode().rstrip("=")


def make_jwt(aud, exp_offset=3600, sub="20494626978", cliente=""):
    """JWT de mentira (firma sin verificar): solo interesan aud/exp/clientId."""
    payload = {"aud": aud, "sub": sub}
    if exp_offset is not None:
        payload["exp"] = time.time() + exp_offset
    if cliente:
        payload["clientId"] = cliente
    return f"{_b64({'alg': 'HS256'})}.{_b64(payload)}.firma"


def aud_sire():
    """Audiencia de la API de libros SIRE (propuesta/ticket)."""
    return [{"api": AUDIENCE_SIRE, "recurso": [{"id": RECURSO_MIGEIGV}]}]


def aud_cpe(recurso=RECURSO_CONSULTACPE):
    """Audiencia de la API de consulta de comprobantes CPE."""
    return [{"api": AUDIENCE_CPE, "recurso": [{"id": recurso}]}]


def creds_file(tmp_path, empresas):
    creds = tmp_path / "sire_credentials.json"
    creds.write_text(json.dumps(empresas), encoding="utf-8")
    return creds


def cache_file(tmp_path, contenido):
    """Escribe la caché de tokens (dict) y devuelve su ruta."""
    ruta = tmp_path / "sire_tokens.json"
    ruta.write_text(json.dumps(contenido), encoding="utf-8")
    return ruta


def token_cache_entry(token, recursos, exp_offset=3600):
    return {
        "token": token,
        "exp": time.time() + exp_offset,
        "recursos": list(recursos),
        "origen": "test",
    }


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise ValueError("No JSON body")
        return self._json_data


def install_post(monkeypatch, response):
    """Instala un ``requests.post`` falso que registra las llamadas."""
    calls = []

    def fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(token_mod.requests, "post", fake_post)
    return calls


def sin_red(monkeypatch):
    """Hace que cualquier petición HTTP falle (para probar que se usa la caché)."""
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("no se debería llamar a la red")

    monkeypatch.setattr(token_mod.requests, "post", fake_request)
    monkeypatch.setattr(token_mod.requests, "get", fake_request)
    return calls


EMPRESA_API = {
    "name": "Air Majoro",
    "ruc": "20494626978",
    "user": "FLYMAJOR",
    "password": "ClaveSol",
    "client_id": "00d37468-d6ea-4e1a-8bd6-380ceb473f5e",
    "client_secret": "secreto",
    "sire_scope": "https://api-sire.sunat.gob.pe",
}


def resource(tmp_path, empresas=None, cache=None, **kwargs):
    """``SireTokenResource`` con credenciales y caché en ``tmp_path``."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    creds = creds_file(tmp_path, empresas or [EMPRESA_API])
    ruta_cache = cache_file(tmp_path, cache or {})
    return SireTokenResource(
        credentials_path=str(creds), tokens_cache_path=str(ruta_cache), **kwargs
    )


# --- rutas y credenciales -----------------------------------------------------


def test_rutas_por_defecto():
    assert DEFAULT_CREDENTIALS_PATH.endswith("sire_credentials.json")
    assert "env" in DEFAULT_CREDENTIALS_PATH
    # La caché de tokens vive junto a las credenciales, en `env/` (ya no en `logs/`).
    assert DEFAULT_TOKENS_CACHE_PATH.endswith(os.path.join("env", "sire_tokens.json"))
    assert "logs" not in DEFAULT_TOKENS_CACHE_PATH


def test_companies_y_ruc(tmp_path):
    r = resource(
        tmp_path,
        empresas=[
            {"name": "Air Majoro", "ruc": "20494626978"},
            {"name": "Air Majoro Selva", "ruc": "20601234567"},
        ],
    )
    assert r.companies() == ["Air Majoro", "Air Majoro Selva"]
    assert r.ruc("Air Majoro Selva") == "20601234567"


def test_missing_name_raises(tmp_path):
    r = resource(tmp_path)
    with pytest.raises(ValueError, match="No existe un objeto de credenciales"):
        r.token("X", AUDIENCE_SIRE, RECURSO_MIGEIGV)


def test_credenciales_no_lista(tmp_path):
    creds = tmp_path / "sire_credentials.json"
    creds.write_text(json.dumps({"name": "Air Majoro"}), encoding="utf-8")
    r = SireTokenResource(
        credentials_path=str(creds), tokens_cache_path=str(tmp_path / "cache.json")
    )
    with pytest.raises(ValueError, match="debe ser una lista JSON"):
        r.companies()


# --- caché: hit, caducidad, cobertura y ausencia -------------------------------


def test_usa_la_cache_sin_tocar_la_red(tmp_path, monkeypatch):
    llamadas = sin_red(monkeypatch)
    r = resource(
        tmp_path,
        cache={
            AUDIENCE_CPE: {
                "Air Majoro": token_cache_entry("tok-cpe", [RECURSO_CONSULTACPE])
            }
        },
    )

    assert (
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE) == "tok-cpe"
    )
    assert llamadas == []


def test_cache_de_otra_audiencia_no_sirve(tmp_path, monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=204))
    jwt = make_jwt(aud_sire())
    r = resource(
        tmp_path,
        cache={
            AUDIENCE_SIRE: {
                "Air Majoro": token_cache_entry(jwt, [RECURSO_MIGEIGV])
            }
        },
        portal_enabled=False,
    )

    with pytest.raises(SireTokenError, match="No hay token válido"):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_cache_caducada_se_descarta_y_se_pide_otra(tmp_path, monkeypatch):
    jwt = make_jwt(aud_sire(), exp_offset=3600)
    calls = install_post(
        monkeypatch, FakeResponse(status_code=200, json_data={"access_token": jwt})
    )
    r = resource(
        tmp_path,
        cache={
            AUDIENCE_SIRE: {
                "Air Majoro": token_cache_entry(
                    make_jwt(aud_sire(), exp_offset=-10), [RECURSO_MIGEIGV]
                )
            }
        },
    )

    assert r.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV) == jwt
    assert len(calls) == 1


def test_cache_sin_recursos_que_cubran_el_pedido(tmp_path, monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=400, text="invalid_client"))
    jwt = make_jwt(aud_cpe(recurso="/v1/contribuyente/controlcpe"))
    r = resource(
        tmp_path,
        cache={
            AUDIENCE_CPE: {
                "Air Majoro": token_cache_entry(
                    jwt, ["/v1/contribuyente/controlcpe"]
                )
            }
        },
        portal_enabled=False,
    )

    with pytest.raises(SireTokenError):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_token_en_cache_descarta_vencidos_y_no_jwt_sin_exp(tmp_path):
    cache = {
        AUDIENCE_SIRE: {
            "A": token_cache_entry("tok-1", [RECURSO_MIGEIGV]),
            "B": token_cache_entry("tok-2", [RECURSO_MIGEIGV], exp_offset=-10),
        }
    }
    assert token_en_cache(cache, "A", AUDIENCE_SIRE, RECURSO_MIGEIGV) == "tok-1"
    assert token_en_cache(cache, "B", AUDIENCE_SIRE, RECURSO_MIGEIGV) is None
    assert token_en_cache(cache, "C", AUDIENCE_SIRE, RECURSO_MIGEIGV) is None
    # Margen: con 2 h de margen el de 1 h ya no sirve.
    assert token_en_cache(cache, "A", AUDIENCE_SIRE, RECURSO_MIGEIGV, 7200) is None


# --- vía 1: API de seguridad ---------------------------------------------------


def test_api_de_seguridad_cachea_el_token_en_todas_sus_audiencias(
    tmp_path, monkeypatch
):
    jwt = make_jwt([*aud_sire(), *aud_cpe()])
    calls = install_post(
        monkeypatch,
        FakeResponse(
            status_code=200, json_data={"access_token": jwt, "expires_in": 3600}
        ),
    )
    r = resource(tmp_path)

    assert r.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV) == jwt

    # El POST va al client_id de la empresa con usuario RUC+usuario SOL.
    assert calls[0]["url"] == SECURITY_TOKEN_URL_TEMPLATE.format(
        client_id=EMPRESA_API["client_id"]
    )
    assert calls[0]["data"]["username"] == "20494626978FLYMAJOR"
    assert calls[0]["data"]["grant_type"] == "password"
    assert calls[0]["data"]["scope"] == EMPRESA_API["sire_scope"]

    # El mismo token queda cacheado bajo las DOS audiencias que cubre.
    cache = leer_cache(r.tokens_cache_path)
    assert cache[AUDIENCE_SIRE]["Air Majoro"]["token"] == jwt
    assert cache[AUDIENCE_CPE]["Air Majoro"]["token"] == jwt
    assert cache[AUDIENCE_CPE]["Air Majoro"]["recursos"] == [RECURSO_CONSULTACPE]

    # Y una segunda petición ya no toca la red.
    assert r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE) == jwt
    assert len(calls) == 1


def test_otro_proceso_reutiliza_la_cache(tmp_path, monkeypatch):
    jwt = make_jwt([*aud_sire(), *aud_cpe()])
    calls = install_post(
        monkeypatch, FakeResponse(status_code=200, json_data={"access_token": jwt})
    )
    primero = resource(tmp_path)
    primero.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)

    # Instancia nueva (como otro step/proceso) leyendo el mismo fichero.
    segundo = SireTokenResource(
        credentials_path=primero.credentials_path,
        tokens_cache_path=primero.tokens_cache_path,
        portal_enabled=False,
    )
    assert segundo.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE) == jwt
    assert len(calls) == 1


def test_api_seguridad_sin_credenciales(tmp_path, monkeypatch):
    sin_red(monkeypatch)
    r = resource(
        tmp_path,
        empresas=[{"name": "Air Majoro", "ruc": "20494626978"}],
        portal_enabled=False,
    )

    with pytest.raises(SireTokenError, match="sin client_id"):
        r.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)


def test_204_y_error_de_red_se_anotan_como_motivos(tmp_path, monkeypatch):
    r204 = resource(tmp_path / "a")
    install_post(monkeypatch, FakeResponse(status_code=204))
    with pytest.raises(SireTokenError, match="HTTP 204 sin body"):
        r204.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)

    r_red = resource(tmp_path / "b")
    install_post(monkeypatch, token_mod.requests.exceptions.ConnectionError("sin red"))
    with pytest.raises(SireTokenError, match="error de red"):
        r_red.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)


def test_token_manual_del_json_ya_no_se_usa(tmp_path, monkeypatch):
    """Sin fallback manual: el campo ``token`` del JSON se ignora."""
    jwt = make_jwt(aud_sire())
    install_post(
        monkeypatch, FakeResponse(status_code=200, json_data={"access_token": jwt})
    )
    r = resource(
        tmp_path,
        empresas=[{**EMPRESA_API, "token": "tok-manual"}],
        portal_enabled=False,
    )

    with pytest.raises(SireTokenError):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)


# --- vía 2: portal SOL por HTTP (consultacpe) ----------------------------------


def _portal(monkeypatch, token, http=422, error=None):
    """Sustituye la vía del portal por una simulada; devuelve el contador."""
    llamadas = {"portal": 0, "comprobar": 0}

    def fake_obtener(empresa, app=None):
        llamadas["portal"] += 1
        llamadas["empresa"] = empresa
        if error is not None:
            raise error
        return token, "portal SOL (Location del portal)"

    def fake_comprobar(tok, timeout=None):
        llamadas["comprobar"] += 1
        return http

    monkeypatch.setattr(token_mod, "obtener_token_app", fake_obtener)
    monkeypatch.setattr(token_mod, "probar_consultacpe", fake_comprobar)
    return llamadas


def test_portal_da_el_token_de_consultacpe_cuando_seguridad_no_cubre(
    tmp_path, monkeypatch
):
    seguridad = make_jwt(aud_sire())  # cubre api-sire, NO consultacpe
    install_post(
        monkeypatch,
        FakeResponse(status_code=200, json_data={"access_token": seguridad}),
    )
    jwt = make_jwt(aud_cpe())
    llamadas = _portal(monkeypatch, jwt)
    r = resource(tmp_path)

    assert r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE) == jwt
    assert llamadas["portal"] == 1 and llamadas["comprobar"] == 1
    assert llamadas["empresa"]["name"] == "Air Majoro"
    cache = leer_cache(r.tokens_cache_path)
    assert cache[AUDIENCE_CPE]["Air Majoro"]["token"] == jwt
    assert cache[AUDIENCE_CPE]["Air Majoro"]["origen"].startswith("portal SOL")


def test_portal_token_rechazado_en_vivo(tmp_path, monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=204))
    llamadas = _portal(monkeypatch, make_jwt(aud_cpe()), http=401)
    r = resource(tmp_path)

    with pytest.raises(SireTokenError, match="api-cpe rechazó el token"):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)
    assert llamadas["comprobar"] == 1


def test_portal_falla_y_no_reintenta_en_el_mismo_proceso(tmp_path, monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=204))
    llamadas = _portal(
        monkeypatch, "", error=SolPortalError("SUNAT pide captcha (fallas>=3)")
    )
    r = resource(tmp_path)

    with pytest.raises(SireTokenError, match="captcha"):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)
    with pytest.raises(SireTokenError, match="ya se intentó sin éxito"):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)
    assert llamadas["portal"] == 1  # un solo login, sin reintentos


def test_portal_deshabilitado(tmp_path, monkeypatch):
    install_post(monkeypatch, FakeResponse(status_code=204))
    r = resource(tmp_path, portal_enabled=False)

    with pytest.raises(SireTokenError, match="portal SOL: deshabilitado"):
        r.token("Air Majoro", AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_portal_no_se_intenta_para_la_audiencia_de_libros(tmp_path, monkeypatch):
    """``api-sire`` (propuesta) no tiene app de portal verificada."""
    install_post(monkeypatch, FakeResponse(status_code=204))
    llamadas = _portal(monkeypatch, make_jwt(aud_sire()))
    r = resource(tmp_path)

    with pytest.raises(SireTokenError):
        r.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)
    assert llamadas["portal"] == 0


# --- caché de tokens (fichero) -------------------------------------------------


def test_guardar_token_en_todas_las_audiencias_y_gana_el_mas_fresco(tmp_path):
    ruta = tmp_path / "cache.json"
    jwt = make_jwt([*aud_sire(), *aud_cpe()], exp_offset=3600)
    cache = guardar_token(ruta, "Air Majoro", jwt, "api-seguridad")
    assert cache[AUDIENCE_SIRE]["Air Majoro"]["token"] == jwt
    assert cache[AUDIENCE_CPE]["Air Majoro"]["recursos"] == [RECURSO_CONSULTACPE]
    assert leer_cache(ruta) == cache

    # Un token más viejo (misma empresa) no pisa al fresco que ya está.
    viejo = make_jwt([*aud_sire(), *aud_cpe()], exp_offset=100)
    cache2 = guardar_token(ruta, "Air Majoro", viejo, "api-seguridad")
    assert cache2[AUDIENCE_CPE]["Air Majoro"]["token"] == jwt

    # Y uno más fresco sí lo sustituye.
    nuevo = make_jwt([*aud_sire(), *aud_cpe()], exp_offset=7200)
    cache3 = guardar_token(ruta, "Air Majoro", nuevo, "api-seguridad")
    assert cache3[AUDIENCE_CPE]["Air Majoro"]["token"] == nuevo


def test_guardar_token_con_extras_cuando_el_jwt_es_opaco(tmp_path):
    ruta = tmp_path / "cache.json"
    cache = guardar_token(
        ruta,
        "Air Majoro",
        "token-opaco",
        "manual",
        extras=((AUDIENCE_CPE, RECURSO_CONSULTACPE),),
    )
    assert cache[AUDIENCE_CPE]["Air Majoro"]["token"] == "token-opaco"
    assert cache[AUDIENCE_CPE]["Air Majoro"]["exp"] is None


def test_leer_cache_inexistente_vacia_y_corrupta_se_aparta(tmp_path):
    ruta = tmp_path / "cache.json"
    assert leer_cache(ruta) == {}

    ruta.write_text("{esto no es json", encoding="utf-8")
    assert leer_cache(ruta) == {}
    assert not ruta.exists()
    assert ruta.with_suffix(".json.bad").exists()


def test_escribir_cache_deja_json_legible(tmp_path):
    ruta = tmp_path / "sub" / "cache.json"
    escribir_cache(ruta, {AUDIENCE_SIRE: {"Air Majoro": token_cache_entry("t", [])}})
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos[AUDIENCE_SIRE]["Air Majoro"]["token"] == "t"


# --- helpers de JWT y cobertura ------------------------------------------------


def test_decode_jwt_claims():
    assert decode_jwt_claims("tok-1") is None
    assert decode_jwt_claims("a.b") is None
    assert decode_jwt_claims("a.@@@.c") is None
    jwt = make_jwt(aud_sire(), sub="20494626978")
    assert decode_jwt_claims(jwt)["sub"] == "20494626978"


def test_token_expiry_y_caducidad():
    assert token_expiry("tok-1") is None
    assert token_expiry(make_jwt(aud_sire(), exp_offset=None)) is None
    assert not token_is_expired("tok-1")

    jwt = make_jwt(aud_sire(), exp_offset=100)
    assert token_expiry(jwt) is not None
    assert not token_is_expired(jwt, margin_seconds=50)
    assert token_is_expired(jwt, margin_seconds=200)
    assert token_is_expired(make_jwt(aud_sire(), exp_offset=-1))


def test_token_has_audience_por_api_y_recurso():
    jwt = make_jwt(aud_sire())
    assert token_has_audience(jwt, AUDIENCE_SIRE)
    assert token_has_audience(jwt, AUDIENCE_SIRE, RECURSO_MIGEIGV)
    assert not token_has_audience(jwt, AUDIENCE_SIRE, RECURSO_CONSULTACPE)
    assert not token_has_audience(jwt, AUDIENCE_CPE, RECURSO_CONSULTACPE)
    # Un token no verificable (no JWT) se acepta.
    assert token_has_audience("tok-1", AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_token_has_audience_con_api_cpe_sin_consultacpe():
    """Air Majoro Selva: tiene ``api-cpe`` pero no el recurso de consulta."""
    jwt = make_jwt(
        [
            {
                "api": AUDIENCE_CPE,
                "recurso": [
                    {"id": "/v1/contribuyente/controlcpe"},
                    {"id": "/v1/contribuyente/gem"},
                ],
            }
        ]
    )
    assert token_has_audience(jwt, AUDIENCE_CPE)
    assert not token_has_audience(jwt, AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_token_has_audience_con_aud_string():
    jwt = make_jwt(AUDIENCE_SIRE)
    assert token_has_audience(jwt, AUDIENCE_SIRE)
    assert not token_has_audience(jwt, AUDIENCE_CPE)


def test_token_has_audience_con_aud_string_json():
    """Forma real de SUNAT: el claim ``aud`` es un string con el JSON dentro."""
    aud = json.dumps(
        [
            {
                "api": AUDIENCE_SIRE,
                "recurso": [{"id": RECURSO_MIGEIGV, "indicador": "1"}],
            },
            {"api": AUDIENCE_CPE, "recurso": [{"id": "/v1/contribuyente/controlcpe"}]},
        ]
    )
    jwt = make_jwt(aud)

    assert token_has_audience(jwt, AUDIENCE_SIRE, RECURSO_MIGEIGV)
    assert token_has_audience(jwt, AUDIENCE_CPE)
    assert not token_has_audience(jwt, AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_token_has_audience_con_aud_string_json_objeto():
    """También se admite el string con un único objeto (no lista)."""
    jwt = make_jwt(
        json.dumps({"api": AUDIENCE_CPE, "recurso": [{"id": RECURSO_CONSULTACPE}]})
    )
    assert token_has_audience(jwt, AUDIENCE_CPE, RECURSO_CONSULTACPE)


def test_token_has_audience_con_aud_string_json_roto():
    """Un string que parece JSON pero no lo es se compara como aud simple."""
    jwt = make_jwt('["https://api-sire.sunat.gob.pe"')
    assert not token_has_audience(jwt, AUDIENCE_SIRE)


def test_token_coverage():
    jwt = make_jwt(
        [
            {
                "api": AUDIENCE_SIRE,
                "recurso": [{"id": RECURSO_MIGEIGV}, {"id": RECURSO_MIGEIGV}],
            },
            {"api": AUDIENCE_CPE, "recurso": [{"id": RECURSO_CONSULTACPE}]},
        ]
    )
    assert token_coverage(jwt) == {
        AUDIENCE_SIRE: [RECURSO_MIGEIGV],
        AUDIENCE_CPE: [RECURSO_CONSULTACPE],
    }
    assert token_coverage("tok-opaco") == {}


def test_probar_consultacpe_usa_el_comprobante_de_prueba(monkeypatch):
    calls = []

    class _Resp:
        status_code = 422

    def fake_get(url, headers=None, timeout=None, **kwargs):
        calls.append((url, headers))
        return _Resp()

    monkeypatch.setattr(token_mod.requests, "get", fake_get)
    assert probar_consultacpe("tok-1") == 422
    assert calls[0][1]["Authorization"] == "Bearer tok-1"

    def fake_get_error(*args, **kwargs):
        raise token_mod.requests.exceptions.Timeout("timeout")

    monkeypatch.setattr(token_mod.requests, "get", fake_get_error)
    assert probar_consultacpe("tok-1") is None


# --- username del token endpoint ----------------------------------------------


def test_username_por_defecto_y_desde_el_json(tmp_path, monkeypatch):
    calls = install_post(monkeypatch, FakeResponse(status_code=204))
    r = resource(tmp_path)
    with pytest.raises(SireTokenError):
        r.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)
    assert calls[0]["data"]["username"] == "20494626978FLYMAJOR"

    # Un campo ``username`` en el fichero gana al formato del recurso.
    r2 = resource(
        tmp_path / "b",
        empresas=[{**EMPRESA_API, "username": "DIRECTO"}],
    )
    calls2 = install_post(monkeypatch, FakeResponse(status_code=204))
    with pytest.raises(SireTokenError):
        r2.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)
    assert calls2[0]["data"]["username"] == "DIRECTO"


def test_username_format_sin_llaves(tmp_path, monkeypatch):
    calls = install_post(monkeypatch, FakeResponse(status_code=204))
    r = resource(tmp_path, username_format="USUARIO-FIJO")
    with pytest.raises(SireTokenError):
        r.token("Air Majoro", AUDIENCE_SIRE, RECURSO_MIGEIGV)
    assert calls[0]["data"]["username"] == "USUARIO-FIJO"


