{{ config(materialized='ephemeral') }}

SELECT
{% set ref_ruc_adp = "'" ~ var('ruc_adp') ~ "'" %}
{% set ref_tipo   = get_by_sep('a.referencia', "'-'", 0) %}
{% set ref_serie  = 'substr(' ~ get_by_sep('a.referencia', "'-'", 1) ~ ', 2, 5)' %}
{% set ref_numero = get_by_sep('a.referencia', "'-'", 2) %}

    NULL                                        AS id,
    a.fecha                                     AS doc_date,
    {{ ref_tipo }}                              AS doc_type,
    {{ ref_serie }}                             AS doc_serie,
    {{ ref_numero }}                            AS doc_number,
    s.fecha_vcto_pago                           AS doc_due_date,
    '6'                                         AS partner_doc_type,
    {{ ref_ruc_adp }}                           AS partner_doc,
    NULL                                        AS qnt_type,
    NULL                                        AS qnt,
    {{ normalize_currency('a.moneda') }}        AS currency,
    -- Magnitud POSITIVA (factura); la volta a negativo la hace `moves`
    -- (todo lo que no es venta).
    a.imp_unitario                              AS amnt_taxable,
    a.imp_igv                                   AS amnt_taxes,
    COALESCE(
        a.fec_hora_llegada, 
        a.fec_hora_salida,
        a.fecha
        )                                       AS serv_date,
    a.descripcion_servicio                      AS serv_desc,
    {{ extract_cost_center('a.matricula') }}    AS cost_center,
    {{ obtener_aeropuerto('a.origen') }}        AS serv_org_airport,
    {{ obtener_aeropuerto('a.destino') }}       AS serv_dest_airport,
    NULL                                        AS account,
    if(cliente_origen = 'AIR MAJORO S.A.', 'Air Majoro', null) AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Compras') }}'         AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa

FROM from_email_adp_reports a
-- OJO: los tramos de `a.referencia` se sacan con `get_by_sep` y el `car_sunat` con
-- `get_car`, que usa TRY_CAST. Hace falta: hoy hay 60 filas con `referencia` VACÍA
-- (y `servicio` no nulo, así que pasan el filtro) que con un CAST a pelo tumbaban
-- `dbt run` ("Could not convert string '' to INT64"). Con TRY_CAST su clave queda
-- NULL, el INNER JOIN no casa y la fila se descarta sola (sin referencia de
-- documento no hay compra que derivar).
JOIN {{ ref('sire_purchs_no_dups') }} s
    ON s.car_sunat = {{ get_car(ref_ruc_adp, ref_tipo, ref_serie, ref_numero) }}
WHERE a.servicio is not null
