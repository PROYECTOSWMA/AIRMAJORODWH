{{ config(materialized='ephemeral') }}

-- Copia la tabla `static_aux_airports` de `db.sqlite` (nombre "pelado" resuelto
-- por `search_path: src.main`). El modelo ya no lleva prefijo (`aux_airports`) y el
-- macro `obtener_aeropuerto` lo referencia con ese nombre.
SELECT
    icao,
    iata,
    denominacion,
    ubicacion,
    departamento
FROM static_aux_airports
