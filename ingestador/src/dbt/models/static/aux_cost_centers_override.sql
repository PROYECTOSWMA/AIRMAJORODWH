{{ config(materialized='ephemeral') }}

-- Copia la tabla `static_aux_cost_centers_override` de `db.sqlite` (nombre "pelado"
-- resuelto por `search_path: src.main`). El modelo ya no lleva prefijo
-- (`aux_cost_centers_override`) y `moves` lo referencia con ese nombre.
-- Todo TEXT (y en particular `doc_number`): el join de `moves` es contra una
-- columna que en la unión es TEXTO (planilla usa códigos como '1-0059').
SELECT
    partner_doc,
    doc_serie,
    doc_number,
    cost_center
FROM static_aux_cost_centers_override
