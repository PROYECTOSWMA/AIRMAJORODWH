"""Constantes del flujo del reporte de estadísticas de vuelos (SISA).

Es una consulta SQL directa contra el mismo endpoint ``/query`` que usa el asset
``sisa_sales_monthly``, pero **independiente**: no comparte tablas ni recursos con
él (tabla ``flight_reports``, sin relación con nada del proyecto).
"""

# Endpoint de consulta (POST, sin headers). El body es ``{"sql": <EXECUTE>}``.
SISA_QUERY_URL = "http://38.187.7.111:5500/query"

# El endpoint responde rápido pero a veces se cuelga/encola: cada intento tiene un
# deadline duro de reloj y, si no termina a tiempo, se reintenta.
FLIGHT_REPORTS_QUERY_TIMEOUT_SECONDS = 30
FLIGHT_REPORTS_QUERY_MAX_ATTEMPTS = 3

# Opción del reporte de estadísticas de vuelos (``@OpcionReporte``).
OPCION_REPORTE_VUELOS = 4

# Plantilla del EXECUTE. Solo varían @FechaInicio/@FechaFin (el mes de la partición).
FLIGHT_REPORTS_SQL_TEMPLATE = (
    "EXECUTE [db_mantenimiento].[dbo].[USP_ESTADISTICAS_VUELOS_PERIODO] "
    "@FechaInicio='{fecha_inicio}', "
    "@FechaFin='{fecha_fin}', "
    "@OpcionReporte={opcion_reporte}"
)
