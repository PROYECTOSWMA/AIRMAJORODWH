{#
    get_by_sep(text, sep, n)

    Tramo (segmento) ``n``-ésimo de ``text`` al separarlo por ``sep`` (índice 0).

    - ``n = 0``: desde el inicio hasta la 1.ª ocurrencia; si ``sep`` no aparece,
      todo el texto.
    - ``n >= 1``: entre la ``n``-ésima y la ``(n+1)``-ésima ocurrencia.
    - Si la ``n``-ésima no existe: ``NULL``.
    - Si existe la ``n``-ésima pero no la siguiente: hasta el final.

    Nunca incluye el separador. ``text``/``sep`` pueden ser literales o columnas;
    ``n`` es un literal entero >= 0. Ej.: con '01-0F001-0111360' y '-' ->
    n=0 '01', n=1 '0F001', n=2 '0111360'.

    ----------------------------------------------------------------------------
    IMPLEMENTACIÓN NATIVA (DuckDB) — la recursión anterior TUMBABA `dbt run`.

    Antes esto era un ``WITH RECURSIVE`` escalar. El problema NO era la
    recursión en sí, sino que ``adp_purchs_std`` la usa **dentro de la clave de
    un JOIN** (3 veces: tipo, serie y número). DuckDB no sabe decorrelacionar un
    CTE recursivo, así que degradaba el JOIN a ``LEFT_DELIM_JOIN`` (ejecución
    dependiente fila por fila): con 4.654 filas de ADP × 15.603 de ``sire_purchs``
    eso son ~72,6 M evaluaciones recursivas, y el join llegaba a **spill de ~8 GB**
    en ``analytics_poc.duckdb.tmp/`` hasta agotar la RAM de la máquina. Verificado
    con ``EXPLAIN``: el plan pasaba de delimited joins (con REC_CTE_SCAN por fila)
    a un ``HASH_JOIN`` plano.

    Equivalencia exacta con la versión recursiva: ``split(text, sep)[n]``
    (0-indexado) y ``NULL`` cuando ese tramo no existe. Se usa ``string_split`` +
    ``list_extract`` y NO ``split_part`` porque ``split_part`` devuelve la cadena
    VACÍA fuera de rango (``''``) y aquí el contrato es ``NULL`` (lo necesitan
    ``adp_purchs_std``/``get_car``: un número que no existe debe quedar NULL, no
    0). ``list_extract`` sí devuelve NULL fuera de rango, también para el índice 0.
    ``n + 1`` porque ``list_extract`` es 1-indexado.
#}
{% macro get_by_sep(text, sep, n) -%}
    (list_extract(string_split({{ text }}, {{ sep }}), {{ n + 1 }}))
{%- endmacro %}
