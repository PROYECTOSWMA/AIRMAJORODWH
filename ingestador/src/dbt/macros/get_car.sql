{#
    get_car(emisor, tipo, serie, numero)

    Construye la clave SUNAT ``car_sunat`` de un comprobante a partir de sus
    partes, con el mismo formato que cc_filename_to_car_sunat:

        RUC emisor (11) + tipo (2) + serie (4) + número a 10 dígitos

    ``emisor``/``serie`` se concatenan tal cual; ``tipo``/``numero`` se convierten
    a enteros para que printf les aplique el ancho fijo. Se usa en ``compras``
    (para cruzar la unión con ``cost_centers``) y en ``adp_purchs_std`` (para
    reconstruir el ``car_sunat`` de sire_purchs desde la referencia de ADP).

    Los CAST son a ``BIGINT`` (64 bits) y no a ``INTEGER``: en DuckDB ``INTEGER``
    es INT32 y los números de documento/RUC de 10 dígitos lo desbordan
    ("Could not convert string ... to INT32"), mientras que en SQLite ``BIGINT``
    tiene afinidad INTEGER (64 bits), así que el SQL vale en ambos motores.

    OJO — se usa ``safe_int`` (``TRY_CAST`` en DuckDB), NO un ``CAST`` a pelo:
    un ``CAST('' AS BIGINT)`` **revienta dbt** con
    "Conversion Error: Could not convert string '' to INT64". Pasó de verdad:
    ``from_email_adp_reports`` tiene 60 filas con ``referencia`` VACÍA (y
    ``servicio`` no nulo, así que pasan el ``WHERE`` del modelo) y esas 60 filas
    llegaban al ``CAST`` del JOIN de ``adp_purchs_std`` y tumbaban todo el
    ``dbt run``. Con ``TRY_CAST`` el tramo vacío/ no numérico queda NULL ⇒ la
    clave entera es NULL ⇒ el INNER JOIN no casa y la fila se descarta sola
    (que es lo correcto: sin referencia de documento no hay compra que derivar),
    en vez de romper. Es la misma política que ya documenta ``moves.sql``
    ("Siempre TRY_CAST, nunca CAST").
#}
{% macro get_car(emisor, tipo, serie, numero) -%}
    {{ emisor }} || printf('%02d', {{ safe_int(tipo) }})
        || {{ serie }} || printf('%010d', {{ safe_int(numero) }})
{%- endmacro %}