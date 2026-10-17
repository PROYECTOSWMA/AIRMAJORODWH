{{ config(materialized='ephemeral') }}

SELECT
    p.car_sunat,
    cc.aeronave,
    {{ aeropuerto_ubicacion("split_part(h.cod_del_cliente, '/', 2)", 'icao') }} AS aeropuerto,
    NULL                                                                      AS aeropuerto_destino
FROM from_sire_cep_cost_centers cc
JOIN sire_purchs_files f ON f.id = cc.id_file
JOIN sire_purchs       p ON p.id = f.sire_purch_id
-- La cabecera del PDF de CEP (``fe.corporacion.energetico@gmail.com``) trae el
-- ``cod_del_cliente`` en su primera columna de datos (``NZA/SPZA``). Se cruza por
-- la factura: ``serie + correlativo`` (el correlativo se compara como entero para
-- no depender de los ceros a la izquierda que imprima el PDF). ``removedups``
-- evita duplicar el comprobante si el mismo PDF llegó en dos correos.
LEFT JOIN (
    SELECT factura, cod_del_cliente
    FROM ({{ removedups('from_email_cep_docs_headers', 'factura') }})
) h
    ON split_part(h.factura, '-', 1) = p.serie_del_cdp
    AND TRY_CAST(split_part(h.factura, '-', 2) AS BIGINT)
        = TRY_CAST(p.nro_cp_o_doc_nro_inicial_rango AS BIGINT)
UNION ALL
SELECT
    p.car_sunat,
    cc.aeronave,
    {{ aeropuerto_ubicacion('cc.texto_planta', 'nombre') }}                   AS aeropuerto,
    NULL                                                                      AS aeropuerto_destino
FROM from_sire_icaro_cost_centers cc
JOIN sire_purchs_files f ON f.id = cc.id_file
JOIN sire_purchs       p ON p.id = f.sire_purch_id
UNION ALL
SELECT
    p.car_sunat,
    cc.aeronave,
    {{ aeropuerto_ubicacion('cc.aeropuerto', 'nombre') }}                     AS aeropuerto,
    NULL                                                                      AS aeropuerto_destino
FROM from_sire_petroperu_cost_centers cc
JOIN sire_purchs_files f ON f.id = cc.id_file
JOIN sire_purchs       p ON p.id = f.sire_purch_id
UNION ALL

-- TERPEL (sin ``id_file``, ver arriba): el nombre del PDF del pedido lleva el
-- comprobante a partir de la posición 17 (``Fact_..._FV02-00031828.pdf``); se
-- reconstruye el ``filename`` del XML y de ahí el ``car_sunat``, igual que antes.
{% set terpel_filename = "'" ~ var('ruc_terpel') ~ "' || '-01-' || substr(replace(upper(o.filename), '.PDF', ''), 17) || '.XML'" %}
SELECT
    {{ cc_filename_to_car_sunat(terpel_filename) }} AS car_sunat,
    t.matricula                                     AS aeronave,
    {{ aeropuerto_ubicacion('t.estacion', 'iata') }} AS aeropuerto,
    {{ aeropuerto_ubicacion('t.destino', 'iata') }}  AS aeropuerto_destino
-- Una fila por orden (filename): `removedups` conserva la de menor `id`.
FROM ({{ removedups('from_email_terpel_invoicem_docs', 'filename') }}) o
LEFT JOIN ({{ removedups('from_email_terpel_tickets_tickets', 'o_entrega') }}) t
    ON CAST(t.o_entrega AS BIGINT) = o.agregado_o_entrega
