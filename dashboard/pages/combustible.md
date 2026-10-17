---
title: Combustible
sidebar_position: 5
page_width: full
---

# Combustible

```sql dim_anios
select distinct extract(year from fecha_emision)::int as anio
from dwh.vista_reporte_gerencial
where cuenta_contable_codigo = '603201'
-- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
order by anio desc
```

```sql dim_tipos
select distinct
  coalesce(nullif(trim(descripcion_servicio), ''), 'NO IDENTIFICADO') as tipo_combustible
from dwh.vista_reporte_gerencial
where cuenta_contable_codigo = '603201'
-- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
order by tipo_combustible
```

```sql dim_proveedores
select distinct cliente_proveedor as proveedor
from dwh.vista_reporte_gerencial
where cuenta_contable_codigo = '603201'
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
  and coalesce(cliente_proveedor, '') <> ''
order by proveedor
```

```sql dim_empresas
select distinct empresa
from dwh.vista_reporte_gerencial
where cuenta_contable_codigo = '603201'
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
  and coalesce(empresa, '') <> ''
order by empresa
```

```sql dim_centros_costo
select distinct centro_de_costo as cc
from dwh.vista_reporte_gerencial
where cuenta_contable_codigo = '603201'
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
  and coalesce(centro_de_costo, '') <> ''
order by cc
```

{% row %}
  {% dropdown id="anio" data="dim_anios" value_column="anio" label_column="anio" title="Año" order="anio desc" select_first=true placeholder="Año" /%}
  {% dropdown id="empresa" data="dim_empresas" value_column="empresa" label_column="empresa" title="Empresa" multiple=true placeholder="Todas las empresas" /%}
  {% dropdown id="cc" data="dim_centros_costo" value_column="cc" label_column="cc" title="Centro de costo" multiple=true search=true placeholder="Todos los centros de costo" /%}
  {% dropdown id="proveedor" data="dim_proveedores" value_column="proveedor" label_column="proveedor" title="Proveedor" multiple=true search=true placeholder="Todos los proveedores" /%}
  {% dropdown id="tipo" data="dim_tipos" value_column="tipo_combustible" label_column="tipo_combustible" title="Tipo de combustible" multiple=true placeholder="Todos los tipos" /%}
{% /row %}

## Resumen

```sql kpis
with base as (
  select
    cantidad,
    subtotal_base,
    subtotal_base_soles,
    documento,
    cliente_proveedor,
    centro_de_costo,
    empresa,
    fecha_emision,
    coalesce(nullif(trim(descripcion_servicio), ''), 'NO IDENTIFICADO') as tipo_combustible
  from dwh.vista_reporte_gerencial
  where cuenta_contable_codigo = '603201'
  -- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
)
select
  sum(cantidad) as galones,
  sum(-subtotal_base_soles) as costo,
  count(distinct documento) as facturas
from base
where 1 = 1
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and tipo_combustible in {{ tipo }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and centro_de_costo in {{ cc }} ]]
```

{% row %}
  {% big_value data="kpis" value="galones" fmt="num1" title="Galones consumidos" /%}
  {% big_value data="kpis" value="costo" fmt="num0" title="Costo (S/)" /%}
  {% big_value data="kpis" value="facturas" fmt="num0" title="Facturas" /%}
{% /row %}

## Costo de combustible por período

```sql combustible_mes
with base as (
  select
    subtotal_base_soles,
    fecha_emision,
    cliente_proveedor,
    centro_de_costo,
    empresa,
    coalesce(nullif(trim(descripcion_servicio), ''), 'NO IDENTIFICADO') as tipo_combustible
  from dwh.vista_reporte_gerencial
  where cuenta_contable_codigo = '603201'
  -- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
)
select
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(-subtotal_base_soles) as costo
from base
where 1 = 1
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and tipo_combustible in {{ tipo }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1
```

{% line_chart
  data="combustible_mes"
  x="mes"
  y="sum(costo) as `Costo`"
  date_grain="month"
  y_fmt="num0"
/%}

## Costo promedio ponderado

```sql costo_promedio_mes
with base as (
  select
    cantidad,
    subtotal_base,
    fecha_emision,
    cliente_proveedor,
    centro_de_costo,
    empresa,
    coalesce(nullif(trim(descripcion_servicio), ''), 'NO IDENTIFICADO') as tipo_combustible
  from dwh.vista_reporte_gerencial
  where cuenta_contable_codigo = '603201'
  -- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
)
select
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  tipo_combustible,
  sum(-subtotal_base) as costo_usd,
  sum(cantidad) as galones
from base
where 1 = 1
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and tipo_combustible in {{ tipo }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2
```

{% line_chart
  data="costo_promedio_mes"
  x="mes"
  y="sum(costo_usd) / nullif(sum(galones), 0) as `Costo (US$/galón)`"
  series="tipo_combustible"
  date_grain="month"
  y_fmt="num2"
/%}

## Número de galones por tipo de combustible

```sql galones_tabla
with base as (
  select
    cantidad,
    fecha_emision,
    cliente_proveedor,
    centro_de_costo,
    empresa,
    coalesce(nullif(trim(descripcion_servicio), ''), 'NO IDENTIFICADO') as tipo_combustible
  from dwh.vista_reporte_gerencial
  where cuenta_contable_codigo = '603201'
  -- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
)
select
  tipo_combustible,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(cantidad) as galones
from base
where 1 = 1
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and tipo_combustible in {{ tipo }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2
```

{% table
  data="galones_tabla"
  page_size=100
  freeze_columns=1
  repeat_values=true
%}
  {% dimension value="tipo_combustible" title="Tipo de combustible" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(galones)" title="Galones" fmt="num1" /%}
{% /table %}

## Costo por proveedor

```sql costo_proveedor
with base as (
  select
    subtotal_base_soles,
    fecha_emision,
    cliente_proveedor,
    centro_de_costo,
    empresa,
    coalesce(nullif(trim(descripcion_servicio), ''), 'NO IDENTIFICADO') as tipo_combustible
  from dwh.vista_reporte_gerencial
  where cuenta_contable_codigo = '603201'
  -- Los 'NO IDENTIFICADO' (CC que no es aeronave del maestro) no se muestran.
  and coalesce(descripcion_servicio, '') <> 'NO IDENTIFICADO'
)
select
  cliente_proveedor as proveedor,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(-subtotal_base_soles) as costo
from base
where 1 = 1
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and tipo_combustible in {{ tipo }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2
```

{% table
  data="costo_proveedor"
  page_size=100
  freeze_columns=1
  repeat_values=true
%}
  {% dimension value="proveedor" title="Proveedor" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(costo)" title="Costo" fmt="num0" /%}
{% /table %}

## Galones por hora de vuelo

```sql galones_por_hora
select
  mes,
  aeronave,
  horas,
  galones,
  galones_por_hora
from dwh.gallons_per_flight_hour
where 1 = 1
[[ and extract(year from mes)::int = {{ anio }} ]]
[[ and aeronave in {{ cc }} ]]
```

{% table
  data="galones_por_hora"
  page_size=100
  freeze_columns=1
  repeat_values=true
  show_total_column=false
%}
  {% dimension value="aeronave" title="Aeronave" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(galones_por_hora)" title="Galones por hora" fmt="num2" /%}
{% /table %}


