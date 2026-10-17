"""Asset mensual del reporte RH (recibos por honorarios) del SEE-SOL de SUNAT.

Antes el reporte se bajaba con ``scripts/sol_rh_seesol.py`` a los TXT estáticos
``static/RH/<empresa>/MM.txt`` y lo ingería ``static_data_asset`` (partición
anual). Ahora el RH tiene su **propio asset al primer nivel** de ``assets/``
(``seesol_rh_monthly``), con **partición mensual**, y la vía HTTP vive en su
``resources/api_resource``: el asset pide a SUNAT el reporte del mes (1 login
por empresa y mes) y lo ingiere en ``db.sqlite``. Mantiene el layout del patrón
del repo: un asset por carpeta
(``seesol_rh_asset.py``), ``models/`` (peewee), ``parsers/`` (el texto
pipe-delimited de 16 columnas), ``resources/api_resource/`` (login del portal
SOL + app "Consulta Receptor" + descarga) y ``resources/db_resource.py`` (el
upsert de ``seesol_rh`` por ``(period, empresa)``). Ya **no** hay ficheros
intermedios en ``static/RH``.
"""
