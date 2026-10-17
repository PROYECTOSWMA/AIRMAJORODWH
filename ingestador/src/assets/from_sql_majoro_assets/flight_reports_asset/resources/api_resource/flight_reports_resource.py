"""Consulta del reporte de estadísticas de vuelos (SISA) vía el endpoint ``/query``.

Arma el ``EXECUTE`` de ``USP_ESTADISTICAS_VUELOS_PERIODO`` con las fechas del mes
de la partición (``@OpcionReporte=4``), lo envía al endpoint (POST, sin headers) y
devuelve las filas como dicts con claves snake_case.

Cada consulta corre en un hilo con **deadline duro**
(``FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS``): si no termina en ese tiempo —aunque el
servidor vaya mandando datos poco a poco— se reintenta hasta
``FLIGHT_REPORTS_QUERY_MAX_ATTEMPTS`` veces; si sigue sin responder, falla con
``FlightReportsQueryError``. Las consultas se **serializan** (una a la vez) porque
el endpoint no tolera consultas en paralelo. Cualquier respuesta inesperada (red,
HTTP no 200, ``ok`` falso o ``error`` no nulo) derrumba la materialización.
"""

from __future__ import annotations

import threading
from calendar import monthrange
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
)
from datetime import datetime
from typing import Any

import requests
from dagster import ConfigurableResource

from assets.from_sql_majoro_assets.flight_reports_asset.resources.api_resource.constants import (
    FLIGHT_REPORTS_QUERY_MAX_ATTEMPTS,
    FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS,
    FLIGHT_REPORTS_SQL_TEMPLATE,
    OPCION_REPORTE_VUELOS,
    SISA_QUERY_URL,
)
from assets.utils import normalize_rows

# El endpoint responde rápido pero no tolera consultas en paralelo (se cuelga).
# El lock serializa las llamadas: una a la vez, cada una espera a que termine la
# anterior. Cada llamada usa un executor propio (hilo de vida corta) con deadline.
_SERIAL_LOCK = threading.Lock()


class FlightReportsQueryError(Exception):
    """Error durante la consulta del reporte de vuelos (derrumba la materialización)."""


class FlightReportsResource(ConfigurableResource):
    """Resource que consulta el reporte de estadísticas de vuelos de un mes.

    ``get_report`` construye el SQL con las fechas del mes de la partición, lo envía
    al endpoint ``/query`` y devuelve las filas normalizadas.
    """

    def get_report(self, period: str) -> list[dict[str, Any]]:
        """Devuelve las filas del reporte de vuelos para el mes de ``period``.

        ``period`` es la clave de la partición mensual (``"2026-08-01"``). La llamada
        espera (lock) a que termine cualquier consulta anterior y se ejecuta con un
        deadline duro de ``FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS``.
        """
        with _SERIAL_LOCK:
            fecha_inicio, fecha_fin = _mes_ventana(period)
            sql = FLIGHT_REPORTS_SQL_TEMPLATE.format(
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                opcion_reporte=OPCION_REPORTE_VUELOS,
            )
            ident = f"(período '{period}')"

            for intento in range(1, FLIGHT_REPORTS_QUERY_MAX_ATTEMPTS + 1):
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="flight_reports_query",
                )
                try:
                    future = executor.submit(self._query_and_parse, sql, ident)
                    return future.result(
                        timeout=FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS
                    )
                except FuturesTimeoutError:
                    if intento < FLIGHT_REPORTS_QUERY_MAX_ATTEMPTS:
                        continue
                    raise FlightReportsQueryError(
                        f"El endpoint SISA no respondió en "
                        f"{FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS}s tras "
                        f"{FLIGHT_REPORTS_QUERY_MAX_ATTEMPTS} intentos para {ident}"
                    ) from None
                finally:
                    # No esperar a una llamada colgada: su hilo queda en segundo
                    # plano hasta que el socket responda.
                    executor.shutdown(wait=False)

    def _query_and_parse(self, sql: str, ident: str) -> list[dict[str, Any]]:
        """Ejecuta el POST al endpoint y devuelve las filas normalizadas.

        Corre en el hilo del executor; las excepciones que lanza se propagan a
        ``future.result()`` (o se convierten en timeout en ``get_report``).
        """
        try:
            response = requests.post(
                SISA_QUERY_URL,
                json={"sql": sql},
                timeout=FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise FlightReportsQueryError(
                f"No hubo respuesta del endpoint SISA para {ident}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise FlightReportsQueryError(
                f"Status HTTP {response.status_code} en {SISA_QUERY_URL} para "
                f"{ident}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise FlightReportsQueryError(
                f"Respuesta 200 no es JSON en {SISA_QUERY_URL}: {response.text}"
            ) from exc

        if not isinstance(data, dict) or not data.get("ok"):
            raise FlightReportsQueryError(
                f"El endpoint no respondió ok=True para {ident}: {data}"
            )
        error = data.get("error")
        if error is not None:
            raise FlightReportsQueryError(
                f"El endpoint devolvió error para {ident}: {error}"
            )

        columns = data.get("columns") or []
        rows = data.get("rows") or []
        return normalize_rows(columns, rows)


def _mes_ventana(period: str) -> tuple[str, str]:
    """Devuelve (FechaInicio, FechaFin) del mes de la partición ``"2026-08-01"``.

    Ej.: ``"2026-08-01"`` -> ``("01/08/2026", "31/08/2026")``.
    """
    fecha = datetime.strptime(period, "%Y-%m-%d").date()
    ultimo = monthrange(fecha.year, fecha.month)[1]
    return (
        f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year}",
        f"{ultimo:02d}/{fecha.month:02d}/{fecha.year}",
    )
