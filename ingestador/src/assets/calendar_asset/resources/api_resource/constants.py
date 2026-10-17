"""Constantes del flujo del calendario de tipos de cambio (SUNAT / apis.net.pe).

El endpoint devuelve la lista de días del mes pedido con ``fecha``, ``compra`` y
``venta``. Los nombres de mes se guardan en inglés (así se ven en ``dwh_calendar``).
"""

# Endpoint de tipo de cambio SUNAT: GET ?year=YYYY&month=MM.
CALENDAR_API_URL = "https://api.apis.net.pe/v1/tipo-cambio-sunat"

CALENDAR_TIMEOUT_SECONDS = 30
# 1 intento inicial + 5 reintentos = 6 llamadas totales como máximo.
CALENDAR_MAX_ATTEMPTS = 6
# Pausa (segundos) entre intentos para fallos de red / 5xx.
CALENDAR_RETRY_SLEEP_SECONDS = 0.2
# Pausa específica del HTTP 429 (rate limit de apis.net.pe): bastante más larga
# que la genérica porque el servidor necesita tiempo para recuperarse. Si la
# respuesta trae ``Retry-After`` se respeta ese valor (el mayor de los dos).
CALENDAR_RATE_LIMIT_SLEEP_SECONDS = 5

# Nombres de mes en inglés: ``dwh_calendar.month_name`` usa el nombre completo.
MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
