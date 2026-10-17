{{ config(materialized='ephemeral') }}

WITH base AS (
    SELECT
        s.*,
        upper(trim(s.sheet_name))                                          AS sheet_upper,
        upper(trim(coalesce(s.agente, '')))                                AS agente_upper,
        -- Documento: `NRO MANIF` en las hojas SELVA, `NRO` en las hojas S.A.
        coalesce(nullif(trim(s.nro_manif), ''), nullif(trim(s.nro), ''))   AS doc_raw
    FROM sales_selva s
),
parsed AS (
    SELECT
        b.*,
        -- Fecha de la PROPIA celda, a ISO: las hojas 2026 traen datetime
        -- ('2026-09-01 00:00:00') y las hojas 2025 fecha texto ('02.01.25'
        -- = DD.MM.YY -> 2025-01-02). `replace(',', '.')` cubre las erratas con
        -- coma ('26,05.25'). Si aun así no casa (erratas tipo '23.04.5' o la celda
        -- con el nº de documento volcado encima) queda NULL y lo resuelve `docs`.
        CASE
            WHEN b.fecha LIKE '____-__-__%' THEN substr(b.fecha, 1, 10)
            WHEN replace(b.fecha, ',', '.') LIKE '__.__.__'
            THEN '20' || substr(replace(b.fecha, ',', '.'), 7, 2) || '-'
                 || substr(replace(b.fecha, ',', '.'), 4, 2) || '-'
                 || substr(replace(b.fecha, ',', '.'), 1, 2)
        END                                             AS fecha_celda
    FROM base b
),
periodo_hoja AS (
    -- Fecha de referencia de la hoja: su año-mes MÁS FRECUENTE (el libro trae una
    -- hoja por mes y empresa, así que la hoja *es* el periodo). Rescata las filas
    -- con la celda FECHA ilegible: sin esto quedarían sin `doc_date` y se caerían
    -- del EERR. Se usa el MODO y no el mínimo/máximo porque hay erratas de año
    -- suelto (p.ej. un '2029' entre fechas de 2025) que el máximo arrastraría.
    SELECT sheet_name, ym
    FROM (
        SELECT sheet_name,
               substr(fecha_celda, 1, 7)                                AS ym,
               row_number() OVER (
                   PARTITION BY sheet_name
                   ORDER BY count(*) DESC, substr(fecha_celda, 1, 7)
               )                                                        AS rn
        FROM parsed
        WHERE fecha_celda IS NOT NULL
        GROUP BY sheet_name, substr(fecha_celda, 1, 7)
    )
    WHERE rn = 1
),
docs AS (
    SELECT
        p.*,
        -- `doc_date`/`serv_date`: la fecha de la celda si es PLAUSIBLE; si no, el
        -- día 1 del mes de la hoja (`periodo_hoja`). Cubre dos casos:
        --   * celda ilegible (NULL tras `parsed`);
        --   * celda legible pero con el AÑO disparatado (errata: en la hoja
        --     'SELVA ABR-25' hay un '2029-04-28' por '2025-04-28', que metía un
        --     periodo 2029 fantasma en el EERR). Se acepta el año de la hoja ± 1.
        -- Así NINGUNA fila de venta queda sin fecha ni con fecha absurda.
        CASE
            WHEN p.fecha_celda IS NOT NULL
                 AND CAST(substr(p.fecha_celda, 1, 4) AS INTEGER)
                     BETWEEN CAST(substr(ph.ym, 1, 4) AS INTEGER) - 1
                         AND CAST(substr(ph.ym, 1, 4) AS INTEGER) + 1
            THEN p.fecha_celda
            ELSE ph.ym || '-01'
        END                                             AS fecha_iso,
        CASE
            WHEN instr(p.doc_raw, '-') > 0
            THEN substr(p.doc_raw, 1, instr(p.doc_raw, '-') - 1)
        END                                             AS doc_serie,
        CASE
            WHEN instr(p.doc_raw, '-') > 0
            THEN TRY_CAST(substr(p.doc_raw, instr(p.doc_raw, '-') + 1) AS BIGINT)
        END                                             AS doc_number
    FROM parsed p
    LEFT JOIN periodo_hoja ph ON ph.sheet_name = p.sheet_name
),
ventas AS (
    -- Solo documentos válidos, sin cobranzas/pagos y sin repetir el documento.
    SELECT
        d.*,
        row_number() OVER (
            PARTITION BY d.doc_serie, d.doc_number
            ORDER BY d.sheet_name, d.row_number
        ) AS rn
    FROM docs d
    WHERE d.doc_number IS NOT NULL
      AND d.agente_upper NOT IN ('COBRANZA', 'PP VENTAS', 'PP CARGA')
)

SELECT
    NULL                                        AS id,
    v.fecha_iso                                 AS doc_date,
    NULL                                        AS doc_type,
    v.doc_serie                                 AS doc_serie,
    v.doc_number                                AS doc_number,
    NULL                                        AS doc_due_date,
    'INTERNO'                                   AS partner_doc_type,
    NULL                                        AS partner_doc,
    NULL                                        AS qnt_type,
    TRY_CAST(v.tot_pax AS DECIMAL(18,3))        AS qnt,
    -- El reporte no declara moneda; es la operación de Pucallpa (Air Majoro Selva) en soles.
    'PEN'                                       AS currency,
    TRY_CAST(v.total AS DECIMAL(18,6)) / 1.18   AS amnt_taxable,
    TRY_CAST(v.total AS DECIMAL(18,6)) / 1.18 * 0.18
                                                AS amnt_taxes,
    v.fecha_iso                                 AS serv_date,
    nullif(trim(
        coalesce(v.tipo_de_vuelo, v.vuelo, '')
        || CASE
            WHEN v.de IS NOT NULL AND v.a IS NOT NULL THEN ' ' || v.de || '-' || v.a
            ELSE ''
        END
    ), '')                                      AS serv_desc,
    {{ extract_cost_center('v.avion') }}        AS cost_center,
    NULL                                        AS serv_org_airport,
    NULL                                        AS serv_dest_airport,
    704106                                      AS account,
    CASE
        WHEN v.sheet_upper LIKE 'SELVA%' THEN 'Air Majoro Selva'
        ELSE 'Air Majoro'
    END                                         AS company,
    NULL                                        AS error,
    {{ now_utc() }}                             AS ingested_at,
    '{{ var('move_type', 'Ventas') }}'          AS move_type,
    NULL                                        AS source_sire_sales,
    NULL                                        AS source_sire_sales_details,
    NULL                                        AS source_sisa
FROM ventas v
WHERE v.rn = 1
