{{ config(materialized='table') }}

-- Copia el maestro `dwh_static_airplanes` de `db.sqlite` a DuckDB (nombre "pelado"
-- resuelto por `search_path: src.main`). El modelo se llama `static_airplanes` (sin
-- el prefijo `dwh_`) y materializa esa tabla en DuckDB, que es la que publica
-- el asset `publish_dwh` al DWH.
SELECT
    registration,
    owner,
    model,
    business_unit,
    base,
    passengers,
    fuel
FROM static_dwh_airplanes
