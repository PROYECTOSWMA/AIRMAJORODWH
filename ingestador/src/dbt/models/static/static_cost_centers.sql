{{ config(materialized='table') }}

-- Copia el maestro de centros de costo `dwh_static_cost_centers` de `db.sqlite` a
-- DuckDB (nombre "pelado" resuelto por `search_path: src.main`). El modelo se llama
-- `static_cost_centers`: sin el prefijo `dwh_` y NO `cost_centers`, que ya lo usa el
-- efímero de compras `purchs/cost_centers.sql` (dbt no admite dos nodos con el
-- mismo nombre).
-- Columnas del CSV (renombradas en 2026-10; antes eran `cc`, `code`, `description`):
--
--   · `codigo`         → el CÓDIGO de centro de costo que traen la planilla y `moves`
--     ('101', '200', 'OPE-NAZCA', ...).
--   · `abreviatura`    → la clave corta del maestro: el nº de aeronave para las
--     aeronaves ('1919', '2092', ...) y la clave del movimiento para el resto
--     ('ADM-PCL', 'VEN-PCL', 'OMA', ...). Es el texto con el que `moves` etiqueta el
--     centro de costo.
--   · `descripcion`    → la etiqueta legible ('OB1919', 'GASTO ADMINISTRATIVO PUCALLPA').
--   · `grupo`          → la agrupación del maestro (COSTO_VENTAS, GASTO ADMINISTRATIVO,
--     GASTO DE VENTAS, GASTO FINANCIERO, GASTOS DE OPERACION).
--   · `unidad_negocio` → la UNIDAD DE NEGOCIO ya resuelta en el maestro (NAZCA, SELVA,
--     MEDEVAC, Costo de Ventas Otros, Gasto de administración, ...): es la que usa el
--     informe de Gastos de Personal (`static_payroll`) sin ningún `CASE` en SQL.
SELECT
    codigo,
    abreviatura,
    descripcion,
    grupo,
    unidad_negocio
FROM static_dwh_cost_centers
