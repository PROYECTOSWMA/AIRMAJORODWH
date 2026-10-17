---
title: Técnico - Invoices
sidebar_position: 9
page_width: full
---

# Técnico - Invoices

Qué se **ingirió** de `static/INVOICE INTERNACIONALES` y qué se **cruzó**, documento por
documento y línea por línea: el **fichero** del que sale cada dato, cuántas **líneas** trae,
si encontró su **orden de compra** (y con qué aeronave/tipo) y si el importe de las líneas
**cuadra** con el subtotal del documento. Es la página para responder dudas sobre los datos
sin abrir un PDF.

> **Cómo leerla**: `subtotal_documento` es lo que deben sumar las líneas (el PDF imprime las
> líneas por el subtotal, sin flete ni impuesto); `total_documento` es el total de la factura.
> Si `diferencia` no es 0, o el PDF tiene una línea que no se pudo leer, o el documento no
> imprime subtotal. Las facturas con **¿Orden? = No** no pueden completarse con aeronave ni
> tipo de mantenimiento.

```sql dim_proveedores
select distinct replace(proveedor, 'INVC-', '') as proveedor
from dwh.invoices_audit
order by 1
```

```sql dim_tipos
select distinct tipo_documento
from dwh.invoices_audit
order by 1
```

```sql dim_estado
select estado
from (values ('Con orden'), ('Sin orden'), ('Descuadra')) as t(estado)
```

{% row %}
  {% dropdown id="proveedor" data="dim_proveedores" value_column="proveedor" label_column="proveedor" title="Proveedor" multiple=true search=true placeholder="Todos los proveedores" /%}
  {% dropdown id="tipo" data="dim_tipos" value_column="tipo_documento" label_column="tipo_documento" title="Tipo" multiple=true placeholder="Facturas y órdenes" /%}
  {% dropdown id="estado" data="dim_estado" value_column="estado" label_column="estado" title="Estado" multiple=true placeholder="Todos" /%}
{% /row %}

```sql kpis
select
  count(distinct archivo)                             as documentos,
  count(*)                                            as lineas,
  count(distinct archivo) filter (where tipo_documento = 'FACTURA' and not po_encontrada)
                                                      as facturas_sin_orden,
  count(distinct archivo) filter (
    where abs(coalesce(subtotal_documento, 0) - importe) > 0.01
      and coalesce(subtotal_documento, 0) <> 0
  )                                                   as con_descadre
from dwh.invoices_audit
where 1 = 1
[[ and ('INVC-' || proveedor) in {{ proveedor }} ]]
[[ and tipo_documento in {{ tipo }} ]]
[[ and case
        when po_encontrada and abs(coalesce(subtotal_documento, 0) - importe) < 0.01
          then 'Con orden'
        when not po_encontrada then 'Sin orden'
        else 'Descuadra'
      end in {{ estado }} ]]
```

{% row %}
  {% big_value data="kpis" value="documentos" fmt="num0" title="Documentos (ficheros)" /%}
  {% big_value data="kpis" value="lineas" fmt="num0" title="Líneas ingeridas" /%}
  {% big_value data="kpis" value="facturas_sin_orden" fmt="num0" title="Facturas sin orden" /%}
  {% big_value data="kpis" value="con_descadre" fmt="num0" title="Documentos que descuadran" /%}
{% /row %}


## Documentos

Una fila por **fichero** (documento) leído.

```sql documentos
select
  replace(proveedor, 'INVC-', '')                              as proveedor,
  tipo_documento,
  archivo,
  documento,
  min(fecha)                                                   as fecha,
  count(*)                                                     as lineas,
  round(sum(importe), 2)                                       as importe_lineas,
  round(max(subtotal_documento), 2)                            as subtotal,
  round(max(total_documento), 2)                               as total,
  round(coalesce(max(subtotal_documento), 0) - sum(importe), 2) as diferencia,
  case when bool_or(po_encontrada) then 'Sí' else 'No' end      as encontro_orden,
  min(nullif(po_numero, ''))                                   as po_numero,
  max(cost_center)                                             as aeronave,
  max(tipo_mantenimiento)                                      as tipo_mantenimiento,
  case
    when coalesce(max(subtotal_documento), 0) = 0 then 'sin subtotal'
    when abs(max(subtotal_documento) - sum(importe)) > 0.01 then 'DESCUADRA'
    else 'OK'
  end                                                          as cuadre
from dwh.invoices_audit
where 1 = 1
[[ and ('INVC-' || proveedor) in {{ proveedor }} ]]
[[ and tipo_documento in {{ tipo }} ]]
[[ and case
        when po_encontrada and abs(coalesce(subtotal_documento, 0) - importe) < 0.01
          then 'Con orden'
        when not po_encontrada then 'Sin orden'
        else 'Descuadra'
      end in {{ estado }} ]]
group by 1, 2, 3, 4
order by tipo_documento, proveedor, documento
```

{% table
  data="documentos"
  page_size=25
  freeze_columns=3
%}
  {% dimension value="tipo_documento" title="Tipo" /%}
  {% dimension value="proveedor" title="Proveedor" /%}
  {% dimension value="documento" title="Documento" /%}
  {% dimension value="archivo" title="Fichero" /%}
  {% dimension value="fecha" title="Fecha" /%}
  {% measure value="lineas" title="Líneas" fmt="num0" /%}
  {% measure value="importe_lineas" title="Importe líneas" fmt="num2" /%}
  {% measure value="subtotal" title="Subtotal" fmt="num2" /%}
  {% measure value="total" title="Total" fmt="num2" /%}
  {% measure value="diferencia" title="Diferencia" fmt="num2" /%}
  {% dimension value="cuadre" title="Cuadre" /%}
  {% dimension value="encontro_orden" title="¿Orden?" /%}
  {% dimension value="po_numero" title="Nº de orden" /%}
  {% dimension value="aeronave" title="Aeronave" /%}
  {% dimension value="tipo_mantenimiento" title="Tipo mantenimiento" /%}
{% /table %}

## Todas las líneas

El detalle completo de lo ingerido (una fila por línea del PDF).

```sql lineas
select
  tipo_documento,
  replace(proveedor, 'INVC-', '')                 as proveedor,
  archivo,
  documento,
  fecha,
  item,
  part_number,
  descripcion,
  qnt,
  uom,
  precio_unitario,
  importe,
  currency,
  po_numero,
  case when po_encontrada then 'Sí' else 'No' end as encontro_orden,
  cost_center                                     as aeronave,
  tipo_mantenimiento
from dwh.invoices_audit
where 1 = 1
[[ and ('INVC-' || proveedor) in {{ proveedor }} ]]
[[ and tipo_documento in {{ tipo }} ]]
[[ and case
        when po_encontrada and abs(coalesce(subtotal_documento, 0) - importe) < 0.01
          then 'Con orden'
        when not po_encontrada then 'Sin orden'
        else 'Descuadra'
      end in {{ estado }} ]]
order by tipo_documento, proveedor, documento, item
```

{% table
  data="lineas"
  page_size=50
  freeze_columns=3
%}
  {% dimension value="tipo_documento" title="Tipo" /%}
  {% dimension value="proveedor" title="Proveedor" /%}
  {% dimension value="documento" title="Documento" /%}
  {% dimension value="archivo" title="Fichero" /%}
  {% dimension value="fecha" title="Fecha" /%}
  {% dimension value="item" title="Línea" /%}
  {% dimension value="part_number" title="P/N" /%}
  {% dimension value="descripcion" title="Descripción" /%}
  {% measure value="qnt" title="Cant." fmt="num2" /%}
  {% dimension value="uom" title="UOM" /%}
  {% measure value="precio_unitario" title="P. unit." fmt="num2" /%}
  {% measure value="importe" title="Importe" fmt="num2" /%}
  {% dimension value="currency" title="Mon." /%}
  {% dimension value="encontro_orden" title="¿Orden?" /%}
  {% dimension value="po_numero" title="Nº de orden" /%}
  {% dimension value="aeronave" title="Aeronave" /%}
  {% dimension value="tipo_mantenimiento" title="Tipo mantenimiento" /%}
{% /table %}
