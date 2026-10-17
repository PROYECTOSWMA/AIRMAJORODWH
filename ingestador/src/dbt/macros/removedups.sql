{#
    removedups(source, key_col)

    Quita filas repetidas por el valor de ``key_col`` conservando una sola fila
    por clave (la de menor ``id``).

    Uso típico: los modelos que procesan ``sire_purchs``/``sire_sales`` deben
    evitar duplicar documentos que SUNAT repite en más de un período. En lugar
    de leer la tabla fuente directo, se envuelve:

        FROM ({{ removedups('sire_purchs', 'car_sunat') }}) s

    No toca la tabla fuente: es una deduplicación en la consulta.

    Implementación SIN índice y en un solo barrido: se conserva, por cada clave
    NO nula, la fila de ``MIN(id)`` (subconsulta agrupada + búsqueda por rowid).
    Así se evita el anti-join correlacionado cuadrático (O(N²)) que barría toda
    la tabla por cada fila. Las filas con ``key_col`` NULL se conservan TODAS,
    igual que el antiguo ``NOT EXISTS`` (donde ``NULL = NULL`` nunca casa), de
    modo que el resultado no pierde filas. No usa ``WITH``/ventana y su
    resultado se puede incrustar como subconsulta en SQLite.
#}
{% macro removedups(source, key_col) -%}
SELECT * FROM {{ source }} s
WHERE s.{{ key_col }} IS NULL
   OR s.id IN (
       SELECT MIN(o.id)
       FROM {{ source }} o
       WHERE o.{{ key_col }} IS NOT NULL
       GROUP BY o.{{ key_col }}
   )
{%- endmacro %}
