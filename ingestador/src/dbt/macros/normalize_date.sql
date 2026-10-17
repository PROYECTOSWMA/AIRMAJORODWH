{#
    normalize_date(column, input_format='DD/MM/YYYY', output_format='YYYY-MM-DD')

    Normaliza una fecha en texto cruda al formato estándar del DWH (por defecto
    ISO 'YYYY-MM-DD', que es el que consumen las columnas DATE de PostgreSQL) y
    devuelve NULL cuando la fecha no es utilizable.

    Casos que devuelven NULL:
      * la columna es NULL o una cadena vacía / solo espacios,
      * el año queda fuera del rango [1900, 2030] (esto cubre el centinela
        '00/00/0000' de las fuentes, cuyo año es 0000),
      * el mes queda fuera de [1, 12] o el día fuera de [1, 31] (fechas
        corruptas que PostgreSQL rechazaría al publicar el DuckDB (asset `publish_dwh`).

    El formato de entrada llega como parámetro y la macro BUSCA en él los
    patrones 'YYYY', 'MM' y 'DD' (regex nativo de dbt: modules.re) para saber en
    qué posición está cada parte; no asume posiciones fijas. El separador puede
    ser cualquiera ('/', '-', '.', ...) y se ignoran los caracteres ajenos a los
    tokens (por ejemplo la hora ' HH:MM' que trae CORPAC en 'DD/MM/YYYY HH:MM').

    Nota: SQLite no tiene función nativa para parsear 'DD/MM/YYYY' (date() solo
    entiende ISO-8601 y además normaliza desbordes en silencio), por eso se
    reordena con substr y se valida con guardas explícitas (año/mes/día).

    Las guardas usan el macro `safe_int` (CAST en SQLite, TRY_CAST en DuckDB)
    porque un CAST estricto a entero de un texto no numérico revienta en DuckDB
    ("Conversion Error: Could not convert string '' to INT64") donde SQLite
    devolvía 0. Cada motor marca el valor inválido de forma distinta (0 vs NULL),
    así que la guarda cubre las dos: `IS NULL OR NOT BETWEEN ...`.

    Argumentos:
      * column        -> expresión/columna SQL con la fecha en texto.
      * input_format  -> formato de la fecha cruda (default 'DD/MM/YYYY').
      * output_format -> formato deseado, reordenando los mismos tokens
                         (default 'YYYY-MM-DD').

    Ej.:
      normalize_date('d.fecha_llegada')                  -> '11/08/2026 15:12' -> '2026-08-11'
      normalize_date('l.fecha_factura')                  -> '08/07/2026'      -> '2026-07-08'
      normalize_date('p.fecha')                          -> '00/00/0000'      -> NULL
      normalize_date('p.fecha')                          -> '' / NULL         -> NULL
      normalize_date('x.fecha', 'YYYY-MM-DD')            -> '2026-07-08'      -> '2026-07-08'
#}
{% macro normalize_date(column, input_format='DD/MM/YYYY', output_format='YYYY-MM-DD') -%}
    {%- set in_fmt = input_format | upper -%}
    {#- Busca los patrones con la regex nativa de dbt para localizar cada parte. -#}
    {%- set y = modules.re.search('YYYY', in_fmt) -%}
    {%- set m = modules.re.search('MM', in_fmt) -%}
    {%- set d = modules.re.search('DD', in_fmt) -%}
    {%- if not (y and m and d) -%}
        {{ exceptions.raise_compiler_error("normalize_date: input_format='" ~ input_format ~ "' debe contener los tokens YYYY, MM y DD.") }}
    {%- endif -%}
    {%- set y_pos, m_pos, d_pos = y.start(), m.start(), d.start() -%}
    {%- set year_txt  = "substr(trim(" ~ column ~ "), " ~ (y_pos + 1) ~ ", 4)" -%}
    {%- set month_txt = "substr(trim(" ~ column ~ "), " ~ (m_pos + 1) ~ ", 2)" -%}
    {%- set day_txt   = "substr(trim(" ~ column ~ "), " ~ (d_pos + 1) ~ ", 2)" -%}
    {#- Reordena los tokens del output_format: '@' delimita los tokens y cada
        literal restante (el separador) se emite entre comillas. -#}
    {%- set marked = output_format | upper | replace('YYYY', '@Y@') | replace('MM', '@M@') | replace('DD', '@D@') -%}
    {%- set ns = namespace(parts=[]) -%}
    {%- for tok in marked.split('@') -%}
        {%- if tok == 'Y' -%}
            {%- set ns.parts = ns.parts + [year_txt] -%}
        {%- elif tok == 'M' -%}
            {%- set ns.parts = ns.parts + [month_txt] -%}
        {%- elif tok == 'D' -%}
            {%- set ns.parts = ns.parts + [day_txt] -%}
        {%- elif tok != '' -%}
            {%- set ns.parts = ns.parts + ["'" ~ tok ~ "'"] -%}
        {%- endif -%}
    {%- endfor -%}
    CASE
        WHEN {{ column }} IS NULL OR trim({{ column }}) = '' THEN NULL
        WHEN {{ safe_int(year_txt) }} IS NULL
             OR {{ safe_int(year_txt) }} NOT BETWEEN 1900 AND 2030 THEN NULL
        WHEN {{ safe_int(month_txt) }} IS NULL
             OR {{ safe_int(month_txt) }} NOT BETWEEN 1 AND 12 THEN NULL
        WHEN {{ safe_int(day_txt) }} IS NULL
             OR {{ safe_int(day_txt) }} NOT BETWEEN 1 AND 31 THEN NULL
        ELSE {{ ns.parts | join(' || ') }}
    END
{%- endmacro %}
