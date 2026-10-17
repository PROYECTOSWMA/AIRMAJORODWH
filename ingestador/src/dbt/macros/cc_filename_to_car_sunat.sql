{#
    cc_filename_to_car_sunat(filename)

    Convierte un ``filename`` (nombre del XML de un comprobante) en el ``car_sunat``.
    Hoy lo usa **solo** la rama TERPEL de ``cost_centers``: es el único proveedor
    sin ``id_file`` (su aeronave sale de los PDFs de pedido), así que su clave se
    deriva del nombre del PDF. Los 3 proveedores de SIRE (CEP / ÍCARO / PETROPERÚ)
    ya **no** lo usan: resuelven el ``car_sunat`` por la FK ``id_file`` →
    ``sire_purchs_files`` → ``sire_purchs`` (dato estable frente al ``filename``).
    La clave SUNAT se forma como:

        RUC(11) + tipo(2) + serie(4) + número a 10 dígitos

    y el filename viene como ``<RUC>-<tipo>-<serie>-<numero>.XML``, p. ej.:

        '20613566881-01-F002-010479.XML'  -> 2061356688101F0020000010479
        '20100128218-01-F230-0008784.xml' -> 2010012821801F2300000008784

    El número del filename tiene longitud variable según el emisor (6, 7 u 8
    dígitos; PetroPeru usa 7: '0008784'). Con ``printf('%010d', ...)`` se
    completa con ceros a la izquierda hasta 10 dígitos sea cual sea su longitud.
    Así basta con quitar el '.XML' y los '-', dejar intactos los primeros 17
    caracteres (RUC+tipo+serie) y rellenar el resto (el número).

    Igual que en ``get_car``, el entero se saca con ``safe_int`` (``TRY_CAST`` en
    DuckDB): un filename corto o malformado deja el tramo del número en
    ``NULL``/no numérico y con un ``CAST`` a pelo dbt moriría ("Could not convert
    string '' to INT64"). Con ``TRY_CAST`` la clave queda NULL y el JOIN de
    ``compras`` no casa (la fila conserva su ``cost_center`` de origen). Hoy los
    1.358 ``filename`` de Terpel están todos bien formados, así que este cambio
    no altera ningún resultado; es red de seguridad.
#}
{% macro cc_filename_to_car_sunat(filename) -%}
    {% set base = "replace(replace(upper(" ~ filename ~ "), '.XML', ''), '-', '')" %}
    substr({{ base }}, 1, 17) || printf('%010d', {{ safe_int('substr(' ~ base ~ ', 18)') }})
{%- endmacro %}
