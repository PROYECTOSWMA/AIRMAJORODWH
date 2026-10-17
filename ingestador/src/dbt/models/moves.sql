{{ config(materialized='table') }}

-- Consolidado de los 3 dominios en las 27 columnas del contrato, **con los tipos
-- del DWH ya aplicados**: los datos entran como TEXT/DOUBLE (heredado de SQLite) y
-- aquí se castean a DATE / INTEGER / BIGINT / DECIMAL para que la publicación
-- del asset `publish_dwh` cree esas columnas con su tipo real en PostgreSQL (antes salían
-- TEXT/DOUBLE en `dwh.moves`, que es lo que lee el reporte gerencial).
-- Siempre `TRY_CAST` (nunca `CAST`): un valor raro queda NULL en vez de romper dbt.
WITH mv_without_accounts as (
    SELECT * FROM {{ ref('purchs_std') }}
    UNION ALL
    SELECT * FROM {{ ref('sales_std') }}
    UNION ALL
    SELECT * FROM {{ ref('labor_std') }}
),

-- El centro de costo FINAL (con el override del proveedor ya aplicado) se necesita
-- para estandarizar `serv_desc`, así que el cuerpo queda como CTE.
mv_con_cc AS (
SELECT
    -- `id`: solo lo trae la vía de planilla; el resto de ramas vienen con NULL.
    TRY_CAST(mv.id AS BIGINT)                    AS id,
    -- Fechas: las ramas ya las traen en ISO; `normalize_date` valida el rango
    -- (descarta años fuera de [1900, 2030]) y el cast fija el tipo DATE. El
    -- `CAST(... AS VARCHAR)` de dentro es una salvaguarda: el tipo del `UNION ALL`
    -- lo decide DuckDB y el macro necesita texto (con DATE también funciona).
    TRY_CAST({{ normalize_date('CAST(mv.doc_date AS VARCHAR)', 'YYYY-MM-DD') }} AS DATE)
                                                 AS doc_date,
    -- `doc_type`: código SUNAT (1, 3, 7, 8...). Rellena con NULL las vías que no
    -- traen código numérico (planilla/RH y las compras del exterior van con
    -- `move_type` = 'Compras'; su cuenta es la que las separa).
    TRY_CAST(mv.doc_type AS INTEGER)             AS doc_type,
    mv.doc_serie,
    TRY_CAST(mv.doc_number AS BIGINT)            AS doc_number,
    TRY_CAST({{ normalize_date('CAST(mv.doc_due_date AS VARCHAR)', 'YYYY-MM-DD') }} AS DATE)
                                                 AS doc_due_date,
    mv.partner_doc_type,
    mv.partner_doc,
    mv.qnt_type,
    TRY_CAST(mv.qnt AS DECIMAL(18,3))            AS qnt,
    mv.currency,
    -- VOLTEADA (en el ORIGEN, la propia tabla `moves`): todo lo que NO es venta
    -- (compras, planilla, RH, ...) queda en NEGATIVO y las ventas en POSITIVO.
    -- Así el EERR solo SUMA: ventas (+) menos costos/gastos ya negativos (-).
    -- Se decide por `move_type` ('Ventas...'); hoy solo hay 'Ventas'/'Compras'.
    TRY_CAST(mv.amnt_taxable AS DECIMAL(18,6))
        * CASE WHEN mv.move_type ILIKE 'Ventas%' THEN 1 ELSE -1 END
                                                 AS amnt_taxable,
    TRY_CAST(mv.amnt_taxes AS DECIMAL(18,6))
        * CASE WHEN mv.move_type ILIKE 'Ventas%' THEN 1 ELSE -1 END
                                                 AS amnt_taxes,
    TRY_CAST({{ normalize_date('CAST(mv.serv_date AS VARCHAR)', 'YYYY-MM-DD') }} AS DATE)
                                                 AS serv_date,
    mv.serv_desc,
    -- Override de centros de costo fallados por el proveedor
    COALESCE(
        override.cost_center,
        NULLIF(mv.cost_center, ''),
        {{ cost_center_from_serv_desc('mv.serv_desc') }}
    )                                            AS cost_center,
    mv.serv_org_airport,
    mv.serv_dest_airport,
    mv.account,
    mv.company,
    -- `error` es siempre NULL: en DuckDB una columna de NULLs sale INTEGER y en el
    -- DWH la columna es de texto (mensajes de error).
    TRY_CAST(mv.error AS VARCHAR)                AS error,
    mv.ingested_at,
    mv.move_type,
    mv.source_sire_sales,
    mv.source_sire_sales_details,
    mv.source_sisa,
    -- Columna 27 del contrato (la añaden los modelos de `models/invoices/`): el
    -- **tipo de mantenimiento** que la orden de compra le aporta a su factura
    -- (`CORRECTIVO`, `PREVENTIVO`, `1000 hrs.`, `STOCK`: la columna TIPO DE
    -- MANTENIMIENTO del formulario de la PO) y, en las órdenes **sin** factura, el de
    -- la propia orden. Las ramas que no son del exterior (`sales_std`, `labor_std` y
    -- las compras con reporte propio) lo traen NULL.
    TRY_CAST(mv.appended_tipo_mantenimiento AS VARCHAR)
                                                 AS appended_tipo_mantenimiento
FROM mv_without_accounts mv
LEFT JOIN {{ ref('aux_cost_centers_override') }} override
    ON override.partner_doc = mv.partner_doc
    AND override.doc_serie   = mv.doc_serie
    AND override.doc_number  = mv.doc_number
)

-- Estandarización de `serv_desc` en las compras de COMBUSTIBLE (cuenta 603201) y
-- ÚNICA forma de asignar el tipo de combustible: NO se deriva del centro de costo
-- ni de la aeronave. Se hace aquí (no en `purchs_std`) porque necesita el centro de
-- costo FINAL, que recién queda resuelto en el CTE anterior (override incluido).
SELECT mv.*
REPLACE (
    CASE
        -- Cualquier otra cuenta pasa intacta.
        WHEN mv.account <> '603201' THEN mv.serv_desc
        -- Anticipos de combustible de TERPEL: NO son compras. Se conserva el texto
        -- porque `dwh.vista_reporte_gerencial` los excluye justamente por él
        -- (mismas dos formas: 'PAGO ADELANTADO' / 'PAGOS ADELANTADOS'); reescribirlo
        -- los haría aparecer en el reporte gerencial.
        WHEN mv.partner_doc = '20259880603'
            AND (mv.serv_desc ILIKE '%PAGO ADELANTADO%'
                 OR mv.serv_desc ILIKE '%PAGOS ADELANTADOS%') THEN mv.serv_desc
        -- Sin descripción no hay nada que clasificar.
        WHEN NULLIF(trim(mv.serv_desc), '') IS NULL THEN 'NO IDENTIFICADO'
        -- Centro de costo que NO es una aeronave del maestro `static_airplanes`
        -- (p. ej. 2000, 2190, 2056, 2222): no se puede saber qué combustible es.
        WHEN NULLIF(trim(mv.cost_center), '') IS NOT NULL
            AND NOT EXISTS (
                SELECT 1
                FROM {{ ref('static_airplanes') }} a
                WHERE a.registration = mv.cost_center
            ) THEN 'NO IDENTIFICADO'
        -- Regla del negocio: manda la DESCRIPCIÓN. Si trae '100' es AVGAS (100LL);
        -- cualquier otra ('TURBO A-1', 'TURBO A-1 JET', 'TURBO A1 -', ...) es
        -- TURBO JET A1.
        WHEN instr(mv.serv_desc, '100') > 0 THEN '100LL'
        ELSE 'TURBO JET A1'
    END AS serv_desc
)
FROM mv_con_cc mv
