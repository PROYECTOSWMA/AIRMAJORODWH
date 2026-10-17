{{ config(materialized='table') }}

-- Copia el maestro de cuentas PCGE `dwh_static_master_accounts` de `db.sqlite` a
-- DuckDB (nombre "pelado" resuelto por `search_path: src.main`). El modelo se llama
-- `static_master_accounts` (sin el prefijo `dwh_`) y materializa esa tabla, que es
-- la que publica el asset `publish_dwh`.
SELECT
    codigo_pcge,
    grupo,
    cuenta,
    cuenta_pcge,
    comentario
FROM static_dwh_master_accounts
