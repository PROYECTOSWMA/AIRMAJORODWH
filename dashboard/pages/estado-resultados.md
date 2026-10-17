---
title: Estado de Resultados
sidebar_position: 1
page_width: full
---

# Estado de Resultados

```sql dim_anios
select distinct anio
from dwh.newview
order by anio desc
```

```sql dim_centros_costo
with pares as (
  select distinct cost_center as cc, cost_center_codigo as codigo
  from dwh.newview
),
exacto as (
  select s.abreviatura as cc, min(s.descripcion) as descripcion
  from dwh.static_cost_centers s
  where exists (select 1 from pares p where p.cc = s.abreviatura)
  group by 1
),
por_codigo as (
  select
    s.codigo as code,
    case when count(distinct s.descripcion) = 1 then min(s.descripcion) end as descripcion
  from dwh.static_cost_centers s
  group by 1
),
nombres as (
  select
    p.cc,
    coalesce(e.descripcion, c.descripcion) as descripcion
  from pares p
  left join exacto e on e.cc = p.cc
  left join por_codigo c on c.code = p.codigo
)
select
  cc,
  case when descripcion is null then cc else descripcion || ' · ' || cc end as centro_costo
from nombres
order by 2
```

{% row %}
  {% dropdown id="anio" data="dim_anios" value_column="anio" label_column="anio" title="Año" order="anio desc" select_first=true placeholder="Año" /%}
  {% dropdown id="cc" data="dim_centros_costo" value_column="cc" label_column="centro_costo" title="Centro de costo" multiple=true search=true placeholder="Todos los centros de costo" /%}
{% /row %}

## Resultado por mes

```sql er
with filtrado as (
  select
    n.grupo_orden,
    n.grupo,
    n.orden_fila,
    n.descripcion,
    make_date(n.anio, n.mes_num, 1) as mes,
    n.importe
  from dwh.newview n
  where 1 = 1
  [[ and n.anio = {{ anio }} ]]
  [[ and n.cost_center in {{ cc }} ]]
),
cuentas as (
  select
    grupo_orden,
    orden_fila,
    grupo,
    descripcion as cuenta,
    mes,
    sum(importe) as importe
  from filtrado
  group by 1, 2, 3, 4, 5
),
medidas as (
  select
    m.orden as grupo_orden,
    m.grupo,
    m.grupo as cuenta,
    f.mes,
    sum(
      case
        when m.orden = 3 and f.grupo_orden in (1, 2) then f.importe
        when m.orden = 9 and f.grupo_orden in (1, 2, 4, 5, 6, 7, 8) then f.importe
        when m.orden = 12 then f.importe
        else 0
      end
    ) as importe
  from filtrado f
  cross join (
    select orden, grupo
    from dwh.static_master_account_groups
    where tipo = 'MEDIDA'
    union all
    select 12 as orden, 'RESULTADO NETO' as grupo
  ) m
  group by 1, 2, 3, 4
),
lineas as (
  select grupo_orden, orden_fila, grupo, cuenta, mes, importe, 'CUENTA' as nivel
  from cuentas
  union all
  select grupo_orden, 99999 as orden_fila, grupo, cuenta, mes, importe, 'MEDIDA' as nivel
  from medidas
)
select
  grupo_orden * 100000 + orden_fila as orden,
  grupo,
  cuenta,
  nivel,
  mes,
  importe
from lineas
```

{% table
  data="er"
  title="Estado de resultados (S/)"
  page_size=200
  freeze_columns=2
  repeat_values=true
  show_subtotal_rows=false
  show_total_row=false
  row_conditional_colors="case when nivel = 'MEDIDA' then 'hsl(0 0% 96%)' end"
%}
  {% dimension value="orden" hide=true sort="asc" /%}
  {% dimension value="nivel" hide=true /%}
  {% dimension value="grupo" title="Grupo" /%}
  {% dimension value="cuenta" title="Cuenta" /%}
  {% pivot value="mes" date_grain="month" fmt="mmm-yy" /%}
  {% measure value="sum(importe)" title="Importe" fmt="num0" /%}
{% /table %}
