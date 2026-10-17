{#
    prefer_equal(column, value, when_expr, else_expr)

    Genera un CASE WHEN column = value THEN when_expr ELSE else_expr END.
    La comparación se evalúa por-fila en runtime.
    Ej: {{ prefer_equal('doc_type', '7', '-qnt', 'qnt') }}
#}
{% macro prefer_equal(column, value, when_expr, else_expr) -%}
    CASE WHEN {{ column }} = {{ value }} THEN {{ when_expr }} ELSE {{ else_expr }} END
{%- endmacro %}