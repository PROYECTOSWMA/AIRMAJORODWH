{{ config(materialized='ephemeral') }}

-- Unión de las vías de ventas: SOLO `UNION ALL`, con UNA fila por documento
-- (clave: `doc_serie` + `doc_number`) y prioridad ambulancia > SISA > SIRE > SELVA.
-- Además se RESTAN las NOTAS DE CRÉDITO de SISA (`nc`, importes ya negativos).
-- Aquí NO se asignan cuentas contables ni `move_type`: cada rama trae lo suyo.
--
-- OJO: el cuerpo DEBE empezar por `WITH` (o `SELECT`): dbt inyecta ahí sus CTEs de
-- los modelos efímeros; si empieza por una expresión suelta, el SQL no es válido.
WITH amb_docs AS (
    -- TODOS los documentos del array `agregado_factura` del reporte de ambulancia
    -- (no solo el primero: 22 vuelos traen 2 facturas). `from_json` + `unnest`
    -- expande el array; los arrays vacíos no aportan filas.
    SELECT DISTINCT
        split_part(d.doc, '-', 1)                 AS doc_serie,
        -- `TRY_CAST` (no `CAST`): hay comprobantes del reporte **sin correlativo**
        -- (p. ej. `B001`, una boleta) y ahí `split_part(...,'-',2)` es ''; un `CAST`
        -- crudo a BIGINT aborta `moves` entero. Con `TRY_CAST` esa fila queda con
        -- `doc_number` NULL: no casa con ningún documento (en el anti-join NULL no
        -- es igual a nada) pero tampoco tumba el pipeline.
        TRY_CAST(split_part(d.doc, '-', 2) AS BIGINT) AS doc_number
    FROM static_ambulance_sales_reports
    CROSS JOIN unnest(
        coalesce(from_json(agregado_factura, '["VARCHAR"]'), []::VARCHAR[])
    ) AS d(doc)
),
amb AS (
    -- `observaciones` no es parte del contrato de 26 columnas.
    SELECT * EXCLUDE (observaciones)
    FROM {{ ref('ambulance_sales_std') }}
),
sisa AS (
    -- SISA (liquidaciones, 1 fila por documento): se descartan los documentos que
    -- ya vienen en el reporte de ambulancia.
    SELECT s.*
    FROM {{ ref('sisa_sales_std') }} s
    WHERE NOT EXISTS (
        SELECT 1
        FROM amb_docs a
        WHERE a.doc_serie = s.doc_serie
          AND a.doc_number = s.doc_number
    )
),
nc AS (
    -- Notas de crédito de SISA (`sisa_credit_notes`): los importes ya vienen en
    -- NEGATIVO (restan de las ventas) y son documentos propios, así que se añaden
    -- sin anti-join.
    SELECT * FROM {{ ref('sisa_credit_notes_std') }}
),
sire AS (
    -- SIRE (1 fila por línea de detalle): se descartan los documentos que ya
    -- vinieron de ambulancia y los que ya vinieron de SISA.
    SELECT x.*
    FROM {{ ref('sire_sales_std') }} x
    WHERE NOT EXISTS (
        SELECT 1
        FROM amb_docs a
        WHERE a.doc_serie = x.doc_serie
          AND a.doc_number = x.doc_number
    )
    AND NOT EXISTS (
        SELECT 1
        FROM sisa s
        WHERE s.doc_serie = x.doc_serie
          AND s.doc_number = x.doc_number
    )
    -- Las NOTAS DE CRÉDITO de SISA (`nc`) también ceden paso a SIRE: si el mismo
    -- documento está en la liquidación de NC de SISA, no se vuelve a contar desde
    -- SIRE (evita restar dos veces la misma NC).
    AND NOT EXISTS (
        SELECT 1
        FROM nc n
        WHERE n.doc_serie = x.doc_serie
          AND n.doc_number = x.doc_number
    )
),
selva AS (
    -- Reporte de ventas ESTÁTICO "1.- REPORTE DE VENTAS" (Air Majoro Selva y
    -- Air Majoro S.A). Sus NRO/NRO MANIF NO son comprobantes de SISA/SIRE, así que
    -- hoy el anti-join no descarta nada; se deja por consistencia (y para no
    -- duplicar un documento si mañana coincidiera con una de las otras vías).
    SELECT x.*
    FROM {{ ref('selva_sales_std') }} x
    WHERE NOT EXISTS (
        SELECT 1
        FROM amb_docs a
        WHERE a.doc_serie = x.doc_serie
          AND a.doc_number = x.doc_number
    )
    AND NOT EXISTS (
        SELECT 1
        FROM sisa s
        WHERE s.doc_serie = x.doc_serie
          AND s.doc_number = x.doc_number
    )
    AND NOT EXISTS (
        SELECT 1
        FROM sire r
        WHERE r.doc_serie = x.doc_serie
          AND r.doc_number = x.doc_number
    )
)

-- La columna 27 del contrato (`appended_tipo_mantenimiento`) solo la traen las compras
-- del exterior (la aporta la orden de compra): en ventas va NULL, y se añade envolviendo
-- la unión para que las 5 ramas no tengan que declararla cada una.
SELECT *, CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento
FROM (
    SELECT * FROM amb
    UNION ALL
    SELECT * FROM sisa
    UNION ALL
    SELECT * FROM nc
    UNION ALL
    SELECT * FROM sire
    UNION ALL
    SELECT * FROM selva
) AS ventas
