{{ config(materialized='ephemeral') }}

-- Unión de las 4 ramas de compras (las 26 columnas) y, sobre esa unión, el
-- centro de costo calculado y la cuenta contable por regla (gana el patrón MÁS
-- LARGO). Todo va en **un único `WITH`**: los CTEs se separan con comas;
-- repetir `WITH` antes de cada CTE es un error de sintaxis.
WITH purchases AS (
    -- Las ramas que NO son de las facturas del exterior no traen el tipo de
    -- mantenimiento (columna 27 del contrato): va NULL para que el `UNION ALL`
    -- tenga la misma forma que `invoice_std` y `po_std`.
    SELECT *,
           CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento
    FROM {{ ref('sire_purchs_std') }}
    -- ⚠️ `coalesce(..., '')`: en SQL, `NULL NOT IN (...)` NO es TRUE (es NULL), así
    -- que **toda fila sin RUC de contraparte se caía de `moves`** — 26 comprobantes
    -- de **VSE AVIATION (40.033,00 S/, DAM de importación con `nro_doc_identidad`
    -- NULL)** que hoy no aparecen en el reporte gerencial. Con el coalesce entran y
    -- siguen siendo los mismos proveedores ocultos los que se filtran (2026-10-09).
    WHERE coalesce(partner_doc, '') NOT IN (
        '{{ var('ruc_corpac') }}',    -- CORPAC
        '{{ var('ruc_adp') }}',       -- ADP / AEROPUERTOS DEL PERU
        '{{ var('ruc_lap') }}',       -- LAP / LIMA AIRPORT PARTNERS
        -- Ocultos del DWH (2026-10, pedido del cliente): no deben aparecer
        -- porque su gasto se paga a través de otro proveedor/empresa, o porque
        -- es un activo (balance general) y no va en el EERR.
        '20312239117',                -- AQP EXPRESS CARGO S.A.C.
        '20137422604',                -- SHOHIN S.A.
        '75821860'                    -- WAS TURBINE CENTER LLC
    )
    UNION ALL
    SELECT *, CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento
    FROM {{ ref('corpac_purchs_std') }}
    UNION ALL
    SELECT *, CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento
    FROM {{ ref('adp_purchs_std') }}
    UNION ALL
    SELECT *, CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento
    FROM {{ ref('lap_purchs_std') }}
    UNION ALL
    -- Facturas de proveedores del EXTERIOR (Fenix, JetSet, Kal, Peniel, Precision y
    -- Textron) **más las órdenes de compra que no tienen factura**, desde las tablas
    -- del asset `static_data_asset`; ver `models/invoices/`. Cada compra entra una
    -- sola vez (la factura si existe, y si no la orden). La cuenta (603301,
    -- CONSUMIBLES) la deja cada rama.
    SELECT * FROM {{ ref('invoice_std') }}
),

purchases_cc AS (
    SELECT p.*
    REPLACE (
        -- La descripción del servicio de los COMBUSTIBLES NO se toca aquí: se
        -- estandariza al final (CTE `purchases_combustible`), cuando la cuenta ya
        -- está resuelta y se puede excluir todo lo que no sea 603201.
        COALESCE(p.cost_center, {{ extract_cost_center('cc.aeronave') }}) AS cost_center,
        -- ``cost_centers`` resuelve el aeropuerto de los proveedores de combustible
        -- (PETROPERÚ, CEP, ÍCARO y TERPEL); las vías con reporte propio (CORPAC,
        -- ADP, LAP) traen el suyo y ahí ``cc.aeropuerto`` es NULL (ver el LEFT JOIN).
        COALESCE(cc.aeropuerto, p.serv_org_airport)                       AS serv_org_airport,
        COALESCE(cc.aeropuerto_destino, p.serv_dest_airport)              AS serv_dest_airport
    )
    FROM purchases p
    -- `cost_centers` ya expone el `car_sunat` estable de cada comprobante (los 3
    -- proveedores de SIRE lo resuelven por su `id_file`, FK a `sire_purchs_files`,
    -- en lugar de reconstruirlo desde el `filename`; ver `cost_centers.sql`).
    LEFT JOIN {{ ref('cost_centers') }} cc
        ON {{ get_car('p.partner_doc', 'p.doc_type', 'p.doc_serie', 'p.doc_number') }}
            = cc.car_sunat
),


purchases_cc_acc AS (
    SELECT q.*
    REPLACE (
        COALESCE(
            (
                SELECT r.account
                FROM {{ ref('aux_accounts_assignment') }} r
                WHERE r.partner_doc = q.partner_doc
                AND (
                    r.serv_desc_pattern IS NULL
                    OR r.serv_desc_pattern = ''
                    OR instr(upper(q.serv_desc), upper(r.serv_desc_pattern)) > 0
                )
                ORDER BY length(r.serv_desc_pattern) DESC NULLS LAST
                LIMIT 1
            ),
            q.account,
            '659902'
        ) AS account
    )
    FROM purchases_cc q
)

SELECT * FROM purchases_cc_acc
