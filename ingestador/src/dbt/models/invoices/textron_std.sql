{{ config(materialized='ephemeral') }}

-- `ephemeral` (a propósito): se inlinea en `invoice_std`. OJO con el bug de
-- DuckDB que obliga al `disabled_optimizers` de `profiles.yml` (ver la nota allí).

-- **Facturas de Textron Aviation** en el contrato de 27 columnas del DWH: una fila
-- por línea de factura.
--
-- OJO con el precio: la factura imprime **dos** (``list_price`` y ``unit_price``);
-- al DWH va el **``unit_price``** (sin IGV), que es el que se cruza con la PO.
-- ``quantity`` es la cantidad facturada y el ``amount`` el total de la línea.
-- ``serv_date``/``cost_center`` salen de la orden de compra (``po_cost_center``).
-- Cuenta **603301 (CONSUMIBLES)**; ``currency`` USD (o la que imprima la factura).
WITH factura AS (
    SELECT
        h.invoice_number,
        h.invoice_date,
        h.due_date,
        h.po_number,
        h.currency,
        d.line,
        d.part_number,
        d.description_1,
        d.description_2,
        d.list_price,
        d.discount,
        d.quantity,
        d.uom,
        d.unit_price,
        d.amount
    FROM static_invoice_textron_header h
    JOIN static_invoice_textron_details d
        ON d.source_file = h.source_file
)

SELECT
    NULL                                            AS id,
    f.invoice_date                                  AS doc_date,
    NULL                                            AS doc_type,
    {{ split_invoice_doc('f.invoice_number', 'serie') }}  AS doc_serie,
    TRY_CAST({{ split_invoice_doc('f.invoice_number', 'numero') }} AS BIGINT)
                                                    AS doc_number,
    f.due_date                                      AS doc_due_date,
    '0'                                             AS partner_doc_type,
    -- El proveedor es extranjero y no tiene RUC: se identifica con un código
    -- sintético ``INVC-<nombre del proveedor>`` (la CARPETA es el proveedor) y
    -- `partners` le pone su nombre como descripción. Su tax id del PDF no se
    -- pierde: sigue en ``static_invoice_textron_header.fed_tax_id``.
    'INVC-TEXTRON'                                  AS partner_doc,
    f.uom                                           AS qnt_type,
    TRY_CAST(f.quantity AS DECIMAL(18,3))           AS qnt,
    COALESCE(f.currency, 'USD')                     AS currency,
    TRY_CAST(f.amount AS DECIMAL(18,6))             AS amnt_taxable,
    0                                               AS amnt_taxes,
    COALESCE(po_part.po_date, po_gen.po_date, f.invoice_date) AS serv_date,
    NULLIF(
        trim(COALESCE(f.description_1, '') || ' ' || COALESCE(f.description_2, '')),
        ''
    )                                               AS serv_desc,
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
