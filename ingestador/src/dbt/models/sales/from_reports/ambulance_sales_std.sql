{{ config(materialized='ephemeral') }}

-- Rama de ambulancia aérea en el formato estándar del contrato (26 columnas) más
-- `observaciones` (2ª factura del vuelo, NO es parte del contrato: `sales_std` la
-- excluye). Las columnas técnicas que este reporte no tiene (`id`, `error`,
-- `ingested_at`, `move_type` y los 3 `source_*`) van en NULL: así el modelo
-- cumple el contrato y el `UNION ALL` de `sales_std` casa, sin inventar dato
-- alguno (la cuenta y el `move_type` los resuelve otra capa, no `sales_std`).
SELECT
    NULL                                    AS id,
    -- `doc_date`: la factura del SIRE si existe; si el vuelo NO está en SIRE el
    -- LEFT JOIN deja `fecha_de_emision` en NULL y la venta se quedaba sin fecha
    -- (74 filas, ~2,39 M, que se caían del EERR). En ese caso se usa la fecha del
    -- vuelo (`fecha_vlo`), que es un dato real de la propia hoja y el que ya
    -- alimenta `serv_date`.
    coalesce(CAST(s.fecha_de_emision AS VARCHAR), b.fecha_vlo) AS doc_date,
    s.tipo_cp_doc                           AS doc_type,
    s.serie_del_cdp                         AS doc_serie,
    s.nro_cp_o_doc_nro_inicial_rango        AS doc_number,
    s.fecha_vcto_pago                       AS doc_due_date,
    ifnull(s.tipo_doc_identidad, 'INTERNO') AS partner_doc_type,
    -- Cliente/tercero que NO está en SIRE (no tiene RUC): se identifica con un
    -- código sintético ``NORUC-<nombre>`` en vez del nombre suelto, que no era un
    -- "código" y por eso se quedaba sin descripción en ``partners``. La
    -- descripción que le pone ``partners`` es justo el nombre, sin el prefijo.
    CASE
        WHEN trim(coalesce(s.nro_doc_identidad, '')) <> '' THEN s.nro_doc_identidad
        WHEN trim(coalesce(b.cliente, '')) <> ''           THEN 'NORUC-' || trim(b.cliente)
    END                                     AS partner_doc,
    NULL                                    AS qnt_type,
    NULL                                    AS qnt,
    -- Solo hay soles o dolares: PEN si `soles` trae dato, si no USD.
    CASE WHEN b.soles IS NOT NULL THEN 'PEN' ELSE 'USD' END
                                            AS currency,
    coalesce(b.soles, b.dolares) / 1.18     AS amnt_taxable,
    coalesce(b.soles, b.dolares) / 1.18 * 0.18
                                            AS amnt_taxes,
    b.fecha_vlo                             AS serv_date,
    b.servicio_paciente                     AS serv_desc,
    {{ extract_cost_center('b.aeronave') }} AS cost_center,
    -- ruta "ANS-LIM" -> origen "ANS", destino "LIM" (códigos IATA)
    {{ obtener_aeropuerto(get_by_sep('b.ruta', "'-'", 0), 'iata') }}
                                            AS serv_org_airport,
    {{ obtener_aeropuerto(get_by_sep('b.ruta', "'-'", 1), 'iata') }}
                                            AS serv_dest_airport,
    703201                                  AS account,
    'Air Majoro'                            AS company,
    NULL                                    AS error,
    NULL                                    AS ingested_at,
    'Ventas'                                AS move_type,
    NULL                                    AS source_sire_sales,
    NULL                                    AS source_sire_sales_details,
    NULL                                    AS source_sisa,
    json_extract_string(b.agregado_factura, '$[1]')
                                            AS observaciones
FROM static_ambulance_sales_reports b
LEFT JOIN sire_sales s
    ON s.serie_del_cdp = split_part(json_extract_string(b.agregado_factura, '$[0]'), '-', 1)
    -- `TRY_CAST` (no `CAST`): hay comprobantes del reporte **sin correlativo**
    -- (p. ej. `B001`, una boleta), y ahí `split_part(...,'-',2)` es '' y un `CAST`
    -- crudo a BIGINT aborta `moves` entero. Con `TRY_CAST` esa venta simplemente
    -- no cruza con SIRE (sin número no hay con qué cruzar) y sigue su camino con
    -- la fecha del vuelo, que es lo que ya hace `coalesce` en `doc_date`.
    AND s.nro_cp_o_doc_nro_inicial_rango = TRY_CAST(
        split_part(json_extract_string(b.agregado_factura, '$[0]'), '-', 2) AS BIGINT)

WHERE b.pilotos_cop is not null
