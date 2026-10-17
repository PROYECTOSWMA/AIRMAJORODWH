---
title: Costos por Moneda
sidebar_position: 3
page_width: full
---

# Costos por Moneda

```sql dim_anios
select distinct extract(year from fecha_emision)::int as anio
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
order by anio desc
```

```sql dim_monedas
select distinct moneda
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
order by moneda
```

```sql dim_empresas
select distinct empresa
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras' and coalesce(empresa, '') <> ''
order by empresa
```

```sql dim_cuentas
select distinct cuenta_contable_descripcion as cuenta
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
order by cuenta
```

```sql dim_centros_costo
with pares as (
  select distinct centro_de_costo as cc
  from dwh.vista_reporte_gerencial
  where tipo_movimiento = 'Compras' and coalesce(centro_de_costo, '') <> ''
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
  {% dropdown id="empresa" data="dim_empresas" value_column="empresa" label_column="empresa" title="Empresa" multiple=true placeholder="Todas las empresas" /%}
  {% dropdown id="moneda" data="dim_monedas" value_column="moneda" label_column="moneda" title="Moneda" multiple=true placeholder="Todas las monedas" /%}
  {% dropdown id="cuenta" data="dim_cuentas" value_column="cuenta" label_column="cuenta" title="Cuenta contable" multiple=true search=true placeholder="Todas las cuentas" /%}
  {% dropdown id="cc" data="dim_centros_costo" value_column="cc" label_column="centro_costo" title="Centro de costo" multiple=true search=true placeholder="Todos los centros de costo" /%}
{% /row %}

## Resumen

```sql kpis
select
  sum(-subtotal_base_soles) as costo_total_soles
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and cuenta_contable_descripcion in {{ cuenta }} ]]
[[ and centro_de_costo in {{ cc }} ]]
```

{% row %}
  {% big_value data="kpis" value="costo_total_soles" fmt="num0" title="Costo total (S/, tipo de cambio aplicado)" /%}
{% /row %}

## Costos por moneda y mes

```sql costos_mes
select
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  moneda,
  sum(-subtotal_base_soles) as costo
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and cuenta_contable_descripcion in {{ cuenta }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2
```

{% line_chart
  data="costos_mes"
  x="mes"
  y="sum(costo) as `Costo (S/)`"
  series="moneda"
  date_grain="month"
  y_fmt="num0"
/%}

## Detalle mensual por moneda

```sql costos_tabla
select
  cuenta_contable_descripcion as cuenta,
  moneda,
  extract(year from fecha_emision)::int as anio,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(-subtotal_base_soles) as costo
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and cuenta_contable_descripcion in {{ cuenta }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2, 3, 4
```

{% table
  data="costos_tabla"
  page_size=200
  freeze_columns=3
  repeat_values=true
  subtotals=false
%}
  {% dimension value="cuenta" title="Cuenta" /%}
  {% dimension value="moneda" title="Moneda" /%}
  {% dimension value="anio" title="Año" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(costo)" title="Costo" fmt="num0" /%}
{% /table %}

## Total en soles

```sql total_soles
select
  cuenta_contable_descripcion as cuenta,
  make_date(
    extract(year from fecha_emision)::int,
    extract(month from fecha_emision)::int,
    1
  ) as mes,
  sum(-subtotal_base_soles) as costo
from dwh.vista_reporte_gerencial
where tipo_movimiento = 'Compras'
[[ and extract(year from fecha_emision)::int = {{ anio }} ]]
[[ and empresa in {{ empresa }} ]]
[[ and moneda in {{ moneda }} ]]
[[ and cuenta_contable_descripcion in {{ cuenta }} ]]
[[ and centro_de_costo in {{ cc }} ]]
group by 1, 2
```

{% table
  data="total_soles"
  page_size=200
  freeze_columns=1
  repeat_values=true
%}
  {% dimension value="cuenta" title="Cuenta" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(costo)" title="Costo" fmt="num0" /%}
{% /table %}
