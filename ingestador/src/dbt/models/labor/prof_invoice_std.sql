{{ config(materialized='ephemeral') }}

SELECT
    NULL                                        AS id,
    {{ normalize_date('rh.fecha_de_emision', 'DD/MM/YYYY') }} 
                                                AS doc_date,
    CASE
        WHEN upper(rh.tipo_doc_emitido) = 'RH' THEN 2
        WHEN upper(rh.tipo_doc_emitido) = 'NC' THEN 7
        ELSE NULL
    END                                         AS doc_type,
    CASE
        WHEN instr(rh.nro_doc_emitido, '-') > 0
            THEN substr(rh.nro_doc_emitido, 1, instr(rh.nro_doc_emitido, '-') - 1)
        ELSE rh.nro_doc_emitido
    END                                         AS doc_serie,
    CASE
        WHEN instr(rh.nro_doc_emitido, '-') > 0
            THEN CAST(substr(rh.nro_doc_emitido, instr(rh.nro_doc_emitido, '-') + 1) AS BIGINT)
        ELSE NULL
    END                                         AS doc_number,
    NULL                                        AS doc_due_date,
    rh.tipo_de_doc_emisor                       AS partner_doc_type,
    rh.nro_doc_emisor                           AS partner_doc,
    'RH'                                        AS qnt_type,
    1                                           AS qnt,
    {{ normalize_currency('rh.moneda_de_operacion') }}
                                                AS currency,
    rh.renta_bruta                              AS amnt_taxable,
    rh.impuesto_a_la_renta                      AS amnt_taxes,
    {{ normalize_date('rh.fecha_de_emision', 'DD/MM/YYYY') }} 
                                                AS serv_date,
    rh.descripcion                              AS serv_desc,
    NULL                                        AS cost_center,
    NULL                                        AS serv_org_airport,
    NULL                                        AS serv_dest_airport,
    -- Cuenta de la vía RH (recibos por honorarios). Prioridad:
    --   1) regla explícita del emisor (DNI) en `aux_accounts_assignment`;
    --   2) descripción que mencione "APOYO MEDICO" -> SERVICIOS MEDICOS (639902);
    --   3) COSTO DE PERSONAL / planilla (621101) por defecto.
    -- El patrón `'%APOYO M%EDICO%'` tolera el acento ("APOYO MÉDICO") y mayúsculas.
    COALESCE(
        (
            SELECT r.account
            FROM {{ ref('aux_accounts_assignment') }} r
            WHERE r.partner_doc = rh.nro_doc_emisor
            AND (
                r.serv_desc_pattern IS NULL
                OR r.serv_desc_pattern = ''
                OR instr(upper(rh.descripcion), upper(r.serv_desc_pattern)) > 0
            )
            ORDER BY length(r.serv_desc_pattern) DESC NULLS LAST
            LIMIT 1
        ),
        CASE WHEN rh.descripcion ILIKE '%APOYO M%EDICO%' THEN '639902' END,
        '621101'
    )                                           AS account,
    rh.empresa                                  AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    'Compras'                                   AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa
FROM seesol_rh rh
