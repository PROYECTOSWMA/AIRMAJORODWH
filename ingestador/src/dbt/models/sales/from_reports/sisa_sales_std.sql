{{ config(materialized='ephemeral') }}

-- Rama SISA (liquidaciones) en formato estandar: **1 fila por documento**.
-- La base es `sisa_sales` y se complementa con `sire_sales` (solo el encabezado:
-- unir `sire_sales_details` expandiria las filas y aqui no hacen falta).
-- SISA no trae fecha de vencimiento ni tipo de documento, y su RUC de cliente
-- viene vacio en la mayoria de filas: eso es lo que aporta `sire_sales`.
-- `nro_documento` viene como '<serie>-<numero>' (p. ej. 'F001-5007').
WITH sire AS (
    -- Encabezado SIRE con su clave de documento, para poder cruzar por columna.
    SELECT
        s.*,
        s.serie_del_cdp || '-' || CAST(s.nro_cp_o_doc_nro_inicial_rango AS TEXT) AS doc_key
    FROM {{ ref('sire_sales_no_dups') }} s
)

SELECT
    NULL                                        AS id,
    sisa.fechaemisio                            AS doc_date,
    COALESCE(s.tipo_cp_doc,
             CASE sisa.t01tipdoref WHEN 'FT' THEN 1 WHEN 'BV' THEN 3 END)
                                                AS doc_type,
    substr(sisa.nro_documento, 1, instr(sisa.nro_documento, '-') - 1)
                                                AS doc_serie,
    CAST(substr(sisa.nro_documento, instr(sisa.nro_documento, '-') + 1) AS BIGINT)
                                                AS doc_number,
    s.fecha_vcto_pago                           AS doc_due_date,
    s.tipo_doc_identidad                        AS partner_doc_type,
    COALESCE(sisa.ruc_cliente20, sisa.numeroderuc, s.nro_doc_identidad)
                                                AS partner_doc,
    NULL                                        AS qnt_type,
    sisa.cantidad                               AS qnt,
    {{ normalize_currency('sisa.nomtipmoned') }} AS currency,
    COALESCE(sisa.dorefsubtot,
             sisa.doreftotnum - sisa.dorefimpimp,
             s.bi_gravada)                      AS amnt_taxable,
    COALESCE(sisa.dorefimpimp, s.igv_ipm)       AS amnt_taxes,
    COALESCE(sisa.fechavuelo, sisa.fechaemisio)
                                                AS serv_date,
    sisa.observacion                            AS serv_desc,
    {{ extract_cost_center('sisa.aenavmatric') }} AS cost_center,
    {{ capitalize_words('sisa.desorigen') }}    AS serv_org_airport,
    {{ capitalize_words('sisa.desdestino') }}   AS serv_dest_airport,
    CASE nombre_sede
    WHEN 'Lima' THEN 704101 WHEN 'Nazca' THEN 704102 
    WHEN 'Pucallpa' THEN 704103 ELSE NULL END
                                                AS account,
    sisa.nombre_empresa                         AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Ventas') }}'          AS move_type,
    s.id                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    sisa.id                                     AS source_sisa
FROM sisa_sales sisa
LEFT JOIN sire s
    ON s.doc_key = sisa.nro_documento
    AND s.empresa = sisa.nombre_empresa
    AND s.tipo_cp_doc = CASE sisa.t01tipdoref WHEN 'FT' THEN 1 WHEN 'BV' THEN 3 END
