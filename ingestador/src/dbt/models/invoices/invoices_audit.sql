{{ config(materialized='table') }}

-- **Trazabilidad de lo que se ingirió** (pestaña *Técnico - Invoices* del dashboard):
-- una fila por **línea** de cada documento leído de `static/INVOICE INTERNACIONALES`,
-- con el **fichero** del que sale (para poder abrirlo a mano), el documento, la
-- **orden de compra** con la que cruzó y los importes. Responde sin dudas a: ¿qué
-- ficheros entraron?, ¿cuántas líneas trae cada uno?, ¿encontró su orden?, ¿la suma de
-- las líneas cuadra con el total del documento?
--
-- `total_documento` viene de la cabecera y **se repite en todas las líneas** del mismo
-- fichero (la página lo compara con `sum(importe)` por documento). Es NULL cuando el
-- documento no imprime total (p. ej. las órdenes de reparación que se emiten sin coste:
-- "we send our formal PO when receive the final cost").
--
-- `po_encontrada` = el Nº de orden de la factura existe en el maestro de órdenes
-- (`static_invoice_po_header`, clave canónica `invoice_po_key`). Si es FALSE, esa
-- factura **no** puede completarse con aeronave ni tipo de mantenimiento.
WITH documentos AS (
    SELECT 'FACTURA' AS tipo_documento, 'INVC-FENIX AEROSPACE' AS proveedor,
           h.source_file, h.invoice_number AS documento, h.invoice_date AS fecha,
           h.po_number, h.currency,
           d.line_number AS item, d.part_number, d.description AS descripcion,
           d.qty AS qnt, d.uom, d.unit_price AS precio_unitario, d.amount AS importe,
           h.subtotal AS subtotal_documento, h.total AS total_documento
    FROM static_invoice_fenix_header h
    JOIN static_invoice_fenix_details d ON d.source_file = h.source_file
    UNION ALL
    SELECT 'FACTURA', 'INVC-JETSET',
           h.source_file, h.invoice_number, h.invoice_date, h.po_number, h.currency,
           d.item, d.part_number, d.description, d.shipped, d.uom, d.unit_price, d.amount,
           h.subtotal, h.total
    FROM static_invoice_jetset_header h
    JOIN static_invoice_jetset_details d ON d.source_file = h.source_file
    UNION ALL
    SELECT 'FACTURA', 'INVC-KAL AIRPARTS',
           h.source_file, h.invoice_number, h.invoice_date, h.po_number, h.currency,
           d.item, d.part_number, d.description, d.ship_qty, NULL, d.unit_price, d.amount,
           h.total_due, h.total_due
    FROM static_invoice_kal_header h
    JOIN static_invoice_kal_details d ON d.source_file = h.source_file
    UNION ALL
    SELECT 'FACTURA', 'INVC-PENIEL',
           h.source_file, h.invoice_number, h.invoice_date, h.po_number, h.currency,
           d.item, d.part_number, d.description, d.shipped, d.uom, d.unit_price, d.amount,
           h.subtotal, h.total
    FROM static_invoice_peniel_header h
    JOIN static_invoice_peniel_details d ON d.source_file = h.source_file
    UNION ALL
    SELECT 'FACTURA', 'INVC-PRECISION HELIPARTS',
           h.source_file, h.invoice_number, h.invoice_date, h.po_number, h.currency,
           d.line, d.part_number, d.description, d.qty_shipped, d.uom, d.unit_price,
           d.amount, h.subtotal, COALESCE(h.total, h.balance)
    FROM static_invoice_precision_header h
    JOIN static_invoice_precision_details d ON d.source_file = h.source_file
    UNION ALL
    SELECT 'FACTURA', 'INVC-TEXTRON',
           h.source_file, h.invoice_number, h.invoice_date, h.po_number, h.currency,
           d.line, d.part_number,
           COALESCE(d.description_1, '') || COALESCE(' ' || d.description_2, ''),
           d.quantity, d.uom, d.unit_price, d.amount, h.subtotal, h.total
    FROM static_invoice_textron_header h
    JOIN static_invoice_textron_details d ON d.source_file = h.source_file
    UNION ALL
    -- Las **órdenes de compra** (todo el maestro, para poder cruzarlas con las facturas).
    SELECT 'ORDEN',
           CASE split_part(h.source_file, '/', 1)
               WHEN 'FENIX'                     THEN 'INVC-FENIX AEROSPACE'
               WHEN 'JETSET'                    THEN 'INVC-JETSET'
               WHEN 'KAL AIRPARTS'              THEN 'INVC-KAL AIRPARTS'
               WHEN 'PENIEL'                    THEN 'INVC-PENIEL'
               WHEN 'PRECISION HELIPARTS (PAG)' THEN 'INVC-PRECISION HELIPARTS'
               WHEN 'TEXTRON'                   THEN 'INVC-TEXTRON'
           END,
           h.source_file, h.po_number, h.po_date, h.po_number, h.currency,
           d.item, d.part_number, d.description, d.qty, d.um, d.unit_cost, d.total_cost,
           h.subtotal, h.total
    FROM static_invoice_po_header h
    JOIN static_invoice_po_details d ON d.source_file = h.source_file
),

maestro AS (
    SELECT DISTINCT {{ invoice_po_key('po_number') }} AS po_key
    FROM static_invoice_po_header
    WHERE po_number IS NOT NULL
)


SELECT
    d.tipo_documento,
    d.proveedor,
    d.source_file                                      AS archivo,
    d.documento,
    TRY_CAST(d.fecha AS DATE)                          AS fecha,
    d.po_number                                        AS po_numero,
    m.po_key IS NOT NULL                               AS po_encontrada,
    TRY_CAST(d.item AS VARCHAR)                        AS item,
    d.part_number,
    d.descripcion,
    TRY_CAST(d.qnt AS DECIMAL(18,3))                   AS qnt,
    d.uom,
    TRY_CAST(d.precio_unitario AS DECIMAL(18,6))       AS precio_unitario,
    TRY_CAST(d.importe AS DECIMAL(18,6))               AS importe,
    COALESCE(d.currency, 'USD')                        AS currency,
    -- `subtotal_documento` es lo que tienen que sumar las líneas (las líneas del PDF
    -- son el subtotal; el flete/impuesto no vienen como línea y `total_documento` ya
    -- los incluye). Así la página puede decir si un fichero cuadra.
    TRY_CAST(d.subtotal_documento AS DECIMAL(18,6))    AS subtotal_documento,
    TRY_CAST(d.total_documento AS DECIMAL(18,6))       AS total_documento,
    -- Lo que aporta la orden: fecha de servicio, aeronave (centro de costo) y tipo.
    po.po_date                                         AS po_fecha,
    po.cost_center                                     AS cost_center,
    po.appended_tipo_mantenimiento                     AS tipo_mantenimiento
FROM documentos d
LEFT JOIN maestro m
    ON m.po_key = {{ invoice_po_key('d.po_number') }}
-- **Un solo JOIN** a `po_cost_center` y por la fila **general** de la orden (`'*'`): el
-- CTE efímero no puede inlinearse dos veces (DuckDB tiene un bug con eso dentro de
-- `UNION ALL` largos: devolvía las filas de OTRA rama — la de Peniel salía con los
-- ficheros de JetSet) y así tampoco se puede multiplicar una línea. El centro de costo
-- “de la orden” es el que trae el formulario cuando toda la orden es de una aeronave.
LEFT JOIN {{ ref('po_cost_center') }} po
    ON po.po_key = {{ invoice_po_key('d.po_number') }}
    AND po.part_key = '*'