# Project Brief — REPOAIMNUEVO

## Resumen ejecutivo
Repositorio que construye el **DWH contable de AIR MAJORO** (empresas de
aviación). Ingiere datos de varias fuentes (correo Gmail, APIs de SUNAT/SIRE,
SISA, CORPAC, tipo de cambio y archivos estáticos), los normaliza en una **SQLite**
(`db.sqlite`, capa de integración), los transforma con **dbt sobre DuckDB** a un
esquema contable común de **26 columnas** y los publica a un **PostgreSQL**
remoto (asset `publish_dwh`, schema `dwh`).

## Meta del proyecto
Consolidar **ventas, compras, planilla y RR.HH.** de Air Majoro (Lima, Nazca y
Pucallpa) en tablas normalizadas con **cuenta contable** y **centro de costo**
asignados, listas para el reporte gerencial.

## Empresas del grupo
- **AIR MAJORO S.A. (AM)** — RUC 20494626978. Sede **Lima** (empresa `01`, sede
  `01`) y **Nazca** (empresa `01`, sede `02`).
- **AIR MAJORO SELVA (MSA)** — **Pucallpa** (empresa `02`, sede `06`).

## Cadena de datos (alto nivel)
1. **Origen**: correo Gmail, APIs (SUNAT/SIRE, SEE-SOL, SISA, CORPAC, tipo de
   cambio) y archivos estáticos en `static/` (todos al primer nivel).
2. **Integración (Dagster → SQLite `db.sqlite`)**: **17 assets de ingesta** llenan tablas por
   dominio (`emails`, `email_attachments`, `sire_*`, `from_email_*`,
   `from_sire_*`, `sisa_sales`, `ambulancia_ventas_reports`, `lap_reports`,
   `planilla`, `seesol_rh` y las **6 tablas de los CSV de referencia**).
3. **Analítica (dbt sobre DuckDB)**: lee `db.sqlite` con la extensión `sqlite` y
   materializa en **`analytics_poc.duckdb`**: **24 modelos** (6 tablas + 18
   efímeros), entre ellas `moves` (26 columnas, con `account` y `cost_center`) y
   `partners` (código -> descripción de proveedores y clientes).
4. **Publicación**: el asset `publish_dwh` (el motor vive en `DwhPublishResource`)
   publica **todas las tablas del DuckDB** en
   el schema `dwh` de Postgres **con el mismo nombre** (`moves` -> `dwh.moves`):
   crea lo que falte, `DELETE` + `COPY` (sin `DROP`, hay vistas encima).
   Desde el 2026-09-17, `dbt run` (`dbt_run`) y la publicación (`publish_dwh`) son
   **assets** del grupo `dwh` (19 assets en total), así que el orden assets → dbt →
   publicación lo impone el grafo; `src/jobs.py` define **7 jobs con nombre** y el
   disparo sigue siendo el cron externo (sin `ScheduleDefinition`).

## Scope / limitaciones
- Todo el código vive en `src/` (assets + `definitions.py` + proyecto dbt); los
  archivos fuente estáticos en `static/` (todos al primer nivel; `static/RH/` es
  la única subcarpeta, ya histórica: el RH entra por HTTP). El token de SUNAT lo
  resuelve el resource de SIRE (`assets/sire_assets/resources/token_resource.py` +
  `sol_portal.py`) y se cachea en `env/sire_tokens.json`; el único plan B de token
  está documentado en `docs/sol_token_navegador.py` (`scripts/` sólo tiene el cron).
- La ingesta se orquesta con **Dagster**; no hay API propia ni UI más allá del
  webserver de Dagster.
- `db.sqlite` (~19 GB) está en la raíz y **no se versiona**; `analytics_poc.duckdb`
  tampoco.
