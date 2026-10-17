# Progress — Qué funciona y estado

> Solo estado presente (sin historial).

## Qué funciona hoy (implementado en el código)
- **Capa analítica y publicación como assets (2026-09-17)**: `dbt_run` (grupo `dwh`, sin
  particiones, `deps` de las **14** fuentes que dbt lee —desde el 2026-09-23 **no** incluye
  `sire_files_monthly` (`sire_*_files`), `ingest_emails` (`emails`/`email_attachments`) ni
  `corpac_files_daily` (`from_email_corpac_files`), cuyas tablas no lee ningún modelo, así que el DWH
  ya no depende de la descarga de PDF/ZIP de SIRE, de Gmail ni del portal CORPAC—; corre dbt en
  proceso con `dbtRunner` y el CWD en
  `src/dbt`) y `publish_dwh` (`deps=[dbt_run]`, envuelve `sync_db.py` sin duplicarlo). 7
  jobs con nombre en `src/jobs.py` + `jobs=JOBS` en `definitions.py`. El pipeline completo se
  lanza con **`scripts/run_pipeline.py`** (1 línea en el cron; `--dry-run` imprime el plan de
  5 runs, `--publish` añade la publicación). El cuelgue de `moves` (8,9 GB de *spill* +
  OOM el 2026-09-17) está **RESUELTO el 2026-09-18**: era la recursión de los macros
  `get_by_sep`/`capitalize_words` usada **dentro de la clave de un JOIN** (ver
  `activeContext.md`). Hoy `dbt run` completo = **PASS=6 en 2,44 s y 0 bytes de spill**.
- **Correo Gmail** → `emails` / `email_attachments`. Append-only **y con descarga
  incremental (2026-09-18)**: `ingest_emails` lista primero los ids del día
  (`list_message_ids`, barato), pregunta a la tabla cuáles faltan
  (`existing_email_ids`) y descarga el mensaje completo (`format="raw"`: cuerpo +
  adjuntos) **solo de los nuevos**; el insert (`append_emails` /
  `append_email_attachments`, antes `upsert_*`) solo agrega ids nuevos. Las tablas
  `from_email_*` tienen FK a `emails`/`email_attachments`.
- **Adjuntos de proveedores** (2026-09-17: toda la cadena de correo es **diaria** y
  comparte `correos_daily_partitions_def` de `src/assets/_common/partitions.py`; **ninguna**
  declara condiciones de automatización): CORPAC (`corpac_files_daily` por portal Mercurio →
  `from_email_corpac_files`, append-only; `corpac_data_daily` →
  `from_email_corpac_headers` / `from_email_corpac_details`) y ADP/TALMA/TERPEL
  (`adp_reports_daily`, `talma_reports_daily`, `terpel_tickets_daily`, `terpel_order_daily`;
  renombrados desde `*_monthly`), los 4 con `BackfillPolicy.single_run()` y upsert por **día**
  (`upsert_day`). Reparto de políticas desde el **2026-09-23**: `ingest_emails` y
  `corpac_files_daily` con `BackfillPolicy.multi_run(max_partitions_per_run=30)` y
  `corpac_data_daily` + los 4 reportes + `calendar_weekly` + `sisa_sales_monthly` con
  `single_run()`. Los que van con rango recorren `partition_days(context)` partición a partición
  (`procesar_dia`/`procesar_semana`/`procesar_mes`) y devuelven `MaterializeResult` sin valor, así
  que el rango entero cae en **un solo run** sin tocar el IO manager.
- **Carga inicial del grupo ligero (2026-09-17)**: `--partition-range
  "2026-01-01...2026-09-16"` = **1 run / 4 steps, RUN_SUCCESS** (~6 min) →
  `from_email_talma_reports` 839 filas/8 días · `from_email_adp_reports` 4.487/16 ·
  `from_email_terpel_tickets` 748/210 · `from_email_terpel_order` 1.334/97. La carga de
  `ingest_emails` + `corpac_*` queda **pendiente** (Gmail + descargas CORPAC: la parte pesada).
- **Fix de raíz del cron (2026-09-17)**: los 7 assets con `single_run()` que van en
  rango de 2 meses (6 de SIRE + `seesol_rh_monthly`) devolvían `Output` con valor y
  el IO manager por defecto reventaba **después** de escribir los datos
  (*"does not support persisting an output associated with multiple partitions"*).
  Ahora devuelven `MaterializeResult` sin valor (detalle y tests en
  `activeContext.md`). Validado en vivo: RH `RUN_SUCCESS` con el rango; propuesta
  SIRE bajó RCE+RVIE de 202608 y 202609 de las 2 empresas (202609: 760 compras /
  156 ventas nuevas de Air Majoro; el RVIE de agosto trajo **0 filas nuevas**
  porque ese libro ya estaba cargado). `TICKET_POLL_SECONDS` 10 → 2.
- **Resiliencia ante SUNAT (2026-09-17)**: el cron ya no muere por dos fallos
  transitorios de SUNAT — el **422/cod 1070** ("no hay comprobantes en el
  periodo") al consultar el ticket se reintenta con un ticket **nuevo** (3
  intentos) y si insiste se registra como periodo sin comprobantes (0 filas +
  WARNING); el **503** del proxy al bajar un PDF/ZIP se reintenta y el documento
  queda como `missing_*` (lo recoge el próximo run) en vez de tumbar el paso.
  Detalle y tests en `activeContext.md`.
- **Resiliencia ante SUNAT, 3er caso (2026-09-23)**: el **422/cod 42209** ("aún tiene
  un proceso de 'Generar archivo exportar propuesta' en curso con Ticket: ...") al
  **pedir un ticket nuevo** mientras el anterior sigue corriendo se reintenta (30 s,
  hasta 5 veces) en vez de tumbar el run; y `get_zip` espera 15 s entre intentos del
  1070. Detalle y tests en `activeContext.md`.
- **Resiliencia ante SUNAT, 4º caso (2026-09-23)**: `TicketResource._request` ya no
  muere por un **error de red** (`OSError [Errno 101]`, DNS, timeouts): reintenta con
  presupuesto propio (10 × 30 s) y la petición lleva
  **`timeout=HTTP_REQUEST_TIMEOUT_SECONDS` (60 s)** para que un socket colgado no
  bloquee el run. Detalle y tests en `activeContext.md`.
- **SIRE/SUNAT**: `sire_proposal_monthly`, `sire_details_monthly` (detalle de CPE por
  API) y `sire_files_monthly` (PDF/ZIP) — los 3 **mensuales, grupo `from_sire` y
  append-only** (2026-09-17). **Políticas**: `sire_proposal_monthly` con `single_run()`;
  `sire_details_monthly` y `sire_files_monthly` **sin política a propósito** (= `multi_run(1)`,
  decisión del usuario 2026-09-23), así que el grupo se lanza **un run por mes con `--partition`**
  (`--partition-range` está rechazado por el CLI al incluir esos 2). La propuesta pide **1 libro
  por mes/empresa** y details/files solo bajan lo que falta. Asignación de centro de costo desde
  `sire_purchs_files`: `cep_cost_centers_monthly`, `icaro_cost_centers_monthly`,
  `petroperu_cost_centers_monthly` (mensuales, dependen **solo** de `sire_files_monthly` y saltan
  los ZIP ya procesados). Desde el **2026-09-23** esos 3 **no** consultan `sire_purchs`: el
  proveedor se identifica por el RUC con el que SUNAT nombra el ZIP y la FK de
  `sire_purchs_files` garantiza el vínculo con la compra.
- **Tokens SIRE automáticos, por audiencia y cacheados (2026-09-17)**: `SireTokenResource`
  (`src/assets/sire_assets/resources/token_resource.py`) resuelve
  `token(empresa, audience, recurso)` con tres pasos: **caché de fichero**
  (`env/sire_tokens.json`, dict **audiencia → empresa → token** con `exp`/`recursos`/`origen`)
  → **API de seguridad** (OAuth2, `grant_type=password`, usuario RUC+usuario SOL, clave SOL) →
  **portal SOL por HTTP puro** (`resources/sol_portal.py`, sólo para `consultacpe`). Valida
  `exp` (margen 60 s) y el claim `aud` (que SUNAT manda como **string con JSON dentro**). Al
  obtener un token se guarda bajo **todas las audiencias que cubre** y gana **el más fresco**;
  si no hay forma de obtenerlo, **`SireTokenError`** tumba la materialización. **No hay token
  manual** (el campo `token` del JSON se ignora) y `fixed_token_resource.py` se **eliminó**.
  La propuesta/ticket piden `api-sire` + `/v1/contribuyente/migeigv`; detalles/archivos,
  `api-cpe` + `/v1/contribuyente/consultacpe`. Verificado **en vivo**: Air Majoro recibe ambos
  recursos en el de seguridad (0 logins); Air Majoro Selva **no** recibe `consultacpe` ⇒ sus
  detalles/archivos van solos por el portal.
- **`docs/sol_token_navegador.py`**: **plan B documentado** con **navegador headless**
  (Selenium + Firefox + geckodriver; `selenium` comentado en `requirements.txt`). Fue el que
  descubrió el flujo real (hay que **pulsar `#btnAceptar`**, no `LoginForm.submit()`; el JWT
  acaba en `sessionStorage["SUNAT.token"]`) y sirve para depurar a la vista. Valida con los
  helpers del resource y deja el token en la **misma caché**. La sesión de cookies del portal
  no se puede reutilizar: el WAF (F5) contesta `Request Rejected`.
- **`scripts/` se queda sólo con `pipeline_cron.sh`**: `scripts/sol_token.py` se **eliminó**
  (su lógica HTTP vive en `resources/sol_portal.py`) y `PIPELINE_TOKEN_EMPRESA` (paso 0) ya
  **no existe**: el cron no refresca tokens.
- **`seesol_rh_monthly` (2026-09-17)**: el **reporte RH del SEE-SOL** (el que alimenta
  `seesol_rh`) es ahora un asset **al primer nivel** (`src/assets/seesol_rh_asset/`,
  partición **mensual** = `monthly_partitions_def`, `BackfillPolicy.single_run()`, sin
  dependencias) con la vía **HTTP pura** dentro de su `resources/api_resource/`
  (el login del portal lo toma de `resources/sol_portal.py`). Flujo: login (1 intento,
  aborta si `fallas >= 3`) → `action=execute&code=11.5.1.1.14` →
  `accion=CapturaCriterioConsulatRec1` (con `tipocomprobante="01;02;03;"`; **mandarlo
  vacío devuelve 0 registros**) → `accion=descargaConsultaReceptor` (`text/plain`).
  Upsert **por (mes, empresa)** (`upsert_month`), con aviso si el mes trae menos filas
  que antes. Contrato: `RhResource.get_month(company, period)`. El archivo que baja es
  **byte a byte idéntico** al manual (verificado con `cmp` en ago-2026 para las 2
  empresas, cuando el flujo vivía en el script). El **cron** (paso 0bis, activo salvo
  `PIPELINE_RH=0`) materializa el mes anterior y el actual. `scripts/sol_rh_seesol.py`
  se **eliminó** y los TXT de `static/RH` ya no se leen.
- **`scripts/pipeline_cron.sh`**: paso 0bis (RH, activo salvo `PIPELINE_RH=0`) y los SIRE +
  correo. **Ya no hay paso de tokens** (`PIPELINE_TOKEN_EMPRESA` se eliminó).
- **SISA**: `sisa_sales_monthly` (liquidaciones por empresa/sede).
- **Tipo de cambio**: `calendar_weekly` → `dwh_calendar`.
- **Estáticos**: un solo asset `static_data_asset` (partición `"2026"`) que deja en
  `db.sqlite` los 3 snapshots (`ambulancia_ventas_reports`, `lap_reports`,
  `planilla`, con `period="2026"`) y los **6 CSV de referencia** (`dwh_static_*`,
  `static_aux_*`) con `replace_all` (9 tablas). El RH **no** está aquí: lo llena
  `seesol_rh_monthly` (ver arriba).
  Los archivos de origen están **todos al primer nivel de `static/`** (sin subcarpeta
  de assets; `static/RH/<empresa>/MM.txt` es la única subcarpeta, hoy histórica).
- **dbt**: normalización a 26 columnas → `moves` (con `account`, `cost_center` y los
  tipos del DWH: `date`/`integer`/`bigint`/`numeric`) y el catálogo `partners`
  (código -> descripción de proveedores y clientes, 11.292 filas); `dbt run` en verde
  (**6 tablas**, 18 efímeros) cuando las tablas de origen están cargadas. `sales_std`
  deduplica por documento (serie + número) con prioridad ambulancia > SISA > SIRE.
  Validado el 2026-09-16 con perfil temporal en `/tmp` (PASS=7) y **corrido también
  contra el `analytics_poc.duckdb` real** (`cd src/dbt && dbt run`, PASS=6, 2,57 s):
  `moves` 45.376 filas
  y ningún (serie, número) repetido entre SISA y SIRE. Los estáticos y `calendar` leen
  **de la BD**, no del CSV.
- **Publicación**: `sync_db.py` publica **todas las tablas del DuckDB** en el esquema
  `dwh` con el mismo nombre (crea lo que falte, `DELETE` + `COPY`, sin `DROP` por las
  vistas). Verificado el 2026-09-16 contra el DWH real: **6 tablas / 57.135 filas**
  (`moves` 45.376, `partners` 11.292, `calendar` 332, `static_master_accounts` 96,
  `static_cost_centers` 28, `static_airplanes` 11), con los conteos
  `duckdb == postgres` cuadrando tabla por tabla y re-ejecución idempotente.
- **`sync_db.duckdb_connect()` (2026-09-18)**: abre el DuckDB en `read_only=True` y, si el
  error es *"different configuration than existing connections"*, reabre con la configuración
  existente (lectura-escritura). Es lo que permite `dbt_run` + `publish_dwh` en el **mismo
  proceso** (`run_pipeline.py`, executor in-process): dbt deja el fichero abierto en
  lectura-escritura y DuckDB rechaza la segunda conexión con otra config. Validado con el job
  real in-process: `dbt_run` PASS=6 + `publish_dwh` 6 tablas / 64.180 filas (dry-run).
- **La publicación es POR DEFECTO (2026-09-18)**: el paso `dbt/publicación` de
  `run_pipeline.py` arranca con `solo=("dbt_run", "publish_dwh")`; `--sin-publish` es el flag
  para saltarla (y `--publish` sigue aceptándose como no-op, por compatibilidad con líneas de
  cron viejas). Sin `PGHOST` **no** se deja de publicar en silencio: se emite un AVISO y el step
  falla al conectar. Antes era opt-in, y por eso `publish_dwh` **nunca** aparecía en la historia
  de Dagster: los 5 runs de `dwh_publish_job` solo tenían el step `dbt_run`. Las credenciales
  salen de `env/.env` (claves `PG*`), que el runner carga al arrancar. Dry-run validado el
  2026-09-18 contra el DWH real: 6 tablas / **64.180 filas** (`moves` 52.099, `partners` 11.614,
  `calendar` 332...) ⇒ el `dwh` estaba desactualizado desde el 2026-09-16 (`dwh.moves` 45.376).

## Cobertura de pruebas
- Suite pytest en `tests/` (50 archivos); helpers en `tests/conftest.py`
  (`make_pdf`). Cubre resources, db_resources, parsers y modelos pydantic de todos
  los dominios (CORPAC, SIRE details/files/proposal, SEE-SOL RH, SISA, TERPEL, TALMA,
  ADP, planilla, calendar, estáticos), el resource de tokens `SireTokenResource`
  (`tests/test_token_resource.py`: caché de fichero, multi-audiencia, "gana el más fresco",
  API de seguridad, portal HTTP simulado, sin fallback manual), el protocolo del portal
  (`tests/test_sol_portal.py`: helpers, captcha/fallas, login de 1 intento, `action=execute`
  con el JWT en el `Location`), la base `AbstractDbResource` (incluido
  `_replace(model, None, rows)` = reemplazo de tabla completa), el asset estático
  (snapshots + CSV), el parser de CSV, el asset del RH
  (`tests/test_seesol_rh_asset.py`), la vía HTTP del RH
  (`tests/test_rh_asset.py`: helpers puros, captcha/fallas, login de 1 intento y
  `get_month` simulado) y su resource de BD (`tests/test_seesol_rh_db_resource.py`).
- **Estado actual: 479 passed, 0 errores** (`pytest` desde la raíz; +30 de esta sesión:
  `tests/test_dbt_resource.py`, `tests/test_dwh_publish_resource.py`,
  `tests/test_dwh_assets.py` y `tests/test_jobs.py`, que fijan los 2 assets del DWH, sus
  resources, los 7 jobs y la ausencia de schedules/`automation_condition`). `pytest` y
  `python -m dagster definitions validate -m definitions` en verde con **19 assets** y 7 jobs
  (grafo mensual de SIRE, `seesol_rh_monthly` y la capa `dwh`).
- `tests/fixtures/` (corpac, terpel) y `tests/live_smoke.py` (smoke en vivo).

## Conocido / pendiente de validar
- **`dbt run` ya es ligero (RESUELTO el 2026-09-18)**: el OOM del 2026-09-17 (8,9 GB de
  *spill* en `analytics_poc.duckdb.tmp/`, RAM agotada, había que matar el proceso) NO era
  por volumen (las fuentes suman ~100 k filas) sino por la **recursión de
  `get_by_sep`/`capitalize_words` metida en la clave de un JOIN**: DuckDB no puede decorrelacionar un
  `WITH RECURSIVE` y degradaba a `LEFT_DELIM_JOIN` (fila por fila, 4.654 × 15.603 ≈ 72,6 M
  evaluaciones recursivas). Ahora esos 2 macros son nativos (`string_split`+`list_extract`
  y `unnest WITH ORDINALITY`+`string_agg`) y `get_car`/`cc_filename_to_car_sunat` usan
  `safe_int` (TRY_CAST) porque 60 filas de `from_email_adp_reports` con `referencia=''`
  tumbaban dbt con `Could not convert string '' to INT64`. Validado: `PASS=6` en 2,44 s y
  0 spill (ver `activeContext.md`). `PIPELINE_DBT=0` sigue desactivando el paso en el cron.
- **Quedan restos de la corrida fallida**: `analytics_poc.duckdb.tmp/` con ~8 GB de
  ficheros `duckdb_temp_storage_*` del OOM del 2026-09-18 (borrables cuando no haya ningún
  proceso con el DuckDB abierto).
- **La vista `public.vw_move_reporte_gerencial` ya no existe** (el schema `public` se
  eliminó): el DWH quedó reducido al schema `dwh` con las 6 tablas del pipeline y
  **una sola vista, `dwh.vista_reporte_gerencial`**, ya reapuntada a `dwh.moves`
  (joins a `static_master_accounts`, `calendar` y `partners`; filtro 2026;
  `subtotal_base_soles` con tipo de cambio si la moneda es USD; excluye los pagos
  adelantados de TERPEL).
- **`moves.account` trae 5 valores fuera del maestro**: `700000` (literal de
  `sire_sales_std`), `700001` (literal de `ambulance_sales_std`), `704104`/`704105`
  (de SISA) y el literal **`'Planilla'`** de `payroll_std.sql` (2.098 filas: es una
  etiqueta, no un código PCGE). En `dwh.vista_reporte_gerencial` eso deja **14.093 de
  43.154 filas (32,6%) sin `cuenta_contable_descripcion`**.
- **No hay tests de dbt** (`schema.yml` ni carpeta `tests/`).
- **Las filas de ambulancia salen con `move_type` NULL** (a propósito: `sales_std` ya
  no asigna `move_type` ni `account`; lo pone la capa que consuma `moves`), y los 22
  segundos documentos de los vuelos con 2 facturas **no** entran como fila propia
  (solo van en `observaciones` y se descartan de SISA y de SIRE, que es la regla
  pedida).
- **`models/static/`**: renombrar esos modelos obliga a actualizar los `ref()` de
  `purchs_std`, `moves` y el macro `obtener_aeropuerto` (el nombre del modelo debe ser
  el de su tabla).
- **Los 3 maestros `dwh_static_*` no los consume ningún modelo** todavía (se
  materializan para poder usarlos y publicarlos).
- **Regla de cuentas** (`static_aux_accounts_assignment`, 4 columnas sin `orden`): la
  regla ganadora es el `serv_desc_pattern` más largo; si un `partner_doc` vuelve a
  tener varias reglas, revisar ese criterio.
- **Edición manual de los CSV** de referencia (LibreOffice) → los conteos cambian
  entre corridas; no hardcodearlos.
- **`db.sqlite` ~19 GB**: gestionar espacio/copias; DuckDB abre
  `analytics_poc.duckdb` con lock exclusivo (DBeaver abierto ⇒ `dbt run` falla).
