
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any

import requests
from dagster import ConfigurableResource, InitResourceContext
from pydantic import PrivateAttr

from assets.sire_assets.resources.token_resource import (
    AUDIENCE_CPE,
    RECURSO_CONSULTACPE,
    SireTokenResource,
)

_logger = logging.getLogger(__name__)

# Roles de la consulta (último segmento de la URL del comprobante).
ROLE_EMISOR = 1
ROLE_RECEPTOR = 2

# API de consulta de comprobantes CPE. La URL final es
# ``{CPE_DETAILS_BASE_URL}/{senderruc}-{tipo}-{serie}-{numero}-{rol}``.
# Se define aquí (y no en los constants de details) para evitar el import
# circular: ``constants`` de details importa ``ROLE_EMISOR``/``ROLE_RECEPTOR``
# de este módulo.
CPE_DETAILS_BASE_URL = (
    "https://api-cpe.sunat.gob.pe/v1/contribuyente/consultacpe/comprobantes"
)

# Status transitorios del proxy de SUNAT ("Service Unavailable" con body HTML):
# se reintentan igual que el 500 y, agotados los intentos, el comprobante se trata
# como ``missing`` (el próximo run lo vuelve a pedir) en vez de tumbar el paso.
RETRYABLE_HTTP_STATUSES = (500, 502, 503, 504)


class SireApiError(Exception):
    """Error durante la consulta de un comprobante CPE."""


class SireApiMissing(SireApiError):
    """El recurso no se pudo obtener (500/502/503/504 agotados o la API no responde).

    El asset lo captura, registra el documento en la metadata ``missing_*`` y sigue.
    """


class SireApiUnauthorized(SireApiError):
    """El token no es válido o está vencido (HTTP 401). Debe caer la materialización."""


class SireApiUnexpectedStatus(SireApiError):
    """Status HTTP no manejado (ni 200, 401 ni 500/502/503/504). Cae la materialización."""


class DetailsAndFilesResource(ConfigurableResource, ABC):
    token_resource: SireTokenResource
    base_url: str = CPE_DETAILS_BASE_URL
    user_agent: str = "Mozilla"
    retry_max_attempts: int = 10
    retry_wait_seconds: float = 0.001
    request_timeout_seconds: float = 10
    log_retries: bool = False
    # Audiencia (claim ``aud``) y recurso de la API de consulta de comprobantes:
    # el token que se pide al ``token_resource`` debe cubrir ambos.
    audience: str = AUDIENCE_CPE
    recurso: str | None = RECURSO_CONSULTACPE

    _session: requests.Session | None = PrivateAttr(default=None)

    def _get_session(self) -> requests.Session:
        """Devuelve la session HTTP del recurso, creándola la primera vez."""
        if self._session is None:
            self._session = requests.Session()
        return self._session

    def setup_for_execution(self, context: InitResourceContext) -> None:
        self._log = context.log

    def _info(self, msg: str) -> None:
        log = getattr(self, "_log", None)
        if log is not None:
            log.info(msg)
        else:
            _logger.info(msg)

    def companies(self) -> list[str]:
        """Nombres de las empresas disponibles en ``sire_credentials.json``."""
        return self.token_resource.companies()

    def ruc(self, name: str) -> str:
        """RUC de la empresa ``name`` (campo ``ruc`` de ``sire_credentials.json``)."""
        return self.token_resource.ruc(name)

    def get_items(
        self,
        senderruc: str,
        tipo: str,
        serie: str,
        numero: int | str,
        rol: int = ROLE_EMISOR,
        *,
        empresa: str,
        suffix: str = "",
    ) -> Any:
        subpath = f"{senderruc}-{tipo}-{serie}-{numero}-{rol}"
        url = f"{self.base_url}/{subpath}{suffix}"
        headers = {
            "User-Agent": self.user_agent,
            "Authorization": "Bearer "
            + self.token_resource.token(
                empresa, audience=self.audience, recurso=self.recurso
            ),
        }

        response: requests.Response | None = None
        for i in range(self.retry_max_attempts):
            try:
                response = self._get_session().get(
                    url, headers=headers, timeout=self.request_timeout_seconds
                )
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                raise SireApiMissing(
                    f"Timeout {subpath} (empresa '{empresa}'): {exc}"
                ) from exc

            # We have a response
            if response.status_code not in (200, 401, *RETRYABLE_HTTP_STATUSES):
                raise SireApiUnexpectedStatus(
                    f"Status HTTP {response.status_code} no manejado en {url}: {response.text}"
                )
            elif response.status_code == 401:
                raise SireApiUnauthorized(
                    f"Token no autorizado (HTTP 401) para la empresa '{empresa}' en "
                    f"{url}: {response.text}"
                )
            elif response.status_code == 200:
                try:
                    data = response.json()
                except ValueError as exc:
                    raise SireApiUnexpectedStatus(
                        f"Respuesta 200 no es JSON en {url}: {response.text}"
                    ) from exc
                return self._parse_response(data)
            elif response.status_code in RETRYABLE_HTTP_STATUSES:
                if response.status_code == 500:
                    try:
                        response.json()
                    except ValueError:
                        # 500 con body no-JSON (p.ej. página HTML de un WAF/proxy):
                        # se interpreta como problema de autenticación/sesión y se
                        # corta sin reintentar.
                        raise SireApiUnauthorized(
                            f"HTTP 500 con body no-JSON en {url}: {response.text}"
                        )
                # 500 con body JSON válido y 502/503/504 (proxy de SUNAT caído, body
                # HTML): son transitorios, así que se reintenta esperando
                # ``retry_wait_seconds``. Si se agotan todos los intentos se lanza
                # ``SireApiMissing`` y el comprobante queda como ``missing`` (el
                # próximo run lo vuelve a pedir) en vez de caer el paso entero.
                time.sleep(self.retry_wait_seconds)

        # Se agotaron los reintentos con un status transitorio (500/502/503/504).
        raise SireApiMissing(
            f"HTTP {response.status_code} tras {self.retry_max_attempts} intentos "
            f"para {subpath} (empresa '{empresa}'): {response.text}"
        )


    @abstractmethod
    def _parse_response(self, data: dict[str, Any]) -> Any:
        """Extrae de ``data`` lo que devuelve ``get_items`` (respuesta 200)."""

