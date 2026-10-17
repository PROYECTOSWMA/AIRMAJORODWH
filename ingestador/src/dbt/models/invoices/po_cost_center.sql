{{ config(materialized='ephemeral') }}

-- Centro de costo, fecha de servicio y **tipo de mantenimiento** que aporta cada
-- **orden de compra**. Es la tabla de apoyo del cruce factura ↔ PO: la factura trae
-- el Nº de PO y el P/N de cada línea, y de la PO salen la **aeronave** (centro de
-- costo), la **fecha de la orden** (fecha de servicio) y el **tipo de mantenimiento**
-- (la columna `TIPO DE MANTENIMIENTO` del formulario de la PO: CORRECTIVO,
-- PREVENTIVO, 'SECCION CALIENTE DE MOTOR', '1000 hrs.', STOCK…), que es lo que
-- espera el DWH.
--
-- OJO (por qué hay dos JOIN en cada factura, no uno):
--   * ``part_key`` = clave del P/N: es el cruce fino y manda. Una fila por
--     (PO, P/N) — un ``GROUP BY`` garantiza que el JOIN no duplique líneas.
--   * ``part_key = '*'`` = **fila general de la PO**: su centro de costo y su tipo
--     de mantenimiento, pero **solo si toda la orden apunta a un único valor**
--     (``count(DISTINCT ...) = 1``). Es el respaldo para las líneas sin P/N
--     comparable (fletes, P/N tecleado distinto). Si la PO mezcla aeronaves o
--     tipos no se emite la fila, porque repartir a ciegas sería inventar el dato.
--
-- La aeronave se busca en las **dos** columnas donde la escriben los compradores
-- (``cc`` y ``aeronave``: 'OB2180' / '2180'): ``normalize_registration`` deja solo
-- la matrícula y devuelve NULL para lo que no es una aeronave ('STOCK', 'NEW').
WITH items AS (
    SELECT
        {{ invoice_po_key('h.po_number') }}                             AS po_key,
        CASE
            WHEN NULLIF(trim(d.part_number), '') IS NULL THEN NULL
            ELSE regexp_replace(upper(trim(d.part_number)), '[^A-Z0-9]', '', 'g')
        END                                                             AS part_key,
        h.po_date                                                       AS po_date,
        COALESCE(
            {{ normalize_registration('d.cc') }},
            {{ normalize_registration('d.aeronave') }}
        )                                                               AS cost_center,
        NULLIF(trim(d.maintenance_note), '')                            AS tipo_mantenimiento
    FROM static_invoice_po_header h
    JOIN static_invoice_po_details d
        ON d.source_file = h.source_file
    WHERE h.po_number IS NOT NULL
),

por_part AS (
    SELECT
        po_key,
        part_key,
        max(po_date)          AS po_date,
        max(cost_center)      AS cost_center,
        max(tipo_mantenimiento) AS appended_tipo_mantenimiento
    FROM items
    WHERE part_key IS NOT NULL
    GROUP BY 1, 2
),

por_po AS (
    SELECT
        po_key,
        '*'                   AS part_key,
        max(po_date)          AS po_date,
        CASE WHEN count(DISTINCT cost_center) = 1 THEN max(cost_center) END AS cost_center,
        CASE WHEN count(DISTINCT tipo_mantenimiento) = 1
             THEN max(tipo_mantenimiento) END                               AS appended_tipo_mantenimiento
    FROM items
    GROUP BY 1
)

SELECT * FROM por_part
UNION ALL
SELECT * FROM por_po
WHERE cost_center IS NOT NULL
