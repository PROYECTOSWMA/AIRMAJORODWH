{#
    aeropuerto_ubicacion(expr, tipo='icao')

    Devuelve la **ubicación** del aeropuerto al que se refiere ``expr``, leyéndola
    del catálogo ``static_aux_airports`` (modelo ``aux_airports``), o ``NULL`` si no
    está en el catálogo.

    Es la variante "estricta" de ``obtener_aeropuerto``: aquel devuelve un mensaje
    de texto (``'No es nomenclatura ...'``) cuando el código no está en el catálogo,
    mientras que este macro **solo** puede devolver un valor de la columna
    ``ubicacion`` (o NULL). Es lo que exige el contrato de los proveedores de
    combustible (PETROPERÚ, CEP, ÍCARO y TERPEL): todas sus filas de ``moves`` con
    aeropuerto deben salir con una ``ubicacion`` del catálogo.

    ``tipo`` elige la columna del catálogo contra la que se cruza ``expr``:

      * ``'icao'``  -> ``icao`` (CEP: el ``cod_del_cliente`` de la factura es
        ``<código local>/<ICAO>``, p. ej. ``NZA/SPZA`` -> SPZA -> ``Nazca``).
      * ``'iata'``  -> ``iata`` (TERPEL: ``estacion``/``destino`` son IATA, p. ej.
        ``LIM`` -> ``Callao``).
      * ``'nombre'``-> ``ubicacion`` **o** ``departamento`` (PETROPERÚ e ÍCARO traen
        el nombre del lugar o el departamento, p. ej. ``PUCALLPA`` o ``Ucayali``).
        Si el texto coincide con un departamento con varios aeródromos, gana el que
        tiene código IATA (el "principal": ``Ucayali`` -> SPCL/``Pucallpa``).

    Es un subquery escalar (no añade JOIN), así que se usa directo en el SELECT de
    ``purchs/cost_centers.sql``.
#}
{% macro aeropuerto_ubicacion(expr, tipo='icao') -%}
    {%- if tipo in ('icao', 'iata') -%}
        (SELECT a.ubicacion
         FROM {{ ref('aux_airports') }} a
         WHERE upper(a.{{ tipo }}) = upper({{ expr }})
         LIMIT 1)
    {%- else -%}
        (SELECT a.ubicacion
         FROM {{ ref('aux_airports') }} a
         WHERE upper(a.ubicacion) = upper({{ expr }})
            OR upper(a.departamento) = upper({{ expr }})
         ORDER BY (a.iata IS NULL), a.ubicacion
         LIMIT 1)
    {%- endif -%}
{%- endmacro %}
