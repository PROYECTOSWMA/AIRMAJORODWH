{#
    normalize_currency(column_name)

    Normaliza una moneda cruda de cualquier fuente a la moneda canónica del
    consolidado: solo 'PEN' (soles) o 'USD' (dólares).

    Las fuentes mandan la moneda de muchas formas:
      * sire (ventas/compras)  -> 'PEN' / 'USD'
      * RH                     -> 'SOLES' y 'DÓLARES DE NORTE AMÉRICA' (este
                                  último llega además con el encoding corrupto
                                  'Dï¿½LARES DE NORTE AMï¿½RICA' por la Ó/É).
      * sisa (liquidaciones)  -> 'MN' (soles) / 'US' (dólares)
      * from_email_corpac_details -> 'S/' / 'US$'   (no se usa como currency)
      * from_email_adp_reports -> 'USD' / ''     ('' -> NULL)
      * lap / planilla         -> 'USD' / 'PEN'
      * talma                  -> 'DOL'          (tabla no usada hoy en dbt)

    Cualquier valor que no se pueda resolver (incluido NULL o '') se deja como
    NULL; las filas sin moneda se filtran aguas abajo donde corresponda.
#}
{% macro normalize_currency(column_name) -%}
CASE
    WHEN {{ column_name }} IS NULL THEN NULL
    WHEN upper(trim({{ column_name }})) IN ('PEN', 'SOL', 'SOLES', 'S/', 'NUEVOS SOLES', 'SOLES PERUANOS', 'MN') THEN 'PEN'
    WHEN upper({{ column_name }}) LIKE 'SOLES%' THEN 'PEN'
    WHEN upper(trim({{ column_name }})) IN ('USD', 'US$', 'US', 'DOL', 'DOLAR', 'DOLARES', 'DOLLARS', 'DOLARES AMERICANOS', 'DOLARES DE NORTE AMERICA', 'DOLARES DE NORTEAMERICA') THEN 'USD'
    WHEN upper({{ column_name }}) LIKE 'US$%' THEN 'USD'
    WHEN upper({{ column_name }}) LIKE '%LARES%' THEN 'USD'
    ELSE NULL
END
{%- endmacro %}
