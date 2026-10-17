---
title: Ventas
sidebar_position: 2
page_width: full
---

# Ventas

```sql dim_anios
select distinct extract(year from fecha_emision)::int as anio
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
order by anio desc
```

```sql dim_unidades
select distinct cuenta_contable_descripcion as unidad
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
order by unidad
```

```sql dim_aeropuertos
select distinct aeropuerto_origen as aeropuerto
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas' and coalesce(aeropuerto_origen, '') <> ''
order by aeropuerto
```

```sql dim_monedas
select distinct moneda
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
order by moneda
```

```sql dim_centros_costo
with pares as (
  select distinct centro_de_costo as cc
  from dwh.vista_reporte_gerencial
  where tipo_movimiento = 'Ventas' and coalesce(centro_de_costo, '') <> ''
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

{% row %}
  {% dropdown id="anio" data="dim_anios" value_column="anio" label_column="anio" title="Año" order="anio desc" select_first=true placeholder="Año" /%}
  {% dropdown id="unidad" data="dim_unidades" value_column="unidad" label_column="unidad" title="Unidad de negocio" multiple=true search=true placeholder="Todas las unidades" /%}
  {% dropdown id="aeropuerto" data="dim_aeropuertos" value_column="aeropuerto" label_column="aeropuerto" title="Aeropuerto" multiple=true search=true placeholder="Todos los aeropuertos" /%}
  {% dropdown id="moneda" data="dim_monedas" value_column="moneda" label_column="moneda" title="Moneda" multiple=true placeholder="Todas las monedas" /%}
  {% dropdown id="cc" data="dim_centros_costo" value_column="cc" label_column="centro_costo" title="Centro de costo" multiple=true search=true placeholder="Todos los centros de costo" /%}
{% /row %}

## Resumen

```sql kpis
select
  sum(subtotal_base_soles) as ventas_soles,
  sum(case when moneda = 'USD' then subtotal_base_soles else 0 end) as ventas_usd,
  sum(case when moneda = 'PEN' then subtotal_base_soles else 0 end) as ventas_pen,
  count(distinct documento) as comprobantes,
  count(distinct cliente_proveedor) as clientes,
  sum(subtotal_base_soles) / nullif(count(distinct documento), 0) as ticket_promedio
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and cuenta_contable_descripcion in {{ unidad }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and centro_de_costo in {{ cc }} ]]
```

{% row %}
  {% big_value data="kpis" value="ventas_soles" fmt="num0" title="Ventas (S/)" /%}
  {% big_value data="kpis" value="ventas_usd" fmt="num0" title="Ventas facturadas en USD (S/)" /%}
  {% big_value data="kpis" value="ventas_pen" fmt="num0" title="Ventas facturadas en PEN (S/)" /%}
  {% big_value data="kpis" value="comprobantes" fmt="num0" title="Comprobantes emitidos" /%}
  {% big_value data="kpis" value="clientes" fmt="num0" title="Clientes" /%}
  {% big_value data="kpis" value="ticket_promedio" fmt="num0" title="Ticket promedio (S/)" /%}
{% /row %}

## Ventas por mes

```sql ventas_mes
select
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  moneda,
  sum(subtotal_base_soles) as ventas
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and cuenta_contable_descripcion in {{ unidad }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2
```

{% line_chart
  data="ventas_mes"
  x="mes"
  y="sum(ventas) as Ventas"
  series="moneda"
  date_grain="month"
  y_fmt="num0"
  title="Ventas por mes (S/)"
  subtitle="Serie por moneda de facturación"
/%}

## Composición de las ventas

```sql ventas_aeropuerto
select
  coalesce(aeropuerto_origen, '(sin aeropuerto)') as aeropuerto,
  sum(subtotal_base_soles) as ventas
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and cuenta_contable_descripcion in {{ unidad }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1
order by 2 desc
```

{% treemap
  data="ventas_aeropuerto"
  category="aeropuerto"
  value="ventas"
  value_fmt="num0"
  title="Ventas por aeropuerto (S/)"
/%}

## Detalle mensual

```sql ventas_tabla
select
  extract(year from fecha_emision)::int as anio,
  moneda,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(subtotal_base_soles) as ventas
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Ventas'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and cuenta_contable_descripcion in {{ unidad }} ]]
[[ and aeropuerto_origen in {{ aeropuerto }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2, 3
```

{% table
  data="ventas_tabla"
  title="Ventas por mes y moneda (S/)"
  page_size=100
  freeze_columns=2
  repeat_values=true
%}
  {% dimension value="anio" title="Año" /%}
  {% dimension value="moneda" title="Moneda" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(ventas)" title="Ventas" fmt="num0" /%}
{% /table %}
