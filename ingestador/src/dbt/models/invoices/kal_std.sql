{{ config(materialized='ephemeral') }}

-- `ephemeral` (a propósito): se inlinea en `invoice_std`. OJO con el bug de
-- DuckDB que obliga al `disabled_optimizers` de `profiles.yml` (ver la nota allí).

-- **Facturas de Kal-Airparts / Kal-Aviation** en el contrato de 27 columnas del
-- DWH: una fila por línea de factura.
--
-- Kal imprime **dos cantidades** (``order_qty`` y ``ship_qty``): al DWH va la
-- **facturada** (``ship_qty``). El ``amount`` es el total de la línea (sin IGV) y
-- ``unit_price`` el valor unitario. ``serv_date``/``cost_center`` salen de la orden
-- de compra (``po_cost_center``). Cuenta **603301 (CONSUMIBLES)**.
WITH factura AS (
    SELECT
        h.invoice_number,
        h.invoice_date,
        h.po_number,
        d.item,
        d.part_number,
        d.description,
        d.condition,
        d.order_qty,
        d.ship_qty,
        d.unit_price,
        d.amount
    FROM static_invoice_kal_header h
    JOIN static_invoice_kal_details d
        ON d.source_file = h.source_file
)

SELECT
    NULL                                            AS id,
    f.invoice_date                                  AS doc_date,
    NULL                                            AS doc_type,
    {{ split_invoice_doc('f.invoice_number', 'serie') }}  AS doc_serie,
    TRY_CAST({{ split_invoice_doc('f.invoice_number', 'numero') }} AS BIGINT)
                                                    AS doc_number,
    NULL                                            AS doc_due_date,
    '0'                                             AS partner_doc_type,
    -- Proveedor extranjero SIN RUC: código sintético ``INVC-<nombre>`` (la CARPETA
    -- es el proveedor); `partners` le pone el nombre como descripción.
    'INVC-KAL AIRPARTS'                             AS partner_doc,
    NULL                                            AS qnt_type,
    TRY_CAST(f.ship_qty AS DECIMAL(18,3))           AS qnt,
    'USD'                                           AS currency,
    TRY_CAST(f.amount AS DECIMAL(18,6))             AS amnt_taxable,
    0                                               AS amnt_taxes,
    COALESCE(po_part.po_date, po_gen.po_date, f.invoice_date) AS serv_date,
    f.description                                   AS serv_desc,
    COALESCE(po_part.cost_center, po_gen.cost_center) AS cost_center,
    NULL                                            AS serv_org_airport,
    NULL                                            AS serv_dest_airport,
    '603301'                                        AS account,
    'Air Majoro'                                    AS company,
    NULL                                            AS error,
    {{ now_utc() }}                                 AS ingested_at,
    '{{ var('move_type', 'Compras') }}'             AS move_type,
    NULL                                            AS source_sire_sales,
    NULL                                            AS source_sire_sales_details,
    NULL                                            AS source_sisa,
    -- Tipo de mantenimiento que aporta la orden (columna TIPO DE MANTENIMIENTO del
    -- formulario de la PO): por P/N y, si la orden entera tiene uno solo, el de toda
    -- la orden (ver `po_cost_center`). Es la columna 27 del contrato, la que baja a
    -- `moves` como `appended_tipo_mantenimiento`.
    COALESCE(po_part.appended_tipo_mantenimiento, po_gen.appended_tipo_mantenimiento)
                                                    AS appended_tipo_mantenimiento
FROM factura f
LEFT JOIN {{ ref('po_cost_center') }} po_part
    ON po_part.po_key = {{ invoice_po_key('f.po_number') }}
    AND po_part.part_key = regexp_replace(upper(trim(f.part_number)), '[^A-Z0-9]', '', 'g')
LEFT JOIN {{ ref('po_cost_center') }} po_gen
    ON po_gen.po_key = {{ invoice_po_key('f.po_number') }}
    AND po_gen.part_key = '*'
