{{ config(materialized='table') }}

-- Copia la tabla `flight_reports` de `db.sqlite` (nombre "pelado" resuelto por
-- `search_path: src.main`) a `analytics_poc.duckdb`. Tabla **independiente**: no
-- la consume ningún otro modelo y no tiene relación con el resto del proyecto; el
-- asset `flight_reports_asset` la llena en `db.sqlite` y la publicación
-- (`publish_dwh`) la copia al schema `dwh` de PostgreSQL con el mismo nombre.
--
-- `empresa`: NO viene en el origen, se DERIVA de `sede_operacion`. La sede SELVA
-- vuela como "Air Majoro Selva" y el resto de sedes (NASCA, MEDEVAC, ...) como
-- "Air Majoro". Los dos literales son los mismos que usa
-- `dwh.vista_reporte_gerencial.empresa` (y `payroll_std.company`), para poder
-- filtrar/cruzar por empresa en el informe sin normalizar cadenas.
select
    *,
    case
        when upper(trim(coalesce(sede_operacion, ''))) = 'SELVA' then 'Air Majoro Selva'
        else 'Air Majoro'
    end as empresa
from flight_reports

