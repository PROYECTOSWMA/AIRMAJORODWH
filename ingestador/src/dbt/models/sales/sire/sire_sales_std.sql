{{ config(materialized='ephemeral') }}

-- Rama SIRE de ventas "expandida": **1 fila por linea de detalle**
-- (`sire_sales_details`). Es SIRE puro: no toca SISA. La cuenta contable, la
-- aeronave y la ruta salen de la liquidacion, que es otra rama (`sisa_sales_std`).
SELECT
    NULL                                        AS id,
    s.fecha_de_emision                          AS doc_date,
    s.tipo_cp_doc                               AS doc_type,
    s.serie_del_cdp                             AS doc_serie,
    s.nro_cp_o_doc_nro_inicial_rango            AS doc_number,
    s.fecha_vcto_pago                           AS doc_due_date,
    s.tipo_doc_identidad                        AS partner_doc_type,
    s.nro_doc_identidad                         AS partner_doc,
    d.des_unidad_medida                         AS qnt_type,
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', 'd.cnt_items') }}
                                                AS qnt,
    {{ normalize_currency('s.moneda') }}        AS currency,

    {% set amnt_taxable_raw = prefer_null('d.id', 'd.mto_val_unitario', 's.bi_gravada') %}
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', amnt_taxable_raw) }}
                                                AS amnt_taxable,

    {% set amnt_taxes_raw = prefer_null('d.id', 'd.mto_imp_total - d.mto_val_unitario', 's.igv_ipm') %}
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', amnt_taxes_raw) }}
                                                AS amnt_taxes,

    s.fecha_de_emision                          AS serv_date,
    d.des_item                                  AS serv_desc,
    NULL                                        AS cost_center,
    NULL                                        AS serv_org_airport,
    NULL                                        AS serv_dest_airport,
    '700000'                                    AS account,
    s.empresa                                   AS company,

    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Ventas') }}'          AS move_type,
    s.id                                        AS source_sire_sales,
    d.id                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa
FROM {{ ref('sire_sales_no_dups') }} s
LEFT JOIN sire_sales_details d ON d.sire_sale_id = s.id
