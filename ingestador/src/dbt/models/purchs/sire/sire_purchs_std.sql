{{ config(materialized='ephemeral') }}

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
    -- Importe de la línea. Si SIRE trae DETALLE (30.267 filas), manda el detalle.
    --
    -- ⚠️ Si NO trae detalle (543 compras) SIRE solo informa a nivel de comprobante,
    -- y no siempre en `bi_gravado_dg`: hay **395 compras con base gravada 0** cuyo
    -- importe está en otro sitio — los **DAM de importación (tipo 54: 66 filas /
    -- 93.323,00 S/, todo en `otros_trib_cargos`)** y las **facturas de banco y
    -- servicios no gravados (tipo 1: 324 filas / 383.459,11 S/, en
    -- `valor_adq_ng`+`total_cp`)**. Con solo `bi_gravado_dg` entraban a `moves`
    -- con **importe 0** (476.782,11 S/ que se perdían del EERR y salían como filas
    -- "vacías" en el reporte gerencial; detectado el 2026-10-09).
    -- La cadena es: base gravada → bases no gravadas → total del comprobante menos
    -- sus tributos repercutibles (IGV/ISC/ICBPER). NUNCA se reparte el total del
    -- padre entre las líneas hijas: solo se usa cuando NO hay detalle.
    {% set bases_no_gravadas = 'NULLIF(
            coalesce(s.bi_gravado_dgng, 0)
            + coalesce(s.bi_gravado_dng, 0)
            + coalesce(s.valor_adq_ng, 0), 0)' %}
    {% set total_menos_tributos = 's.total_cp
            - coalesce(s.igv_ipm_dg, 0) - coalesce(s.isc, 0) - coalesce(s.icbper, 0)' %}
    {% set amnt_taxable_raw = prefer_null(
        'd.id',
        'd.mto_val_unitario * d.cnt_items',
        'coalesce(NULLIF(s.bi_gravado_dg, 0), ' ~ bases_no_gravadas
            ~ ', ' ~ total_menos_tributos ~ ')',
    ) %}
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', amnt_taxable_raw) }}
                                                AS amnt_taxable,
    {% set amnt_taxes_raw = prefer_null('d.id', 'd.mto_imp_total - d.mto_val_unitario * d.cnt_items', 's.igv_ipm_dg') %}
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', amnt_taxes_raw) }}
                                                AS amnt_taxes,
    s.fecha_de_emision                          AS serv_date,
    d.des_item                                  AS serv_desc,
    -- El centro de costo NO se resuelve aquí: lo hace `compras` (al final, sobre
    -- la unión de las 4 vías), cruzando con el modelo `cost_centers`.
    NULL                                        AS cost_center,
    NULL                                        AS serv_org_airport,
    NULL                                        AS serv_dest_airport,
    NULL                                        AS account,
    s.empresa                                   AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Compras') }}'         AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa

-- Rama SIRE de compras (1 fila por detalle) normalizada a las 26 columnas.
-- Está en formato estándar y NO aplica reglas transversales: ni el filtro de los
-- proveedores con vía propia (CORPAC / ADP / LAP) ni el centro de costo. Las dos
-- los aplica `compras`, que es el modelo final de la unión.
FROM {{ ref('sire_purchs_no_dups') }} s
LEFT JOIN sire_purchs_details d ON d.sire_purch_id = s.id
