"""Consulta del tipo de cambio SUNAT por mes (endpoint apis.net.pe).

``get_month`` pide ``?year=YYYY&month=MM`` y devuelve un dict indexado por fecha
(``{fecha: {"compra": ..., "venta": ...}}``). Reintenta ante fallos de red / 5xx y,
con una pausa propia más larga, ante el **429** (rate limit: respeta ``Retry-After``).
Agotados los intentos lanza ``CalendarApiError``, que el asset captura para degradar
sin tumbar el run.
"""

from __future__ import annotations

import time
from typing import Any

import requests
from dagster import ConfigurableResource

from assets.calendar_asset.resources.api_resource.constants import (
    CALENDAR_API_URL,
    CALENDAR_MAX_ATTEMPTS,
    CALENDAR_RATE_LIMIT_SLEEP_SECONDS,
    CALENDAR_RETRY_SLEEP_SECONDS,
    CALENDAR_TIMEOUT_SECONDS,
)


class CalendarApiError(Exception):
    """Error durante la consulta del tipo de cambio (el asset lo captura y degrada)."""


class CalendarApiResource(ConfigurableResource):
    """Resource que consulta el tipo de cambio SUNAT de un (year, month)."""

    api_url: str = CALENDAR_API_URL
    timeout_seconds: int = CALENDAR_TIMEOUT_SECONDS
    max_attempts: int = CALENDAR_MAX_ATTEMPTS

    def get_month(self, year: int, month: int) -> dict[str, dict[str, Any]]:
        """Devuelve ``{fecha: {"compra": ..., "venta": ...}}`` del mes dado.

        Reintenta ante fallos de red, 5xx y sobre todo **429** (rate limit): el 429
        espera ``CALENDAR_RATE_LIMIT_SLEEP_SECONDS`` entre intentos (o el
        ``Retry-After`` de la respuesta si es mayor) en lugar de la pausa genérica.
        Agotados los intentos lanza ``CalendarApiError``; es el asset quien decide
        degradar sin tumbar el run.
        """
        url = f"{self.api_url}?year={year}&month={month:02d}"
        for intento in range(1, self.max_attempts + 1):
            try:
                res = requests.get(url, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                if intento < self.max_attempts:
                    time.sleep(CALENDAR_RETRY_SLEEP_SECONDS)
                    continue
                raise CalendarApiError(
                    f"No hubo respuesta del endpoint de tipo de cambio para "
                    f"{year}-{month:02d}: {exc}"
                ) from exc
            if res.status_code == 429:
                if intento < self.max_attempts:
                    time.sleep(self._retry_after(res))
                    continue
                raise CalendarApiError(
                    f"Status HTTP 429 (rate limit) en {url} tras "
                    f"{self.max_attempts} intentos"
                )
            if res.status_code != 200:
                if intento < self.max_attempts:
                    time.sleep(CALENDAR_RETRY_SLEEP_SECONDS)
                    continue
                raise CalendarApiError(
                    f"Status HTTP {res.status_code} en {url}: {res.text}"
                )
            try:
                data = res.json()
            except ValueError as exc:
                raise CalendarApiError(
                    f"Respuesta 200 no es JSON en {url}: {res.text}"
                ) from exc
            return self._index_by_fecha(data)
        raise CalendarApiError(
            f"Sin respuesta de {url} tras {self.max_attempts} intentos"
        )

    def _retry_after(self, res: requests.Response) -> float:
        """Segundos a esperar tras un 429: ``Retry-After`` válido o el valor por defecto.

        ``Retry-After`` puede venir como segundos o como fecha HTTP; si no es un
        número parseable se ignora y se usa ``CALENDAR_RATE_LIMIT_SLEEP_SECONDS``.
        """
        cabecera = res.headers.get("Retry-After") if res.headers else None
        if cabecera:
            try:
                return max(float(cabecera), CALENDAR_RATE_LIMIT_SLEEP_SECONDS)
            except (TypeError, ValueError):
                pass
        return CALENDAR_RATE_LIMIT_SLEEP_SECONDS

    def _index_by_fecha(self, data: Any) -> dict[str, dict[str, Any]]:
        """Convierte la lista de items del mes en un dict indexado por ``fecha``."""
        if not isinstance(data, list):
            raise CalendarApiError(f"Respuesta inesperada (no es lista): {data!r}")
        result: dict[str, dict[str, Any]] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            fecha = item.get("fecha")
            if not fecha:
                continue
            result[str(fecha)] = {
                "compra": item.get("compra"),
                "venta": item.get("venta"),
            }
        return result
