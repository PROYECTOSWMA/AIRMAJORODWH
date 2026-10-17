#!/usr/bin/env python
"""PLAN B (documentado) del token de `consultacpe`: navegador real (Firefox headless).

**Este script NO es la vía del pipeline.** El token se obtiene automáticamente en
los assets: ``assets/sire_assets/resources/token_resource.py``
(``SireTokenResource``) resuelve la audiencia primero contra la **API de
seguridad** de SUNAT y, si no concede ``consultacpe``, contra el **portal SOL por
HTTP puro** (``assets/sire_assets/resources/sol_portal.py``: login de 1 intento +
``action=execute``), y cachea el token en ``env/sire_tokens.json``. Este fichero
se guarda en ``docs/`` como **plan B** por si algún día cambia el flujo del portal
y la vía HTTP dejara de funcionar.

**Por qué existe**: si el portal dejara de devolver el JWT en el 302 del
``action=execute``, la alternativa es un navegador de verdad, porque el token
también vive en la URL de la app
(``.../consultacpe/consulta/loader/nuevaconsulta.html?token=<JWT>``) y en la
``sessionStorage`` de la página, y eso solo lo ve un navegador ejecutando el JS
del portal:

1. abre Firefox con **geckodriver** (Selenium) en modo ``-headless``;
2. hace **el login en el navegador** (1 intento; aborta si SUNAT ya pide captcha,
   ``fallas >= 3``);
3. pide al menú la app ``11.38.1.1.1`` ("Nueva Consulta de comprobantes de pago")
   con ``MenuInternet.htm?action=execute&code=...``;
4. busca el JWT en la URL (``?token=``) y en la ``sessionStorage`` de cada ventana
   y marco, lo **valida** (JWT legible + audiencia ``consultacpe`` + caducidad +
   llamada real a api-cpe) y lo **deja en la misma caché** que usa el resource
   (``env/sire_tokens.json``, bajo todas las audiencias que cubre), de modo que
   el pipeline lo reutiliza sin volver a pedirlo.

**Servidor Linux (sin escritorio)**: necesita ``selenium`` (en
``requirements.txt``, comentado como sólo-plan-B), ``firefox`` y ``geckodriver``
visibles para el usuario que ejecuta el script (``GECKODRIVER`` / ``FIREFOX_BIN``
o ``--driver`` / ``--binario`` permiten fijarlos a mano). El perfil de Firefox va
a ``logs/ff_perfil`` (**nunca** a ``/tmp``: si Firefox y geckodriver son snaps, su
``/tmp`` es privado y no ven el del host). Consumo: un proceso Firefox (~300 MB)
durante unos segundos, así que conviene lanzarlo solo cuando el token vaya a
caducar (el token dura 1 hora), no cada minuto.

Uso (desde la raíz del repo):
    python docs/sol_token_navegador.py --dry-run
    python docs/sol_token_navegador.py --empresa "Air Majoro Selva"
    python docs/sol_token_navegador.py --empresa "Air Majoro Selva" --sin-guardar
    python docs/sol_token_navegador.py --login --visible    # mirando, para depurar
"""


from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]  # el script vive en `docs/` del repo
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import requests  # noqa: E402
from assets.sire_assets.resources import sol_portal  # noqa: E402
from assets.sire_assets.resources.token_resource import (  # noqa: E402
    AUDIENCE_CPE,
    DEFAULT_CREDENTIALS_PATH,
    DEFAULT_TOKENS_CACHE_PATH,
    RECURSO_CONSULTACPE,
    decode_jwt_claims,
    guardar_token,
    probar_consultacpe,
    token_expiry,
    token_has_audience,
)

# Rutas: la caché de tokens es la MISMA que usa el resource del pipeline, así el
# token que consiga este plan B lo reutilizan los assets sin volver a pedirlo.
CREDENTIALS_PATH = Path(DEFAULT_CREDENTIALS_PATH)
TOKENS_CACHE_PATH = Path(DEFAULT_TOKENS_CACHE_PATH)
SESION_PATH = REPO / "logs" / "sol_sesion.json"

# Item del menú SOL (pestaña 11 → "Comprobantes de Pago" → "Nueva Consulta de
# comprobantes de pago"): es la app que el portal abre con el JWT en la URL.
APP_COMPROBANTES = sol_portal.APP_COMPROBANTES
MENU_HOST = "https://e-menu.sunat.gob.pe/cl-ti-itmenu"
MENU_URL = sol_portal.MENU_URL
URL_EJECUTE = MENU_HOST + "/MenuInternet.htm?action=execute&code={app}"
# Página estática del propio e-menu: sirve de "ancla" para inyectar cookies sin
# disparar el JS que salta a api-seguridad ni reglas del WAF por pedir un directorio.
ANCLA_COOKIES = "https://e-menu.sunat.gob.pe/a/imagenes/loading.gif"
PERFIL_POR_DEFECTO = REPO / "logs" / "ff_perfil"
SALIDA_POR_DEFECTO = REPO / "logs" / "sol_explore"
GECKODRIVER_CANDIDATOS = (
    "/snap/bin/geckodriver",
    "/usr/local/bin/geckodriver",
    "/usr/bin/geckodriver",
)
# JS del portal: `login()` es lo que ejecuta el botón `#btnAceptar` (copia los
# campos visibles a los ocultos del LoginForm y hace submit). Se usa como respaldo.
JS_LOGIN = "if (typeof login === 'function') { login(); return true; } return false;"
# JS del portal: `sessionStorage["SUNAT.token"]` es donde la app guarda el JWT.
JS_TOKEN_SESION = (
    "return (window.sessionStorage ? "
    "window.sessionStorage.getItem('SUNAT.token') : null) || null;"
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _importar_selenium() -> None:
    try:
        import selenium  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise SystemExit(
            "Falta selenium en este entorno. Instálalo con:\n"
            "    .venv/bin/python -m pip install selenium\n"
            "y en el servidor ten disponibles firefox y geckodriver (ver README)."
        ) from exc


def _primera_ruta(rutas: tuple[str | None, ...]) -> str | None:
    """Primera ruta que existe (para geckodriver/firefox sin depender del PATH)."""
    for ruta in rutas:
        if ruta and Path(ruta).exists():
            return ruta
    return None


def crear_driver(args: argparse.Namespace) -> Any:
    """Arranca Firefox (headless salvo `--visible`) con el perfil del repo."""
    _importar_selenium()
    from selenium import webdriver
    from selenium.webdriver.firefox.options import Options
    from selenium.webdriver.firefox.service import Service

    perfil = Path(args.perfil).expanduser().resolve()
    perfil.mkdir(parents=True, exist_ok=True)

    opciones = Options()
    if not args.visible:
        opciones.add_argument("-headless")
    # El perfil va en una ruta real del usuario, no en /tmp (ver docstring).
    opciones.add_argument("-profile")
    opciones.add_argument(str(perfil))
    # El menú abre la app en una ventana nueva: sin esto Firefox la bloquea.
    opciones.set_preference("dom.disable_open_during_load", False)
    opciones.set_preference(
        "dom.popup_allowed_events", "click dblclick mousedown pointerdown"
    )
    opciones.set_preference("browser.startup.homepage", "about:blank")

    binario = args.binario or os.environ.get("FIREFOX_BIN")
    if binario:
        opciones.binary_location = binario

    ruta_driver = (
        args.driver
        or os.environ.get("GECKODRIVER")
        or shutil.which("geckodriver")
        or _primera_ruta(GECKODRIVER_CANDIDATOS)
    )
    servicio = Service(executable_path=ruta_driver) if ruta_driver else None

    _log(f"[navegador] perfil     : {perfil}")
    _log(
        "[navegador] firefox    : "
        f"{binario or '(lo localiza geckodriver por su cuenta)'}"
    )
    _log(f"[navegador] geckodriver: {ruta_driver or '(lo busca Selenium Manager)'}")
    inicio = time.time()
    driver = (
        webdriver.Firefox(options=opciones, service=servicio)
        if servicio
        else webdriver.Firefox(options=opciones)
    )
    _log(
        "[navegador] listo: "
        f"{driver.capabilities.get('browserName')} "
        f"{driver.capabilities.get('browserVersion')} en {time.time() - inicio:.1f}s"
    )
    driver.set_page_load_timeout(90)
    return driver


def guardar_vista(driver: Any, salida: Path, nombre: str) -> None:
    """Deja HTML + captura de lo que se está viendo (para depurar en el servidor)."""
    try:
        salida.mkdir(parents=True, exist_ok=True)
        (salida / f"navegador_{nombre}.html").write_text(
            driver.page_source, encoding="utf-8", errors="replace"
        )
        driver.save_screenshot(str(salida / f"navegador_{nombre}.png"))
        _log(f"    (vista en {salida}/navegador_{nombre}.html|.png)")
    except Exception as exc:  # noqa: BLE001 - nunca debe tumbar el flujo
        _log(f"    (no se pudo guardar la vista: {str(exc)[:120]})")


def _token_en_contexto(driver: Any, contexto: str) -> tuple[str, str] | None:
    """Mira en el contexto actual (ventana o marco): URL y ``sessionStorage``."""
    try:
        url = driver.execute_script("return window.location.href;")
    except Exception:  # noqa: BLE001 - marco de otro origen sin permiso
        url = driver.current_url
    url = url or driver.current_url or ""
    token = sol_portal.extraer_param([url], "token")
    if token:
        return token, f"{contexto}: {url.split('?')[0][:70]}"
    try:
        valor = driver.execute_script(JS_TOKEN_SESION)
    except Exception:  # noqa: BLE001
        valor = None
    return (valor, f"{contexto}: sessionStorage['SUNAT.token']") if valor else None


def token_en_navegador(driver: Any) -> tuple[str, str] | None:
    """Busca YA un token no vacío en cada ventana y en los iframes del menú.

    El token de la app de comprobantes aparece en la URL (``?token=``) cuando el
    portal la abre y en ``sessionStorage['SUNAT.token']`` después: se miran las dos
    cosas en **todas** las ventanas (la app se abre en una ventana nueva) y en los
    iframes del menú (``iframeApplication``).
    """
    from selenium.webdriver.common.by import By

    for handle in list(driver.window_handles):
        try:
            driver.switch_to.window(handle)
        except Exception:  # noqa: BLE001 - la ventana se cerró entre medias
            continue
        indice = list(driver.window_handles).index(handle)
        hallado = _token_en_contexto(driver, f"ventana {indice}")
        if hallado:
            return hallado
        for numero, marco in enumerate(driver.find_elements(By.TAG_NAME, "iframe")):
            try:
                driver.switch_to.frame(marco)
            except Exception:  # noqa: BLE001
                driver.switch_to.default_content()
                continue
            try:
                hallado = _token_en_contexto(driver, f"ventana {indice}, iframe {numero}")
            finally:
                driver.switch_to.default_content()
            if hallado:
                return hallado
    return None


def esperar_token(driver: Any, segundos: float, intervalo: float = 1.0) -> tuple[str, str] | None:
    """Espera a que el portal abra la app y deje el JWT a la vista."""
    fin = time.time() + segundos
    while True:
        hallado = token_en_navegador(driver)
        if hallado:
            return hallado
        if time.time() >= fin:
            return None
        time.sleep(intervalo)


# --- entrada al portal: cookies de la sesión guardada o login en el navegador --


def sesion_guardada() -> dict[str, Any] | None:
    """Cookies de una sesión guardada a mano en ``logs/sol_sesion.json`` (opcional).

    Ya no lo genera nadie (el login por HTTP vive en ``sol_portal``); solo se
    intenta si el usuario lo ha creado él mismo.
    """
    ruta = SESION_PATH
    if not ruta.exists():
        return None
    edad = time.time() - ruta.stat().st_mtime
    _log(f"[sesión] {ruta.name}: {int(edad / 60)} min de antigüedad")
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log(f"[sesión] no se pudo leer {ruta}: {str(exc)[:100]}")
        return None


def inyectar_cookies(driver: Any, datos: dict[str, Any]) -> int:
    """Mete en el navegador las cookies de la sesión guardada (sin mandar claves).

    **Ojo**: el portal está detrás de un WAF (F5) cuyas cookies (``TS*``,
    ``dtCookie``) van ligadas al cliente que las obtuvo, así que SUNAT puede
    contestar ``Request Rejected`` al inyectarlas en Firefox. Esta vía es un atajo
    best-effort: si falla, **el camino bueno es el login en el navegador** (que es
    lo que hace el script cuando no se pasa ``--cookies``).
    """
    cookies = datos.get("cookies") or {}
    if not cookies:
        raise SystemExit("La sesión guardada no tiene cookies (fichero opcional)")
    # Hay que estar en el dominio antes de add_cookie, en una URL que no redirija
    # (con MenuInternet.htm el JS saltaría a api-seguridad y la cookie acabaría en
    # el dominio equivocado).
    driver.get(ANCLA_COOKIES)
    puestas = 0
    for nombre, valor in cookies.items():
        try:
            driver.add_cookie({"name": nombre, "value": valor})
            puestas += 1
        except Exception as exc:  # noqa: BLE001
            _log(f"    (cookie {nombre} no aceptada: {str(exc)[:90]})")
    _log(
        f"[sesión] {puestas}/{len(cookies)} cookies de '{datos.get('empresa')}' inyectadas"
    )
    return puestas


def estado_del_portal(driver: Any) -> str:
    """``'login'`` (pide credenciales), ``'menu'`` (ya dentro) o ``'cargando'``."""
    from selenium.webdriver.common.by import By

    try:
        if driver.find_elements(By.ID, "txtRuc"):
            return "login"
        if driver.find_elements(By.ID, "divContainerMenu"):
            return "menu"
    except Exception:  # noqa: BLE001
        return "cargando"
    return "cargando"


def abrir_portal(driver: Any, timeout: float, salida: Path) -> str:
    """GET del menú y espera a ver si pide login o si ya hay sesión."""
    driver.get(MENU_URL)
    fin = time.time() + timeout
    while time.time() < fin:
        hallado = estado_del_portal(driver)
        if hallado != "cargando":
            _log(f"[portal] estado: {hallado} ({driver.current_url.split('?')[0][:95]})")
            return hallado
        time.sleep(0.5)
    _log(f"[portal] título: {driver.title!r}; {len(driver.page_source)} bytes")
    guardar_vista(driver, salida, "portal_sin_estado")
    raise SystemExit(
        f"El portal no mostró ni login ni menú en {int(timeout)}s "
        f"(URL: {driver.current_url.split('?')[0][:120]})"
    )


def login_en_navegador(
    driver: Any, empresa: dict[str, Any], timeout: float, salida: Path
) -> str:
    """Login real en el navegador (1 intento, sin reintentos).

    Rellena los campos **visibles** del portal (``#txtRuc``, ``#txtUsuario``,
    ``#txtContrasena``) y **pulsa ``#btnAceptar``**: el JS del portal (``login()``)
    copia esos valores a los ocultos (``tipo=2``, ``custom_ruc``, ``j_username``,
    ``j_password``) y hace ``document.LoginForm.submit()``. Si el botón no dispara
    nada o no se puede pulsar, se llama al ``login()`` del portal por JS.
    Devuelve el estado tras el envío: ``'menu'`` o ``'error'``.
    """
    from selenium.webdriver.common.by import By

    usuario = str(empresa.get("user") or "")
    ruc = str(empresa.get("ruc") or "")
    clave = str(empresa.get("password") or "")
    if not (usuario and ruc and clave):
        raise SystemExit(
            f"'{empresa.get('name')}' no tiene ruc/user/password en "
            f"{CREDENTIALS_PATH}"
        )

    _log(
        "[login] 1 intento con las credenciales SOL "
        f"[usuario={usuario[:3]}…, ruc=…{ruc[-4:]}, clave={'·' * 6}, captcha vacío]"
    )
    # El portal tiene dos modos (RUC/DNI): el botón fija `tipoLogueo=2` (RUC).
    try:
        driver.find_element(By.ID, "btnPorRuc").click()
    except Exception as exc:  # noqa: BLE001
        _log(f"    (no se pudo pulsar #btnPorRuc: {str(exc)[:90]})")
    for identificador, valor in (
        ("txtRuc", ruc),
        ("txtUsuario", usuario),
        ("txtContrasena", clave),
    ):
        elemento = driver.find_element(By.ID, identificador)
        elemento.clear()
        elemento.send_keys(valor)
    try:
        driver.find_element(By.ID, "btnAceptar").click()
        _log("[login] #btnAceptar pulsado (su JS rellena el form y lo envía)")
    except Exception as exc:  # noqa: BLE001
        _log(f"    (no se pudo pulsar #btnAceptar: {str(exc)[:90]}; se llama a login())")
        driver.execute_script(JS_LOGIN)

    inicio = time.time()
    fin = inicio + timeout
    respaldo = False
    while time.time() < fin:
        if driver.find_elements(By.ID, "divContainerMenu"):
            _log("[login] OK: credenciales aceptadas y menú cargado")
            return "menu"
        mensajes = [
            e.text.strip()
            for e in driver.find_elements(By.CSS_SELECTOR, "#spanMensajeError")
            if e.is_displayed() and (e.text or "").strip()
        ]
        if mensajes:
            _log(f"[login] FALLO: el portal dice «{mensajes[0][:180]}» (no se reintenta)")
            guardar_vista(driver, salida, "login_error")
            return "error"
        # Si a los 10 s el envío no ha ocurrido (los ocultos siguen vacíos), el clic
        # no llegó a disparar el handler: se llama al `login()` del portal por JS.
        if not respaldo and time.time() - inicio > 10:
            ocultos = driver.find_elements(By.ID, "j_username")
            if ocultos and not (ocultos[0].get_attribute("value") or ""):
                _log("[login] el form seguía sin enviarse: se llama a login() por JS")
                driver.execute_script(JS_LOGIN)
            respaldo = True
        time.sleep(0.5)
    _log(
        f"[login] FALLO: ni menú ni error en {int(timeout)}s "
        f"(URL: {driver.current_url.split('?')[0][:110]})"
    )
    guardar_vista(driver, salida, "login_sin_menu")
    return "error"


# --- abrir la app de comprobantes (el paso que solo hace el JS del portal) -----


def _trigger_ejecuta(driver: Any, app: str) -> bool:
    """Llama al ``ejecuta(...)`` del menú, igual que el ``onclick`` de sus accesos."""
    return bool(
        driver.execute_script(
            "if (typeof ejecuta !== 'function') { return false; }"
            "ejecuta(arguments[0], false, arguments[1], arguments[2], arguments[3]);"
            "return true;",
            f"MenuInternet.htm?action=execute&code={app}",
            "Consulta de comprobantes de pago",
            f"#nivel1_{app.split('.')[0]}",
            app,
        )
    )


def _clic_item(driver: Any, app: str) -> bool:
    """Clic (por JS) en el ítem del menú, buscándolo por su ``data-id``."""
    return bool(
        driver.execute_script(
            "var e = document.querySelector('[data-id=\"' + arguments[0] + '\"]');"
            "if (!e) { return false; } e.click(); return true;",
            app,
        )
    )


def pedir_app(driver: Any, app: str, timeout: float, salida: Path) -> tuple[str, str] | None:
    """Pide al portal que abra la app de comprobantes y espera el JWT.

    Prueba tres vías (la primera es la que usa el propio menú): el ``ejecuta(...)``
    del menú, la navegación directa a ``MenuInternet.htm?action=execute&code=`` y el
    clic en el ítem. Devuelve ``(token, de_dónde)`` o ``None``.
    """
    intentos: list[tuple[str, Any]] = [
        ("JS del menú (ejecuta)", lambda: _trigger_ejecuta(driver, app)),
        (
            "navegación directa a action=execute",
            lambda: driver.get(URL_EJECUTE.format(app=app)) or True,
        ),
        ("clic en el ítem del menú (data-id)", lambda: _clic_item(driver, app)),
    ]
    for descripcion, accion in intentos:
        _log(f"[app] {descripcion}")
        try:
            disparado = accion()
        except Exception as exc:  # noqa: BLE001
            _log(f"      no se pudo: {str(exc).splitlines()[0][:130]}")
            continue
        if not disparado:
            _log("      esa vía no está disponible en esta página")
            continue
        hallado = esperar_token(driver, timeout)
        if hallado:
            return hallado
        _log(f"      sin token en {int(timeout)}s")
        guardar_vista(driver, salida, "app_sin_token")
    return None


# --- validación + guardado (misma caché que usa el resource del pipeline) ------


def cargar_empresas() -> list[dict[str, Any]]:
    """Objetos de credenciales de ``env/sire_credentials.json``."""
    return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))


def buscar_empresa(nombre: str | None) -> dict[str, Any]:
    """El objeto de credenciales de ``nombre`` (o el primero si no se indica)."""
    empresas = cargar_empresas()
    if nombre is None:
        return empresas[0]
    for empresa in empresas:
        if empresa.get("name") == nombre:
            return empresa
    raise SystemExit(
        f"No existe '{nombre}'. Empresas: {[e.get('name') for e in empresas]}"
    )


def validar_y_guardar(token: str, empresa: dict[str, Any], guardar: bool = True) -> int:
    """Valida el token y lo deja en ``env/sire_tokens.json`` (caché del pipeline).

    Usa la **misma** validación que el resource de los assets (JWT legible,
    audiencia ``consultacpe``, caducidad y una llamada real a api-cpe) y el mismo
    ``guardar_token`` (que escribe el token bajo **todas** las audiencias que
    cubre), de modo que los assets lo reutilizan sin volver a pedirlo.
    """
    claims = decode_jwt_claims(token)
    exp = token_expiry(token)
    if claims is None:
        raise SystemExit("Lo que devolvió el navegador no es un JWT legible")
    _log(
        f"[validación] sub={claims.get('sub')} clientId={claims.get('clientId')} "
        f"cubre consultacpe={token_has_audience(token, AUDIENCE_CPE, RECURSO_CONSULTACPE)} "
        f"caduca en {int(exp - time.time()) if exp else '?'}s"
    )
    if not token_has_audience(token, AUDIENCE_CPE, RECURSO_CONSULTACPE):
        raise SystemExit("Ese token no cubre /v1/contribuyente/consultacpe")
    if exp is None or exp <= time.time():
        raise SystemExit("Ese token ya está caducado")
    http = probar_consultacpe(token)
    _log(f"[validación] comprobación en vivo en api-cpe -> HTTP {http}")
    if http not in (200, 422):
        raise SystemExit("api-cpe no acepta ese token (401/500)")
    if not guardar:
        _log("  (no se escribe la caché: solo se ha validado)")
        return 0
    guardar_token(
        TOKENS_CACHE_PATH,
        str(empresa.get("name")),
        token,
        "navegador (plan B)",
        extras=((AUDIENCE_CPE, RECURSO_CONSULTACPE),),
    )
    _log(f"[validación] token guardado en {TOKENS_CACHE_PATH}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--empresa", help="name de la empresa en sire_credentials.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="abre el navegador y llega a la pantalla de login SIN mandar credenciales",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="hace el login en el navegador (1 intento) en vez de reutilizar la sesión",
    )
    parser.add_argument(
        "--cookies",
        action="store_true",
        help=(
            "intenta reutilizar la sesión de logs/sol_sesion.json en vez de loguearse "
            "(SUNAT suele rechazarla por su WAF; es un atajo best-effort)"
        ),
    )
    parser.add_argument("--visible", action="store_true", help="ventana visible (depurar)")
    parser.add_argument("--perfil", default=str(PERFIL_POR_DEFECTO), help="perfil de Firefox")
    parser.add_argument(
        "--binario",
        help=(
            "ruta al ejecutable REAL de firefox (o FIREFOX_BIN); solo si geckodriver "
            "no lo encuentra (el wrapper /usr/bin/firefox de snap NO vale)"
        ),
    )
    parser.add_argument("--driver", help="ruta a geckodriver (o la variable GECKODRIVER)")
    parser.add_argument(
        "--espera", type=float, default=60.0, help="segundos de espera (60 por defecto)"
    )
    parser.add_argument(
        "--app", default=APP_COMPROBANTES, help="ítem del menú SOL a abrir (11.38.1.1.1)"
    )
    parser.add_argument(
        "--sin-guardar", action="store_true", help="valida el token pero no escribe el fichero"
    )
    parser.add_argument(
        "--html", default=str(SALIDA_POR_DEFECTO), help="carpeta de volcados de depuración"
    )
    args = parser.parse_args()

    if args.login and args.cookies:
        raise SystemExit("--login y --cookies son excluyentes: elige una vía")
    if not args.visible:
        _log(
            "[aviso] Firefox en headless: si SUNAT pide captcha (fallas >= 3) esta vía "
            "no sirve; el script lo comprueba antes de mandar nada."
        )
    salida = Path(args.html).expanduser().resolve()
    driver = crear_driver(args)
    try:
        # 1) fallos del usuario: mismo endpoint que usa el navegador (no autentica).
        fallas = sol_portal.fallas_pendientes(requests.Session())
        _log(f"[portal] fallas del usuario: {fallas}")
        if isinstance(fallas, int) and fallas >= 3 and not (args.cookies or args.dry_run):
            raise SystemExit(
                "SUNAT tiene >= 3 fallos para este usuario: pedirá captcha. "
                "Entra al portal a mano una vez (eso lo limpia) y vuelve a intentarlo."
            )

        # 2) entrada al portal: por defecto **el login lo hace el navegador** (es la
        #    vía fiable). Con --cookies se intenta reutilizar una sesión guardada a
        #    mano en `logs/sol_sesion.json` (ya no la genera nadie: el login por
        #    HTTP vive en `assets/.../sol_portal.py`), cosa que el WAF de SUNAT a
        #    veces rechaza (ver `inyectar_cookies`).
        if args.cookies and not args.dry_run:
            datos = sesion_guardada()
            if not datos:
                raise SystemExit(
                    "No hay sesión reutilizable en "
                    f"{SESION_PATH} o quita --cookies (así el login lo hace el "
                    "navegador)."
                )
            inyectar_cookies(driver, datos)

        estado = abrir_portal(driver, args.espera, salida)

        if args.dry_run:
            _log(f"[dry-run] ni una credencial enviada; estado del portal: {estado}")
            guardar_vista(driver, salida, "dry_run")
            return 0

        empresa = buscar_empresa(args.empresa)
        _log(f"\nEmpresa: {empresa.get('name')} (ruc …{str(empresa.get('ruc'))[-4:]})")

        if estado != "menu":
            if args.cookies:
                raise SystemExit(
                    "Las cookies guardadas ya no valen (el portal pide login): quita "
                    "--cookies y el login lo hará el navegador."
                )
            if login_en_navegador(driver, empresa, args.espera, salida) != "menu":
                return 1

        # 3) abrir la app de comprobantes y leer el JWT que deja el JS del portal.
        hallado = pedir_app(driver, args.app, args.espera, salida)
        if not hallado:
            guardar_vista(driver, salida, "sin_token")
            raise SystemExit(
                "El portal no dejó el token a la vista (ni en la URL ni en "
                f"sessionStorage). Revisa los volcados en {salida}/navegador_*.html|.png: "
                "puede ser un cambio del portal o que la app no esté disponible para "
                "este usuario."
            )
        token, de_donde = hallado
        _log(f"[token] encontrado en {de_donde}")
        return validar_y_guardar(token, empresa, guardar=not args.sin_guardar)
    finally:
        try:
            driver.quit()
            _log("[navegador] cerrado")
        except Exception as exc:  # noqa: BLE001
            _log(f"[navegador] (no se pudo cerrar limpio: {str(exc)[:90]})")


if __name__ == "__main__":
    raise SystemExit(main())
