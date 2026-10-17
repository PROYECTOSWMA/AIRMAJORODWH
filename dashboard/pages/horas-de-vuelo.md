---
title: Horas de Vuelo
sidebar_position: 7
page_width: full
---

# Horas de Vuelo

```sql dim_anios
select distinct extract(year from fecha_vuelo)::int as anio
from dwh.flight_reports
order by anio desc
```

```sql dim_meses
select
  m as mes,
  case m
    when 1 then 'Enero'
    when 2 then 'Febrero'
    when 3 then 'Marzo'
    when 4 then 'Abril'
    when 5 then 'Mayo'
    when 6 then 'Junio'
    when 7 then 'Julio'
    when 8 then 'Agosto'
    when 9 then 'Setiembre'
    when 10 then 'Octubre'
    when 11 then 'Noviembre'
    when 12 then 'Diciembre'
  end as mes_nombre
from generate_series(1, 12) as m
where m in (
  select distinct extract(month from fecha_vuelo)::int
  from dwh.flight_reports
)
order by mes
```

```sql dim_unidades
select distinct sede_operacion as unidad_negocio
from dwh.flight_reports
where coalesce(sede_operacion, '') <> ''
order by unidad_negocio
```

```sql dim_empresas
select distinct empresa
from dwh.flight_reports
where coalesce(empresa, '') <> ''
order by empresa
```

```sql dim_matriculas
select distinct matricula
from dwh.flight_reports
where coalesce(matricula, '') <> ''
order by matricula
```

{% row %}
  {% dropdown id="anio" data="dim_anios" value_column="anio" label_column="anio" title="Año" order="anio desc" select_first=true placeholder="Año" /%}
  {% dropdown id="empresa" data="dim_empresas" value_column="empresa" label_column="empresa" title="Empresa" multiple=true placeholder="Todas las empresas" /%}
  {% dropdown id="mes" data="dim_meses" value_column="mes" label_column="mes_nombre" title="Mes" order="mes" multiple=true placeholder="Todos los meses" /%}
  {% date_grain_selector id="grano" preset_values=["day","month"] default_value="day" title="Ver por" /%}
  {% dropdown id="sede" data="dim_unidades" value_column="unidad_negocio" label_column="unidad_negocio" title="Unidad de Negocio" multiple=true placeholder="Todas las unidades de negocio" /%}
  {% dropdown id="matricula" data="dim_matriculas" value_column="matricula" label_column="matricula" title="Aeronave" multiple=true search=true placeholder="Todas las aeronaves" /%}
{% /row %}

## Resumen

```sql kpis
select
  sum(horas_vuelo) as horas,
  count(*) as vuelos,
  count(distinct fecha_vuelo) as dias_con_vuelo,
  count(distinct matricula) as aeronaves,
  count(distinct sede_operacion) as unidades,
  sum(total_pasajeros) as pasajeros
from dwh.flight_reports
where 1 = 1
[[ and extract(year from fecha_vuelo)::int = {{ anio }} ]]
[[ and extract(month from fecha_vuelo)::int in {{ mes }} ]]
[[ and sede_operacion in {{ sede }} ]]
[[ and matricula in {{ matricula }} ]]
[[ and empresa in {{ empresa }} ]]
```

{% row %}
  {% big_value data="kpis" value="horas" fmt="num1" title="Horas de vuelo" /%}
  {% big_value data="kpis" value="vuelos" fmt="num0" title="Registros de vuelo" /%}
  {% big_value data="kpis" value="dias_con_vuelo" fmt="num0" title="Días con vuelo" /%}
  {% big_value data="kpis" value="aeronaves" fmt="num0" title="Aeronaves" /%}
  {% big_value data="kpis" value="unidades" fmt="num0" title="Unidades de negocio" /%}
  {% big_value data="kpis" value="pasajeros" fmt="num0" title="Pasajeros" /%}
{% /row %}

## Horas de vuelo por período y unidad de negocio

```sql horas_periodo_unidad
select
  date_trunc({{ grano.selected }}, fecha_vuelo)::date as periodo,
  sede_operacion as unidad_negocio,
  sum(horas_vuelo) as horas
from dwh.flight_reports
where 1 = 1
[[ and extract(year from fecha_vuelo)::int = {{ anio }} ]]
[[ and extract(month from fecha_vuelo)::int in {{ mes }} ]]
[[ and sede_operacion in {{ sede }} ]]
[[ and matricula in {{ matricula }} ]]
[[ and empresa in {{ empresa }} ]]
group by 1, 2
order by 1
```

{% bar_chart
  data="horas_periodo_unidad"
  x="periodo"
  y="sum(horas) as Horas"
  series="unidad_negocio"
  stacked=true
  date_grain={{grano}}
  y_fmt="num1"
/%}

## Total de horas de vuelo por período y unidad de negocio

```sql horas_unidad
select
  sede_operacion as unidad_negocio,
  date_trunc({{ grano.selected }}, fecha_vuelo)::date as periodo,
  sum(horas_vuelo) as horas
from dwh.flight_reports
where 1 = 1
[[ and extract(year from fecha_vuelo)::int = {{ anio }} ]]
[[ and extract(month from fecha_vuelo)::int in {{ mes }} ]]
[[ and sede_operacion in {{ sede }} ]]
[[ and matricula in {{ matricula }} ]]
[[ and empresa in {{ empresa }} ]]
group by 1, 2
```

{% table
  data="horas_unidad"
  page_size=100
  freeze_columns=1
  repeat_values=true
%}
  {% dimension value="unidad_negocio" title="Unidad de negocio" /%}
  {% pivot value="periodo" date_grain={{grano}} /%}
  {% measure value="sum(horas)" title="Horas" fmt="num1" /%}
{% /table %}

## Número de pasajeros por período (NASCA y SELVA)

```sql pasajeros_periodo
select
  date_trunc({{ grano.selected }}, fecha_vuelo)::date as periodo,
  sum(total_pasajeros) as pasajeros
from dwh.flight_reports
where 1 = 1
[[ and extract(year from fecha_vuelo)::int = {{ anio }} ]]
[[ and extract(month from fecha_vuelo)::int in {{ mes }} ]]
[[ and matricula in {{ matricula }} ]]
[[ and empresa in {{ empresa }} ]]
  and sede_operacion in ('NASCA', 'SELVA')
group by 1
order by 1
```

{% line_chart
  data="pasajeros_periodo"
  x="periodo"
  y="sum(pasajeros) as Pasajeros"
  date_grain={{grano}}
  y_fmt="num0"
/%}
