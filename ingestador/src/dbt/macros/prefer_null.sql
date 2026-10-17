{#
    prefer_null(column, when_expr, else_expr)

    Genera un CASE WHEN column IS NOT NULL THEN when_expr ELSE else_expr END.
    La condición "IS NOT NULL" se evalúa por-fila en runtime.
    Ej: {{ prefer_null('d.id', 'd.mto_val_unitario', 's.bi_gravada') }}
#}
{% macro prefer_null(column, when_expr, else_expr) -%}
    CASE WHEN {{ column }} IS NOT NULL THEN {{ when_expr }} ELSE {{ else_expr }} END
{%- endmacro %}