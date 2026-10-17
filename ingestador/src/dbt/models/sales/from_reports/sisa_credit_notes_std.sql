{{ config(materialized='ephemeral') }}

-- Rama de las NOTAS DE CRÉDITO de SISA (`sisa_credit_notes`, la ingiere el asset
-- `sisa_sales_monthly` desde el procedure `USP_UVW_LIQUIDACION_NOTACREDITO`).
-- Se mapean a las 26 columnas del contrato de ventas con los importes en NEGATIVO:
-- en `moves` las ventas van en POSITIVO (`move_type ILIKE 'Ventas%'` => *1), así
-- que una nota de crédito debe restar de las ventas. La cuenta es la MISMA que la
-- de la sede en `sisa_sales_std`, para que netee en la misma línea del EERR.
WITH nc AS (
    SELECT * FROM sisa_credit_notes
)

SELECT
    NULL                                        AS id,
    nc.fechaemisio                              AS doc_date,
    7                                           AS doc_type,
    nc.sunatnserie                              AS doc_serie,
    TRY_CAST(nc.sunatnforma AS BIGINT)          AS doc_number,
    NULL                                        AS doc_due_date,
    NULL                                        AS partner_doc_type,
    nc.numeroderuc                              AS partner_doc,
    NULL                                        AS qnt_type,
    NULL                                        AS qnt,
    {{ normalize_currency('nc.nomtipmoned') }}  AS currency,
    -COALESCE(nc.dorefsubtot, nc.doreftotnum - nc.dorefimpimp)
                                                AS amnt_taxable,
    -nc.dorefimpimp                             AS amnt_taxes,
    COALESCE(nc.fechavuelo, nc.fechaemisio)     AS serv_date,
    COALESCE(NULLIF(nc.nomsitdoref, ''), nc.razonsocial)
                                                AS serv_desc,
    NULL                                        AS cost_center,
    NULL                                        AS serv_org_airport,
    NULL                                        AS serv_dest_airport,
    -- Cuenta de la sede del ORIGEN de la NC. La serie de la propia NC indica la
    -- sede (001 Lima, 002 Nazca, 006 Pucallpa), que es la misma cuenta que la
    -- venta que reduce. Fallback por `nombre_sede` (las 3 sedes del pipeline).
    CASE
        WHEN nc.sunatnserie LIKE 'F001%' OR nc.sunatnserie LIKE 'B001%' THEN 704101
        WHEN nc.sunatnserie LIKE 'F002%' OR nc.sunatnserie LIKE 'B002%' THEN 704102
        WHEN nc.sunatnserie LIKE 'F006%' OR nc.sunatnserie LIKE 'B006%' THEN 704103
        WHEN nc.nombre_sede = 'Lima' THEN 704101
        WHEN nc.nombre_sede = 'Nazca' THEN 704102
        WHEN nc.nombre_sede = 'Pucallpa' THEN 704103
    END                                         AS account,
    nc.nombre_empresa                           AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Ventas') }}'          AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    nc.id                                       AS source_sisa
FROM nc
