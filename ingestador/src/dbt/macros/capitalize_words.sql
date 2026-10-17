{#
    capitalize_words(column)

    Convierte una cadena a "capitalización de palabras" (title case): la primera
    letra de cada palabra en mayúscula y el resto en minúscula.
    Ej: 'ATALAYA' -> 'Atalaya', 'PUERTO BREU' -> 'Puerto Breu',
        'RODRIGUEZ DE MENDOZA' -> 'Rodriguez De Mendoza'.

    Devuelve un subquery escalar, así que se puede usar en el SELECT.
    NULL -> NULL; vacío -> ''.

    ----------------------------------------------------------------------------
    IMPLEMENTACIÓN NATIVA (DuckDB) — se quitó la recursión por el mismo motivo
    que en ``get_by_sep``: un ``WITH RECURSIVE`` dentro de una subconsulta escalar
    correlacionada no lo puede decorrelacionar DuckDB, así que se ejecutaba
    palabra por palabra y arrastraba ``LEFT_DELIM_JOIN``. Aquí no es tan grave
    como en ``get_by_sep`` (esta macro no va en claves de JOIN), pero forma parte
    del mismo patrón que tumbaba ``dbt run``.

    DuckDB **no** tiene ``initcap`` ni ``title`` (verificado en 1.5.5:
    "Scalar Function with name initcap does not exist"), así que NO se puede
    sustituir por una función de una sola llamada. Se hace con herramientas
    vectorizadas nativas:

        string_split -> lista de palabras (por espacios)
        unnest ... WITH ORDINALITY -> una fila por palabra, conservando el orden
        string_agg(..., ' ' ORDER BY i) -> se vuelven a unir con un espacio

    y, por palabra, ``upper(substr(w,1,1)) || lower(substr(w,2))``.

    Equivalencia con la versión recursiva (validada con ``EXPLAIN`` + comparación
    fila a fila de TODOS los valores reales: 10.010 ``sisa_sales.desorigen`` x2,
    10.010 ``desdestino``, 78 ``static_aux_airports.ubicacion`` -> 0 diferencias):
      * Solo se parte por ESPACIO (no por otros separadores: 'PUERTO-BREU' ->
        'Puerto-breu'), igual que antes; ``initcap`` habría cambiado eso.
      * NULL -> ``string_split`` da NULL, ``unnest`` no produce filas y
        ``string_agg`` de cero filas es NULL.
      * '' -> '' (una sola palabra vacía) y los espacios de los extremos se
        recortan antes de partir (``trim``), como el ``rtrim`` de antes.
      * ÚNICA diferencia, y es un DEFECTO del macro viejo: ante ESPACIOS
        CONSECUTIVOS el anterior se comía un carácter del tramo vacío y usaba
        ``substr(str,1,1)`` (¡el propio espacio!) como primera letra, así que
        INFLABA los espacios en uno: 'A  B' -> 'A   B' (3), 'multi   spaces' ->
        'Multi     Spaces' (5). El nuevo PRESERVA la entrada: 'A  B' -> 'A  B'.
        Los 30.098 valores reales no tienen espacios consecutivos, así que el
        cambio no afecta a ningún dato del DWH.
#}
{% macro capitalize_words(column) -%}
(
    SELECT string_agg(
               upper(substr(w, 1, 1)) || lower(substr(w, 2)),
               ' ' ORDER BY i
           )
    FROM unnest(string_split(trim({{ column }}), ' ')) WITH ORDINALITY AS t(w, i)
)
{%- endmacro %}
