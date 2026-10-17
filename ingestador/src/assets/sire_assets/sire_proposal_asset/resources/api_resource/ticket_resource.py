"""Lógica de obtención del ticket de exportación de propuestas SIRE (workflow async).

Solicita el ticket, espera a que el reporte esté listo y descarga el ZIP.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import requests
from dagster import ConfigurableResource, InitResourceContext

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
    HTTP_RETRY_MAX_ATTEMPTS,
    HTTP_RETRY_WAIT_SECONDS,
    HTTP_NETWORK_MAX_ATTEMPTS,
    HTTP_NETWORK_WAIT_SECONDS,
    HTTP_REQUEST_TIMEOUT_SECONDS,
    PROPOSAL_EXPORT_PATH_PURCHS,
    PROPOSAL_EXPORT_PATH_SALES,
    PROPOSAL_FILE_TYPE_CSV,
    PROPOSAL_PROCESS_CODE,
    REPORT_FILE_PATH,
    SIRE_API_BASE,
    SIRE_HOST,
    TICKET_EMPTY_PERIOD_CODE,
    TICKET_EMPTY_PERIOD_MAX_ATTEMPTS,
    TICKET_EMPTY_PERIOD_WAIT_SECONDS,
    TICKET_IN_PROGRESS_CODE,
    TICKET_IN_PROGRESS_MAX_ATTEMPTS,
    TICKET_IN_PROGRESS_WAIT_SECONDS,
    TICKET_POLL_SECONDS,
    TICKET_STATUS_FINISHED,
    TICKET_STATUS_PATH,
)

_logger = logging.getLogger(__name__)


class PropuestaRceError(Exception):
    """Error ocurrido durante la exportación de una propuesta en SIRE."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


@dataclass
class ArchivoDescarga:
    """Archivo de reporte listo para descargar tras finalizar un ticket."""

    nom_archivo_reporte: str
    cod_tipo_archivo_reporte: str
    per_tributario: str
    cod_proceso: str
    num_ticket: str


class TicketResource(ConfigurableResource):
    """Resource que obtiene el ZIP de la propuesta SIRE (ticket asíncrono).

    Único método público: ``get_zip``. Internamente solicita el ticket,
    espera (polling) a que el reporte esté listo y lo descarga.

    Depende de ``token_resource`` (``SireTokenResource``) para autenticarse
    contra la API de SIRE. La empresa se pasa por parámetro a ``get_zip``.
    """

    token_resource: SireTokenResource

    def setup_for_execution(self, context: InitResourceContext) -> None:
        """Guarda el log manager de Dagster para loguear con ``context.log``."""
        self._log = context.log

    def _info(self, msg: str) -> None:
        log = getattr(self, "_log", None)
        if log is not None:
            log.info(msg)
        else:
            _logger.info(msg)

    def _warning(self, msg: str) -> None:
        log = getattr(self, "_log", None)
        if log is not None:
            log.warning(msg)
        else:
            _logger.warning(msg)

    def get_zip(
        self,
        per_tributario: str,
        book_code: str = BOOK_CODE_PURCHASES,
        poll_seconds: int = TICKET_POLL_SECONDS,
        *,
        empresa: str,
    ) -> bytes | None:
        """Solicita el ticket, espera al reporte y devuelve el ZIP de la propuesta.

        ``per_tributario`` debe venir en formato ``yyyymm`` (ej. ``"202607"``) y
        ``empresa`` es el ``name`` de la empresa en ``sire_credentials.json``.

        Devuelve ``None`` cuando SUNAT responde 422/``cod 1070`` ("No se ha
        encontrado información de comprobantes de pago en Periodo Seleccionado")
        tras agotar ``TICKET_EMPTY_PERIOD_MAX_ATTEMPTS`` intentos: ese periodo se
        trata como **sin comprobantes** (0 filas) en vez de tumbar el run de
        SIRE. El 422 es transitorio (el proceso masivo lo contesta a veces justo
        al crear el ticket), así que cada reintento pide un ticket **nuevo**, con
        una pausa de ``TICKET_EMPTY_PERIOD_WAIT_SECONDS`` para no chocar con el
        proceso anterior (que SUNAT rechaza con 422/``cod 42209``).
        """
        for intento in range(1, TICKET_EMPTY_PERIOD_MAX_ATTEMPTS + 1):
            num_ticket = self._request_ticket(per_tributario, book_code, empresa=empresa)
            self._info(f"[{empresa}] Ticket created: {num_ticket}")

            try:
                archivo = self._wait_for_ticket(
                    per_tributario, num_ticket, poll_seconds, empresa=empresa
                )
            except PropuestaRceError as exc:
                if not _es_periodo_sin_comprobantes(exc):
                    raise
                self._info(
                    f"[{empresa}] Ticket {num_ticket} sin comprobantes en "
                    f"{per_tributario} (cod {TICKET_EMPTY_PERIOD_CODE}); "
                    f"intento {intento}/{TICKET_EMPTY_PERIOD_MAX_ATTEMPTS}"
                )
                if intento < TICKET_EMPTY_PERIOD_MAX_ATTEMPTS:
                    # El proceso del ticket anterior sigue vivo unos segundos y
                    # SUNAT rechaza el siguiente ticket con 422/42209: se le da
                    # un respiro para que termine antes de pedir otro.
                    time.sleep(TICKET_EMPTY_PERIOD_WAIT_SECONDS)
                continue

            self._info(f"[{empresa}] File ready: {archivo.nom_archivo_reporte}")
            return self._download_zip(archivo, book_code, empresa=empresa)

        self._warning(
            f"[{empresa}] Tras {TICKET_EMPTY_PERIOD_MAX_ATTEMPTS} intentos SUNAT "
            f"sigue sin encontrar comprobantes en {per_tributario} (cod "
            f"{TICKET_EMPTY_PERIOD_CODE}); se trata como periodo SIN comprobantes "
            "(0 filas)"
        )
        return None

    def _request_ticket(
        self,
        per_tributario: str,
        book_code: str = BOOK_CODE_PURCHASES,
        *,
        empresa: str,
    ) -> str:
        """Solicita la exportación de la propuesta y devuelve el ``numTicket``.

        Si SUNAT contesta HTTP 422/``cod 42209`` ("aún tiene un proceso de
        'Generar archivo exportar propuesta' en curso") es que el ticket anterior
        del mismo libro/periodo sigue corriendo: no es un fallo definitivo, así
        que se espera ``TICKET_IN_PROGRESS_WAIT_SECONDS`` y se reintenta hasta
        ``TICKET_IN_PROGRESS_MAX_ATTEMPTS``; agotados, se propaga el último error.
        """
        path_template = (
            PROPOSAL_EXPORT_PATH_SALES
            if book_code == BOOK_CODE_SALES
            else PROPOSAL_EXPORT_PATH_PURCHS
        )
        url = f"{SIRE_API_BASE}{path_template.format(tax_period=per_tributario)}"
        params = {
            "codTipoArchivo": PROPOSAL_FILE_TYPE_CSV,
            "codOrigenEnvio": (
                API_ORIGIN_CODE_SALES
                if book_code == BOOK_CODE_SALES
                else API_ORIGIN_CODE_PURCHASES
            ),
        }
        ultimo_error: PropuestaRceError | None = None
        for intento in range(1, TICKET_IN_PROGRESS_MAX_ATTEMPTS + 1):
            try:
                data = self._request("GET", url, params=params, empresa=empresa)
            except PropuestaRceError as exc:
                if not _es_proceso_en_curso(exc):
                    raise
                ultimo_error = exc
                self._info(
                    f"[{empresa}] SUNAT aún tiene un proceso de exportación de "
                    f"propuesta en curso para {per_tributario}; reintentando en "
                    f"{TICKET_IN_PROGRESS_WAIT_SECONDS}s "
                    f"(intento {intento}/{TICKET_IN_PROGRESS_MAX_ATTEMPTS})"
                )
                time.sleep(TICKET_IN_PROGRESS_WAIT_SECONDS)
                continue
            num_ticket = data.get("numTicket")
            if not num_ticket:
                raise PropuestaRceError(
                    "Response does not contain numTicket",
                    response_body=data,
                )
            return str(num_ticket)
        if ultimo_error is not None:
            raise ultimo_error
        raise PropuestaRceError(
            f"No se pudo solicitar el ticket de {per_tributario} "
            f"(sin intentos configurados)",
            response_body={"intentos": TICKET_IN_PROGRESS_MAX_ATTEMPTS},
        )

    def _wait_for_ticket(
        self,
        per_tributario: str,
        num_ticket: str,
        poll_seconds: int = TICKET_POLL_SECONDS,
        *,
        empresa: str,
    ) -> ArchivoDescarga:
        """Consulta el estado del ticket (1 registro) hasta que el archivo esté listo."""
        while True:
            estado = self._request(
                "GET",
                f"{SIRE_API_BASE}{TICKET_STATUS_PATH}",
                params={
                    "perIni": per_tributario,
                    "perFin": per_tributario,
                    "page": 1,
                    "perPage": 1,
                    "numTicket": num_ticket,
                },
                empresa=empresa,
            )
            archivo = _ready_download(estado)
            if archivo:
                return archivo
            desc = _ticket_status_label(estado)
            self._info(
                f"Ticket {num_ticket} in progress ({desc}). "
                f"Retrying in {poll_seconds}s..."
            )
            time.sleep(poll_seconds)

    def _download_zip(
        self,
        archivo: ArchivoDescarga,
        book_code: str,
        *,
        empresa: str,
    ) -> bytes:
        """Descarga el ZIP con el reporte de la propuesta."""
        response = self._request(
            "GET",
            f"{SIRE_API_BASE}{REPORT_FILE_PATH}",
            params={
                "nomArchivoReporte": archivo.nom_archivo_reporte,
                "codTipoArchivoReporte": archivo.cod_tipo_archivo_reporte,
                "codLibro": book_code,
                "perTributario": archivo.per_tributario,
                "codProceso": archivo.cod_proceso,
                "numTicket": archivo.num_ticket,
            },
            raw=True,
            empresa=empresa,
        )
        return response.content

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        raw: bool = False,
        empresa: str,
    ) -> requests.Response | dict[str, Any]:
        """Ejecuta la petición autenticada contra la API de SIRE.

        ``empresa`` es el ``name`` de la empresa en ``sire_credentials.json`` y se
        usa para resolver, con la audiencia de la API de libros SIRE, el token con
        ``token_resource.token(empresa, audience=AUDIENCE_SIRE,
        recurso=RECURSO_MIGEIGV)``.

        Ante HTTP 429 (rate limit de SUNAT) reintenta hasta
        ``HTTP_RETRY_MAX_ATTEMPTS`` veces esperando ``HTTP_RETRY_WAIT_SECONDS``
        entre intentos; cualquier otro status no OK lanza ``PropuestaRceError``.

        Los **errores de red** (DNS, "Network is unreachable", timeouts) son
        transitorios y llevan su propio presupuesto
        (``HTTP_NETWORK_MAX_ATTEMPTS`` × ``HTTP_NETWORK_WAIT_SECONDS``), más largo
        que el del 429 porque este ya consume intentos del mismo bucle; agotado,
        se lanza ``PropuestaRceError`` "Error de red". La petición lleva
        ``timeout=HTTP_REQUEST_TIMEOUT_SECONDS`` (como en los demás resources de
        SIRE) para que un socket colgado no bloquee el run.

        Con ``raw=True`` devuelve la ``Response`` (contenido binario);
        en caso contrario devuelve el JSON de respuesta parseado como ``dict``.
        """
        headers = {
            "Authorization": "Bearer "
            + self.token_resource.token(
                empresa, audience=AUDIENCE_SIRE, recurso=RECURSO_MIGEIGV
            ),
            "Host": SIRE_HOST,
        }
        intentos_429 = 0
        intentos_red = 0
        while True:
            try:
                response = requests.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=HTTP_REQUEST_TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException as exc:
                intentos_red += 1
                if intentos_red >= HTTP_NETWORK_MAX_ATTEMPTS:
                    raise PropuestaRceError(
                        f"Error de red en {method} {url} tras "
                        f"{HTTP_NETWORK_MAX_ATTEMPTS} intentos: {exc}",
                        response_body=str(exc),
                    ) from exc
                self._info(
                    f"[{empresa}] Error de red en {method} {url} ({exc}); "
                    f"reintentando en {HTTP_NETWORK_WAIT_SECONDS}s "
                    f"(intento {intentos_red}/{HTTP_NETWORK_MAX_ATTEMPTS})"
                )
                time.sleep(HTTP_NETWORK_WAIT_SECONDS)
                continue
            if response.status_code != 429:
                break
            intentos_429 += 1
            self._info(
                f"[{empresa}] HTTP 429 en {method} {url}; "
                f"reintentando en {HTTP_RETRY_WAIT_SECONDS}s "
                f"(intento {intentos_429}/{HTTP_RETRY_MAX_ATTEMPTS})"
            )
            if intentos_429 >= HTTP_RETRY_MAX_ATTEMPTS:
                break
            time.sleep(HTTP_RETRY_WAIT_SECONDS)
        if not response.ok:
            raise PropuestaRceError(
                f"Error HTTP {response.status_code} on {method} {url}: {response.text}",
                status_code=response.status_code,
                response_body=response.text,
            )
        if raw:
            return response
        data = response.json()
        if not isinstance(data, dict):
            raise PropuestaRceError(
                f"Unexpected response on {method} {url}", response_body=data
            )
        return data


def _codigos_error(error: PropuestaRceError) -> set[str]:
    """Códigos ``errors[].cod`` del body JSON de SUNAT.

    El body de estos 422 viene como JSON (``{"cod": 422, "errors": [{"cod":
    1070, "msg": "..."}]}``) y puede llegar como ``str`` o ``bytes``. Si no es
    JSON parseable o no es un ``dict`` se devuelve el conjunto vacío para **no**
    enmascarar un fallo distinto.
    """
    body = error.response_body
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except ValueError:
            return set()
    if not isinstance(body, dict):
        return set()
    return {
        str(error_item.get("cod"))
        for error_item in (body.get("errors") or [])
        if isinstance(error_item, dict)
    }


def _es_periodo_sin_comprobantes(error: PropuestaRceError) -> bool:
    """True si el error es el 422/``cod 1070`` de SUNAT ("no hay comprobantes")."""
    return error.status_code == 422 and str(TICKET_EMPTY_PERIOD_CODE) in _codigos_error(
        error
    )


def _es_proceso_en_curso(error: PropuestaRceError) -> bool:
    """True si el error es el 422/``cod 42209`` ("ya hay un proceso en curso").

    SUNAT lo contesta al pedir un ticket nuevo mientras el proceso del ticket
    anterior sigue corriendo: es transitorio (se espera y se reintenta), **no** un
    periodo sin comprobantes.
    """
    return error.status_code == 422 and str(TICKET_IN_PROGRESS_CODE) in _codigos_error(
        error
    )


def _ready_download(estado: dict[str, Any]) -> ArchivoDescarga | None:
    """Devuelve el ``ArchivoDescarga`` si el ticket terminó y el reporte está listo."""
    registros = estado.get("registros") or []
    if not registros:
        return None
    registro = registros[0]
    if str(registro.get("desEstadoProceso", "")).strip().lower() != TICKET_STATUS_FINISHED:
        return None
    if str(registro.get("showReporteDescarga", "")).strip() != "1":
        return None
    archivo = (registro.get("archivoReporte") or [None])[0]
    nombre = (archivo or {}).get("nomArchivoReporte")
    if not nombre:
        return None
    return ArchivoDescarga(
        nom_archivo_reporte=str(nombre),
        cod_tipo_archivo_reporte=str(
            # SUNAT devuelve el campo con el typo "codTipoAchivoReporte" (verificado en vivo)
            archivo.get("codTipoAchivoReporte")
            or archivo.get("codTipoArchivoReporte", "null")
        ),
        per_tributario=str(registro.get("perTributario")),
        cod_proceso=str(registro.get("codProceso", PROPOSAL_PROCESS_CODE)),
        num_ticket=str(registro.get("numTicket")),
    )


def _ticket_status_label(estado: dict[str, Any]) -> str:
    registros = estado.get("registros") or []
    if not registros:
        return "no records"
    r = registros[0]
    return str(r.get("desEstadoProceso") or r.get("codEstadoProceso") or "unknown")
