"""Constantes del flujo de la liquidación contable de ventas (SISA).

Empresas y sedes del flujo SISA: viven aquí (no en ``sire_credentials``) porque
este asset no tiene relación con los assets SIRE.
"""

# Endpoint de consulta (POST, sin headers). El body es ``{"sql": <EXECUTE>}``.
SISA_QUERY_URL = "http://38.187.7.111:5500/query"

# El endpoint responde rápido pero a veces tarda (p. ej. Pucallpa, la sede con
# más filas, puede superar los 5s) y a veces se cuelga/encola. Cada intento tiene
# un deadline duro de reloj de ``SISA_QUERY_TIMEOUT_SECONDS``: si una llamada no
# termina en ese tiempo (aunque el servidor vaya mandando datos poco a poco) se
# reintenta hasta ``SISA_QUERY_MAX_ATTEMPTS`` veces y, si sigue sin responder,
# la materialización falla con error claro.
SISA_QUERY_TIMEOUT_SECONDS = 30
SISA_QUERY_MAX_ATTEMPTS = 3

# Plantilla del EXECUTE. Solo varían @CODEMPDOREF/@CODSEDDOREF (empresa/sede) y
# @FECHAINICIO/@FECHATERMIN (el mes de la partición).
SISA_QUERY_SQL_TEMPLATE = (
    "EXECUTE [dbo].[USP_UVW_LIQUIDACION_CONTA] "
    "@CODORGDOREF='01', "
    "@CODEMPDOREF='{cod_emp_doref}', "
    "@CODSEDDOREF='{cod_sed_doref}', "
    "@RAZONSOCIAL=NULL, "
    "@CODNVEDOREF=NULL, "
    "@T01TIPOPAGO=NULL, "
    "@NUMERODERUC=NULL, "
    "@FECHAINICIO='{fecha_inicio}', "
    "@FECHATERMIN='{fecha_termin}'"
)

# Plantilla del EXECUTE de las NOTAS DE CRÉDITO. El procedure
# ``USP_UVW_LIQUIDACION_NOTACREDITO`` tiene los mismos 9 parámetros que
# ``USP_UVW_LIQUIDACION_CONTA`` (verificado consultando ``sys.parameters`` en el
# endpoint), PERO los filtros opcionales hay que pasarlos como **cadena vacía**
# (`''`), no como `NULL`: con `NULL` el procedure devuelve 0 filas (su WHERE
# compara por igualdad y `NULL` no casa con nada). Con `''` (y `@CODNVEDOREF='00'`)
# devuelve las NC reales. Estas filas se RESTAN de las ventas de SISA.
SISA_NC_QUERY_SQL_TEMPLATE = (
    "EXECUTE [dbo].[USP_UVW_LIQUIDACION_NOTACREDITO] "
    "@CODORGDOREF='01', "
    "@CODEMPDOREF='{cod_emp_doref}', "
    "@CODSEDDOREF='{cod_sed_doref}', "
    "@RAZONSOCIAL='', "
    "@CODNVEDOREF='00', "
    "@T01TIPOPAGO='', "
    "@NUMERODERUC='', "
    "@FECHAINICIO='{fecha_inicio}', "
    "@FECHATERMIN='{fecha_termin}'"
)

# Empresas del flujo SISA: código -> nombre comercial.
EMPRESAS = {
    "01": "Air Majoro",
    "02": "Air Majoro Selva",
}

# Sedes a materializar en cada partición: (empresa, sede) -> nombre de la sede.
SEDES = [
    {"cod_emp_doref": "01", "cod_sed_doref": "01", "nombre": "Lima"},
    {"cod_emp_doref": "01", "cod_sed_doref": "02", "nombre": "Nazca"},
    {"cod_emp_doref": "02", "cod_sed_doref": "06", "nombre": "Pucallpa"},
]
