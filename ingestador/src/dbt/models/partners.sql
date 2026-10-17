{{ config(materialized='table') }}

-- Prioridad: 1 = códigos SINTÉTICOS (``INVC-`` facturas del exterior y ``NORUC-``
-- terceros de ambulancia sin RUC), 2 = SIRE ventas, 3 = SIRE compras, 4 = SISA,
-- 5 = auxiliares, 6 = RH (seesol), 7 = planilla. Menor número = descripción preferida.
-- Los sintéticos van con 1 porque no son documentos reales: nunca chocan con un
-- código de las otras vías y su descripción (el nombre pelado) siempre gana.
WITH partners_all AS (
    SELECT
        nro_doc_identidad                 AS partner_doc,
        apellidos_nombres_razon_social    AS partner_desc,
        2                                 AS prioridad
    FROM sire_sales

    UNION ALL
    SELECT
        nro_doc_identidad                 AS partner_doc,
        apellidos_nombres_razon_social    AS partner_desc,
        3                                 AS prioridad
    FROM sire_purchs

    UNION ALL
    SELECT
        coalesce(ruc_cliente20, numeroderuc) AS partner_doc,
        razonsocial                          AS partner_desc,
        4                                    AS prioridad
    FROM sisa_sales

    UNION ALL
    SELECT
        partner_doc, partner_desc, 5 AS prioridad
    FROM static_aux_accounts_assignment

    UNION ALL
    SELECT
        nro_doc_emisor                                              AS partner_doc,
        apellidos_y_nombres_denominacion_o_razon_social_del_emisor AS partner_desc,
        6                                                           AS prioridad
    FROM seesol_rh

    UNION ALL
    SELECT
        dni    AS partner_doc,
        nombre AS partner_desc,
        7      AS prioridad
    FROM static_payroll

    UNION ALL
    -- Facturas del exterior (`INVC-<proveedor>`): aquí el nombre sale del propio
    -- código, porque el proveedor ES la carpeta de `INVOICE INTERNACIONALES`. Se
    -- lee de `invoice_std` (y no de una lista escrita a mano) para que si mañana
    -- aparece otra carpeta/proveedor su descripción venga sola.
    SELECT DISTINCT
        partner_doc                       AS partner_doc,
        replace(partner_doc, 'INVC-', '') AS partner_desc,
        1                                 AS prioridad
    FROM {{ ref('invoice_std') }}
    WHERE partner_doc LIKE 'INVC-%'

    UNION ALL
    -- Terceros del reporte de ambulancias que no están en SIRE (`NORUC-<nombre>`):
    -- la descripción es el nombre pelado, sin el prefijo.
    SELECT DISTINCT
        partner_doc                        AS partner_doc,
        replace(partner_doc, 'NORUC-', '') AS partner_desc,
        1                                  AS prioridad
    FROM {{ ref('ambulance_sales_std') }}
    WHERE partner_doc LIKE 'NORUC-%'
),

-- Todos los códigos vistos (aunque ninguna fuente traiga su descripción).
codigos AS (
    SELECT DISTINCT partner_doc AS codigo
    FROM partners_all
    WHERE partner_doc IS NOT NULL AND trim(partner_doc) <> ''
),

-- La mejor descripción de cada código (prioridad y, a igualdad, orden alfabético).
partners_best AS (
    SELECT
        partner_doc,
        partner_desc,
        row_number() OVER (
            PARTITION BY partner_doc
            ORDER BY prioridad, partner_desc
        ) AS rn
    FROM partners_all
    WHERE partner_doc IS NOT NULL AND trim(partner_doc) <> ''
      AND partner_desc IS NOT NULL AND trim(partner_desc) <> ''
)

SELECT
    c.codigo,
    trim(b.partner_desc) AS descripcion
FROM codigos c
LEFT JOIN partners_best b
    ON b.partner_doc = c.codigo
    AND b.rn = 1
