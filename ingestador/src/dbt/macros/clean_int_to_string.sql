{% macro clean_int_to_string(column_name) %}
    COALESCE(
        TRY_CAST(TRY_CAST({{ column_name }} AS BIGINT) AS VARCHAR),
        TRY_CAST(TRY_CAST({{ column_name }} AS DOUBLE) AS BIGINT)::VARCHAR,
        {{ column_name }}::VARCHAR
    )
{% endmacro %}