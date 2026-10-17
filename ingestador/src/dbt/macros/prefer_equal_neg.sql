{#
    prefer_equal_neg(column, value, expr)

    Genera un CASE WHEN column = value THEN -(expr) ELSE expr END
    (niega expr cuando column == value).
    Ej: {{ prefer_equal_neg('s.tipo_cp_doc', '7', amnt_taxable_raw) }}
#}

{% macro prefer_equal_neg(column, value, expr) -%}
    CASE WHEN {{ column }} = {{ value }} THEN - ({{ expr }}) ELSE {{ expr }} END
{%- endmacro %}