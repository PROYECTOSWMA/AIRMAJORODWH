"""Constantes y helpers del flujo de descarga de propuestas SIRE (ticket + CSV)."""

# Re-export de la utilidad compartida a nivel de assets para no romper los
# imports existentes (``from ...constants import to_db_field``).
from assets.utils import to_db_field  # noqa: F401

# SIRE libros API
SIRE_API_BASE = "https://api-sire.sunat.gob.pe/v1/contribuyente/migeigv/libros"
SIRE_HOST = "api-sire.sunat.gob.pe"

BOOK_CODE_PURCHASES = "080000"
BOOK_CODE_SALES = "140000"

# Proposal export (async ticket workflow)
PROPOSAL_EXPORT_PATH_PURCHS = "/rce/propuesta/web/propuesta/{tax_period}/exportacioncomprobantepropuesta"
PROPOSAL_EXPORT_PATH_SALES = "/rvie/propuesta/web/propuesta/{tax_period}/exportapropuesta"
TICKET_STATUS_PATH = "/rvierce/gestionprocesosmasivos/web/masivo/consultaestadotickets"
REPORT_FILE_PATH = "/rvierce/gestionprocesosmasivos/web/masivo/archivoreporte"

API_ORIGIN_CODE_PURCHASES = "2"
API_ORIGIN_CODE_SALES = "1"
PROPOSAL_PROCESS_CODE = "10"
# Sondeo del ticket asíncrono de SUNAT: el reporte suele tardar 10 s-2 min, así que
# se pregunta cada 2 s (el bucle ``_wait_for_ticket`` es ``while True``: solo cambia
# con qué frecuencia se pregunta, no la espera máxima).
TICKET_POLL_SECONDS = 2
TICKET_STATUS_FINISHED = "terminado"

# "No se ha encontrado información de comprobantes de pago en Periodo Seleccionado":
# SUNAT lo contesta **con HTTP 422 y cod 1070** en ``consultaestadotickets`` cuando el
# proceso masivo del ticket no ve comprobantes del periodo. Verificado en vivo el
# 2026-09-17: el MISMO ticket/libro (RVIE 202608 de Air Majoro) devolvió 1070 recién
# creado y bajó con datos al pedir un ticket nuevo ⇒ hay que reintentar antes de dar
# el periodo por vacío.
TICKET_EMPTY_PERIOD_CODE = 1070
# 1 intento + 2 reintentos (cada reintento pide un ticket NUEVO).
TICKET_EMPTY_PERIOD_MAX_ATTEMPTS = 3
# Pausa entre intentos del 1070 (solo si quedan intentos): pedir un ticket nuevo
# 2 s después del anterior, que aún se está procesando, provoca el 42209 de abajo.
TICKET_EMPTY_PERIOD_WAIT_SECONDS = 15

# "Estimado contribuyente aún tiene un proceso de 'Generar archivo exportar
# propuesta' en curso con Ticket: ...": SUNAT contesta **HTTP 422 / cod 42209** al
# pedir un ticket NUEVO mientras el proceso anterior sigue corriendo. Verificado en
# vivo el 2026-09-23 (RVIE 202605 de Air Majoro): tras dos tickets con cod 1070 (que
# resultaron prematuros) el tercer ticket fue rechazado con 42209 y el run murió.
# NO es "periodo sin comprobantes": hay que esperar y reintentar hasta que el
# proceso anterior termine.
TICKET_IN_PROGRESS_CODE = 42209
TICKET_IN_PROGRESS_MAX_ATTEMPTS = 5
TICKET_IN_PROGRESS_WAIT_SECONDS = 30

# HTTP retry (SUNAT limita por tasa con HTTP 429)
HTTP_RETRY_MAX_ATTEMPTS = 5
HTTP_RETRY_WAIT_SECONDS = 30

# Sin ``timeout`` una conexión colgada bloquea el run indefinidamente (el bucle de
# ``_request`` es de reintentos, no hay deadline global).
HTTP_REQUEST_TIMEOUT_SECONDS = 60

# Errores de red (DNS caído, "Network is unreachable", timeouts de conexión): son
# transitorios. Verificado en vivo el 2026-09-23: un ``OSError [Errno 101]`` a
# mitad de la propuesta (RCE 202603 de Air Majoro) mató el run. Se reintentan con
# presupuesto propio (más largo que el 429, que ya consume intentos) antes de
# rendirse con un ``PropuestaRceError`` "Error de red".
HTTP_NETWORK_MAX_ATTEMPTS = 10
HTTP_NETWORK_WAIT_SECONDS = 30

# Proposal CSV parsing
PROPOSAL_ENCODING = "utf-8-sig"
PROPOSAL_EXTENSION = ".csv"
PROPOSAL_CSV_SEPARATOR = ","
PROPOSAL_FILE_TYPE_CSV = 1
