{{ config(materialized='ephemeral') }}

-- `ephemeral` (a propósito): se inlinea en `invoice_std`. OJO con el bug de
-- DuckDB que obliga al `disabled_optimizers` de `profiles.yml` (ver la nota allí).

-- **Facturas de Fenix Aerospace** en el contrato de 27 columnas del DWH
-- (el mismo de ``purchs_std``): una fila por **línea de factura**.
--
--   * ``doc_date``   = fecha de la factura; ``doc_number`` = Nº (serie aparte).
--   * ``serv_date``  = **fecha de la orden de compra** (la del servicio).
--   * ``cost_center``= **aeronave de la PO** (cruce por Nº de PO y P/N: ver
--     ``po_cost_center``); si la línea no casa por P/N se usa el centro de costo
--     de la PO cuando la orden entera apunta a una sola aeronave.
--   * ``amnt_taxable`` = importe de la línea **sin IGV** (factura de exportación);
--     ``amnt_taxes`` = 0. Magnitud POSITIVA: el signo lo pone ``moves``.
--   * ``account`` = **603301** (CONSUMIBLES, COSTO DE VENTAS): todo el exterior va
--     ahí, como pidió el cliente (estos proveedores no tienen regla por RUC).
--   * ``currency`` = USD; ``company`` = Air Majoro.
WITH factura AS (
    SELECT
        h.invoice_number,
        h.invoice_date,
        h.po_number,
        h.currency,
        d.part_number,
        d.line_number,
        d.description,
        d.condition,
        d.qty,
        d.uom,
        d.unit_price,
        d.amount
    FROM static_invoice_fenix_header h
    JOIN static_invoice_fenix_details d
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
    -- El proveedor es extranjero y no tiene RUC: se identifica con un código
    -- sintético ``INVC-<nombre del proveedor>`` (la CARPETA es el proveedor) y
    -- `partners` le pone su nombre como descripción. Su tax id del PDF no se
    -- pierde: sigue en ``static_invoice_fenix_header.vat_tax_id``.
    'INVC-FENIX AEROSPACE'                          AS partner_doc,
    f.uom                                           AS qnt_type,
    TRY_CAST(f.qty AS DECIMAL(18,3))                AS qnt,
    COALESCE(f.currency, 'USD')                     AS currency,
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
