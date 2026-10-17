{#
    split_invoice_doc(column, parte)

    Separa el número de factura **tal como lo imprime el proveedor** en las dos
    columnas del contrato del DWH:

      * ``parte = 'serie'``  -> la parte de texto antes del guion ('INVC', 'KA26');
      * ``parte = 'numero'`` -> lo que va después del guion ('18214', '0204').

    Reglas (los formatos reales de ``static/INVOICE INTERNACIONALES``):

      * 'INVC-18214' -> serie 'INVC'   / número '18214'   (Fenix);
      * 'KA26-0204'  -> serie 'KA26'   / número '0204'    (Kal);
      * 'IJ17531927' -> serie 'IJ17531927' / número NULL  (Textron: sin guion y con
        letras, así que el número queda en la serie para **no perder** la identidad
        de la factura; el ``TRY_CAST`` a BIGINT del número daría NULL);
      * '54998'      -> serie NULL     / número '54998'    (JetSet, todo numérico);
      * 'I67995'     -> serie 'I67995' / número NULL       (Peniel, igual que Textron);
      * '99214024'   -> serie NULL     / número '99214024' (PAG).

    Se resuelve con ``instr`` + ``get_by_sep`` (nada de ``regexp`` para el corte)
    porque el mismo proyecto corre en DuckDB y el ``get_by_sep`` ya está probado en
    las otras ramas.
#}
{% macro split_invoice_doc(column, parte) -%}
    CASE
        WHEN {{ column }} IS NULL OR trim({{ column }}) = '' THEN NULL
        {%- if parte == 'serie' %}
        WHEN instr({{ column }}, '-') > 0 THEN {{ get_by_sep(column, "'-'", 0) }}
        -- Sin guion: si NO es un número puro, la serie se queda con todo el número
        -- (así 'IJ17531927' no se pierde); si es numérico, no hay serie.
        WHEN TRY_CAST(trim({{ column }}) AS BIGINT) IS NULL THEN trim({{ column }})
        ELSE NULL
        {%- elif parte == 'numero' %}
        WHEN instr({{ column }}, '-') > 0 THEN {{ get_by_sep(column, "'-'", 1) }}
        ELSE trim({{ column }})
        {%- else %}
        {% do exceptions.raise_compiler_error("split_invoice_doc: 'parte' debe ser 'serie' o 'numero'") %}
        {%- endif %}
    END
{%- endmacro %}
