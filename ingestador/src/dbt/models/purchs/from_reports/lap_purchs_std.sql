{{ config(materialized='ephemeral') }}

SELECT
    NULL                                        AS id,
    {{ normalize_date('l.fecha_factura', 'DD/MM/YYYY') }} 
                                                AS doc_date,
    -- Documento 'TT-SSSS-NNNNNNNN' (tipo-serie-número)
    CAST(substr(l.factura, 1, 2) AS BIGINT)    AS doc_type,
    substr(l.factura, 4, 4)                     AS doc_serie,
    CAST(substr(l.factura, 9) AS BIGINT)       AS doc_number,

    NULL                                        AS doc_due_date,
    '6'                                         AS partner_doc_type,
    '20501577252'                               AS partner_doc,
    NULL                                        AS qnt_type,
    NULL                                        AS qnt,
    {{ normalize_currency('l.moneda') }}        AS currency,
    -- Magnitud POSITIVA (factura); la volta a negativo la hace `moves`
    -- (todo lo que no es venta).
    l.importe_bruto                             AS amnt_taxable,
    l.importe_igv                               AS amnt_taxes,
    {{ normalize_date('l.fecha_factura', 'DD/MM/YYYY') }} 
                                                AS serv_date,
    l.servicio                                  AS serv_desc,
    {{ extract_cost_center('l.matricula') }}    AS cost_center,
    {{ obtener_aeropuerto('l.origen') }}        AS serv_org_airport,
    {{ obtener_aeropuerto('l.destino') }}       AS serv_dest_airport,
    NULL                                        AS account,
    'Air Majoro'                                AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Compras') }}'         AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa

FROM static_lap_reports l
WHERE l.factura IS NOT NULL AND l.factura <> ''
AND l.factura LIKE '%-%-%'
