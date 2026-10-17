---
title: Gastos de Personal
sidebar_position: 6
page_width: full
---

# Gastos de Personal

_Costo = total ingresos + total aportes_

```sql dim_anios
select distinct trim(periodo) as anio
from dwh.static_payroll
where coalesce(trim(periodo), '') <> ''
order by anio desc
```

```sql dim_areas
-- Área de planilla normalizada (mayúsculas y sin acentos) para que las variantes
-- del excel ('Administración' / 'ADMINISTRACIÓN') sean un solo valor.
select distinct translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU') as area
from dwh.static_payroll
where coalesce(translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU'), '') <> ''
order by area
```

```sql dim_unidades
-- Unidad de negocio del maestro de centros de costo, copiada a la planilla por dbt
-- (`static_payroll.agregado_unidad_de_negocio` = `static_cost_centers.unidad_negocio`):
-- NAZCA / SELVA / MEDEVAC / Costo de Ventas Otros / Gasto de administración / ...
select distinct agregado_unidad_de_negocio as unidad_de_negocio
from dwh.static_payroll
order by unidad_de_negocio
```

```sql dim_centros
-- Etiqueta del centro de costo del maestro de centros de costo, copiada a la planilla
-- por dbt (`static_payroll.agregado_centro_de_costo` = `static_cost_centers.descripcion`):
-- 'OB1919', 'GASTO ADMINISTRATIVO PUCALLPA', 'OMA', ... Las filas de la planilla cuyo
-- centro de costo NO está en el maestro no entran en la página (cruce interno en dbt).
select distinct agregado_centro_de_costo as centro_de_costo
from dwh.static_payroll
order by centro_de_costo
```

```sql dim_empresas
-- Empresa de la planilla, derivada del RÉGIMEN: RG -> Air Majoro, RMT -> Air Majoro Selva.
select distinct
  case trim(upper(regimen))
    when 'RG' then 'Air Majoro'
    when 'RMT' then 'Air Majoro Selva'
    else '(sin régimen)'
  end as empresa
from dwh.static_payroll
order by empresa
```

{% row %}
  {% dropdown id="anio" data="dim_anios" value_column="anio" label_column="anio" title="Año" order="anio desc" select_first=true placeholder="Año" /%}
  {% dropdown id="area" data="dim_areas" value_column="area" label_column="area" title="Área" multiple=true search=true placeholder="Todas las áreas" /%}
  {% dropdown id="unidad" data="dim_unidades" value_column="unidad_de_negocio" label_column="unidad_de_negocio" title="Unidad de negocio" multiple=true placeholder="Todas las unidades" /%}
  {% dropdown id="cc" data="dim_centros" value_column="centro_de_costo" label_column="centro_de_costo" title="Centro de costo" multiple=true search=true placeholder="Todos los centros de costo" /%}
  {% dropdown id="empresa" data="dim_empresas" value_column="empresa" label_column="empresa" title="Empresa" multiple=true placeholder="Todas las empresas" /%}
{% /row %}

## Resumen

```sql kpis
select
  count(distinct dni) as personas,
  sum(total_ingresos + total_aportes) as costo
from dwh.static_payroll
where 1 = 1
  [[ and trim(periodo) = {{ anio }} ]]
  [[ and translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU') in {{ area }} ]]
  [[ and agregado_unidad_de_negocio in {{ unidad }} ]]
  [[ and agregado_centro_de_costo in {{ cc }} ]]
  [[ and case trim(upper(regimen)) when 'RG' then 'Air Majoro' when 'RMT' then 'Air Majoro Selva' else '(sin régimen)' end in {{ empresa }} ]]
```

{% row %}
  {% big_value data="kpis" value="personas" fmt="num0" title="Personas" /%}
  {% big_value data="kpis" value="costo" fmt="num0" title="Costo" /%}
{% /row %}

## Costo y personal por período

```sql personal_mes
select
  make_date(trim(periodo)::int, trim(mes)::int, 1) as mes,
  count(distinct dni) as personas,
  sum(total_ingresos + total_aportes) as costo
from dwh.static_payroll
-- `periodo`/`mes` son texto en la planilla ('2026', '7'): el filtro por expresión
-- regular garantiza que el cast a entero nunca falle con datos sucios.
where trim(periodo) ~ '^[0-9]{4}$'
  and trim(mes) ~ '^[0-9]{1,2}$'
  [[ and trim(periodo) = {{ anio }} ]]
  [[ and translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU') in {{ area }} ]]
  [[ and agregado_unidad_de_negocio in {{ unidad }} ]]
  [[ and agregado_centro_de_costo in {{ cc }} ]]
  [[ and case trim(upper(regimen)) when 'RG' then 'Air Majoro' when 'RMT' then 'Air Majoro Selva' else '(sin régimen)' end in {{ empresa }} ]]
group by 1
order by 1
```

{% row %}
  {% line_chart
    data="personal_mes"
    x="mes"
    y="sum(costo) as Costo"
    date_grain="month"
    y_fmt="num0"
  /%}
  {% line_chart
    data="personal_mes"
    x="mes"
    y="sum(personas) as Personas"
    date_grain="month"
    y_fmt="num0"
  /%}
{% /row %}

## Tamaño de personal por unidad de negocio

```sql personal_unidad
select
  agregado_unidad_de_negocio as unidad_de_negocio,
  count(distinct dni) as personas
from dwh.static_payroll
where 1 = 1
  [[ and trim(periodo) = {{ anio }} ]]
  [[ and translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU') in {{ area }} ]]
  [[ and agregado_unidad_de_negocio in {{ unidad }} ]]
  [[ and agregado_centro_de_costo in {{ cc }} ]]
  [[ and case trim(upper(regimen)) when 'RG' then 'Air Majoro' when 'RMT' then 'Air Majoro Selva' else '(sin régimen)' end in {{ empresa }} ]]
group by 1
order by 2 desc
```

{% pie_chart
  data="personal_unidad"
  category="unidad_de_negocio"
  value="sum(personas)"
  value_fmt="num0"
  pct=true
  legend=true
/%}

## Personal y costo por área

```sql personal_area
select
  coalesce(
    nullif(translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU'), ''),
    '(sin área)'
  ) as area,
  make_date(trim(periodo)::int, trim(mes)::int, 1) as mes,
  count(distinct dni) as personas,
  sum(total_ingresos + total_aportes) as costo
from dwh.static_payroll
where trim(periodo) ~ '^[0-9]{4}$'
  and trim(mes) ~ '^[0-9]{1,2}$'
  [[ and trim(periodo) = {{ anio }} ]]
  [[ and translate(upper(trim(area)), 'ÁÉÍÓÚ', 'AEIOU') in {{ area }} ]]
  [[ and agregado_unidad_de_negocio in {{ unidad }} ]]
  [[ and agregado_centro_de_costo in {{ cc }} ]]
  [[ and case trim(upper(regimen)) when 'RG' then 'Air Majoro' when 'RMT' then 'Air Majoro Selva' else '(sin régimen)' end in {{ empresa }} ]]
group by 1, 2
```

{% table
  data="personal_area"
  page_size=200
  freeze_columns=1
  repeat_values=true
%}
  {% dimension value="area" title="Área" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(personas)" title="Personas" fmt="num0" /%}
  {% measure value="sum(costo)" title="Costo" fmt="num0" /%}
{% /table %}

