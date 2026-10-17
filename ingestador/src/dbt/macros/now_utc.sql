{#
    now_utc()

    Marca temporal de ingesta (``ingested_at``) en UTC, escrita en el dialecto del
    motor activo. Los modelos la usan como:

        {{ now_utc() }}                             AS ingested_at,

    Motivo: el proyecto corre sobre dos motores mientras dura la migración
    (targets ``dev`` = dbt-sqlite y ``duck`` = dbt-duckdb).

      * dbt-sqlite -> ``datetime('now')``: texto UTC 'YYYY-MM-DD HH:MM:SS'.
      * dbt-duckdb -> ``timezone('UTC', now())``: TIMESTAMP normalizado a UTC.
        DuckDB no tiene ``datetime()`` (error: "Scalar Function with name datetime
        does not exist"); el perfil fija ``TimeZone=UTC`` para que el resultado sea
        el mismo instante en UTC que devolvía SQLite.
#}
{% macro now_utc() -%}
{%- if target.type == 'duckdb' -%}timezone('UTC', now()){%- else -%}datetime('now'){%- endif -%}
{%- endmacro %}
