{#
    obtener_aeropuerto(codigo, tipo='icao')

    Resuelve el nombre/ubicación de un aeropuerto a partir de su código, cruzando
    contra la seed `static_aux_airports`:
      * tipo='icao' -> columna `icao` (compras: SPJC, SPME...).
      * tipo='iata' -> columna `iata` (ventas: ANS, LIM...).

    Devuelve:
      * NULL si `codigo` es NULL,
      * la `ubicacion` de la seed normalizada SIEMPRE a Title Case
        (`capitalize_words`),
      * o 'No es nomenclatura ICAO|IATA: "<codigo>"' si el código no está en la
        seed.

    El resultado se capitaliza siempre: antes había un parámetro `capitalizar`
    (por defecto false), pero la seed ya viene en Title Case y así todas las
    fuentes (compras y ventas) salen igual.

    Es un subquery escalar (no añade JOIN), así que se usa directo en el SELECT de
    cada fuente (compras y ventas) y sustituye al CASE+JOIN que se hacía
    centralizado al final de `compras`.

    Ej.: obtener_aeropuerto('d.aeropuerto_origen')  -> 'Jorge Chavez'
         obtener_aeropuerto('f.org_code', 'iata')   -> 'Atalaya'
#}
{% macro obtener_aeropuerto(codigo, tipo='icao') -%}
    {%- set tipo_col = tipo | lower -%}
    {%- set etiqueta = 'ICAO' if tipo_col == 'icao' else 'IATA' -%}
    COALESCE(
        (SELECT {{ capitalize_words('ubicacion') }}
         FROM {{ ref('aux_airports') }}
         WHERE {{ tipo_col }} = {{ codigo }}
         LIMIT 1),
        CASE
            WHEN {{ codigo }} IS NULL THEN NULL
            ELSE 'No es nomenclatura {{ etiqueta }}: "' || {{ codigo }} || '"'
        END
    )
{%- endmacro %}
