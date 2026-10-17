# Tech Context — Stack y cómo correr

## Stack
- **Python 3.13** (venv `.venv/`); `requires-python = ">=3.10"`.
- **Dagster** + **dagster-webserver** (>=1.8); **`definitions.py` (RAÍZ del repo)** es el punto
  de entrada (`[tool.dagster] module_name = "definitions"` en el `pyproject.toml` de la raíz,
  así que el CLI se lanza desde la raíz), con los 19 assets, los resources
  y los 7 jobs con nombre de `src/jobs.py` (`jobs=JOBS`).
- **peewee** ORM → SQLite **`db.sqlite`** (raíz, ~19 GB, en `.gitignore`); los
  modelos usan un `DatabaseProxy` compartido (`assets/_common/db.py`), así que el
  motor es intercambiable (SQLite/PostgreSQL).
- **psycopg[binary] (>=3.1)**: motor PostgreSQL alternativo de los `db_resource` y
  lo que usa la publicación (`DwhPublishResource`) para copiar.
- **pydantic** (validación de filas), **pdfplumber** (PDF), **openpyxl**/pandas
  (Excel/ODS), **google-api-python-client**/**google-auth** (Gmail), stdlib `urllib`
  para el resto de APIs. **selenium** (>=4.25) es **sólo para el plan B documentado**
  del token (`docs/sol_token_navegador.py`) y está **comentado** en `requirements.txt`:
  el camino normal del token es HTTP puro dentro de los assets.
- **dbt-core >=1.9.1,<1.10** + **dbt-duckdb** (`duckdb >=1.5,<1.6`). El pin de dbt
  lo impone Dagster/pydantic (dbt-core 1.10+ exige pydantic<2). `dbt-sqlite` sigue
  instalado pero **no se usa**; `dagster-dbt` está instalado y **tampoco** se usa.

## dbt: motor y perfil (target único `dev` = DuckDB)
`src/dbt/profiles.yml` define **un único target**, `dev`, y es el de por defecto:
- `path: ../../analytics_poc.duckdb` (destino), `schema: main`, `threads: 1`.
- `extensions: [sqlite]` (se autodescarga la 1ª vez; necesita red una vez).
- `attach: [{path: ../../db.sqlite, type: sqlite, alias: src}]`: así los modelos
  **leen `db.sqlite`**.
- `settings: {TimeZone: UTC, search_path: src.main}`: los modelos leen las tablas de
  `db.sqlite` con **nombres "pelados"** (`FROM planilla`, `FROM dwh_static_airplanes`,
  `select * from dwh_calendar`). Comprobado en este repo: con
  `search_path = 'src.main'`, un nombre pelado resuelve al **SQLite adjunto** incluso
  si existe una tabla local con el mismo nombre (por eso `moves`/los modelos
  `static/` pueden llamarse igual que su tabla de origen).
- dbt-duckdb deriva `database` del nombre del fichero (`analytics_poc`), así que los
  modelos ven `"analytics_poc"."main"."<modelo>"`.
- **Es DuckDB-only**: `purchs_std`, `sales_std` y `moves` usan `EXCLUDE`/`REPLACE`
  del dialecto DuckDB, así que el proyecto **no compila** con el adaptador SQLite.
- **Lock exclusivo**: DuckDB abre `analytics_poc.duckdb` en exclusiva; con DBeaver
  abierto, `dbt run` falla con `IO Error: Could not set lock on file`. Para validar
  sin tocar ese fichero se puede usar un **perfil temporal** en `/tmp` con solo el
  `path` cambiado. Y dentro del **mismo proceso** DuckDB tampoco deja abrir el fichero
  dos veces con configuraciones distintas (`read_only` vs lectura-escritura): es lo que
  pasa con `dbt_run` + `publish_dwh` en el pipeline sin daemon, y lo resuelve
  **`publish_resource.duckdb_connect()`** (reabre con la configuración existente).

## Puesta en marcha / comandos (Linux)
```bash
# 1) entorno
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2) Dagster (DAGSTER_HOME = dagsterhome/ de la raíz; el CLI se lanza DESDE LA RAÍZ, que
#    es donde viven `definitions.py` y `pyproject.toml`)
export DAGSTER_HOME="$PWD/dagsterhome"
python -m dagster dev           # ojo: los scripts de `.venv/bin/` tienen shebang con la
                                # ruta VIEJA del repo; usar `python -m dagster ...`
# materializar un asset concreto desde la CLI (ej.: el estático de partición 2026)
python -m dagster asset materialize -m definitions --select static_data_asset --partition 2026

# CADENA DE CORREO (diaria, sin demonio ni automatización): 1 comando = 1 run con los
# 7 assets del grupo `from_email` en el día pedido (el orden lo dan las deps)
AYER=$(date -d "yesterday" +%F)
python -m dagster asset materialize -m definitions --select "group:from_email" --partition "$AYER"
# carga inicial por rango (el CLI EXIGE single_run() en TODOS los assets seleccionados): el rango
# completo va en UN run con `corpac_data_daily`, los 4 reportes, `calendar_weekly` y
# `sisa_sales_monthly` (cada uno recorre sus particiones con partition_days)
python -m dagster asset materialize -m definitions \
  --select "talma_reports_daily,adp_reports_daily,terpel_tickets_daily,terpel_order_daily,corpac_data_daily" \
  --partition-range "2026-01-01...2026-09-16"
python -m dagster asset materialize -m definitions \
  --select calendar_weekly --partition-range "2026-01-05...2026-09-21"   # claves = lunes
python -m dagster asset materialize -m definitions \
  --select sisa_sales_monthly --partition-range "2026-01-01...2026-09-01"
# `ingest_emails` y `corpac_files_daily` son multi_run(30): su carga inicial va DÍA A DÍA con
# --partition (o con un backfill de la UI/daemon)
python -m dagster asset materialize -m definitions --select corpac_files_daily --partition 2026-08-11

# CADENA SIRE (mensual, sin demonio ni automatización): MES ANTERIOR + MES ACTUAL
# OJO: `sire_details_monthly` y `sire_files_monthly` NO declaran política (= multi_run(1) a
# propósito), así que el CLI NO acepta `--partition-range` con ellos (exige single_run() en
# TODOS los seleccionados). Se lanza UN RUN POR MES con `--partition`:
MES_ANT=$(date -d "-1 month" +%Y-%m-01); MES_ACT=$(date +%Y-%m-01)
python -m dagster asset materialize -m definitions \
  --select "group:from_sire" --partition "$MES_ANT"
python -m dagster asset materialize -m definitions \
  --select "group:from_sire" --partition "$MES_ACT"
# (la alternativa es un backfill de la UI/daemon, que con multi_run(1) crea 1 run por mes)

# REPORTE RH del SEE-SOL (mensual): 1 run = mes anterior + mes actual del asset
python -m dagster asset materialize -m definitions \
  --select seesol_rh_monthly --partition-range "$MES_ANT...$MES_ACT"

# PIPELINE: ya NO existe `scripts/` (eliminado 2026-09-25). Todo va con Dagster, en serie,
# desde la raíz. `run_pipeline.py` y `pipeline_cron.sh` son OBSOLETOS: sus referencias en
# docs/README son históricas. Equivalente actual de cada paso (ver los comandos de arriba):
#   RH -> --select seesol_rh_monthly ; SIRE -> --select "group:from_sire"
#   correo -> --select "group:from_email" --partition <día>
#   dbt + publicación -> --select "dbt_run,publish_dwh"  (las PG* se leen del ENTORNO:
#   exporta `env/.env` antes, p. ej. `set -a; . env/.env; set +a`)

# DBT + PUBLICACIÓN como assets (grupo `dwh`, SIN particiones; el orden lo dan las deps):
# `dbt_run` corre dbt en proceso (dbtRunner) con el CWD en src/dbt; `publish_dwh` es el
# motor de publicación `DwhPublishResource` (lee las credenciales PG del entorno).
python -m dagster asset materialize -m definitions --select dbt_run
python -m dagster asset materialize -m definitions --select "dbt_run,publish_dwh"
# JOBS con nombre (UI / dg launch; `dagster job execute` NO acepta --partition en 1.13):
#   correo_daily_job, sire_monthly_job, rh_monthly_job, sisa_monthly_job,
#   estaticos_job, calendar_weekly_job, dwh_publish_job

# TOKENS de SUNAT/SIRE: los pide el resource de los assets por audiencia (API de
# seguridad y, para `consultacpe`, el portal SOL por HTTP puro) y los cachea en
# `env/sire_tokens.json`. NO hay paso previo en el cron ni scripts de token:
#   - provider: src/assets/sire_assets/resources/token_resource.py
#   - protocolo del portal: src/assets/sire_assets/resources/sol_portal.py
#   - plan B documentado (NO lo usa el pipeline, necesita selenium): docs/sol_token_navegador.py

# 3) dbt (NO hace falta `dbt seed`: hay 0 seeds)
cd src/dbt
dbt run

# 4) publicación a PostgreSQL: TODAS las tablas el DuckDB al esquema
#    `dwh`, con el MISMO nombre (moves -> dwh.moves). `--dry-run` simula,
#    `--only`/`--exclude` acotan, `--schema` cambia el destino y `--recreate`
#    hace DROP+CREATE (cambio de tipos). Credenciales: las del README.
#    (El motor vive en el resource del asset `publish_dwh`, que es también su CLI.)
export PGHOST=... PGPORT=... PGDATABASE=... PGUSER=... PGPASSWORD=...
python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py
python src/assets/dwh_assets/dwh_publish_asset/resources/publish_resource.py --dry-run  # sin escribir
```
> **ORDEN OBLIGATORIO**: primero los **assets** (llenan `db.sqlite`), después
> **`dbt run`** (lee esa BD y materializa `analytics_poc.duckdb`). Los 6 modelos de
> `models/static/` y `calendar` fallan si sus tablas de `db.sqlite` no existen aún.
> El README incluye la variante Windows (PowerShell); el repo se trabaja en Linux.

## Pruebas
- pytest en `src/tests/` (**58 archivos `test_*.py`** + `conftest.py` + `fixtures/`).
  `src/tests/conftest.py` añade la raíz del repo y `src/` al `sys.path` (la raíz está 3
  niveles arriba) y expone la fixture `make_pdf` (PDFs mínimos en memoria).
- Se corre desde la raíz del repo: `pytest`. **Estado 2026-09-23 (tras el reparto de
  `BackfillPolicy`): 521 passed, 0 failed**. *Histórico*: antes de esa sesión eran 509 passed y 3
  failed (`test_planilla_asset` por deriva de datos: `static/Planilla.ods` tiene 2349 filas y el
  test espera 2098; `test_cargar_env_no_pisa_lo_exportado` y `test_pg_params_defaults` por las
  `PG*` ya exportadas en el shell).
- Nombres: `test_<asset>.py`, `test_<asset>_db_resource.py`,
  `test_<asset>_parser.py`, `test_<asset>_pydantic.py`.
- `tests/fixtures/` (corpac, terpel) y `tests/live_smoke.py` (smoke en vivo, no
  unitario).
- **No hay tests de dbt** (no existe `schema.yml` ni carpeta `tests/` en `src/dbt`).

## Variables/secretos de entorno
- `DAGSTER_HOME` → `dagsterhome/` de la raíz.
- `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` (y `PGDWH_SCHEMA`, por defecto `dwh`)
  → PostgreSQL de publicación. **Fuente única: `env/.env`** (gitignored), que
  `scripts/run_pipeline.py` carga al arrancar con `cargar_env()` (lector propio sin
  dependencias: ignora comentarios, admite `export ` y comillas, y **no pisa** lo ya
  exportado). Los nombres `POSTGRES_*` **no** los lee nadie. Si lanzas `publish_dwh`
  desde la UI de Dagster, hay que exportar las `PG*` en el entorno del proceso.
- Credenciales Gmail (service account/OAuth) usadas por `GmailResource`
  (`jorge.paredes@airmajoro.com`, `contabilidad@airmajoro.com`).
- Token SUNAT/SIRE vía `SireTokenResource`
  (`src/assets/sire_assets/resources/token_resource.py`): resuelve por **audiencia** con
  `token(empresa, audience, recurso)` — 1º la **caché de fichero**
  (`env/sire_tokens.json`, dict **audiencia → empresa → token**), 2º la **API de
  seguridad** (OAuth2, `grant_type=password`, usuario RUC+usuario SOL) y 3º, para
  `consultacpe`, el **portal SOL por HTTP puro** (`resources/sol_portal.py`: login de 1
  intento + `action=execute`); valida `exp` (margen) y el claim `aud` (en SUNAT es un
  string con JSON dentro). **No hay token manual**: el campo `token` del JSON de
  credenciales ya no se lee. `fixed_token_resource.py` se eliminó.
- **Plan B documentado del token (`consultacpe`)**: `docs/sol_token_navegador.py`
  (Selenium + firefox + geckodriver; `GECKODRIVER`/`FIREFOX_BIN` o
  `--driver`/`--binario`). **No lo usa el pipeline** y `selenium` está comentado en
  `requirements.txt`.
- `env/` y `.venv/` no se versionan.

## Endpoints externos (referencia rápida)
- **SUNAT API de seguridad (token OAuth2)**:
  `POST https://api-seguridad.sunat.gob.pe/v1/clientessol/{client_id}/oauth2/token/` con
  `application/x-www-form-urlencoded`
  (`grant_type=password`, `scope=https://api-sire.sunat.gob.pe` o el `sire_scope` del JSON,
  `client_id`, `client_secret`, `username`=`{RUC}{USUARIO SOL}`, `password`=clave SOL) →
  `{"access_token","expires_in","token_type"}`. Con `grant_type=client_credentials` responde
  **HTTP 204 sin body** (verificado en vivo el 2026-09-17).
- **SUNAT/SIRE (CPE)**: `https://api-cpe.sunat.gob.pe/v1/contribuyente/consultacpe/comprobantes/{senderruc}-{tipo}-{serie}-{numero}-{rol}`
  con `/01` (PDF) y `/02` (ZIP). Header `authorization: Bearer <token>`,
  `User-Agent: Mozilla`.
- **SUNAT menú SOL (`action=execute`)**: con la sesión del portal,
  `POST https://e-menu.sunat.gob.pe/cl-ti-itmenu/MenuInternet.htm` con `{action:'prevApp'}` y
  `GET .../MenuInternet.htm?action=execute&code=11.38.1.1.1` (la app `11.38.1.1.1` = "Nueva
  Consulta de comprobantes de pago") → **302** a
  `https://e-factura.sunat.gob.pe/app/contribuyentems/servicio/consultacpe/consulta/loader/nuevaconsulta.html?token=<JWT>`.
  **El intercambio OAuth2 lo hace el servidor**: el JWT llega en el `Location` y no hay que
  canjear ningún `code` a mano.
- **SUNAT SEE-SOL (recibos por honorarios, app `11.5.1.1.14` = "Consulta Receptor")**: el mismo
  `prevApp` + `GET .../MenuInternet.htm?action=execute&code=11.5.1.1.14` responde **302** a
  `https://ww1.sunat.gob.pe/ol-ti-itreciboelectronico/cpelec001Alias?accion=LlamaCriterioConsulatRec1…`.
  Dentro de esa app: `POST https://ww1.sunat.gob.pe/ol-ti-itreciboelectronico/cpelec001Alias` con
  `accion=CapturaCriterioConsulatRec1` (+ `fec_desde`/`fec_hasta` dd/mm/YYYY, ≤ 1 mes,
  `tipocomprobante="01;02;03;"`, `tipoestado=00`) devuelve los resultados, y otro POST con
  `accion=descargaConsultaReceptor` devuelve **`text/plain`** (`Content-Disposition:
  attachment; filename="archivo.txt"`) con el reporte de 16 columnas `|`. Lo pide
  `assets/seesol_rh_asset/resources/api_resource/rh_resource.py` (el asset
  `seesol_rh_monthly`).
- **SISA**: `http://38.187.7.111:5500/query`, POST con
  `{"sql": "EXECUTE [dbo].[USP_UVW_LIQUIDACION_CONTA] @CODORGDOREF='01', ..."}`.
- **CORPAC**: portal Mercurio de CORPAC (POST que devuelve el ZIP de facturas).
- **Gmail**: API de Google. **Tipo de cambio**: resource propio en
  `assets/calendar_asset/resources/api_resource/`.
