{{ config(materialized='table') }}

-- GALONES POR HORA DE VUELO, por mes y por aeronave (indicador pedido por el
-- negocio). Nace del cruce de DOS tablas que viven separadas y sin relación:
--
--   * GALONES  -> `moves`, cuenta de combustibles `603201` (PETROPERÚ, CEP,
--                 ÍCARO y TERPEL). La cantidad son galones (`qnt`) y el CENTRO
--                 DE COSTO es la matrícula de la aeronave (`2209`, `2180`: los
--                 mismos valores que `static_airplanes.registration`). Manda la
--                 fecha de la factura (`doc_date`).
--   * HORAS    -> `flight_reports` (reporte de SISA), `horas_vuelo`. Manda la
--                 fecha del vuelo (`fecha_vuelo`).
--
-- Las dos matrículas se llevan a su forma "pelada" (`normalize_registration`:
-- 'OB-1919-P' -> '1919', '2209' -> '2209') y se cruzan por (mes x aeronave).
--
-- Reglas del cruce:
--   * Cada fuente cuenta en el mes que le es propio (factura vs vuelo).
--   * FULL OUTER JOIN: no se pierde ni la aeronave que solo tiene horas en el mes
--     (galones 0) ni la que solo tiene facturas (horas 0 -> `galones_por_hora`
--     NULL, no se divide entre cero).
--   * Solo aeronaves del maestro `static_airplanes`: así se cae SOLO el
--     combustible cuyo centro de costo no es una aeronave (2000, 2190, 2056,
--     2222, los vacíos y los anticipos de TERPEL, ~4.390 galones), que es el
--     mismo criterio que usa el tipo de combustible en `moves`.
--
-- Contrato (5 columnas, en este orden): mes, aeronave, horas, galones,
-- galones_por_hora. Lo consume la página de Combustible del dashboard
-- (`dashboardaim/pages/combustible.md`), debajo de "Costo por proveedor".
WITH combustible AS (
    SELECT
        CAST(date_trunc('month', doc_date) AS DATE) AS mes,
        {{ normalize_registration('cost_center') }} AS aeronave,
        SUM(qnt)                                    AS galones
    FROM {{ ref('moves') }}
    WHERE account = '603201'          -- cuenta de combustibles
      AND doc_date IS NOT NULL
      AND qnt IS NOT NULL
    GROUP BY 1, 2
),

horas AS (
    SELECT
        CAST(date_trunc('month', fecha_vuelo) AS DATE) AS mes,
        {{ normalize_registration('matricula') }}      AS aeronave,
        SUM(horas_vuelo)                               AS horas
    FROM {{ ref('flight_reports') }}
    WHERE fecha_vuelo IS NOT NULL
    GROUP BY 1, 2
),

cruce AS (
    SELECT
        COALESCE(c.mes, h.mes)           AS mes,
        COALESCE(c.aeronave, h.aeronave) AS aeronave,
        COALESCE(h.horas, 0)             AS horas,
        COALESCE(c.galones, 0)           AS galones
    FROM combustible c
    FULL OUTER JOIN horas h
        ON h.mes = c.mes
        AND h.aeronave = c.aeronave
)

SELECT
    cruce.mes,
    cruce.aeronave,
    cruce.horas,
    cruce.galones,
    round(cruce.galones / nullif(cruce.horas, 0), 2) AS galones_por_hora
FROM cruce
INNER JOIN {{ ref('static_airplanes') }} a
    ON a.registration = cruce.aeronave
