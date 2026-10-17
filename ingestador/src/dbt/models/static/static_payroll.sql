{{ config(materialized='table') }}

-- Copia la tabla `static_payroll` de `db.sqlite` a DuckDB conservando SUS columnas
-- de origen (las mismas que deja la ingesta `static_data_asset` al parsear
-- `Planilla.ods`, spec `planilla`, modelo peewee `StaticPayroll`: una fila por
-- persona y mes — los conceptos remunerativos son COLUMNAS, no filas) y le AÑADE
-- dos columnas derivadas para que el informe separe la planilla sin cruzar con
-- `moves`:
--
--   · `agregado_unidad_de_negocio` → la UNIDAD DE NEGOCIO del maestro de centros de
--     costo (`static_cost_centers.unidad_negocio`).
--   · `agregado_centro_de_costo`   → la ETIQUETA del centro de costo del maestro
--     (`static_cost_centers.descripcion`: 'OB1919', 'GASTO ADMINISTRATIVO PUCALLPA',
--     'OMA', ...).
--
-- NADA de la clasificación vive en SQL: los dos valores salen TAL CUAL del maestro, que
-- se edita en `static/dwh_static_cost_centers.csv`. Antes había aquí un `CASE` con las
-- aeronaves (`static_airplanes.business_unit`/`base`) y con los códigos de gasto, más
-- literales para los códigos que no estaban en el maestro ('AEROLINEA VIVE PERU',
-- 'EJERCITO PERUANO', 'SUMINISTROS E INSUMOS MEDICOS'): todo eso se eliminó al
-- ampliarse el maestro de centros de costo.
--
-- CRUCE: `static_payroll.ccosto` trae el CÓDIGO de centro de costo ('101', '102', ...,
-- 'OPE-NAZCA'), que es el `codigo` del maestro. Se normaliza SOLO para el cruce, porque
-- la planilla trae el mismo código como texto ('101'), como entero con decimales
-- ('104.00') y como número ('104'): `clean_int_to_string` deja todos como '101'/'104'.
-- La columna de origen NO se modifica; la derivada de apoyo (`ccosto_code`) se excluye
-- de la salida.
--
-- El cruce es INNER JOIN: **si el centro de costo de la planilla no está en el maestro
-- no entra** en el informe (no se inventa etiqueta ni se cae a '(sin asignar)').
-- `NOAPLICA` tampoco entra: no identifica ningún centro de costo.
--
-- El nombre "pelado" del `FROM` lo resuelve el `search_path: src.main` contra
-- `db.sqlite` (igual que `flight_reports`): el modelo materializa `main.static_payroll`
-- en DuckDB y el asset `publish_dwh` la publica como `dwh.static_payroll`.
--
-- Se publica SIN el unpivot contable (no pasa por `payroll_std`, que sigue leyendo
-- la tabla de `db.sqlite`): así el informe usa la planilla —área, oficina, régimen y
-- centro de costo por persona— cuando no necesita el detalle por cuenta.

with payroll as (
    select
        p.*,
        {{ clean_int_to_string('p.ccosto') }} as ccosto_code
    from static_payroll p
),

centros_de_costo as (
    -- Una fila por `codigo` (aunque el maestro traiga repetidos: el informe no puede
    -- duplicar personas por un centro de costo). `NOAPLICA` se descarta: no identifica
    -- ningún centro de costo.
    select
        codigo,
        min(descripcion) as descripcion,
        min(unidad_negocio) as unidad_negocio
    from {{ ref('static_cost_centers') }}
    where codigo <> 'NOAPLICA'
    group by codigo
)

select
    p.* exclude (ccosto_code),

    -- Unidad de negocio agregada (la del maestro de centros de costo).
    c.unidad_negocio as agregado_unidad_de_negocio,

    -- Etiqueta del centro de costo (la que se ve en el informe).
    c.descripcion as agregado_centro_de_costo

from payroll p
join centros_de_costo c on c.codigo = p.ccosto_code

