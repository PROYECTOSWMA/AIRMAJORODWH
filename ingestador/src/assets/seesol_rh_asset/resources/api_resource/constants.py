"""Constantes del flujo HTTP del reporte RH del SEE-SOL (recibos por honorarios).

Todo lo que es "protocolo" del portal de SUNAT vive aquí: URLs del menú SOL y de
la app **"Consulta Receptor"** del SEE (``11.5.1.1.14``), el controlador Struts
``cpelec001Alias`` y los campos que espera cada POST, más las cabeceras de
navegador que el portal exige (sin ellas el WAF contesta ``Request Rejected``).
Los valores están verificados **en vivo el 2026-09-17** (ver
``memory-bank/activeContext.md``).
"""

# Protocolo común del portal (URL del menú, `action=fails`, cabeceras de
# navegador y tipo de logueo): una sola definición, en
# `assets/sire_assets/resources/sol_portal.py`.
from assets.sire_assets.resources.sol_portal import (  # noqa: F401
    HEADERS,
    MENU_URL,
    TIPO_LOGUEO_RUC,
    URL_FAILS,
)

# App del menú SOL: 11 → "Comprobantes de Pago" → SEE-SOL → "Recibo por
# Honorarios Electrónicos" → "Consulta Receptor" (`cpelec001Alias` en ww1).
APP_RECEPTOR = "11.5.1.1.14"
# Lo que hace el JS del menú al pulsar la app: `action=execute&code=<app>` responde
# **302** al controlador de la app.
URL_EJECUTE = MENU_URL + "?action=execute&code={app}"

# Ruta (relativa al host del portal) del controlador Struts de la app SEE.
FORM_PATH = "/ol-ti-itreciboelectronico/cpelec001Alias"
# POST con los criterios de búsqueda y POST del botón "Descargar Reporte".
ACCION_CRITERIO = "CapturaCriterioConsulatRec1"
ACCION_DESCARGA = "descargaConsultaReceptor"
# Los 3 tipos de documento que trae el formulario y que el JS concatena en el
# campo oculto `tipocomprobante` (`01`=RH, `02`=NC, `03`=otros ingresos 4ta).
TIPOS_DOC = "01;02;03;"
# `tipoestado=00` = todos los estados (el formulario no filtra por estado).
ESTADO_TODOS = "00"
# El portal rechaza (alert del navegador) los rangos de más de 1 mes.
MAX_DIAS = 32

# Empresas del reporte RH: nombres tal cual aparecen en
# ``env/sire_credentials.json`` (el ``name`` con el que se busca su RUC/usuario).
EMPRESAS = ["Air Majoro", "Air Majoro Selva"]

# El portal corta las peticiones que no parecen de un navegador: las cabeceras
# `HEADERS` (y el `TIPO_LOGUEO_RUC` del form) se importan de `sol_portal` arriba.

# Marcas del reporte que devuelve el portal (16 columnas separadas por `|`).
CABECERA_REPORTE = "Fecha de Emisión|"
SIN_REGISTROS = "No se han encontrado registros"
