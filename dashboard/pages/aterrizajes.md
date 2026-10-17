---
title: Aterrizajes
sidebar_position: 4
page_width: full
---

# Aterrizajes

```sql dim_anios
select distinct extract(year from fecha_emision)::int as anio
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
order by anio desc
```

```sql dim_proveedores
select distinct cliente_proveedor as proveedor
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%' and coalesce(cliente_proveedor, '') <> ''
order by proveedor
```

```sql dim_empresas
select distinct empresa
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%' and coalesce(empresa, '') <> ''
order by empresa
```

```sql dim_centros_costo
with pares as (
  select distinct centro_de_costo as cc
  from dwh.vista_reporte_gerencial
  where cuenta_contable_descripcion ilike '%ATERRIZAJE%' and coalesce(centro_de_costo, '') <> ''
),
exacto as (
  select s.abreviatura as cc, min(s.descripcion) as descripcion
  from dwh.static_cost_centers s
  where exists (select 1 from pares p where p.cc = s.abreviatura)
  group by 1
)
select
  p.cc,
  case when e.descripcion is null then p.cc else e.descripcion || ' · ' || p.cc end as centro_costo
from pares p
left join exacto e on e.cc = p.cc
order by 2
```

```sql dim_aeropuertos
select distinct aeropuerto_origen as aeropuerto
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
  and coalesce(aeropuerto_origen, '') <> ''
  and aeropuerto_origen not ilike 'No es nomenclatura ICAO%'
order by aeropuerto
```

{% row %}
  {% dropdown id="anio" data="dim_anios" value_column="anio" label_column="anio" title="Año" order="anio desc" select_first=true placeholder="Año" /%}
  {% dropdown id="empresa" data="dim_empresas" value_column="empresa" label_column="empresa" title="Empresa" multiple=true placeholder="Todas las empresas" /%}
  {% dropdown id="cc" data="dim_centros_costo" value_column="cc" label_column="centro_costo" title="Centro de costo" multiple=true search=true placeholder="Todos los centros de costo" /%}
  {% dropdown id="proveedor" data="dim_proveedores" value_column="proveedor" label_column="proveedor" title="Proveedor" multiple=true search=true placeholder="Todos los proveedores" /%}
  {% dropdown id="aeropuerto" data="dim_aeropuertos" value_column="aeropuerto" label_column="aeropuerto" title="Aeropuerto" multiple=true search=true placeholder="Todos los aeropuertos" /%}
{% /row %}

## Resumen

```sql kpis
select
  count(distinct documento) as aterrizajes,
  sum(-subtotal_base_soles) as costo,
  sum(-subtotal_base_soles) / nullif(count(distinct documento), 0) as tarifa_promedio
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and centro_de_costo in {{ cc }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
```

{% row %}
  {% big_value data="kpis" value="aterrizajes" fmt="num0" title="Aterrizajes facturados" /%}
  {% big_value data="kpis" value="costo" fmt="num0" title="Costo (S/)" /%}
  {% big_value data="kpis" value="tarifa_promedio" fmt="num2" title="Tarifa promedio (S/)" /%}
{% /row %}

## Costo de aterrizajes por período

```sql aterrizajes_mes
select
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(-subtotal_base_soles) as costo
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and centro_de_costo in {{ cc }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
group by 1
```

{% line_chart
  data="aterrizajes_mes"
  x="mes"
  y="sum(costo) as `Costo`"
  date_grain="month"
  y_fmt="num0"
  data_labels={ position="above" }
/%}

## Distribución por proveedor

```sql aterrizajes_proveedor
select
  cliente_proveedor as proveedor,
  sum(-subtotal_base_soles) as costo
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and centro_de_costo in {{ cc }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
group by 1
order by 2 desc
```

{% pie_chart
  data="aterrizajes_proveedor"
  category="proveedor"
  value="costo"
  value_fmt="num0"
  pct=true
  pct_fmt="pct1"
  legend=false
  inner_radius="0%"
  height=420
/%}

## Aterrizajes por mes

```sql aterrizajes_detalle
select
  cliente_proveedor as proveedor,
  coalesce(nullif(descripcion_servicio, ''), '(sin descripción)') as descripcion_servicio,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  count(distinct documento) as aterrizajes
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and centro_de_costo in {{ cc }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
group by 1, 2, 3
```

{% outline_table data="aterrizajes_detalle" value="aterrizajes" title="Aterrizajes por mes" /%}

## Costo por mes

```sql costos_detalle
select
  cliente_proveedor as proveedor,
  coalesce(nullif(descripcion_servicio, ''), '(sin descripción)') as descripcion_servicio,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(-subtotal_base_soles) as costo
from dwh.vista_reporte_gerencial
where cuenta_contable_descripcion ilike '%ATERRIZAJE%'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and centro_de_costo in {{ cc }} ]]
[[ and cliente_proveedor in {{ proveedor }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
group by 1, 2, 3
```

{% outline_table data="costos_detalle" value="costo" title="Costo por mes" /%}
