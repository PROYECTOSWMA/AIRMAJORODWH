{#
    cost_center_from_serv_desc(serv_desc)

    Devuelve el centro de costo (4 dígitos) cuando en `serv_desc` aparece la
    aeronave "OB" u "OB-" seguida de uno de los códigos de la lista blanca.
    Si no hay match devuelve NULL.

    Ej: 'SERVICIO OB-2221 ...' -> '2221', 'OB2200' -> '2200'.

    Se usa en `movimientos` como fallback de cost_center: si la fila no trae
    cost_center (NULL o '') pero la descripción del servicio contiene uno de
    estos códigos de aeronave, se rellena con esos 4 dígitos.

    Nota: se usa instr() (no REGEXP) porque SQLite por defecto no lo habilita
    en el driver de Python, y coincide con el estilo ya usado en movimientos.
#}
{% macro cost_center_from_serv_desc(serv_desc) -%}
    {% set codes = ['2221','2200','1929','1919','2104','2092','2209','2239'] %}
    CASE
    {% for code in codes %}
        WHEN instr(upper({{ serv_desc }}), 'OB-{{ code }}') > 0 THEN '{{ code }}'
        WHEN instr(upper({{ serv_desc }}), 'OB{{ code }}')  > 0 THEN '{{ code }}'
    {% endfor %}
    END
{%- endmacro %}
