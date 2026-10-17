{{ config(materialized='ephemeral') }}

-- Labor: union de las 2 vias del dominio, ambas en formato estandar (26
-- columnas): `payroll_std` (planilla) y `prof_invoice_std` (recibos por
-- honorarios). Es el equivalente de `purchs_std` / `sales_std` en este dominio:
-- `movimientos_sin_cuentas` lo consume como una sola rama.
-- La columna 27 del contrato (`appended_tipo_mantenimiento`) es de las compras del
-- exterior (la aporta la orden de compra): en labor va NULL.
SELECT *, CAST(NULL AS VARCHAR) AS appended_tipo_mantenimiento
FROM (
    SELECT * FROM {{ ref('payroll_std') }}
    UNION ALL
    SELECT * FROM {{ ref('prof_invoice_std') }}
) AS labor