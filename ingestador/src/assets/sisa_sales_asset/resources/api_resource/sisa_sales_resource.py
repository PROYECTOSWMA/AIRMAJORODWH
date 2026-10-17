"""Consulta de la liquidación contable de ventas (SISA) vía el endpoint ``/query``.

Arma el ``EXECUTE`` de ``USP_UVW_LIQUIDACION_CONTA`` con las fechas del mes de
la partición y la (empresa, sede) dadas, lo envía al endpoint (POST, sin
headers) y devuelve las filas como dicts con claves snake_case.

Cada consulta corre en un hilo con **deadline duro** (``SISA_QUERY_TIMEOUT_SECONDS``):
si no termina en ese tiempo —aunque el servidor vaya mandando datos poco a poco—
se reintenta hasta ``SISA_QUERY_MAX_ATTEMPTS`` veces; si sigue sin responder,
falla con ``SisaSalesQueryError``. Las consultas se **serializan** (una a la vez):
ninguna llamada al endpoint empieza hasta que terminó la anterior. Cualquier
respuesta inesperada (red, HTTP no 200, ``ok`` falso o ``error`` no nulo)
derrumba la materialización.
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

from assets.sisa_sales_asset.resources.api_resource.constants import (
    SISA_NC_QUERY_SQL_TEMPLATE,
    SISA_QUERY_MAX_ATTEMPTS,
    SISA_QUERY_SQL_TEMPLATE,
    SISA_QUERY_TIMEOUT_SECONDS,
    SISA_QUERY_URL,
)
from assets.utils import normalize_rows

# El endpoint responde rápido pero no tolera consultas en paralelo (se cuelga).
# El lock serializa las llamadas: una a la vez, cada una espera a que termine la
# anterior. Cada llamada usa un executor propio (hilo de vida corta) con deadline.
_SERIAL_LOCK = threading.Lock()


class SisaSalesQueryError(Exception):
    """Error durante la consulta de la liquidación SISA (derrumba la materialización)."""


class SisaSalesResource(ConfigurableResource):
    """Resource que consulta la liquidación de ventas de una (empresa, sede) y mes.

    ``get_sales`` construye el SQL con las fechas del mes de la partición y la
    empresa/sede dadas, lo envía al endpoint ``/query`` y devuelve las filas
    normalizadas.
    """

    def get_sales(
        self,
        period: str,
        cod_emp_doref: str,
        cod_sed_doref: str,
    ) -> list[dict[str, Any]]:
        """Devuelve las filas de la liquidación de ``(cod_emp_doref, cod_sed_doref)``
        para el mes de la partición ``period`` (``"2026-08-01"``).

        La llamada espera (lock) a que termine cualquier consulta anterior y se
        ejecuta con un deadline duro de ``SISA_QUERY_TIMEOUT_SECONDS``.
        """
        return self._get(
            period, cod_emp_doref, cod_sed_doref, SISA_QUERY_SQL_TEMPLATE
        )

    def get_credit_notes(
        self,
        period: str,
        cod_emp_doref: str,
        cod_sed_doref: str,
    ) -> list[dict[str, Any]]:
        """Devuelve las **notas de crédito** de ``(cod_emp_doref, cod_sed_doref)``
        para el mes de la partición ``period``.

        Mismo mecanismo que ``get_sales`` pero invocando el procedure
        ``USP_UVW_LIQUIDACION_NOTACREDITO`` (mismos parámetros). Estas filas se
        RESTAN de las ventas de SISA.
        """
        return self._get(
            period, cod_emp_doref, cod_sed_doref, SISA_NC_QUERY_SQL_TEMPLATE
        )

    def _get(
        self,
        period: str,
        cod_emp_doref: str,
        cod_sed_doref: str,
        sql_template: str,
    ) -> list[dict[str, Any]]:
        """Ejecuta la consulta (ventas o notas de crédito) con deadline y reintentos.

        ``sql_template`` es la plantilla del ``EXECUTE`` a usar. La llamada espera
        (lock) a que termine cualquier consulta anterior y se ejecuta con un
        deadline duro de ``SISA_QUERY_TIMEOUT_SECONDS``.
        """
        with _SERIAL_LOCK:
            fecha_inicio, fecha_termin = _mes_ventana(period)
            sql = sql_template.format(
                cod_emp_doref=cod_emp_doref,
                cod_sed_doref=cod_sed_doref,
                fecha_inicio=fecha_inicio,
                fecha_termin=fecha_termin,
            )
            ident = f"(empresa '{cod_emp_doref}', sede '{cod_sed_doref}', período '{period}')"

            for intento in range(1, SISA_QUERY_MAX_ATTEMPTS + 1):
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="sisa_sales_query",
                )
                try:
                    future = executor.submit(self._query_and_parse, sql, ident)
                    return future.result(timeout=SISA_QUERY_TIMEOUT_SECONDS)
                except FuturesTimeoutError:
                    if intento < SISA_QUERY_MAX_ATTEMPTS:
                        continue
                    raise SisaSalesQueryError(
                        f"El endpoint SISA no respondió en {SISA_QUERY_TIMEOUT_SECONDS}s "
                        f"tras {SISA_QUERY_MAX_ATTEMPTS} intentos para {ident}"
                    ) from None
                finally:
                    # No esperar a una llamada colgada: su hilo queda en segundo
                    # plano hasta que el socket responda.
                    executor.shutdown(wait=False)

    def _query_and_parse(self, sql: str, ident: str) -> list[dict[str, Any]]:
        """Ejecuta el POST al endpoint y devuelve las filas normalizadas.

        Corre en el hilo del executor; las excepciones que lanza se propagan a
        ``future.result()`` (o se convierten en timeout en ``get_sales``).
        """
        try:
            response = requests.post(
                SISA_QUERY_URL,
                json={"sql": sql},
                timeout=SISA_QUERY_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise SisaSalesQueryError(
                f"No hubo respuesta del endpoint SISA para {ident}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise SisaSalesQueryError(
                f"Status HTTP {response.status_code} en {SISA_QUERY_URL} para "
                f"{ident}: {response.text}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise SisaSalesQueryError(
                f"Respuesta 200 no es JSON en {SISA_QUERY_URL}: {response.text}"
            ) from exc

        if not isinstance(data, dict) or not data.get("ok"):
            raise SisaSalesQueryError(
                f"El endpoint no respondió ok=True para {ident}: {data}"
            )
        error = data.get("error")
        if error is not None:
            raise SisaSalesQueryError(
                f"El endpoint devolvió error para {ident}: {error}"
            )

        columns = data.get("columns") or []
        rows = data.get("rows") or []
        return normalize_rows(columns, rows)


def _mes_ventana(period: str) -> tuple[str, str]:
    """Devuelve (FECHAINICIO, FECHATERMIN) del mes de la partición ``"2026-08-01"``.

    Ej.: ``"2026-08-01"`` -> ``("01/08/2026", "31/08/2026")``.
    """
    fecha = datetime.strptime(period, "%Y-%m-%d").date()
    ultimo = monthrange(fecha.year, fecha.month)[1]
    return (
        f"{fecha.day:02d}/{fecha.month:02d}/{fecha.year}",
        f"{ultimo:02d}/{fecha.month:02d}/{fecha.year}",
    )


