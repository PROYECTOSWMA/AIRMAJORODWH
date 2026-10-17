"""Protocolo HTTP del portal SOL de SUNAT: login + apertura de apps del menú.

Es la **vía HTTP pura** (``requests``, sin navegador) que antes vivía en
``scripts/sol_token.py`` y que ahora usan los ``api_resource`` de SIRE cuando el
token de la API de seguridad no cubre la audiencia pedida (caso de
``consultacpe`` para Air Majoro Selva). La vía del navegador headless queda sólo
como plan B documentado en ``docs/sol_token_navegador.py``.

Flujo verificado **en vivo el 2026-09-17**:

1. ``GET MenuInternet.htm`` (anónimo) → su JS redirige a
   ``api-seguridad.sunat.gob.pe/v1/clientessol/{client_id_portal}/oauth2/authen?...``.
   El portal usa **su** ``client_id``.
2. Ese GET acaba en ``.../oauth2/loginMenuSol?...``: la pantalla de login, cuyo
   form ``LoginForm`` hace ``POST j_security_check`` con ``tipo`` (2 = RUC),
   ``j_username`` (usuario SOL), ``custom_ruc`` (RUC), ``j_password`` (clave SOL) y
   ``captcha`` (**vacío** mientras SUNAT no haya contado 3 fallos) más los ocultos
   ``state``/``originalUrl``/``lang`` que el JS copia del query string.
3. Ya autenticado, ``POST MenuInternet.htm {action:'prevApp'}`` +
   ``GET MenuInternet.htm?action=execute&code=<app>`` → el portal responde
   **302** al loader de la app con ``?token=<JWT>``. El intercambio OAuth2 del
   ``code`` **lo hace el servidor del portal**: no hay que canjear nada a mano
   (el canje manual contra ``oauth2/token`` responde ``400 parametros
   invalidos``; por eso se descartó).

**Redes de seguridad** (un login real suma fallos y SUNAT exige captcha a partir
de 3, con riesgo de bloqueo del usuario):

* sin credenciales no se manda nada: primero se recorre el flujo anónimo y se
  pregunta ``action=fails`` (endpoint que **no** autentica);
* si ``fallas >= 3`` se aborta antes de mandar credenciales;
* ``hacer_login`` hace **un único intento y nunca reintenta**.

Interfaz pública: ``descubrir_flujo`` / ``hacer_login`` (login de 1 intento),
``abrir_app`` / ``token_de_apertura`` (el ``action=execute`` que entrega el JWT) y
los atajos ``abrir_sesion`` / ``obtener_token_app``.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import requests

_logger = logging.getLogger(__name__)

# Menú de SUNAT Operaciones en Línea (el portal).
MENU_URL = "https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm"
# Pre-chequeo de fallos del portal (`verificaFails()` del JS): NO autentica y
# responde `{"fallas": "n"}`; a partir de 3 SUNAT exige captcha en el login.
URL_FAILS = "https://e-menu.sunat.gob.pe/cl-ti-itmenu/AutenticaMenuInternetPlataforma.htm"
# Lo que hace el JS del menú al pulsar una app: `action=execute&code=<app>`.
URL_EJECUTE = MENU_URL + "?action=execute&code={app}"
# Base del authorization server (la misma para el menú y para cada app).
SECURITY_BASE = "https://api-seguridad.sunat.gob.pe/v1/clientessol"

# App "Nueva Consulta de comprobantes de pago" (catálogo del menú SOL, entrada
# 11.38.1.1.1). Su host real es **e-factura** y el navegador la abre con el JWT
# en la URL: `...nuevaconsulta.html?token=<JWT>` (capturado el 2026-09-17).
APP_COMPROBANTES = "11.38.1.1.1"
CPE_APP_REDIRECT = (
    "https://e-factura.sunat.gob.pe/app/contribuyentems/servicio/consultacpe/consulta"
    "/loader/nuevaconsulta.html"
)
# `client_id` de la app de comprobantes (el que aparece en el token de la sesión
# SOL de Air Majoro Selva); se usa por defecto si no hay token del que leerlo.
DEFAULT_CPE_APP_CLIENT_ID = "cd8e7afb-a0e2-4217-9187-88206e4ba7af"
# Cliente y redirect del **menú** (su `code` llega en el propio 302 del login).
MENU_CLIENT_ID = "4f3b88b3-d9d6-402a-b85d-6a0bc857746a"
MENU_REDIRECT = URL_FAILS

# El portal corta las peticiones que no parecen de un navegador (curl recibe
# "Connection reset by peer"): con estas cabeceras responde con normalidad.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
}

# tipo de logueo del form: 1 = DNI, 2 = RUC (usuario SOL + clave SOL).
TIPO_LOGUEO_RUC = "2"

RE_AUTHEN = re.compile(r"""redirect\(\s*["']([^"']+)["']\s*\)""")
RE_INPUT = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
RE_ATTR = re.compile(r"""(\w+)\s*=\s*["']([^"']*)["']""")
# `token=` en una URL, en un HTML o dentro de un JS (la app lo recibe así; se
# acepta `%` porque el JWT puede venir percent-encoded y luego se decodifica).
RE_TOKEN_URL = re.compile(r"[?&]token=([A-Za-z0-9._%\-]+)")


class SolPortalError(Exception):
    """No se pudo completar un paso del flujo HTTP del portal SOL."""


def fallas_pendientes(session: requests.Session) -> int | None:
    """Pregunta a SUNAT cuántos fallos lleva el usuario (``action=fails``).

    No autentica: es el mismo endpoint que usa el navegador para decidir si pinta
    el captcha (a partir de 3). Devuelve ``None`` si no se puede averiguar.
    """
    try:
        respuesta = session.post(
            URL_FAILS, data={"action": "fails"}, headers=HEADERS, timeout=30
        )
        return int(str((respuesta.json() or {}).get("fallas")))
    except (ValueError, TypeError, AttributeError, requests.exceptions.RequestException):
        return None


def inputs_del_form(html: str) -> dict[str, str]:
    """Campos del form ``LoginForm`` de la pantalla de login.

    Solo los de ese form (es lo que manda ``document.LoginForm.submit()``); los del
    modal de "recuperar clave" y demás comparten nombres y no deben colarse.
    """
    bloques = re.findall(
        r"<form[^>]*name=[\"']?LoginForm[\"']?[^>]*>(.*?)</form>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    cuerpo = bloques[0] if bloques else html
    campos: dict[str, str] = {}
    for etiqueta in RE_INPUT.findall(cuerpo):
        atributos = dict(RE_ATTR.findall(etiqueta))
        nombre = atributos.get("name")
        if nombre:
            campos[nombre] = atributos.get("value", "")
    return campos


def pagina_login(
    session: requests.Session,
    login_url: str,
    authen_url: str,
    fallas: int | None,
    html: str | None = None,
) -> dict[str, Any]:
    """Devuelve el "flujo" (form + estado) de la pantalla de login.

    Con ``html`` se reutiliza la página ya descargada (``descubrir_flujo`` la tiene
    en la mano) y no se vuelve a pedir; sin él se descarga.
    """
    if html is None:
        html = session.get(login_url, headers=HEADERS, timeout=45).text
    ocultos = inputs_del_form(html)
    consulta = {k: v[0] for k, v in parse_qs(urlparse(login_url).query).items()}
    return {
        "authen_url": authen_url,
        "login_url": login_url,
        "action_login": urljoin(login_url, "j_security_check"),
        "campos_ocultos": ocultos,
        "parametros_login": consulta,
        "fallas": fallas,
    }

def descubrir_flujo(session: requests.Session) -> dict[str, Any]:
    """Recorre el portal hasta la pantalla de login del menú y mira los fallos.

    **No manda credenciales**: solo GETs anónimos y el ``action=fails`` que el
    propio navegador usa para saber si hay que pintar el captcha. Lanza
    ``SolPortalError`` si el portal cambió de flujo o si SUNAT ya tiene >= 3
    fallos (a partir de ahí haría falta captcha y el login automático no es viable).
    """
    menu = session.get(MENU_URL, headers=HEADERS, timeout=30)
    match = RE_AUTHEN.search(menu.text)
    if not match:
        raise SolPortalError(
            "No se encontró el redirect() de OAuth2 en el menú del portal "
            f"(HTTP {menu.status_code})"
        )
    authen_url = match.group(1)

    login = session.get(authen_url, headers=HEADERS, timeout=30)
    if "loginMenuSol" not in login.url:
        raise SolPortalError(
            "El portal no llevó a la pantalla de login (¿cambió el flujo?). "
            f"URL final: {login.url}"
        )

    fallas = fallas_pendientes(session)
    _logger.info("[portal SOL] login: fallas=%s", fallas)
    if isinstance(fallas, int) and fallas >= 3:
        raise SolPortalError(
            "SUNAT tiene >= 3 fallos para este usuario: pedirá captcha y el login "
            "automático no es viable. Entra al portal a mano una vez (eso lo limpia) "
            "y vuelve a intentarlo."
        )
    return pagina_login(session, login.url, authen_url, fallas, html=login.text)


def hacer_login(
    session: requests.Session, flujo: dict[str, Any], empresa: dict[str, Any]
) -> list[str]:
    """POST único a ``j_security_check`` replicando el JS del portal.

    **No reintenta nunca**: cada POST fallido suma en el contador ``fallas`` de
    SUNAT. Devuelve las URLs de la cadena de redirecciones tras el login y lanza
    ``SolPortalError`` si las credenciales no son aceptadas o si faltan.
    """
    usuario = str(empresa.get("user") or "")
    ruc = str(empresa.get("ruc") or "")
    clave = str(empresa.get("password") or "")
    if not (usuario and ruc and clave):
        raise SolPortalError(
            f"'{empresa.get('name')}' no tiene ruc/user/password en el JSON de "
            "credenciales (env/sire_credentials.json)"
        )

    fallas = fallas_pendientes(session)
    if fallas is None:
        fallas = flujo.get("fallas")
    if isinstance(fallas, int) and fallas >= 3:
        raise SolPortalError(
            "SUNAT tiene >= 3 fallos para este usuario: pedirá captcha y el login "
            "automático no es viable. Entra al portal a mano una vez (eso lo limpia) "
            "y vuelve a intentarlo."
        )

    # El JS `url2Fields()` copia del query string al form los campos que existan.
    datos = dict(flujo["campos_ocultos"])
    for nombre, valor in flujo["parametros_login"].items():
        if nombre in datos:
            datos[nombre] = valor
    datos.update(
        {
            "tipo": TIPO_LOGUEO_RUC,  # 2 = RUC + usuario SOL + clave SOL
            "dni": "",
            "custom_ruc": ruc,
            "j_username": usuario,
            "j_password": clave,
            "captcha": "",  # vacío salvo que `fallas >= 3`
        }
    )

    _logger.info(
        "[portal SOL] POST j_security_check: 1 intento (sin reintentos) "
        "[usuario=%s…, ruc=…%s]",
        usuario[:3],
        ruc[-4:],
    )
    respuesta = session.post(
        flujo["action_login"],
        data=datos,
        headers={
            **HEADERS,
            "Referer": flujo["login_url"],
            "Origin": "https://api-seguridad.sunat.gob.pe",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=45,
        allow_redirects=False,
    )
    destino = respuesta.headers.get("location") or ""
    aceptado = respuesta.status_code in (302, 303) and not any(
        marca in destino.lower() for marca in ("loginmenusol", "/oauth2/login")
    )
    if not aceptado:
        raise SolPortalError(
            "El login del portal no fue aceptado (no se reintenta para no sumar "
            f"fallos; HTTP {respuesta.status_code}). Entra a mano si SUNAT pide "
            "captcha y vuelve a intentarlo."
        )

    urls: list[str] = []
    if destino:
        # El 302 apunta al `originalUrl` con el `state`: **hay que seguirlo** para
        # que la sesión quede establecida en el portal.
        app = session.get(destino, headers=HEADERS, timeout=45)
        urls = [historial.url for historial in getattr(app, "history", [])]
        urls.append(getattr(app, "url", "") or destino)
    _logger.info("[portal SOL] login aceptado")
    return urls


def extraer_param(urls: list[str], nombre: str) -> str | None:
    """Devuelve el primer valor de ``nombre`` que aparezca en esas URLs."""
    for url in urls:
        if not url:
            continue
        valores = parse_qs(urlparse(url).query).get(nombre)
        if valores:
            return valores[0]
    return None


def token_en_texto(texto: str) -> str | None:
    """Primer ``token=`` que aparezca en un texto (URL, HTML o JS), ya decodificado."""
    hallado = RE_TOKEN_URL.search(texto or "")
    return unquote(hallado.group(1)) if hallado else None


def url_authen(client_id: str, redirect_uri: str) -> str:
    """URL del authorization endpoint para el ``client_id`` y el ``redirect_uri``."""
    return (
        f"{SECURITY_BASE}/{client_id}/oauth2/authen"
        f"?client_id={client_id}&response_type=code"
        f"&redirect_uri={quote(redirect_uri, safe='')}&state=&lang=es-PE"
    )


def _pedir_app(
    session: requests.Session, app: str, timeout: int
) -> requests.Response:
    """``POST {action:'prevApp'}`` + ``GET action=execute&code=<app>`` (sin seguir 302).

    Es lo que hace el JS del menú al pulsar una app. El POST ``prevApp`` es
    best-effort (si falla se sigue igual).
    """
    try:
        session.post(
            MENU_URL,
            data={"action": "prevApp"},
            headers={
                **HEADERS,
                "Referer": MENU_URL,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        _logger.info(
            "[portal SOL] (el POST prevApp falló: %s; se sigue igual)", str(exc)[:90]
        )
    url = URL_EJECUTE.format(app=quote(app, safe=""))
    return session.get(
        url,
        headers={**HEADERS, "Referer": MENU_URL},
        timeout=timeout,
        allow_redirects=False,
    )


def abrir_app(
    session: requests.Session, app: str = APP_COMPROBANTES, timeout: int = 45
) -> str:
    """Pide al menú abrir la app y devuelve la URL del 302 al loader de la app.

    Lanza ``SolPortalError`` si el portal no abre la app (sesión caducada, cambio
    de menú o app no disponible para el usuario).
    """
    respuesta = _pedir_app(session, app, timeout)
    destino = respuesta.headers.get("location") or ""
    if respuesta.status_code not in (301, 302, 303) or not destino:
        raise SolPortalError(
            f"El portal no abrió la app {app} (HTTP {respuesta.status_code}, "
            f"location={destino!r}). ¿Caducó la sesión o cambió el menú?"
        )
    return destino


def token_de_apertura(
    session: requests.Session, app: str = APP_COMPROBANTES, timeout: int = 45
) -> tuple[str, str] | None:
    """Pide al menú abrir la app y devuelve ``(token, de_dónde)``.

    El JWT llega en la cabecera ``Location`` del 302 (lo pone el **servidor** del
    portal). Si no viniera ahí, se sigue la cadena de redirecciones y se busca el
    token en las URLs y en el HTML. Devuelve ``None`` si la app no dejó el token.
    """
    respuesta = _pedir_app(session, app, timeout)
    destino = respuesta.headers.get("location") or ""
    token = extraer_param([destino], "token") or token_en_texto(destino)
    if token:
        return token, f"Location del portal ({destino.split('?')[0][:70]})"

    _logger.info(
        "[portal SOL] HTTP %s y sin `token` en el Location (%s): se sigue la cadena",
        respuesta.status_code,
        destino.split("?")[0][:70] or "sin location",
    )
    url = URL_EJECUTE.format(app=quote(app, safe=""))
    seguida = session.get(url, headers={**HEADERS, "Referer": MENU_URL}, timeout=timeout)
    urls = [historial.url for historial in getattr(seguida, "history", [])]
    urls.append(getattr(seguida, "url", "") or url)
    token = extraer_param(urls, "token") or token_en_texto(seguida.text)
    if token:
        return token, "cadena de redirecciones del portal"
    _logger.info(
        "[portal SOL] la app no dejó el token (HTTP %s; %s)",
        seguida.status_code,
        (getattr(seguida, "url", "") or url).split("?")[0][:90],
    )
    return None


def abrir_sesion(empresa: dict[str, Any]) -> requests.Session:
    """Sesión logueada en el portal y lista para las apps del menú.

    ``empresa`` es el objeto de credenciales (``name``/``ruc``/``user``/
    ``password``). Hace el login (**1 intento, sin reintentos**) y deja la sesión
    en el menú real, que es lo que necesita ``action=execute``.
    """
    session = requests.Session()
    flujo = descubrir_flujo(session)
    hacer_login(session, flujo, empresa)
    session.get(MENU_URL, headers=HEADERS, timeout=45)
    return session


def obtener_token_app(
    empresa: dict[str, Any],
    app: str = APP_COMPROBANTES,
    session: requests.Session | None = None,
) -> tuple[str, str]:
    """Token de la app del menú, **sin navegador**: ``(token, de_dónde)``.

    Hace el login (si no se pasa una sesión ya logueada) y pide la apertura de la
    app; el JWT lo entrega el servidor del portal en el 302 del ``action=execute``.
    Lanza ``SolPortalError`` si el portal no lo devuelve.
    """
    session = session or abrir_sesion(empresa)
    _logger.info("[portal SOL] apertura de la app %s (prevApp + action=execute)", app)
    hallado = token_de_apertura(session, app)
    if not hallado:
        raise SolPortalError(
            f"El portal no devolvió el token de la app {app}. Si el flujo del portal "
            "cambió, usa el plan B (navegador headless) documentado en "
            "docs/sol_token_navegador.py."
        )
    token, de_donde = hallado
    _logger.info("[portal SOL] token de la app %s recibido en %s", app, de_donde)
    return token, f"portal SOL ({de_donde})"

