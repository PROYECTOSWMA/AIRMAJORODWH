{#
    extract_cost_center(column)

    Devuelve los 4 caracteres siguientes al primer dígito de una cadena.
    Ej: 'OB-1919-P' -> '1919', 'OB2200' -> '2200'.

    Truco: ltrim() quita los caracteres no-numéricos del inicio; la posición del
    primer dígito es (largo_total - largo(ltrim)) + 1.
#}
{% macro extract_cost_center(column) -%}
    substr(
        {{ column }},
        length({{ column }}) - length(ltrim({{ column }}, 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-')) + 1,
        4
    )
{%- endmacro %}
