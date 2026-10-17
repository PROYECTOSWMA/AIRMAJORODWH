{{ config(materialized='ephemeral') }}

-- Copia la tabla `static_aux_accounts_assignment` de `db.sqlite` (nombre "pelado"
-- resuelto por `search_path: src.main`). El modelo ya no lleva prefijo
-- (`aux_accounts_assignment`) y `purchs_std` lo referencia con ese nombre.
SELECT
    partner_doc,
    partner_desc,
    serv_desc_pattern,
    account
FROM static_aux_accounts_assignment
