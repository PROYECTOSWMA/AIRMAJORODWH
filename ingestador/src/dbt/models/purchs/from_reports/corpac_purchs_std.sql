{{ config(materialized='ephemeral') }}

SELECT
    NULL                                        AS id,
    s.fecha_de_emision                          AS doc_date,
    s.tipo_cp_doc                               AS doc_type,
    s.serie_del_cdp                             AS doc_serie,
    s.nro_cp_o_doc_nro_inicial_rango            AS doc_number,
    NULL                                        AS doc_due_date,
    s.tipo_doc_identidad                        AS partner_doc_type,
    s.nro_doc_identidad                         AS partner_doc,
    NULL                                        AS qnt_type,
    NULL                                        AS qnt,
    {{ normalize_currency('s.moneda') }}        AS currency,
    -- Convención de signo del consolidado (igual que `sire_purchs_std`):
    -- FACTURA positiva y NOTA DE CRÉDITO (tipo 7) negativa. La negación anterior
    -- (-ROUND) invertía CORPAC frente al resto; con la volteada de `moves`
    -- (todo lo que no es venta -> negativo) dejaría los aterrizajes en POSITIVO.
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', 'ROUND(d.precio_unitario / 1.18, 2)') }}
                                                 AS amnt_taxable,
    {{ prefer_equal_neg('s.tipo_cp_doc', '7', 'ROUND((d.precio_unitario / 1.18) * 0.18, 2)') }}
                                                 AS amnt_taxes,

    {{ normalize_date('d.fecha_llegada', 'DD/MM/YYYY') }}   
                                                AS serv_date,
    d.servicio                                  AS serv_desc,
    {{ extract_cost_center('h.matricula') }}    AS cost_center,
    {{ obtener_aeropuerto('d.aeropuerto_origen') }}  AS serv_org_airport,
    {{ obtener_aeropuerto('d.aeropuerto_destino') }} AS serv_dest_airport,
    NULL                                        AS account,
    CASE
        WHEN h.cliente LIKE '%SELVA%' THEN 'Air Majoro Selva'
        ELSE 'Air Majoro'
    END                                         AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Compras') }}'         AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa

FROM {{ ref('sire_purchs_no_dups') }} s
JOIN from_email_corpac_headers h
    ON (s.serie_del_cdp || printf('%07d', s.nro_cp_o_doc_nro_inicial_rango)) = h.factura
JOIN from_email_corpac_details d                ON d.header_id = h.id
WHERE s.nro_doc_identidad = '20100004675'