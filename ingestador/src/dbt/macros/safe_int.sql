{#
    safe_int(column)

    Entero de 64 bits "tolerante": nunca revienta cuando el texto no es un número.

      * dbt-sqlite -> CAST(... AS BIGINT): SQLite devuelve 0 si el texto no es
        numérico, nunca lanza error.
      * dbt-duckdb -> TRY_CAST(... AS BIGINT): NULL si no se puede convertir.
        (Y BIGINT, no INTEGER: en DuckDB INTEGER es INT32 y los números de
        documento/RUC de 10 dígitos lo desbordan.)

    OJO: cada motor "marca" el valor inválido de forma distinta (0 vs NULL), así
    que las guardas deben cubrir las DOS formas:

        WHEN safe_int(x) IS NULL OR safe_int(x) NOT BETWEEN a AND b THEN NULL

    En SQLite el no-numérico llega como 0 y lo caza el NOT BETWEEN; en DuckDB
    llega como NULL y lo caza el IS NULL. Se usa en `normalize_date` para los
    tokens de año/mes/día de fechas crudas.
#}
{% macro safe_int(column) -%}
    {%- if target.type == 'duckdb' -%}
        TRY_CAST({{ column }} AS BIGINT)
    {%- else -%}
        CAST({{ column }} AS BIGINT)
    {%- endif -%}
{%- endmacro %}
