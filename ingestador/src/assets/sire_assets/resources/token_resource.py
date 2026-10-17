"""Resource de tokens de SUNAT/SIRE: los pide por audiencia y los cachea en fichero.

Los tokens de SUNAT **no son fijos**: caducan (``expires_in`` = 3600 s) y cada
audiencia/recurso los emite una vía distinta. Este resource es el **único**
proveedor de tokens de SIRE y resuelve ``token(empresa, audience, recurso)`` así:

1. **Caché** (fichero ``env/sire_tokens.json``, ver abajo): si hay un token de esa
   empresa para esa audiencia, sin caducar y que cubre el recurso pedido, se usa
   **sin tocar la red**.
2. **API de seguridad de SUNAT** (``POST`` a
   ``api-seguridad.sunat.gob.pe/v1/clientessol/{client_id}/oauth2/token/`` con
   ``application/x-www-form-urlencoded``, ``grant_type=password``, ``scope``,
   ``client_id``/``client_secret`` de "Credenciales de API SUNAT", ``username`` =
   RUC + usuario SOL y ``password`` = clave SOL). Es la vía de la propuesta
   (``api-sire`` + ``/v1/contribuyente/migeigv``) y también la de detalles/archivos
   cuando el ``client_id`` tiene el permiso ``consultacpe`` (Air Majoro).
3. **Portal SOL por HTTP puro** (sin navegador; ``assets/.../resources/sol_portal.py``):
   login (1 intento) + ``POST {action:'prevApp'}`` + ``GET
   MenuInternet.htm?action=execute&code=11.38.1.1.1`` → el portal responde **302**
   con el JWT de ``consultacpe`` en el ``Location``. Es la vía de detalles/archivos
   cuando la API de seguridad **no** concede ``consultacpe`` (Air Majoro Selva).
   El plan B con navegador headless queda documentado en
   ``docs/sol_token_navegador.py``.
4. Si nada sirve, **``SireTokenError``** (cae la materialización). No hay token
   manual de respaldo: el campo ``token`` del JSON de credenciales ya no se lee.

**Caché en fichero** (``env/sire_tokens.json``, junto a las credenciales; el JSON de
la caché está en ``.gitignore``):
un diccionario **audiencia → empresa → token** con la forma
``{"<audiencia>": {"<empresa>": {"token", "exp", "recursos", "origen", "obtenido"}}}``.
Cada vez que se obtiene un token, se guarda la **misma** entrada bajo **todas las
audiencias que ese JWT cubre** (se deducen del claim ``aud``) y, si ya había una
entrada, se conserva la **más fresca** (mayor ``exp``). Al leer, se busca la
audiencia y la empresa, y si no está o está vencida se pide otra vez. Así una
corrida pide el token una sola vez por empresa y las siguientes lo reutilizan.

Todo el estado de SIRE vive en la carpeta ``env/``: las credenciales en
``env/sire_credentials.json`` y la caché de tokens en ``env/sire_tokens.json``.
**No se usa ``logs/`` para nada** (sólo herramientas manuales de ``docs/``).

El fichero se escribe de forma **atómica** (tmp + ``os.replace``) y protegido con
``fcntl.flock`` (cuando está disponible) más un lock en proceso, porque los steps
de Dagster corren en procesos distintos.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import requests
from dagster import ConfigurableResource, InitResourceContext
from pydantic import Field, PrivateAttr

from assets.sire_assets.resources.sol_portal import (
    APP_COMPROBANTES,
    SolPortalError,
    obtener_token_app,
)

_logger = logging.getLogger(__name__)

try:  # POSIX: lock entre procesos para no repetir logins en paralelo
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CREDENTIALS_PATH = str(REPO_ROOT / "env" / "sire_credentials.json")
# Caché de tokens (audiencia -> empresa -> token). Todo el estado de SIRE vive en
# `env/` (las credenciales y esta caché); `logs/` ya no se usa. Este JSON está en
# `.gitignore`.
DEFAULT_TOKENS_CACHE_PATH = str(REPO_ROOT / "env" / "sire_tokens.json")

# Endpoint OAuth2 de la API de seguridad de SUNAT. El ``client_id`` va en la ruta
# y **también** en el body (así lo documenta SUNAT).
SECURITY_TOKEN_URL_TEMPLATE = (
    "https://api-seguridad.sunat.gob.pe/v1/clientessol/{client_id}/oauth2/token/"
)
# Valor documentado por SUNAT para este endpoint (con ``client_credentials``
# responde 204 sin body).
SECURITY_TOKEN_GRANT_TYPE = "password"
SECURITY_USER_AGENT = "Mozilla"
SECURITY_CONTENT_TYPE = "application/x-www-form-urlencoded"

# Audiencias (claim ``aud`` del JWT) y recurso de cada API de SUNAT consumida.
# ``RECURSO_MIGEIGV`` es el prefijo de la API de libros SIRE (propuesta/ticket) y
# ``RECURSO_CONSULTACPE`` el de la consulta de comprobantes CPE (detalles/files).
AUDIENCE_SIRE = "https://api-sire.sunat.gob.pe"
RECURSO_MIGEIGV = "/v1/contribuyente/migeigv"
AUDIENCE_CPE = "https://api-cpe.sunat.gob.pe"
RECURSO_CONSULTACPE = "/v1/contribuyente/consultacpe"

# Comprobante de prueba para validar en vivo un token de ``consultacpe``: la API
# responde 422 (documento de ejemplo que no existe) y eso ya demuestra que el
# token es aceptado; 401/500 lo rechazan.
URL_COMPROBANTE_PRUEBA = (
    f"{AUDIENCE_CPE}{RECURSO_CONSULTACPE}/comprobantes/20514513172-01-F001-1-1"
)


class SireTokenError(Exception):
    """No hay ningún token válido (audiencia/caducidad) para esa empresa."""


def decode_jwt_claims(token: str) -> dict[str, Any] | None:
    """Devuelve el payload del JWT **sin verificar la firma**, o ``None``.

    ``None`` cuando el token no es un JWT (o su payload no es JSON), caso en el
    que no se puede comprobar ni la audiencia ni la caducidad.
    """
    partes = token.split(".")
    if len(partes) != 3:
        return None
    payload = partes[1]
    payload += "=" * (-len(payload) % 4)
    try:
        datos = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, binascii.Error):
        return None
    return datos if isinstance(datos, dict) else None


def token_expiry(token: str) -> float | None:
    """Epoch de caducidad (claim ``exp``) del token, o ``None`` si no se puede leer."""
    claims = decode_jwt_claims(token)
    if claims is None:
        return None
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return None
    return float(exp)


def token_is_expired(token: str, margin_seconds: float = 0) -> bool:
    """``True`` si el token caduca dentro de ``margin_seconds``.

    Un token que no es JWT (no verificable) **no** se considera expirado.
    """
    exp = token_expiry(token)
    if exp is None:
        return False
    return exp <= time.time() + margin_seconds


def _audience_entries(aud: Any) -> list[Any]:
    """Normaliza el claim ``aud`` a una lista de entradas.

    SUNAT lo emite como **string con el JSON dentro** (p. ej. ``'[{"api":
    "https://api-sire.sunat.gob.pe","recurso":[{"id":"..."}]}]'``), aunque el
    estándar admite también lista o string simple; aquí se aceptan las tres.
    """
    if isinstance(aud, str):
        texto = aud.strip()
        if texto.startswith("[") or texto.startswith("{"):
            try:
                return _audience_entries(json.loads(texto))
            except ValueError:
                return [aud]
        return [aud]
    if isinstance(aud, dict):
        return [aud]
    if isinstance(aud, list):
        return list(aud)
    return []


def token_has_audience(token: str, audience: str, recurso: str | None = None) -> bool:
    """``True`` si el token cubre ``audience`` (y el ``recurso``, si se indica).

    El claim ``aud`` de SUNAT es (habitualmente como string JSON) una lista de
    ``{"api": ..., "recurso": [{"id": ...}]}``: se busca la ``api`` pedida y,
    cuando se pide ``recurso``, que alguno de sus ``id`` empiece por él
    (p. ej. ``/v1/contribuyente/consultacpe``). Un token que no es JWT (no
    verificable) se acepta.
    """
    claims = decode_jwt_claims(token)
    if claims is None:
        return True
    for entrada in _audience_entries(claims.get("aud")):
        if isinstance(entrada, str):
            if entrada == audience or (
                recurso is not None and entrada.startswith(recurso)
            ):
                return True
            continue
        if not isinstance(entrada, dict) or entrada.get("api") != audience:
            continue
        if recurso is None:
            return True
        for item in entrada.get("recurso") or []:
            identificador = item.get("id") if isinstance(item, dict) else item
            if isinstance(identificador, str) and identificador.startswith(recurso):
                return True
    return False


def token_coverage(token: str) -> dict[str, list[str]]:
    """Audiencias y recursos que cubre el token: ``{audiencia: [recurso, ...]}``.

    Se deduce del claim ``aud`` (la forma de SUNAT: lista de ``{"api", "recurso":
    [{"id"}]}``); es lo que permite guardar **un mismo token bajo todas las
    audiencias que cubre**. Un token sin ``aud`` legible (opaco, ``[]`` o una
    audiencia simple) devuelve ``{audiencia: []}`` para las audiencias string, y
    ``{}`` si no se puede deducir nada.
    """
    claims = decode_jwt_claims(token)
    if claims is None:
        return {}
    cobertura: dict[str, list[str]] = {}
    for entrada in _audience_entries(claims.get("aud")):
        if isinstance(entrada, str):
            cobertura.setdefault(entrada, [])
            continue
        if not isinstance(entrada, dict):
            continue
        api = entrada.get("api")
        if not api:
            continue
        recursos = [
            str(item.get("id") if isinstance(item, dict) else item)
            for item in (entrada.get("recurso") or [])
            if (item.get("id") if isinstance(item, dict) else item)
        ]
        recursos_previos = cobertura.setdefault(str(api), [])
        for recurso in recursos:
            if recurso not in recursos_previos:
                recursos_previos.append(recurso)
    return cobertura


def probar_consultacpe(token: str, timeout: float = 30) -> int | None:
    """Llama a api-cpe con el token y devuelve el status HTTP (o ``None``).

    Sirve para validar un token de ``consultacpe`` **en vivo**: 422 es lo normal
    (el comprobante de prueba no existe, pero el token se acepta), 200 también
    valdría y 401/500 significan que el token no sirve.
    """
    try:
        respuesta = requests.get(
            URL_COMPROBANTE_PRUEBA,
            headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla"},
            timeout=timeout,
        )
    except requests.exceptions.RequestException:
        return None
    return respuesta.status_code


# --- caché en fichero (audiencia -> empresa -> token) --------------------------


@contextmanager
def _lock_de_fichero(path: Path) -> Iterator[None]:
    """Lock entre procesos sobre ``<path>.lock`` (no-op si no hay ``fcntl``)."""
    if fcntl is None:  # pragma: no cover - Windows
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{path}.lock", "w", encoding="utf-8") as manejador:
        try:
            fcntl.flock(manejador.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(manejador.fileno(), fcntl.LOCK_UN)


def leer_cache(path: str | Path) -> dict[str, dict[str, dict[str, Any]]]:
    """Lee la caché de tokens; ``{}`` si no existe o no se puede interpretar.

    Un fichero corrupto se aparta como ``.bad`` (para poder inspeccionarlo) y se
    devuelve ``{}``, de modo que la siguiente petición lo regenere.
    """
    ruta = Path(path)
    if not ruta.exists():
        return {}
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _logger.warning("Caché de tokens ilegible en %s: se aparta como .bad", ruta)
        try:
            ruta.replace(ruta.with_suffix(ruta.suffix + ".bad"))
        except OSError:
            pass
        return {}
    if not isinstance(datos, dict):
        _logger.warning("Caché de tokens con formato inesperado en %s: se ignora", ruta)
        return {}
    return {
        str(audiencia): dict(empresas)
        for audiencia, empresas in datos.items()
        if isinstance(empresas, dict)
    }


def escribir_cache(
    path: str | Path, cache: dict[str, dict[str, dict[str, Any]]]
) -> None:
    """Escribe la caché de tokens de forma atómica (tmp + ``os.replace``)."""
    ruta = Path(path)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + f".tmp{os.getpid()}")
    temporal.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(temporal, ruta)


def _entradas_del_token(
    token: str, extras: tuple[tuple[str, str | None], ...] = ()
) -> dict[str, list[str]]:
    """Audiencias/recursos bajo los que guardar el token.

    Es la cobertura del propio JWT (``token_coverage``) más los pares
    audiencia/recurso pedidos por el llamador (por si el token no es un JWT
    legible y no se puede deducir su cobertura).
    """
    cobertura = token_coverage(token)
    for audience, recurso in extras:
        if not audience:
            continue
        recursos = cobertura.setdefault(audience, [])
        if recurso and recurso not in recursos:
            recursos.append(recurso)
    return cobertura


def guardar_token(
    cache_path: str | Path,
    empresa: str,
    token: str,
    origen: str = "",
    extras: tuple[tuple[str, str | None], ...] = (),
    guardar: bool = True,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Guarda ``token`` para ``empresa`` bajo **todas** las audiencias que cubre.

    Escribe la misma entrada (``token``, ``exp``, ``recursos``, ``origen``,
    ``obtenido``) en cada audiencia de la cobertura del JWT. Si ya había una
    entrada para esa empresa y audiencia se conserva la **más fresca** (mayor
    ``exp``), de modo que un token viejo no pisa a uno nuevo. Devuelve la caché
    resultante; con ``guardar=False`` sólo la calcula (para probar).
    """
    ruta = Path(cache_path)
    with _lock_de_fichero(ruta):
        cache = leer_cache(ruta)
        entradas = _entradas_del_token(token, extras)
        if not entradas:
            _logger.warning(
                "El token de '%s' no declara audiencia legible: no se cachea", empresa
            )
            return cache
        exp = token_expiry(token)
        recurso_obtenido = {
            "token": token,
            "exp": exp,
            "recursos": [],
            "origen": origen or "desconocido",
            "obtenido": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        for audiencia, recursos in entradas.items():
            empresas = cache.setdefault(audiencia, {})
            recurso_obtenido["recursos"] = recursos
            anterior = empresas.get(empresa)
            exp_anterior = anterior.get("exp") if isinstance(anterior, dict) else None
            if (
                isinstance(exp_anterior, (int, float))
                and isinstance(exp, (int, float))
                and exp_anterior > exp
            ):
                _logger.info(
                    "Caché de tokens: '%s' ya tenía un token más fresco para %s",
                    empresa,
                    audiencia,
                )
                continue
            empresas[empresa] = dict(recurso_obtenido)
        if guardar:
            escribir_cache(ruta, cache)
        return cache


def token_en_cache(
    cache: dict[str, dict[str, dict[str, Any]]],
    empresa: str,
    audience: str,
    recurso: str | None = None,
    margin_seconds: float = 0,
) -> str | None:
    """Token cacheado para esa empresa/audiencia que cubra el recurso, o ``None``.

    Descarta las entradas sin token, caducadas (con el margen) o que no cubren el
    recurso pedido. La caducidad es la **más restrictiva** entre el claim ``exp``
    del propio token y el ``exp`` guardado en la entrada (el que traía el token al
    cachearlo), de modo que una entrada vieja no se reutiliza aunque el token no
    sea un JWT legible.
    """
    entrada = (cache.get(audience) or {}).get(empresa)
    if not isinstance(entrada, dict):
        return None
    token = str(entrada.get("token") or "")
    if not token:
        return None
    exp = token_expiry(token)
    guardada = entrada.get("exp")
    if isinstance(guardada, (int, float)) and not isinstance(guardada, bool):
        exp = float(guardada) if exp is None else min(exp, float(guardada))
    if exp is not None and exp <= time.time() + margin_seconds:
        return None
    if recurso:
        recursos = [str(r) for r in (entrada.get("recursos") or [])]
        if recursos and not any(r.startswith(recurso) for r in recursos):
            return None
        if not token_has_audience(token, audience, recurso):
            return None
    return token


# --- resource ------------------------------------------------------------------


class SireTokenResource(ConfigurableResource):
    """Tokens de SUNAT por empresa, resueltos por audiencia y cacheados en fichero.

    La empresa se pasa por parámetro (``name``), no es campo del recurso, así una
    sola instancia sirve para todas las empresas de ``sire_credentials.json``.
    Cada objeto de credenciales tiene: ``name``, ``ruc``, ``user`` (usuario SOL),
    ``password`` (clave SOL), ``client_id``/``client_secret`` ("Credenciales de
    API SUNAT") y ``sire_scope`` (opcional, scope del token endpoint).
    """

    credentials_path: str = Field(
        default=DEFAULT_CREDENTIALS_PATH,
        description="Ruta al JSON de credenciales de SUNAT (env/sire_credentials.json)",
    )
    tokens_cache_path: str = Field(
        default=DEFAULT_TOKENS_CACHE_PATH,
        description=(
            "Ruta de la caché de tokens (audiencia -> empresa -> token); por defecto "
            "env/sire_tokens.json (junto a las credenciales: todo el estado de SIRE "
            "vive en env/)"
        ),
    )
    security_url_template: str = Field(
        default=SECURITY_TOKEN_URL_TEMPLATE,
        description="Plantilla de la URL OAuth2 de la API de seguridad de SUNAT",
    )
    grant_type: str = Field(
        default=SECURITY_TOKEN_GRANT_TYPE,
        description="grant_type del token endpoint (SUNAT espera 'password')",
    )
    scope: str = Field(
        default=AUDIENCE_SIRE,
        description="scope del token endpoint si la empresa no define 'sire_scope'",
    )
    username_format: str = Field(
        default="{ruc}{user}",
        description=(
            "Formato del usuario SOL del token endpoint ({ruc} y {user}); si no "
            "lleva llaves se usa tal cual"
        ),
    )
    request_timeout_seconds: float = 30
    expiry_margin_seconds: float = Field(
        default=60,
        description="Margen (s) con el que se considera caducado un token",
    )
    default_ttl_seconds: float = Field(
        default=300,
        description="Vigencia de caché para tokens sin exp/expires_in legibles",
    )
    portal_enabled: bool = Field(
        default=True,
        description=(
            "Permite pedir el token al portal SOL por HTTP puro (login + "
            "action=execute) cuando la API de seguridad no cubre la audiencia"
        ),
    )
    app_consultacpe: str = Field(
        default=APP_COMPROBANTES,
        description="Ítem del menú SOL de la app de comprobantes (da el token de consultacpe)",
    )
    comprobar_consultacpe: bool = Field(
        default=True,
        description=(
            "Valida en vivo contra api-cpe el token que devuelve el portal (422/200 "
            "= aceptado, 401/500 = rechazado)"
        ),
    )

    _tokens: dict[str, tuple[str, float]] = PrivateAttr(default_factory=dict)
    _security_tokens: dict[str, tuple[str, float]] = PrivateAttr(default_factory=dict)
    _cache: dict[str, dict[str, dict[str, Any]]] = PrivateAttr(default_factory=dict)
    _cache_mtime: float | None = PrivateAttr(default=None)
    _portal_fallido: set[str] = PrivateAttr(default_factory=set)
    _portal_origen: dict[str, str] = PrivateAttr(default_factory=dict)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _log: Any = PrivateAttr(default=None)

    def setup_for_execution(self, context: InitResourceContext) -> None:
        """Guarda el log manager de Dagster para loguear con ``context.log``."""
        self._log = context.log

    def _info(self, msg: str) -> None:
        log = getattr(self, "_log", None)
        if log is not None:
            log.info(msg)
        else:
            _logger.info(msg)

    # --- credenciales -----------------------------------------------------

    def _load_credentials(self) -> list[dict[str, Any]]:
        with open(self.credentials_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError(
                f"sire_credentials en '{self.credentials_path}' debe ser una lista JSON, "
                f"se encontró {type(data).__name__}"
            )
        return data

    def _credentials(self, name: str) -> dict[str, Any]:
        """Objeto de credenciales de la empresa ``name``."""
        for obj in self._load_credentials():
            if obj.get("name") == name:
                return obj
        raise ValueError(
            f"No existe un objeto de credenciales con name '{name}' "
            f"en '{self.credentials_path}'"
        )

    def companies(self) -> list[str]:
        """Devuelve los ``name`` de todas las empresas del fichero de credenciales."""
        return [str(obj.get("name")) for obj in self._load_credentials() if obj.get("name")]

    def ruc(self, name: str) -> str:
        """Devuelve el campo ``ruc`` del objeto cuyo ``name`` coincide con ``name``."""
        return str(self._credentials(name).get("ruc") or "")

    # --- token ------------------------------------------------------------

    def token(
        self,
        name: str,
        audience: str = AUDIENCE_SIRE,
        recurso: str | None = None,
    ) -> str:
        """Token válido para la empresa ``name``, la ``audience`` y el ``recurso``.

        Orden de resolución: **caché del fichero** → **API de seguridad** → **portal
        SOL por HTTP** (sólo para la audiencia de comprobantes, ``api-cpe``) y, si
        nada sirve, ``SireTokenError`` con los motivos. Cada token obtenido se
        guarda en la caché bajo todas las audiencias que cubre.
        """
        clave = f"{name}|{audience}|{recurso or ''}"
        with self._lock:
            vigente = self._tokens.get(clave)
            if vigente is not None and vigente[1] > time.time():
                return vigente[0]

            cacheado = self._token_de_cache(name, audience, recurso)
            if cacheado:
                self._info(
                    f"[{name}] Token de la caché para {audience}"
                    f"{f' ({recurso})' if recurso else ''}"
                )
                self._tokens[clave] = (cacheado, self._expires_at(cacheado))
                return cacheado

            obj = self._credentials(name)
            motivos: list[str] = []

            de_seguridad = self._security_token(name, obj, motivos)
            if de_seguridad and self._usable(
                name, de_seguridad, audience, recurso, "API de seguridad", motivos
            ):
                self._guardar(name, de_seguridad, "api-seguridad", audience, recurso)
                self._tokens[clave] = (de_seguridad, self._expires_at(de_seguridad))
                return de_seguridad

            del_portal = self._token_del_portal(name, obj, audience, recurso, motivos)
            if del_portal and self._usable(
                name,
                del_portal,
                audience,
                recurso,
                self._portal_origen.get(name, "portal SOL"),
                motivos,
            ):
                self._guardar(
                    name,
                    del_portal,
                    self._portal_origen.get(name, "portal SOL"),
                    audience,
                    recurso,
                )
                self._tokens[clave] = (del_portal, self._expires_at(del_portal))
                return del_portal

            detalle = "; ".join(motivos) or "sin motivos registrados"
            raise SireTokenError(
                f"No hay token válido para '{name}' con audiencia '{audience}'"
                f"{f' y recurso {recurso}' if recurso else ''}: {detalle}. "
                f"Revisa las credenciales ('{self.credentials_path}') y el token "
                f"cacheado en '{self.tokens_cache_path}'."
            )

    def _cache_actual(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Caché de tokens del fichero, releída sólo si cambió en disco.

        Como el resource se consulta **por documento** (miles de veces por mes),
        se guarda el JSON ya parseado y se relee únicamente cuando cambia el
        ``mtime`` (otro proceso o una escritura propia).
        """
        ruta = Path(self.tokens_cache_path)
        try:
            mtime = ruta.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self._cache_mtime:
            self._cache = leer_cache(ruta)
            self._cache_mtime = mtime
        return self._cache

    def _token_de_cache(
        self, name: str, audience: str, recurso: str | None
    ) -> str | None:
        """Token de la empresa/audiencia pedida que cubra ``recurso``, o ``None``."""
        return token_en_cache(
            self._cache_actual(),
            name,
            audience,
            recurso,
            margin_seconds=self.expiry_margin_seconds,
        )

    def _guardar(
        self,
        name: str,
        token: str,
        origen: str,
        audience: str,
        recurso: str | None,
    ) -> None:
        """Escribe el token en la caché (bajo todas las audiencias que cubre)."""
        try:
            guardar_token(
                self.tokens_cache_path,
                name,
                token,
                origen,
                extras=((audience, recurso),),
            )
        except OSError as exc:
            _logger.warning("No se pudo escribir la caché de tokens: %s", exc)
            return
        self._cache_mtime = None  # fuerza la relectura en la próxima consulta

    # --- vías de obtención ------------------------------------------------

    def _security_token(self, name: str, obj: dict[str, Any], motivos: list[str]) -> str:
        """Pide un token a la API de seguridad (o devuelve el cacheado).

        Devuelve ``""`` (anotando el motivo en ``motivos``) cuando la empresa no
        tiene credenciales de API, cuando SUNAT rechaza la petición o cuando no se
        puede contactar; en ese caso el llamador prueba la siguiente vía.
        """
        cacheado = self._security_tokens.get(name)
        if cacheado is not None and cacheado[1] > time.time():
            return cacheado[0]

        client_id = str(obj.get("client_id") or "").strip()
        client_secret = str(obj.get("client_secret") or "").strip()
        usuario = str(obj.get("user") or "").strip()
        password = str(obj.get("password") or "")
        if not (client_id and client_secret and usuario and password):
            motivos.append("API de seguridad: sin client_id/client_secret/user/password")
            return ""

        url = self.security_url_template.format(client_id=client_id)
        body = {
            "grant_type": str(obj.get("grant_type") or self.grant_type),
            "scope": str(obj.get("sire_scope") or self.scope),
            "client_id": client_id,
            "client_secret": client_secret,
            "username": self._username(obj),
            "password": password,
        }
        try:
            response = requests.post(
                url,
                data=body,
                headers={
                    "Content-Type": SECURITY_CONTENT_TYPE,
                    "User-Agent": SECURITY_USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=self.request_timeout_seconds,
            )
        except requests.exceptions.RequestException as exc:
            motivos.append(f"API de seguridad: error de red ({exc})")
            return ""

        if response.status_code == 204:
            # SUNAT devuelve 204 sin body cuando rechaza la petición (p. ej. un
            # grant_type distinto de 'password' o credenciales incorrectas).
            motivos.append(
                "API de seguridad: HTTP 204 sin body (petición rechazada: revisa "
                "grant_type y las credenciales de API SUNAT)"
            )
            return ""
        if response.status_code != 200:
            motivos.append(
                f"API de seguridad: HTTP {response.status_code} ({response.text[:200]!r})"
            )
            return ""
        try:
            payload = response.json()
        except ValueError:
            motivos.append("API de seguridad: la respuesta no es JSON")
            return ""
        token = str(payload.get("access_token") or "")
        if not token:
            motivos.append(
                f"API de seguridad: respuesta sin access_token ({sorted(payload)})"
            )
            return ""

        expires_in = payload.get("expires_in")
        expires_at = self._expires_at(
            token, expires_in if isinstance(expires_in, (int, float)) else None
        )
        self._security_tokens[name] = (token, expires_at)
        self._info(
            f"[{name}] Token de la API de seguridad obtenido "
            f"(caduca en ~{int(expires_at - time.time())}s)"
        )
        return token

    def _token_del_portal(
        self,
        name: str,
        obj: dict[str, Any],
        audience: str,
        recurso: str | None,
        motivos: list[str],
    ) -> str:
        """Token del portal SOL por HTTP puro (login + ``action=execute``).

        Sólo se intenta para la audiencia de comprobantes (``api-cpe``), que es la
        única app del menú verificada. Devuelve ``""`` (anotando el motivo) si el
        portal no lo entrega, si SUNAT ya pide captcha o si api-cpe lo rechaza; el
        intento se memoiza para no repetir el login en el mismo proceso (el asset
        pide el token **por documento** y cada POST fallido suma ``fallas``).
        """
        if audience != AUDIENCE_CPE:
            return ""
        if not self.portal_enabled:
            motivos.append("portal SOL: deshabilitado (portal_enabled=False)")
            return ""
        if name in self._portal_fallido:
            motivos.append("portal SOL: ya se intentó sin éxito en este proceso")
            return ""
        try:
            token, origen = obtener_token_app(obj, self.app_consultacpe)
        except SolPortalError as exc:
            self._portal_fallido.add(name)
            motivos.append(f"portal SOL: {exc}")
            return ""

        if self.comprobar_consultacpe:
            http = probar_consultacpe(token, self.request_timeout_seconds)
            if http in (401, 500):
                self._portal_fallido.add(name)
                motivos.append(
                    f"portal SOL: api-cpe rechazó el token de la app (HTTP {http})"
                )
                return ""
            if http is None:
                self._info(
                    f"[{name}] No se pudo comprobar el token de consultacpe en vivo "
                    "(sin respuesta de api-cpe); se usa igualmente"
                )
        self._portal_origen[name] = origen
        return token

    def _username(self, obj: dict[str, Any]) -> str:
        """Usuario SOL del token endpoint (RUC + usuario por defecto)."""
        if obj.get("username"):
            return str(obj["username"])
        if "{" in self.username_format:
            return self.username_format.format(
                ruc=str(obj.get("ruc") or ""), user=str(obj.get("user") or "")
            )
        return self.username_format

    def _usable(
        self,
        name: str,
        token: str,
        audience: str,
        recurso: str | None,
        etiqueta: str,
        motivos: list[str],
    ) -> bool:
        """Comprueba audiencia y caducidad del token, anotando el motivo si no sirve."""
        if not token:
            motivos.append(f"{etiqueta}: sin token")
            return False
        if not token_has_audience(token, audience, recurso):
            motivos.append(
                f"{etiqueta}: no cubre la audiencia {audience}"
                f"{f' (recurso {recurso})' if recurso else ''}"
            )
            return False
        if token_is_expired(token, self.expiry_margin_seconds):
            motivos.append(f"{etiqueta}: token caducado")
            return False
        self._info(
            f"[{name}] Token de {etiqueta} válido para {audience}"
            f"{f' ({recurso})' if recurso else ''}"
        )
        return True

    def _expires_at(self, token: str, expires_in: float | None = None) -> float:
        """Epoch en el que el token deja de cachearse (con el margen ya descontado).

        Se toma del claim ``exp`` del JWT y, si no se puede leer, de ``expires_in``
        (segundos) o de ``default_ttl_seconds``. Para tokens ya caducados devuelve un
        epoch pasado, de modo que la entrada de caché queda inservible al momento.
        """
        margen = self.expiry_margin_seconds
        exp = token_expiry(token)
        if exp is not None:
            return exp - margen
        if expires_in:
            return time.time() + float(expires_in) - margen
        return time.time() + float(self.default_ttl_seconds)




