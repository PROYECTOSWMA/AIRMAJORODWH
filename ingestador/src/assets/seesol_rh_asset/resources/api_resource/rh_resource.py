"""Resource HTTP del reporte RH (recibos por honorarios) del SEE-SOL de SUNAT.

Es la vía HTTP que antes vivía en ``scripts/sol_rh_seesol.py`` (script eliminado):
con **HTTP puro** (``requests``, sin navegador) se baja el ``archivo.txt`` de 16
columnas que publica la app **"Consulta Receptor"** del SEE. El flujo está
verificado **en vivo el 2026-09-17** (el archivo es byte a byte el mismo que se
descargaba a mano):

1. **login del portal** (lo aporta ``assets/sire_assets/resources/sol_portal.py``;
   antes lo hacía el script ``sol_token.py``): ``GET`` del
   menú → el JS redirige a la pantalla de login de OAuth2 → ``POST
   j_security_check`` con RUC/usuario SOL/clave SOL (**1 intento, sin
   reintentos**) → se sigue el 302 que deja la sesión establecida.
2. ``POST MenuInternet.htm {action:'prevApp'}`` + ``GET
   MenuInternet.htm?action=execute&code=11.5.1.1.14`` → **302** a la app
   "Consulta Receptor" en ``https://ww1.sunat.gob.pe/ol-ti-itreciboelectronico/
   cpelec001Alias?accion=LlamaCriterioConsulatRec1...``.
3. ``POST cpelec001Alias`` con ``accion=CapturaCriterioConsulatRec1``,
   ``fec_desde``/``fec_hasta`` (**dd/mm/YYYY**, rango ≤ 1 mes), ``tipocomprobante``
   = ``"01;02;03;"`` y ``tipoestado=00`` → página de resultados.
4. ``POST cpelec001Alias`` con ``accion=descargaConsultaReceptor`` (el "Descargar
   Reporte") → ``text/plain``, ``Content-Disposition: attachment;
   filename="archivo.txt"`` con el reporte.

**Trampa del POST de criterios**: el campo **oculto** ``tipocomprobante`` debe ir
como ``"01;02;03;"`` (tipos concatenados con ``;`` final, lo que arma el JS del
formulario desde sus 3 checkboxes). Mandarlo vacío hace que SUNAT conteste *"No se
han encontrado registros"* aunque el mes sí tenga recibos.

**Redes de seguridad**: el login real suma fallos y SUNAT exige captcha a partir
de 3 (con riesgo de bloqueo del usuario), así que se pregunta ``action=fails``
antes de mandar credenciales y **se aborta si ``fallas >= 3``**; con el login se
hace **un único intento y no se reintenta**. El rango no puede pasar de un mes
(``MAX_DIAS``), de ahí que el asset trabaje por meses.

La interfaz del resource es:

* ``get_month(company, period) -> list[dict]`` — filas del mes, ya parseadas y con
  su ``period`` estampado (el ``empresa`` lo pone el asset);
* ``fetch_report(company, period) -> str`` — el texto crudo del portal (útil para
  depurar o volcar el reporte a disco).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from dagster import ConfigurableResource
from pydantic import Field

from assets.seesol_rh_asset.parsers.rh import parse_rh_text
from assets.seesol_rh_asset.resources.api_resource.constants import (
    ACCION_CRITERIO,
    ACCION_DESCARGA,
    APP_RECEPTOR,
    CABECERA_REPORTE,
    ESTADO_TODOS,
    FORM_PATH,
    MAX_DIAS,
    SIN_REGISTROS,
    TIPOS_DOC,
)
# El protocolo del portal (login de 1 intento y apertura de apps del menú) es
# compartido con el resto de assets: vive en `sire_assets/resources/sol_portal.py`.
from assets.sire_assets.resources import sol_portal
from assets.sire_assets.resources.sol_portal import (
    HEADERS,
    MENU_URL,
    SolPortalError,
    abrir_app as abrir_app_portal,
    abrir_sesion as abrir_sesion_portal,
    descubrir_flujo as descubrir_flujo_portal,
    fallas_pendientes,  # noqa: F401  (re-exportado: lo usan los tests del asset)
    hacer_login as hacer_login_portal,
)

_logger = logging.getLogger(__name__)

# Raíz del repo (parents[5] = .../src/assets/seesol_rh_asset/resources/api_resource).
REPO_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CREDENTIALS_PATH = str(REPO_ROOT / "env" / "sire_credentials.json")


class SeesolRhError(Exception):
    """No se pudo obtener/parsear el reporte RH del SEE-SOL."""


def cargar_empresas(credentials_path: str) -> list[dict[str, Any]]:
    """Lee la lista de empresas de ``env/sire_credentials.json``."""
    return json.loads(Path(credentials_path).read_text(encoding="utf-8"))


# --- 1) cálculos y criterios (puros, sin red) ----------------------------------


def rango_del_mes(anio: int, mes: int) -> tuple[str, str]:
    """Rango (``dd/mm/YYYY``) del mes completo: ``("01/08/2026", "31/08/2026")``."""
    if not 1 <= mes <= 12:
        raise ValueError(f"Mes fuera de rango: {mes}")
    primero = date(anio, mes, 1)
    ultimo = date(anio + (mes == 12), (mes % 12) + 1, 1) - timedelta(days=1)
    return primero.strftime("%d/%m/%Y"), ultimo.strftime("%d/%m/%Y")


def criterios_busqueda(desde: str, hasta: str) -> list[tuple[str, str]]:
    """Campos del POST ``CapturaCriterioConsulatRec1`` (los que envía el JS).

    ``desde``/``hasta`` van en ``dd/mm/YYYY`` y el rango no puede superar
    ``MAX_DIAS`` días: el portal lo rechaza con un ``alert``. Ojo con
    ``tipocomprobante``: el formulario tiene **tres checkboxes**
    (``tipocomprobante1``) y su JS vuelca los marcados en el campo oculto
    ``tipocomprobante`` como ``"01;02;03;"`` **antes** de enviar.
    """
    partes = [p.strip() for p in (desde, hasta)]
    for etiqueta, texto in zip(("desde", "hasta"), partes):
        if len(texto) != 10 or texto[2] != "/" or texto[5] != "/":
            raise ValueError(f"Fecha {etiqueta} inválida para el portal: {texto!r}")
    a = date(int(partes[0][6:10]), int(partes[0][3:5]), int(partes[0][0:2]))
    b = date(int(partes[1][6:10]), int(partes[1][3:5]), int(partes[1][0:2]))
    if b < a:
        raise ValueError(f"El rango acaba antes de empezar: {desde}..{hasta}")
    if (b - a).days + 1 > MAX_DIAS:
        raise ValueError(
            f"El rango {desde}..{hasta} supera el mes que admite el portal "
            f"(máx {MAX_DIAS} días)"
        )
    return [
        ("accion", ACCION_CRITERIO),
        ("tipocomprobante", TIPOS_DOC),
        ("ruc_emisor", ""),
        ("num_serie", ""),
        ("num_comprob", ""),
        ("fec_desde", desde),
        ("fec_hasta", hasta),
        ("tipoestado", ESTADO_TODOS),
        ("tipocomprobante1", "01"),
        ("tipocomprobante1", "02"),
        ("tipocomprobante1", "03"),
        ("wacepta", "Buscar"),
    ]


def sin_registros(html: str) -> bool:
    """¿La página de resultados dice que no hay recibos para el rango pedido?"""
    return SIN_REGISTROS in (html or "")


def base_del_portal(location: str) -> str:
    """``https://ww1.sunat.gob.pe/ol-.../cpelec001Alias?...`` → ``https://ww1.sunat.gob.pe``."""
    partes = urlparse(location)
    if not partes.scheme or not partes.netloc:
        raise SeesolRhError(f"El portal devolvió una URL de app inválida: {location!r}")
    return f"{partes.scheme}://{partes.netloc}"


def inputs_del_form(html: str) -> dict[str, str]:
    """Campos del form ``LoginForm`` de la pantalla de login.

    Delega en ``sol_portal.inputs_del_form`` (el protocolo del portal es común a
    todos los assets).
    """
    return sol_portal.inputs_del_form(html)


# --- 2) login del portal (1 intento, sin reintentos) --------------------------


def descubrir_flujo(session: requests.Session) -> dict[str, Any]:
    """Recorre el portal hasta la pantalla de login y devuelve el "flujo".

    Delega en ``sol_portal.descubrir_flujo``; el error del módulo compartido se
    re-lanza como ``SeesolRhError`` para no cambiar la API de este resource.
    """
    try:
        return descubrir_flujo_portal(session)
    except SolPortalError as exc:
        raise SeesolRhError(str(exc)) from exc


def hacer_login(
    session: requests.Session, flujo: dict[str, Any], empresa: dict[str, Any]
) -> None:
    """POST único a ``j_security_check`` replicando el JS del portal.

    Delega en ``sol_portal.hacer_login`` (**1 intento, sin reintentos**) y traduce
    su error a ``SeesolRhError``.
    """
    try:
        hacer_login_portal(session, flujo, empresa)
    except SolPortalError as exc:
        raise SeesolRhError(str(exc)) from exc


def abrir_sesion(empresa: dict[str, Any]) -> requests.Session:
    """Sesión logueada en el portal y lista para las apps del menú."""
    try:
        return abrir_sesion_portal(empresa)
    except SolPortalError as exc:
        raise SeesolRhError(str(exc)) from exc


# --- 3) app "Consulta Receptor" y descarga del reporte ------------------------


def abrir_app(session: requests.Session, app: str = APP_RECEPTOR) -> str:
    """Pide al menú abrir la app y devuelve la URL a la que redirige (ww1...).

    Delega en ``sol_portal.abrir_app`` (``POST {action:'prevApp'}`` + ``GET
    action=execute&code=<app>`` → **302** al controlador de la app) y traduce su
    error a ``SeesolRhError``.
    """
    try:
        return abrir_app_portal(session, app)
    except SolPortalError as exc:
        raise SeesolRhError(str(exc)) from exc


def descargar_reporte(session: requests.Session, desde: str, hasta: str) -> str:
    """Descarga el reporte RH del rango (``dd/mm/YYYY``) y devuelve su texto.

    Pasos: abrir la app "Consulta Receptor" → ``GET`` del formulario → ``POST`` de
    criterios → ``POST descargaConsultaReceptor`` (el "Descargar Reporte"). El
    portal contesta ``text/plain`` con el archivo ``archivo.txt``.
    """
    location = abrir_app(session)
    host = base_del_portal(location)
    url_app = host + FORM_PATH
    _logger.info("[SEE-SOL RH] app abierta en %s", location.split("?")[0])

    formulario = session.get(
        location, headers={**HEADERS, "Referer": MENU_URL}, timeout=45
    )
    if formulario.status_code != 200 or "fec_desde" not in formulario.text:
        raise SeesolRhError(
            "La app no devolvió el formulario de la Consulta Receptor "
            f"(HTTP {formulario.status_code}, {len(formulario.text)} bytes)"
        )

    resultados = session.post(
        url_app,
        data=criterios_busqueda(desde, hasta),
        headers={
            **HEADERS,
            "Referer": location,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=120,
    )
    if sin_registros(resultados.text):
        _logger.warning(
            "[SEE-SOL RH] búsqueda %s..%s: el portal dice que NO hay registros",
            desde,
            hasta,
        )

    descarga = session.post(
        url_app,
        data={"accion": ACCION_DESCARGA},
        headers={
            **HEADERS,
            "Referer": url_app,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=180,
    )
    if descarga.status_code != 200:
        raise SeesolRhError(
            f"La descarga del reporte falló (HTTP {descarga.status_code})"
        )
    texto = descarga.content.decode("utf-8", "replace")
    if not texto.startswith(CABECERA_REPORTE):
        raise SeesolRhError(
            "La descarga no parece el reporte RH (no empieza por la cabecera de 16 "
            f"columnas): {texto[:120]!r}"
        )
    return texto


# --- 4) resource -------------------------------------------------------------


class RhResource(ConfigurableResource):
    """Resource que descarga el reporte RH del SEE-SOL para una empresa y un mes."""

    credentials_path: str = Field(
        default=DEFAULT_CREDENTIALS_PATH,
        description="Ruta al JSON de credenciales de SUNAT (env/sire_credentials.json)",
    )

    def empresa(self, company: str) -> dict[str, Any]:
        """Objeto de credenciales de ``company`` (por su ``name``)."""
        empresas = cargar_empresas(self.credentials_path)
        for empresa in empresas:
            if empresa.get("name") == company:
                return empresa
        raise SeesolRhError(
            f"No existe '{company}' en {self.credentials_path}. "
            f"Empresas: {[e.get('name') for e in empresas]}"
        )

    def fetch_report(self, company: str, period: str) -> str:
        """Texto crudo del reporte RH de ``company`` del mes de ``period``.

        ``period`` es el mes de la partición (``"2026-08-01"``; también admite
        ``"2026-08"``). Hace **un login por empresa y mes** porque el portal solo
        admite rangos de 1 mes.
        """
        empresa = self.empresa(company)
        anio, mes = (int(parte) for parte in period[:7].split("-"))
        desde, hasta = rango_del_mes(anio, mes)
        session = abrir_sesion(empresa)
        _logger.info(
            "[SEE-SOL RH] %s %s: descargando %s..%s", company, period, desde, hasta
        )
        return descargar_reporte(session, desde, hasta)

    def get_month(self, company: str, period: str) -> list[dict[str, Any]]:
        """Filas del reporte RH de ``company`` en el mes ``period``.

        Cada fila trae su ``period`` estampado (``"2026-08-01"``); el ``empresa``
        lo añade el asset. Un mes sin recibos devuelve ``[]`` (el portal manda el
        archivo solo con la cabecera) y se avisa por log.
        """
        texto = self.fetch_report(company, period)
        filas = [{**row, "period": period} for row in parse_rh_text(texto)]
        if not filas:
            _logger.warning(
                "[SEE-SOL RH] %s %s: el reporte no trae registros (%d bytes)",
                company,
                period,
                len(texto),
            )
        return filas

