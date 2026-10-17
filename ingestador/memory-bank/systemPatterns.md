# System Patterns — Arquitectura y convenciones

## Layout del repositorio
```
REPOAIMNUEVO/
├── README.md                # puesta en marcha (Windows y Linux) + prompts históricos
├── requirements.txt
├── definitions.py           # ENTRY POINT de Dagster: 19 assets + resources + los 7 jobs
├── pyproject.toml           # [tool.dagster] module_name = "definitions" (deps del proyecto)
# (NO hay `scripts/`: se eliminó el 2026-09-25. Todo el pipeline se lanza con el CLI/assets
#  de Dagster: `python -m dagster asset materialize -m definitions --select ...`)
├── db.sqlite                # BD de integración (~19 GB, no versionada)
├── analytics_poc.duckdb     # destino de dbt (no versionado)
├── dagsterhome/             # DAGSTER_HOME
├── docs/                    # EERR.xlsx, diagramas .drawio/.png, reporte.txt, tabla10sunat.ods y
│                            #   sol_token_navegador.py (PLAN B documentado del token: Selenium headless)
├── env/                     # estado de SIRE, junto: sire_credentials.json (credenciales SUNAT)
│                            #   y sire_tokens.json (caché de tokens; gitignored); además .env y
│                            #   email_credentials.json (gitignored)
├── logs/                    # gitignored: logs de los scripts (cron de correo)
├── static/                  # carpeta ÚNICA de estáticos: TODO al primer nivel (operativos + CSV) + RH/<empresa>/
└── src/
    ├── jobs.py              # define_asset_job por cadena (SIN ScheduleDefinition: cron externo)
    ├── assets/
    │   ├── utils.py                 # to_db_field() / normalize_rows() compartidos
    │   ├── _common/                 # db.py (DatabaseProxy), abstract_resource.py
    │   │                            # (con _existing_keys/_insert_new) y partitions.py
    │   │                            # (def diaria de correo, mensual compartida de SIRE y
    │   │                            #  RH, y los helpers partition_days/partition_months)
    │   ├── calendar_asset/          # calendar_weekly (tipo de cambio)
    │   ├── mail_asset/              # ingest_emails -> emails / email_attachments
    │   ├── from_email_assets/       # corpac_data, corpac_files, adp, talma, terpel (tickets + order)
    │   ├── from_sire_files_assets/  # cep / icaro / petroperu cost_centers (+ _aeronave_common)
    │   ├── sire_assets/             # proposal, details, files + resources compartidos:
    │   │                            #   token_resource.py (SireTokenResource: caché + audiencias) y
    │   │                            #   sol_portal.py (login HTTP del portal SOL + action=execute)
    │   ├── seesol_rh_asset/         # seesol_rh_monthly: reporte RH del SEE-SOL por HTTP
    │   │                            # (models/rh.py, parsers/rh.py, resources/api_resource
    │   │                            #  con la Consulta Receptor; el login lo toma de sol_portal)
    │   ├── sisa_sales_asset/
    │   ├── dwh_assets/              # dbt_run (dbtRunner sobre src/dbt) + publish_dwh
    │   │                            # (motor `DwhPublishResource`). Sin particiones, grupo `dwh`
    │   └── static_data_asset/       # UN asset: snapshots + CSV (parsers/, models/, resources/)
    ├── dbt/                         # proyecto dbt (models/, macros/, sources.yml, profiles.yml)
    └── tests/                       # pytest (58 archivos test_*.py) + tests/fixtures/ + tests/live_smoke.py
```

## Patrón por asset (convención dominante)
Cada asset vive en `src/assets/<dominio>_assets/<algo>_asset/` (los dominios de una
sola fuente son una carpeta al primer nivel, p. ej. `sisa_sales_asset/`,
`seesol_rh_asset/`, `static_data_asset/`, `calendar_asset/`) y tiene:
- **`<algo>_asset.py`**: función `@asset` de Dagster con su partición
  (`_daily` / `_monthly` / `_weekly`; el estático usa
  `StaticPartitionsDefinition(["2026"])`). **Toda la cadena de correo es `_daily`** y
  comparte la definición de `assets/_common/partitions.py`; los mensuales (SIRE y
  `seesol_rh_monthly`) comparten la **misma** `MonthlyPartitionsDefinition`
  (`end_offset=1`) de `_common/partitions.py`.
- **`models/model.py`**: modelos **peewee** (una tabla por clase) sobre el `db`
  compartido; el nombre de la tabla es el contrato que lee dbt.
- **`models/pydantic_model.py`**: validación de filas entrantes.
- **`parser.py`** o `parsers/`: parseo local (pdfplumber, ZIP, HTML, CSV, ODS) que
  no toca recursos externos.
- **`resources/db_resource.py`** (hereda de `AbstractDbResource`): upsert de tablas.
- **`resources/api_resource.py`**: llamadas HTTP (requests/urllib, cookies, Bearer).
- Los archivos **hijos** (1 padre a N hijos) guardan el id del padre
  (`id_email`, `file_id`) y limpian/consultan por partición.

## Patrones transversales
- **Tokens de SUNAT/SIRE**: los resuelve **`SireTokenResource`**
  (`assets/sire_assets/resources/token_resource.py`) por **audiencia**:
  `token(empresa, audience, recurso)` → **caché de fichero** (`env/sire_tokens.json`,
  audiencia → empresa → token) → **API de seguridad** → **portal SOL por HTTP puro**
  (`assets/sire_assets/resources/sol_portal.py`; sólo para `consultacpe`). No hay token
  manual ni scripts de token; el plan B con **navegador headless** está **documentado** en
  `docs/sol_token_navegador.py` (no lo usa el pipeline). El login del portal lo comparten
  el resource de tokens **y** el asset del RH, nunca reintenta (`fallas >= 3` ⇒ captcha ⇒
  abortar) y el token dura 1 hora (por eso se cachea).
- **Reporte RH del SEE-SOL (`seesol_rh_monthly`, 2026-09-17)**: el reporte de recibos por
  honorarios (→ `seesol_rh`) lo baja el asset mensual `seesol_rh_monthly` con la vía
  **HTTP pura** de su `resources/api_resource/rh_resource.py` (nada de navegador ni de
  ficheros intermedios): login del portal → `action=execute&code=11.5.1.1.14` (app
  "Consulta Receptor" del SEE, que redirige a
  `ww1.sunat.gob.pe/ol-ti-itreciboelectronico/cpelec001Alias`) → `accion=CapturaCriterioConsulatRec1`
  con `tipocomprobante="01;02;03;"` → `accion=descargaConsultaReceptor` (el "Descargar Reporte",
  `text/plain`). **El rango no puede pasar de 1 mes** (⇒ partición mensual, 1 login por empresa y
  mes) y el archivo baja **byte a byte** igual al manual. El cron (`pipeline_cron.sh`, paso 0bis,
  `PIPELINE_RH=0` lo desactiva) materializa el mes anterior + el actual del asset. El antiguo
  `scripts/sol_rh_seesol.py` (que escribía `static/RH/<empresa>/MM.txt` para que
  `static_data_asset` lo ingiriera) **se eliminó**.
- **Cadena de correo (2026-09-17)**: los 7 assets (`ingest_emails`, `corpac_files_daily`,
  `corpac_data_daily`, `talma_reports_daily`, `adp_reports_daily`, `terpel_tickets_daily`,
  `terpel_order_daily`) comparten `correos_daily_partitions_def`
  (`start_date="2026-01-01"`, sin `end_offset` ⇒ última partición = **ayer**), están en el grupo
  `from_email` y usan `partition_days(context)` para soportar un rango (`single_run` completo,
  `multi_run` troceado) o un día.
  Reparto de `BackfillPolicy`: **`multi_run(max_partitions_per_run=30)`** en `ingest_emails` y
  `corpac_files_daily` (2026-09-23: un run por cada trozo de hasta 30 días, recorrido día a día
  por `procesar_dia`, con `MaterializeResult` sin valor) y **`single_run()`** en
  `corpac_data_daily`, los 4 de reportes, `calendar_weekly` y `sisa_sales_monthly`: todos
  recorren las claves del run con `partition_days(context)` (`procesar_dia`/`procesar_semana`/
  `procesar_mes`), así que el rango entero cae en **un solo run** (las particiones baratas no
  compensan planificar un run por partición).
  **Sin** `automation_condition`: el disparo es un cron externo con
  `--select "group:from_email" --partition <día>`. Ojo: Dagster sólo deja materializar padre e
  hijo en el **mismo run** si comparten `partitions_def` **y** `BackfillPolicy` (y el mapeo es
  identidad); con `--partition` fijo sí van juntos aunque las políticas difieran.
- **Cadena SIRE (2026-09-17, rediseñada a mensual)**: los 6 assets (`sire_proposal_monthly`,
  `sire_details_monthly`, `sire_files_monthly` y los 3 `*_cost_centers_monthly`) comparten
  `sire_monthly_partitions_def` (`start_date="2026-01-01"`, `end_offset=1` ⇒ el mes en curso es
  partición válida) y están en el grupo `from_sire`. **Reparto de `BackfillPolicy` (2026-09-23)**:
  `sire_proposal_monthly` y los 3 cost centers con `single_run()`; **`sire_details_monthly` y
  `sire_files_monthly` SIN política a propósito** (= `multi_run(1)`), así que `sire_monthly_job`
  resuelve **`multi_run(1)`** y el mes anterior + el actual se lanzan con **2 `--partition`** (un
  run por mes) o con un backfill de la UI/daemon: el CLI **rechaza** `--partition-range` cuando la
  selección incluye un asset sin `single_run()`. **Sin** `automation_condition`. Deps **identidad**: `details`/`files` → la propuesta y los cost centers →
  **solo** `sire_files_monthly` (la propuesta entra por transitividad; así el run garantiza que los
  ZIP del mes ya están descargados al extraer las aeronaves). Los cost centers **no** vuelven a leer
  `sire_purchs` (2026-09-23): identifican el ZIP del proveedor por el RUC del `nom_archivo` —SUNAT
  nombra el archivo `<RUC del emisor>-<tipo>-<serie>-<numero>.<ext>`, p. ej.
  `"nomArchivo": "20514513172-08-F040-399-XML.zip"` del ADP— y la FK
  `sire_purchs_files.sire_purch` garantiza que el ZIP pertenece a una compra ya registrada.
  `partition_months(context)` agrupa los meses del run para pedir
  **un libro por mes** (no uno por día) y `_procesar_mes` usa la ventana del mes para
  `select_missing_*`. **Append-only en toda la rama** (`insert_proposal_new` con clave natural
  sobre `_existing_keys`/`_insert_new`, `insert_details`/`insert_files` que solo piden faltantes,
  `insert_aeronaves_new` por `(id_file, aeronave)` y `select_zip_files` que salta los ZIP ya
  procesados) ⇒ los ids del padre no rotan, no hay huérfanos y re-pasar dos meses cada día es
  barato. Las llamadas a `delete_orphan_details`/`delete_orphan_files` quedaron **fuera** del flujo
  (los métodos siguen existiendo para una limpieza puntual).
- **Tokens SIRE (2026-09-17)**: `SireTokenResource` (`assets/sire_assets/resources/token_resource.py`)
  es el único proveedor de tokens. `token(name, audience, recurso)` resuelve **caché de fichero**
  (`env/sire_tokens.json`: **audiencia → empresa → token**, con `exp`/`recursos`/`origen`) →
  **API de seguridad** (`api-seguridad.sunat.gob.pe`..., `grant_type=password`, usuario =
  RUC+usuario SOL, clave SOL) → **portal SOL por HTTP** (`sol_portal.py`, sólo `api-cpe`). Se
  comprueban `exp` (margen 60 s) y el claim `aud` (en SUNAT llega como **string con JSON
  dentro**); al guardar, el token se escribe bajo **todas las audiencias que cubre** y gana el
  **más fresco**. Las audiencias/recurso que pide cada consumidor son campos del resource:
  propuesta/ticket → `AUDIENCE_SIRE` + `/v1/contribuyente/migeigv`; detalles/archivos →
  `AUDIENCE_CPE` + `/v1/contribuyente/consultacpe`. **Sin token manual** y sin
  `fixed_token_resource.py` (borrado). El intento fallido del portal se memoiza por proceso.
- **Normalización**: las columnas se pasan a snake_case sin acentos con
  `assets/utils.py` (`to_db_field`, `normalize_rows`); no duplicar esa lógica.
- **`AbstractDbResource`** (`src/assets/_common/abstract_resource.py`) resuelve el
  motor (`engine="sqlite"` sobre `db.sqlite` o `engine="postgres"`), crea las tablas
  (`create_tables`) y ofrece los upserts portables: `_replace(model, where, rows,
  inject)` (`where=None` = reemplaza la tabla **completa**), `_existing_keys` y
  `_insert_new` (append-only, para correos y adjuntos).
- **`db` es un `DatabaseProxy` compartido**: los modelos no saben si el motor es
  SQLite o PostgreSQL.
- **Correo append-only y con descarga INCREMENTAL** (2026-09-18): el asset
  `ingest_emails` hace 3 fases —
  1. `GmailResource.list_message_ids(query)` ⇒ ids del día **por cuenta** (llamada
     barata a `users.messages.list`: ni cuerpos ni adjuntos);
  2. `DbResource.existing_email_ids(ids)` ⇒ los que ya están en `emails`;
  3. `GmailResource.fetch_emails(..., ids_by_account=..., skip_ids=...)` descarga
     (`format="raw"`: cuerpo + adjuntos base64, la parte cara) **solo los nuevos**.
  El insert sigue siendo append-only: `append_emails`/`append_email_attachments`
  (antes mal llamados `upsert_*`) usan `_existing_keys` + `_insert_new` y **nunca**
  borran ni actualizan (no tocan `_replace`), solo agregan `id` nuevo. Las tablas
  `from_email_*` declaran `ForeignKeyField` a `emails`/`email_attachments` con
  `object_id_name` para que los accesos crudos (`row.email_id`, `row.id_email`)
  sigan devolviendo el id. Ojo: la PK de `emails` es solo `id`, así que un id ya
  guardado se salta en **todas** las bandejas (comportamiento previo del insert).

## Estáticos (`static_data_asset`) — flujo actual
- **Una sola carpeta y SIN subcarpeta de assets**: `static/` (las antiguas
  `static/static_assets/` y `static/dbt_seeds/` se eliminaron), con **todos los
  archivos al primer nivel**: los **operativos** (`VENTAS*.xlsm`, `LAP*.xlsx`,
  `Planilla.ods`) y los **6 CSV de referencia** (`dwh_static_*`, `static_aux_*`).
  La única subcarpeta es `RH/<empresa>/MM.txt`, que **ya no lee el pipeline** (los
  TXT del reporte RH quedan solo como histórico: ahora los baja
  `seesol_rh_monthly` por HTTP, ver la sección del RH más abajo).
- El asset (partición `"2026"`) hace, en este orden:
  1. recorre **`STATIC_SPECS`** (glob + parser + modelo peewee) y hace
     `upsert_partition` con `period = "2026"` → `ambulancia_ventas_reports`,
     `lap_reports`, `planilla`;
  2. recorre **`CSV_SPECS`** (el archivo `<tabla>.csv`), lo parsea con
     `parsers/csv_static.py` (`parse_csv`: `csv` de stdlib, cabeceras con
     `to_db_field`, vacíos → `None`) y hace `replace_all` de la tabla homónima en
     `db.sqlite` → `dwh_static_master_accounts`, `dwh_static_airplanes`,
     `dwh_static_cost_centers`, `static_aux_accounts_assignment`,
     `static_aux_airports`, `static_aux_cost_centers_override`.
- El asset **ya no toca el RH** (ni `parsers/rh.py` ni `models/rh.py` viven aquí:
  se movieron a `assets/seesol_rh_asset/`, junto con el `RhResource` que ahora es
  HTTP y no lee archivos).
- El resource del asset estático crea **9** tablas (3 snapshots + 6 CSV).
- Los modelos peewee de los CSV usan `primary_key = False` (la tabla refleja el CSV
  tal cual, sin columna `id`) y todas las columnas son TEXT.
- **dbt NO lee los CSV** (`read_csv_auto` ya no se usa): los 6 modelos homónimos de
  `src/dbt/models/static/` hacen `FROM <tabla>` y copian la tabla de `db.sqlite` a
  DuckDB. **El asset tiene que correr antes que `dbt run`.**

## Reporte RH del SEE-SOL (`seesol_rh_asset`) — asset mensual, 2026-09-17
- **`seesol_rh_monthly`** es un asset **al primer nivel** (`src/assets/seesol_rh_asset/`)
  con la **misma** `MonthlyPartitionsDefinition` que SIRE (`seesol_rh_monthly_partitions_def`,
  alias de `monthly_partitions_def` en `_common/partitions.py`) y
  `BackfillPolicy.single_run()`; sin dependencias ni condiciones de automatización.
- **`resources/api_resource/rh_resource.py`** es la vía **HTTP pura** del reporte RH (portada
  de `scripts/sol_rh_seesol.py`, script **eliminado**): constantes en
  `resources/api_resource/constants.py` (`MENU_URL`, `URL_FAILS`, `APP_RECEPTOR` =
  `11.5.1.1.14`, `FORM_PATH` = `/ol-ti-itreciboelectronico/cpelec001Alias`,
  `ACCION_CRITERIO`, `ACCION_DESCARGA`, `TIPOS_DOC = "01;02;03;"`, `EMPRESAS`), helpers puros
  (`rango_del_mes`, `criterios_busqueda`, `sin_registros`, `base_del_portal`,
  `inputs_del_form`) y el flujo con `requests`: `descubrir_flujo` (aborta si
  `fallas >= 3`) → `hacer_login` (**1 intento**, sin reintentos, sigue el 302) →
  `abrir_sesion` → `abrir_app` (`prevApp` + `action=execute` → 302 a `ww1.sunat.gob.pe`) →
  `descargar_reporte` (GET del form, POST de criterios, POST `descargaConsultaReceptor`).
  Contrato del resource: `get_month(company, period) -> list[dict]` (filas con su `period`
  estampado) y `fetch_report(company, period) -> str` (texto crudo). Credenciales:
  `credentials_path` (por defecto `env/sire_credentials.json`).
- **`resources/db_resource.py`** (`SeesolRhSqliteResource`): `upsert_month(period, empresa,
  rows)` reemplaza **solo** la pareja (mes, empresa) —los otros meses/empresas no se tocan— y
  `count_month` da las filas previas para el aviso de "menos filas que antes" (mes incompleto).
- **`parser`/`model`**: `parsers/rh.py` (`parse_rh_text`, 16 columnas pipe-delimited con saltos
  de línea en la Descripción) y `models/rh.py` (`Rh` → tabla `seesol_rh`, con `BaseModel`
  propio). Fueron movidos desde `static_data_asset/`.
- El asset estampa `empresa` en cada fila y el resource `period`/`empresa` en el borrado; el
  cron materializa **mes anterior + mes actual** (`--partition-range`) y trata el fallo como
  AVISO (`PIPELINE_RH=0` lo desactiva).

## dbt (capa analítica)
- **24 modelos, 0 seeds**; se corre desde la CLI (`cd src/dbt && dbt run`), sin
  asset de Dagster (`dagster-dbt` sigue instalado pero no se usa).
- **6 tablas** (el 2026-09-16 se quitaron los prefijos `dwh_` de los nombres de
  modelo, y por tanto de las tablas): `moves` (26 columnas: `purchs_std` ∪
  `sales_std` ∪ `labor_std`, con el override de centro de costo de
  `aux_cost_centers_override`), `partners` (código -> descripción de proveedores y
  clientes), `calendar` (copia la tabla `dwh_calendar` de SQLite) y los maestros
  `static_master_accounts` / `static_airplanes` / `static_cost_centers`.
  Los otros **18 son `ephemeral`** (los 3 `aux_*`, `ambulance_sales_std` —que pasó de
  tabla a efímera, así que ya no se publica al DWH— y todas las ramas de
  compras/ventas/labor).
- **`partners`**: junta las **7 vías** de `db.sqlite` donde hay código + descripción
  (`dwh_proveedores` —el catálogo histórico que ya usaba la vista gerencial—,
  `sire_sales`, `sire_purchs`, `sisa_sales`, `static_aux_accounts_assignment`,
  `seesol_rh` y `planilla`) y se queda con la primera descripción no vacía en ese
  orden (`row_number()`); 11.292 códigos y cubre el 99,8% de los `partner_doc` de
  `moves`. Los `partner_doc` que el Excel de ambulancias trae como nombre (no RUC) no
  están: no son códigos.
- **`moves` fija los TIPOS del DWH** (las ramas heredan TEXT/DOUBLE de SQLite y aquí
  se castean, siempre con `TRY_CAST`: un valor inválido queda NULL, no rompe dbt):
  `doc_date` / `doc_due_date` / `serv_date` **DATE** (pasan por `normalize_date`,
  que además descarta años fuera de [1900, 2030]), `doc_type` **INTEGER**,
  `doc_number` **BIGINT**, `qnt` **DECIMAL(18,3)**, `amnt_taxable` / `amnt_taxes`
  **DECIMAL(18,6)** (quita el ruido del `double`: 63.480000000000004 -> 63.480000),
  `error` **VARCHAR**. Efectos: planilla pierde sus códigos de texto en
  `doc_type`/`doc_number` (quedan NULL, como en el antiguo `dwh.movimientos`) y los
  6 `serv_date` basura quedan NULL.
- **`models/static/`: el nombre del MODELO ya no es el de la tabla**. Los 6 modelos
  que copian los CSV son `static_master_accounts`, `static_airplanes`,
  `static_cost_centers` (tablas) y `aux_accounts_assignment`, `aux_airports`,
  `aux_cost_centers_override` (efímeros). **Los `ref()` van al nombre del modelo**
  (`ref('aux_accounts_assignment')` en `purchs_std`,
  `ref('aux_cost_centers_override')` en `moves`, `ref('aux_airports')` en el macro
  `obtener_aeropuerto`), mientras que el nombre "pelado" del `FROM` es el de la TABLA
  de `db.sqlite`, que **conserva el suyo** (`static_aux_*`, `dwh_static_*`,
  `dwh_calendar`). Renombrar un modelo sin actualizar sus `ref()` **rompe la
  compilación** (dbt resuelve al seed deshabilitado homónimo: ya pasó dos veces el
  2026-09-16). `cost_centers` está ocupado por el efímero de compras
  (`purchs/cost_centers.sql`), de ahí `static_cost_centers`.
- **`sales_std` (ventas)**: solo `UNION ALL`, con **una fila por documento**
  (`doc_serie` + `doc_number`) y prioridad **ambulancia > SISA > SIRE**. `amb_docs`
  extrae **todos** los documentos del array `agregado_factura` de
  `ambulancia_ventas_reports` (`coalesce(from_json(..., '["VARCHAR"]'), []::VARCHAR[])`
  + `unnest`); SISA descarta esos documentos y SIRE descarta los de ambulancia **y**
  los de SISA. **No** asigna `account` ni `move_type`.
- **`ambulance_sales_std`** (hoy `ephemeral`: no materializa tabla) emite el contrato
  de 26 columnas + `observaciones` (2ª
  factura del vuelo, fuera del contrato): las columnas técnicas que el reporte no
  trae (`id`, `error`, `ingested_at`, `move_type` y los 3 `source_*`) van en NULL.
- **Estructura**: `purchs/`, `sales/`, `labor/`, `static/` y en la raíz de `models/`
  `moves.sql` y `partners.sql`; los de origen van en subcarpetas `sire/` y
  `from_reports/`, y el nombre del archivo es el del modelo. Ramas estándar con sufijo
  por dominio: `*_purchs_std`, `*_sales_std`.
- **Contrato de 26 columnas** (`id`, `doc_date`, `doc_type`, `doc_serie`,
  `doc_number`, `doc_due_date`, `partner_doc_type`, `partner_doc`, `qnt_type`,
  `qnt`, `currency`, `amnt_taxable`, `amnt_taxes`, `serv_date`, `serv_desc`,
  `cost_center`, `serv_org_airport`, `serv_dest_airport`, `account`, `company`,
  `error`, `ingested_at`, `move_type`, `source_sire_sales`,
  `source_sire_sales_details`, `source_sisa`): cualquier rama nueva debe respetarlo
  o el `UNION ALL` falla.
- **Cuenta contable**: en `purchs_std` se resuelve con una **subconsulta escalar** a
  `static_aux_accounts_assignment` (el CSV ya guarda **códigos PCGE en su columna
  `account`** —91 filas, cabecera `partner_doc, partner_desc, serv_desc_pattern,
  account`—, no nombres, desde el 2026-09-16; `ORDER BY length(serv_desc_pattern) DESC
  NULLS LAST LIMIT 1`: gana el patrón más largo) y, sin regla,
  `COALESCE(q.account, '659902')`. **Centro de costo**: override por
  proveedor+serie+número, si no el de origen y si no
  `cost_center_from_serv_desc(serv_desc)`.
- **Macros** (15) en `src/dbt/macros/`: `obtener_aeropuerto` (usa
  `static_aux_airports`), `get_car`, `cc_filename_to_car_sunat`, `removedups`,
  `extract_cost_center`, `cost_center_from_serv_desc`, `normalize_date`,
  `normalize_currency`, `safe_int`, `now_utc`, `get_by_sep`, `capitalize_words`,
  `prefer_equal`, `prefer_equal_neg`, `prefer_null`.
  - **NO hay ningún `WITH RECURSIVE`** (2026-09-18): `get_by_sep` y
    `capitalize_words` se reescribieron con funciones nativas de DuckDB
    (`string_split`+`list_extract` y `unnest…WITH ORDINALITY`+`string_agg`).
    Motivo: DuckDB **no puede decorrelacionar un CTE recursivo**, así que cuando
    `adp_purchs_std` metía `get_by_sep` 3 veces **en la clave de un JOIN** el
    plan degradaba a `LEFT_DELIM_JOIN` (fila por fila) y `dbt run` se colgaba
    con ~8 GB de *spill* y OOM. **Regla: no metas subconsultas recursivas (ni
    correlacionadas con `LIMIT`) dentro de una clave de JOIN.**
  - Todo entero que salga de **texto de origen** pasa por `safe_int` (`TRY_CAST`
    en DuckDB), nunca por `CAST`: un `''` o un valor no numérico debe quedar
    NULL, no tumbar dbt. `get_car` y `cc_filename_to_car_sunat` ya lo cumplen
    (antes no: 60 filas de ADP con `referencia=''` rompían el `dbt run`).
- **`sources.yml`** documenta 6 grupos de tablas de origen (`sire`, `compras`,
  `cost_centers`, `sisa`, `ambulancia`, `lap`), pero los modelos **no** usan
  `source()`: leen nombres de tabla "pelados" que resuelve el `search_path`.
- **No hay `schema.yml` ni carpeta `tests/` de dbt**: hoy no hay tests de dbt.
- Los 3 maestros `static_*` se materializan pero **hoy ningún modelo los consume**;
  los auxiliares sí (los modelos `aux_accounts_assignment` en `purchs_std`,
  `aux_airports` en el macro de aeropuertos y `aux_cost_centers_override` en `moves`,
  que leen las tablas `static_aux_*` de `db.sqlite`).

## Integración ↔ publicación
- `db.sqlite` es la capa de integración: la llenan los assets y **dbt la lee**.
- **La publicación vive en `DwhPublishResource`** (`src/assets/dwh_assets/dwh_publish_asset/
  resources/publish_resource.py`, que también es su CLI; antes era `sync_db.py` en la raíz).
  Publica el **DuckDB** (no `db.sqlite`): recorre **todas** las tablas
  BASE del esquema `main` de `analytics_poc.duckdb` y las copia al schema `dwh` de
  PostgreSQL **con el mismo nombre** (`moves` -> `dwh.moves`), sin listas ni mapeos
  hardcodeados. Crea la tabla si falta (tipos mapeados desde DuckDB), añade por
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` las columnas nuevas y hace `DELETE` +
  `COPY` (nada de `DROP`: la vista `dwh.vista_reporte_gerencial` cuelga de esas
  tablas). Flags del CLI: `--duckdb`, `--schema`, `--only`, `--exclude`, `--dry-run` y
  `--recreate` (**DROP + CREATE**, necesario cuando cambian los TIPOS de una columna: el
  `CREATE TABLE IF NOT EXISTS` no los toca; solo con tablas sin vistas encima).
  ⚠️ **`--recreate` SIEMPRE con `--only`**: a secas soltaría `moves` y se llevaría por
  delante `dwh.vista_reporte_gerencial` (Power BI). Lo correcto cuando una tabla cambia de
  tipos es `--only <tabla> --recreate` y después publicar el resto con `--exclude <tabla>`
  (si no, el publish global aborta a mitad con un `InvalidTextRepresentation` al hacer
  `COPY` de la tabla desactualizada).
- **La publicación está dentro de un run del pipeline** (`run_pipeline.py`: `dbt_run` +
  `publish_dwh` en el paso `dbt/publicación`, por defecto; `--sin-publish` lo salta) y ambos
  steps corren en el **mismo proceso** (executor in-process). Como dbt deja el DuckDB abierto
  en lectura-escritura, la publicación **no** puede abrirlo en `read_only` (DuckDB rechaza dos
  configuraciones distintas para el mismo fichero en un proceso): para eso está
  **`publish_resource.duckdb_connect()`**, que usan `publicar()` y `DwhPublishResource.tables()`.
  Solo se escribe en el DuckDB desde dbt; la publicación es `SELECT` + `COPY` a PostgreSQL.
- **Ojo con las vistas**: la única es **`dwh.vista_reporte_gerencial`** (rehecha por el
  usuario el 2026-09-16 y ya **reapuntada al pipeline nuevo**): `FROM dwh.moves m` con
  `LEFT JOIN dwh.static_master_accounts` (por `m.account = a.codigo_pcge`),
  `dwh.calendar` (por `cal.date = m.doc_date`) y `dwh.partners` (por
  `p.codigo = m.partner_doc`); filtra 2026 (`serv_date` y `doc_date >= 2026-01-01`),
  calcula `subtotal_base_soles` (`amnt_taxable * exchange_rate_sale` si la moneda es
  USD) y excluye los pagos adelantados de TERPEL. El schema `public` **ya no existe**:
  el DWH es `dwh` y nada más.
- Objetos del `dwh` que no están en el DuckDB: no se tocan, solo se avisan. **Hoy el
  único es la propia vista `dwh.vista_reporte_gerencial`** (el aviso es normal:
  `information_schema` lista vistas y tablas juntas).

