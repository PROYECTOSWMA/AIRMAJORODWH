{{ config(materialized='table') }}

WITH payroll_unpivot AS (
    UNPIVOT static_payroll
    ON sueldo, asignacion_familiar, horas_extras_25, 
       horas_extras_35, sctr_pension, eps
       , vacaciones, movilidad_empresa, alimentacion, 
       adelanto_de_sueldo_y_otros, essalud, sctr_salud,
       bonificacion_al_cargo, bono_de_retencion, bonificacion_por_cierre_de_pliego,

    INTO 
        NAME concepto_remunerativo
        VALUE monto
)
-- Fecha de la planilla: es MENSUAL. `p.fecha` viene en formatos variados
-- ('12/31/2025', '4/30/2026', '30-Aug', '31-Jul'...) que `normalize_date`
-- anulaba (por eso la planilla se quedaba sin `doc_date`). El mes/año fiable
-- está en `p.periodo` (año) y `p.mes` (mes, a veces sin cero); se arma el
-- PRIMER día de ese mes. Verificado: `periodo`/`mes` no traen nulos, así que
-- NINGUNA fila de planilla queda sin fecha.
{% set planilla_fecha %}
    CASE
        WHEN {{ safe_int('p.periodo') }} BETWEEN 1900 AND 2030
             AND {{ safe_int('p.mes') }} BETWEEN 1 AND 12
        THEN TRY_CAST(
            lpad(CAST({{ safe_int('p.periodo') }} AS VARCHAR), 4, '0') || '-' ||
            lpad(CAST({{ safe_int('p.mes') }} AS VARCHAR), 2, '0') || '-01'
            AS DATE
        )
    END
{% endset %}
SELECT
    {% set ccosto_clean = clean_int_to_string('p.ccosto') %}
    NULL                                        AS id,
    {{ planilla_fecha }}                        AS doc_date,
    'PLANILLA'                                  AS doc_type,
    NULL                                        AS doc_serie,
    NULL                                        AS doc_number,
    NULL                                        AS doc_due_date,
    'DNI'                                       AS partner_doc_type,
    p.dni                                       AS partner_doc,
    'DIAS'                                      AS qnt_type,
    p.dias                                      AS qnt,
    {{ normalize_currency('p.monpago') }}       AS currency,
    p.monto                                     AS amnt_taxable,
    0                                           AS amnt_taxes,
    {{ planilla_fecha }}                        AS serv_date,
    trim(p.nombre || ' - ' || coalesce(p.cargo, '') || ' - ' || p.concepto_remunerativo) 
                                                AS serv_desc,
    CASE {{ ccosto_clean }}
        WHEN '101' THEN '1919'
        WHEN '102' THEN '2180'
        WHEN '104' THEN '1921'
        WHEN '106' THEN '2200'
        WHEN '103' THEN '1929'
        WHEN '107' THEN '2209'
        WHEN '112' THEN '2092'
        WHEN '111' THEN '2221'
        WHEN '105' THEN '2104'
        WHEN '109' THEN '2239'
        ELSE {{ ccosto_clean }}
    END                                         AS cost_center,
    NULL                                        AS serv_org_airport,
    NULL                                        AS serv_dest_airport,

    if(
        left({{ ccosto_clean }}, 1) = '1' and concepto_remunerativo in 
        ('sueldo', 'asignacion_familiar', 'horas_extras_25', 
        'horas_extras_35', 'sctr_salud', 'sctr_pension', 'eps', 'essalud', 'vida_ley'), 

    621101 -- PLANILLA
    ,
    case concepto_remunerativo
        when 'sueldo' then 621102 --	SUELDOS
        when 'vacaciones' then 621501 --	VACACIONES
        when 'horas_extras_25' then 621901 --	HORAS EXTRAS
        when 'horas_extras_35' then 621901 --	HORAS EXTRAS
        when 'asignacion_familiar' then 621902 --	ASIGNACION FAMILIAR
        when 'movilidad_empresa' then 625901 --	MOVILIDAD
        when 'alimentacion' then 625902 --	REFRIGERIOS
        when 'adelanto_de_sueldo_y_otros' then 629901 --	OTROS
        when 'sctr_pension' then 629901 --	OTROS (NO HAY OTRA CUENTA)
        when 'sctr_salud' then 629901 --	OTROS
        when 'vida_ley' then 629901 --	OTROS
        when 'eps' then 629901 --	OTROS
        when 'essalud' then 627101 --	REGIMEN DE PRESTACIONES DE SALUD
        when 'sctr_salud' then 627101 --	REGIMEN DE PRESTACIONES DE SALUD
        when 'bonificacion_al_cargo' then 621903 -- BONIFICACIONES
        when 'bono_de_retencion' then 621903 --	BONIFICACIONES
        when 'bonificacion_por_cierre_de_pliego' then 621903 --	BONIFICACIONES
        else null end
    )                                            AS account,
    if(regimen = 'RG' , 'Air Majoro', 'Air Majoro Selva')
                                                AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    'Compras'                                   AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa
FROM payroll_unpivot p