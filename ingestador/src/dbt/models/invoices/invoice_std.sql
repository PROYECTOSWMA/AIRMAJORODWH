{{ config(materialized='table') }}

-- **Todas las facturas del exterior** en el contrato de 27 columnas del DWH: la
-- unión de los seis proveedores, uno por modelo (mismo enfoque que ``purchs_std``
-- con sus ramas), **más las órdenes de compra que no tienen factura**.
--
-- Es la rama que entra en ``purchs_std`` (y de ahí a ``moves`` → EERR) con la
-- cuenta **603301 (CONSUMIBLES, COSTO DE VENTAS)**, como pidió el cliente.
--
-- Cada compra entra **una sola vez**: si tiene factura entra la factura (con el
-- centro de costo, la fecha de servicio y el tipo de mantenimiento que le aporta la
-- orden vía ``po_cost_center``); si **no** tiene factura entra la orden con lo que
-- ella misma dice (CTE ``orden``). Sumar las dos duplicaría el consumo del exterior,
-- así que la orden se descarta en cuanto aparece su factura.
--
-- ⚠️ Seis ramas `ephemeral` en un mismo `UNION ALL` + bug de DuckDB: el
-- optimizador `cte_inlining` mezclaba las ramas y devolvía las filas de otra
-- (las 5 de Peniel salían como las 6 de JetSet ⇒ 461.565,00 en vez de 459,30).
-- Por eso `profiles.yml` lleva `disabled_optimizers: cte_inlining`. Si algún día
-- se quita esa opción, comprobar SIEMPRE estas cifras antes de publicar:
-- Fenix 61 · JetSet 9 · Kal 13 · **Peniel 5** · Precision 9 · Textron 65 = **162**
-- líneas de **factura** (más las líneas de las órdenes sin factura que añade el
-- `UNION ALL` del final: 25).
WITH facturas AS (
    -- Nº de PO (clave canónica) de cada factura del exterior: las 6 carpetas.
    SELECT DISTINCT {{ invoice_po_key('po_number') }} AS po_key
    FROM static_invoice_fenix_header
    UNION
    SELECT DISTINCT {{ invoice_po_key('po_number') }} FROM static_invoice_jetset_header
    UNION
    SELECT DISTINCT {{ invoice_po_key('po_number') }} FROM static_invoice_kal_header
    UNION
    SELECT DISTINCT {{ invoice_po_key('po_number') }} FROM static_invoice_peniel_header
    UNION
    SELECT DISTINCT {{ invoice_po_key('po_number') }} FROM static_invoice_precision_header
    UNION
    SELECT DISTINCT {{ invoice_po_key('po_number') }} FROM static_invoice_textron_header
),

orden AS (
    -- **Órdenes de compra de los 6 proveedores**: una fila por ítem de la orden, con
    -- la información de la propia orden. El **proveedor se sabe por su carpeta** (una
    -- carpeta = un proveedor, igual que en las facturas): de ahí sale el
    -- ``partner_doc``, con el MISMO código que usan las facturas de ese proveedor
    -- (las carpetas se llaman distinto: 'FENIX' vs 'FENIX AEROSPACE', 'PRECISION
    -- HELIPARTS (PAG)' vs 'PRECISION HELIPARTS'). El Nº de PO se cruza con las
    -- facturas por la clave canónica (`invoice_po_key`).
    SELECT
        -- 'PO 687-2026' -> 687 (número correlativo de la orden).
        TRY_CAST(
            trim({{ get_by_sep("trim(regexp_replace(upper(h.po_number), '^PO\\\\.?', ''))", "'-'", 0) }})
            AS BIGINT
        )                                               AS po_number,
        h.po_number                                     AS po_number_raw,
        h.po_date,
        h.source_file,
        h.currency,
        d.part_number,
        d.description,
        d.qty,
        d.um,
        d.total_cost,
        COALESCE(
            {{ normalize_registration('d.cc') }},
            {{ normalize_registration('d.aeronave') }}
        )                                               AS cost_center,
        NULLIF(trim(d.maintenance_note), '')             AS tipo_mantenimiento
    FROM static_invoice_po_header h
    JOIN static_invoice_po_details d
        ON d.source_file = h.source_file
    WHERE h.po_number IS NOT NULL
      -- Muchas órdenes imprimen filas de relleno sin ningún dato (solo el Nº de
      -- ítem): se descartan para no meter filas vacías en `moves`.
      AND (
            NULLIF(trim(d.part_number), '') IS NOT NULL
         OR NULLIF(trim(d.total_cost), '') IS NOT NULL
         OR NULLIF(trim(d.qty), '') IS NOT NULL
         OR NULLIF(trim(d.description), '') IS NOT NULL
      )
      -- Y solo las órdenes que NO tienen factura (su compra ya entra por la factura).
      AND NOT EXISTS (
            SELECT 1
            FROM facturas f
            WHERE f.po_key = {{ invoice_po_key('h.po_number') }}
      )
)
SELECT * FROM {{ ref('fenix_std') }}
UNION ALL
SELECT * FROM {{ ref('jetset_std') }}
UNION ALL
SELECT * FROM {{ ref('kal_std') }}
UNION ALL
SELECT * FROM {{ ref('peniel_std') }}
UNION ALL
SELECT * FROM {{ ref('precision_std') }}
UNION ALL
SELECT * FROM {{ ref('textron_std') }}
UNION ALL
-- Las órdenes **sin** factura: su compra entra con lo que dice la propia orden.
SELECT
    NULL                                            AS id,
    o.po_date                                       AS doc_date,
    NULL                                            AS doc_type,
    o.po_number_raw                                 AS doc_serie,
    o.po_number                                     AS doc_number,
    NULL                                            AS doc_due_date,
    '0'                                             AS partner_doc_type,
    -- El **proveedor por la carpeta** de la orden; mismo código que usan sus
    -- facturas para que el reporte los agrupe (si mañana aparece otra carpeta, la
    -- orden entra igual y solo queda sin proveedor).
    CASE split_part(o.source_file, '/', 1)
        WHEN 'FENIX'                     THEN 'INVC-FENIX AEROSPACE'
        WHEN 'JETSET'                    THEN 'INVC-JETSET'
        WHEN 'KAL AIRPARTS'              THEN 'INVC-KAL AIRPARTS'
        WHEN 'PENIEL'                    THEN 'INVC-PENIEL'
        WHEN 'PRECISION HELIPARTS (PAG)' THEN 'INVC-PRECISION HELIPARTS'
        WHEN 'TEXTRON'                   THEN 'INVC-TEXTRON'
    END                                             AS partner_doc,
    o.um                                            AS qnt_type,
    TRY_CAST(o.qty AS DECIMAL(18,3))                AS qnt,
    COALESCE(o.currency, 'USD')                     AS currency,
    TRY_CAST(o.total_cost AS DECIMAL(18,6))         AS amnt_taxable,
    0                                               AS amnt_taxes,
    o.po_date                                       AS serv_date,
    o.description                                   AS serv_desc,
    o.cost_center                                   AS cost_center,
    NULL                                            AS serv_org_airport,
    NULL                                            AS serv_dest_airport,
    '603301'                                        AS account,
    'Air Majoro'                                    AS company,
    NULL                                            AS error,
    {{ now_utc() }}                                 AS ingested_at,
    'Compras'                                       AS move_type,
    NULL                                            AS source_sire_sales,
    NULL                                            AS source_sire_sales_details,
    NULL                                            AS source_sisa,
    -- El tipo de mantenimiento lo trae la propia orden (no hay factura que completar).
    o.tipo_mantenimiento                            AS appended_tipo_mantenimiento
FROM orden o
