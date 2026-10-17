# Product Context — ¿Por qué existe este proyecto?

## Problema que resuelve
La contabilidad/gestión de la operación aérea de Air Majoro recibe datos muy
heterogéneos: correos con PDF/ZIP de facturación, Excel/ODS de los sistemas de
facturación, planillas y recibos por honorarios, información de SUNAT (SIRE/CPE)
y liquidaciones del sistema SISA. Conciliarlo a mano es lento y propenso a errores.

## Cómo debe funcionar
- **Automatizar la ingesta** de correos y adjuntos (PDF/ZIP/Excel), de las APIs de
  SUNAT/SIRE, SISA y CORPAC, y de los archivos estáticos, sin intervención manual.
- **Normalizar a una sola fuente**: todas las ramas convergen a un esquema común de
  **26 columnas** para poder comparar ventas, compras, planilla y RR.HH.
- **Asignar cuenta y centro de costo** de forma automática (reglas de
  `static_aux_accounts_assignment`, overrides de `static_aux_cost_centers_override`
  y cálculo por descripción/tramos).
- **Publicar a un DWH PostgreSQL** (schema `dwh`) de donde sale el reporte
  gerencial (vista `dwh.vista_reporte_gerencial`).

## Usuarios / objetivo de UX
- Contabilidad y gerencias de Air Majoro consumen el DWH final.
- El equipo de datos opera Dagster (materializa assets por partición: diaria,
  mensual o la estática `"2026"`) y luego corre dbt desde la CLI.

## Criterios de éxito
- Cada corrida deja las tablas de origen, la capa analítica y el PostgreSQL
  consistentes: **upsert sin duplicados** y limpieza de huérfanos.
- **Orden obligatorio de corrida**: primero los assets (llenan `db.sqlite`),
  después `dbt run` (materializa `analytics_poc.duckdb`).
- Un proveedor/fuente nuevo se integra siguiendo el patrón estándar de asset
  (models peewee + pydantic, parser, db_resource, api_resource) sin reinventar.
