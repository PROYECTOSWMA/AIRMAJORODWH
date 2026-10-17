{#
    normalize_registration(column)

    Devuelve la MATRÍCULA de la aeronave en su forma "pelada" (solo el número:
    '1919'), la llave común de las dos fuentes del indicador de consumo:

      * el CENTRO DE COSTO del combustible (`moves.cost_center`), que ya viene
        así ('2209', '2180') cuando la cuenta es la 603201;
      * la MATRÍCULA del reporte de horas de vuelo (`flight_reports.matricula`),
        con los tecleos de SISA: 'OB-1919-P', 'OB2180', 'OB 2209', 'OB2221P'.

    Traduce a SQL la regla de `assets.utils.normalize_matricula` (que se aplica en
    la capa de parseo), algo más permisiva: acepta un sufijo después del número
    ('OB-1919-P'), que es como llega la matrícula en el reporte de vuelos.

    Reglas:
      * '2092' (3-4 dígitos y nada más) -> '2092'  (centro de costo del combustible);
      * 'OB-1919-P' / 'ob 2209' / 'OB2221P' -> '1919' / '2209' / '2221'  (sufijo ignorado);
      * cualquier otra cosa ('SAETA', '' o NULL) -> NULL, para no inventar una
        aeronave: esas filas se caen al cruzar contra el maestro `static_airplanes`.

    Ojo: NO sirve un `regexp_extract` suelto de los primeros dígitos — con un
    centro de costo de 5 cifras ('20920') devolvería '2092' y atribuiría el
    combustible a otra aeronave. Por eso los números pelados se aceptan solo si la
    celda ENTERA son 3-4 dígitos.
#}
{% macro normalize_registration(column) -%}
    CASE
        WHEN {{ column }} IS NULL OR trim({{ column }}) = '' THEN NULL
        WHEN regexp_matches(trim({{ column }}), '^[0-9]{3,4}$') THEN trim({{ column }})
        ELSE NULLIF(
            regexp_extract(upper(trim({{ column }})), '^[0O]B[^0-9]*([0-9]{3,4})', 1),
            ''
        )
    END
{%- endmacro %}
