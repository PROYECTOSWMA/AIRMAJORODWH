# ⚠️ HALLAZGOS DE TRASPASO — Propagación Dagster / SIRE (sesión 2026-09-16)

> **Ruta real del repo (2026-09-17): `/home/josemi/Desktop/ADCOR_PROJECTS/REPOAIMNUEVO`.**
> El repo se movió desde `/home/josemi/Desktop/REPOAIMNUEVO`; por eso la sesión perdió el acceso
> a todo (ENOENT) y este archivo se escribió primero en `/tmp` y luego se copió aquí.
> Las rutas `src/…` y `memory-bank/…` de este documento son relativas a ese repo.


> Escrito en `/tmp` porque **el repo dejó de ser accesible** a mitad de sesión: la terminal
> murió y `read_files`/`search_codebase` daban `ENOENT` para todo lo de
> `/home/josemi/Desktop/REPOAIMNUEVO` (incluido `README.md`, `memory-bank/activeContext.md`,
> `src/definitions.py`, `.git/HEAD`). El editor solo pudo **crear** archivos nuevos (el repo
> no está en esa ruta). **Copiar este archivo al `memory-bank/` del repo real y añadir un
> puntero al principio de `memory-bank/activeContext.md`.** Todo lo de abajo se obtuvo
> **ANTES** del corte con datos reales (no es teoría).

## 1. Resumen

Pregunta del usuario: *"¿conviene pasar `sire_proposals` a particiones diarias para ser coherente
con sus downstream diarios?"* (otro asistente se lo recomendó).
**Respuesta verificada: NO.** El grafo ya es coherente vía `TimeWindowPartitionMapping`
(sección 2). Lo que está roto es la **propagación por identidad de filas**: upsert del padre que
borra+inserta con **ids nuevos**, saneo de huérfanos **acotado al día** y dbt que enlaza por
**id sustituto**. Medido en `db.sqlite`: **5.370 filas huérfanas** (sección 4).

## 2. Evidencia A — el mapping día↔mes ya funciona (dagster 1.13.21)

```
DIA -> MES:  2026-09-16 -> ['2026-09-01']   2026-08-31 -> ['2026-08-01']   2026-09-01 -> ['2026-09-01']
MES -> DIAS: 2026-02-01 -> 28 dias   2026-08-01 -> 31 dias   2026-09-01 -> 16 (existentes)   jul+ago -> 62
```
Docstring instalado (`…/partitions/mapping/time_window.py:50-53`): *"If the upstream time period is
coarser than the downstream time period, then each partition in the downstream asset will map to a
single (larger) upstream partition."*

## 3. Evidencia B — propagación automática (simulada con `evaluate_automation_conditions`)

```
SIM 1: padre(mensual, eager) + hijo(diario, eager)
  [dia 15] 1er tick ......... proposal=[]             details=[]             <- línea base
  -> materializo la partición MENSUAL 2026-09-01
  [dia 15] tras el mes ...... proposal=[]             details=['2026-09-15']  <- el hijo se dispara SOLO
  -> materializo la partición DIARIA 2026-09-15
  [dia 16 (DÍA NUEVO)] ...... proposal=[]             details=['2026-09-16']  <- día nuevo, SOLO
  [dia 16] 2do tick ......... proposal=[]             details=[]             <- no duplica
SIM 2: rectificatoria (re-materializo el MES) -> details=['2026-09-16']        <- re-corre el día en curso
SIM 3: padre con on_cron('0 6 * * *') -> [dia 16] proposal=['2026-09-01'] details=['2026-09-16']
SIM 4: on_cron + in_latest_time_window(62d) -> proposal=['2026-08-01','2026-09-01'] details=['2026-09-16']
```
Reglas verificadas: `eager()`/`on_cron()` incluyen `in_latest_time_window()` ⇒ **solo la última
partición temporal** (los meses pasados necesitan **backfill** con el mapping mes→días).
`lookback_delta` filtra por **inicio de partición**: `45d` NO alcanza al mes anterior, `62d`/`90d` sí.
**El primer tick es línea base** (no pide nada). En `src/` había **0** `automation_condition`,
`AutoMaterializePolicy`, `ScheduleDefinition`, `@sensor`, `define_asset_job`, `backfill_policy`, `pool=`
⇒ hoy **nada se propaga solo**. El `default_automation_condition_sensor` se crea automáticamente si
algún asset declara condición (`_core/definitions/utils.py:389-417`); requiere el **daemon**.

## 4. Evidencia C — 5.370 huérfanos AHORA en `db.sqlite`

| tabla | filas | **huérfanas** | rango |
|---|---|---|---|
| `sire_sales_details` | 21.702 | **1.299** | 2026-08-01 .. 2026-08-11 |
| `sire_purchs_details` | 24.754 | **1.077** | 2026-08-01 .. 2026-08-11 |
| `sire_sales_files` | 33.922 | **1.890** | 2026-08-01 .. 2026-08-11 |
| `sire_purchs_files` | 27.541 | **1.104** | 2026-08-01 .. 2026-08-11 |

## 5. Causa raíz

1. `_replace` = **delete + insert** ⇒ cambian **todos** los ids del mes:
   `src/assets/_common/abstract_resource.py:90-119` +
   `src/assets/sire_assets/sire_proposal_asset/resources/db_resource.py:23-42`.
2. Saneo **por día**: `period = context.partition_key` (el día) en
   `…/sire_details_asset/sire_details_asset.py:120,154` y `…/sire_files_asset/sire_files_asset.py:157,192`.
3. dbt enlaza por id: `sire_sales_std.sql:42-43` / `sire_purchs_std.sql:42-43`
   (`LEFT JOIN sire_sales_details d ON d.sire_sale_id = s.id`); y `src/dbt/macros/removedups.sql`
   conserva `MIN(id)` por `car_sunat`.

Lectura: se re-materializó la propuesta de **agosto** y no se re-corrieron los días 1–11.

## 6. Impacto en `moves`

Esos hijos son **invisibles para dbt** (LEFT JOIN ⇒ `d.*` NULL): se pierden `serv_desc`, `qnt_type`,
`qnt`, y `amnt_taxable`/`amnt_taxes` caen al valor del padre (`prefer_null('d.id', …)` en
`sire_sales_std.sql:20-26` / `sire_purchs_std.sql:16-21`). `serv_desc` NULL degrada el **centro de
costo** (`cost_center_from_serv_desc`) y la **cuenta** (`static_aux_accounts_assignment`).
⇒ 11 días de agosto degradados en `moves`.

## 7. NO hacer

> **DECISIÓN FINAL (sesión 2026-09-17) — esto quedó SUPERADO.** No se parcheó el
> `upsert_proposal`: se eliminó el upsert. La rama SIRE es ahora **mensual** (clave = día 1,
> `end_offset=1`), con `single_run()` en los 6 assets, grupo `from_sire`, deps identidad y
> **append-only** (`insert_proposal_new` = `_existing_keys` + `_insert_new` con clave natural
> estable; `delete_orphan_*` fuera del flujo). El cron (`scripts/pipeline_cron.sh`) materializa
> **mes anterior + mes actual** en un solo run: al ser idempotente y pedir solo lo que falta,
> re-pasar los dos meses cada día es barato y recoge los comprobantes que entran tarde. Detalle
> en `memory-bank/activeContext.md` (§ SIRE), `progress.md` (371 passed) y
> `systemPatterns.md` (§ Patrones transversales).
>
> Lo de abajo se conserva como registro del análisis previo a esa decisión.

No pasar `sire_proposal` a particiones diarias: el origen es un **libro por periodo**
(`per_tributario=yyyymm`); 30 particiones escribirían **las mismas filas** del mes (upsert por
`(period, empresa)`, `sire_proposal_asset.py:34-37,54`) ⇒ `LastMaterialization` miente y un backfill
de 1 día reescribe el mes entero; **no arregla** los huérfanos y los empeora (30 eventos de
invalidación/mes en vez de 1). El coste de API (4 flujos de ticket; `TICKET_POLL_SECONDS=10`,
retry 3×30 s) se paga igual porque el libro crece a diario.

## 8. Plan (1 y 2 arreglan DATOS)

1. **Upsert del padre con identidad estable**: en `SireSqliteResource.upsert_proposal` pasar a
   `insert(...).on_conflict(conflict_target=[period, empresa, tipo_cp_doc, serie_del_cdp,
   nro_cp_o_doc_nro_inicial_rango], update={...})` + borrar del mes solo lo que ya no venga
   (+ índice único de esa clave natural). Modelo a imitar: la cadena de correo (append-only con ids
   estables, `_insert_new` en `abstract_resource.py:146-179`).
2. **Sanear los 5.370 huérfanos**: re-materializar `2026-08-01..2026-08-11` de `sire_details_daily` y
   `sire_files_daily` (o re-materializar agosto con ids estables + backfill de esos días).
3. **Automatización**: `sire_proposal_monthly` con `on_cron("0 6 * * *")`
   (o `in_latest_time_window(timedelta(days=62)) & cron_tick_passed("0 6 * * *").since_last_handled()`
   para incluir el mes anterior); `eager()` en `sire_details_daily`, `sire_files_daily` y los
   `*_cost_centers_monthly` (mantener su `allow_nonexistent_upstream_partitions=True`).
4. **Rectificatorias de meses cerrados = backfill** (mapping mes→días). Nada de tocar particiones.
5. **Protecciones**: `pool`/límite de concurrencia para no pegarle a `db.sqlite` (19 GB, un escritor)
   con varios runs (`dagsterhome/dagster.yaml`: `run_queue.max_concurrent_runs: 12`) + `@asset_check`
   "el mes tiene propuesta" (evitar días verdes vacíos).
6. *(Opcional)* que dbt no dependa del id sustituto (clave natural del comprobante); más caro por
   `removedups` (`MIN(id)` por `car_sunat`).

## 9. TAREA PEDIDA POR EL USUARIO Y AÚN PENDIENTE (empezar aquí)

> *"en los emails son de partición diaria creo que todos sus downstreams y los que siguen.
> ¿Podemos empezar viendo que eso funcione bien?"*

**La cadena de correo NO es toda diaria** (mapa leído del código antes del corte):

| asset | partición | deps |
|---|---|---|
| `ingest_emails` (`assets/mail_asset/mail_asset.py`) | **daily** `start_date="2026-01-01"` | — (Gmail) |
| `corpac_files_daily` | **daily** | `AssetDep(ingest_emails, TimeWindowPartitionMapping())` |
| `corpac_data_daily` | **daily** | `AssetDep(corpac_files_daily, TimeWindowPartitionMapping())` |
| `talma_reports_monthly` / `adp_reports_monthly` | **monthly** | `deps=[…]` ← **por revisar** |
| `terpel_tickets_monthly` / `terpel_order_monthly` | **monthly** | `deps=[…]` ← **por revisar** |
| `sisa_sales_monthly` | monthly | — |
| `calendar_weekly` | **weekly** | — |
| `static_data_asset` | `StaticPartitionsDefinition(["2026"])` | — |

Checklist:
1. **Dirección del mapping**: los `*_monthly` de correo dependen de un padre **diario**
   (fino→grueso). Para el mes en curso el mapping incluye días que **aún no existen**: verificar que
   declaran `allow_nonexistent_upstream_partitions=True` (como los cost centers). Si no, puede fallar.
2. **Ids estables**: `ingest_emails` es append-only (`_insert_new`, ids de Gmail) ⇒ el patrón de
   huérfanos de SIRE **no debería** darse. Confirmarlo midiendo:
   ```sql
   SELECT count(*) FROM from_email_corpac_files f LEFT JOIN emails e ON e.id = f.id_email WHERE e.id IS NULL;
   -- ídem email_attachments / from_email_talma_reports / from_email_adp_reports / from_email_terpel_*
   ```
   (comprobar el nombre real de las columnas FK en `assets/mail_asset/models/` y en cada
   `from_email_assets/*/models/model.py`).
3. **Ventanas por día**: cómo selecciona cada asset diario el correo de su partición (fecha del correo
   vs `ingested_at`), off-by-one y **zona horaria** (Dagster particiona en **UTC**).
4. **Cobertura**: contar correos/adjuntos **por día** y buscar huecos o días con pdf/zip incompletos.
5. **Simular `eager()`** en esta cadena con el tester (sección 10) — recordar: `eager` solo mira la
   última partición.
6. **No romper**: `tests/test_mail_db_resource.py`, `test_corpac_*`, `test_terpel_*`, `test_talma_*`,
   `test_adp_*`; `pytest` daba **337 passed**.

## 10. Comandos de reproducción (copiar/pegar)

**(a) Mapping día↔mes / mes↔días** — ojo con el **orden** de
`get_downstream_partitions_for_partitions(subset, upstream_def, downstream_def, current_time=…)`
(invertirlo da resultados falsos):
```bash
cd <REPO> && .venv/bin/python - <<'EOF'
from datetime import datetime, timezone
from dagster import DailyPartitionsDefinition, MonthlyPartitionsDefinition, TimeWindowPartitionMapping
now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
monthly = MonthlyPartitionsDefinition(start_date="2026-01-01", end_offset=1)
daily = DailyPartitionsDefinition(start_date="2026-01-01", end_offset=1)
up = TimeWindowPartitionMapping()                                              # details/files
down = TimeWindowPartitionMapping(allow_nonexistent_upstream_partitions=True)  # cost_centers
s = daily.subset_with_partition_keys(["2026-09-16"])
print("dia->mes:", up.get_upstream_mapped_partitions_result_for_partitions(
    s, daily, monthly, current_time=now).partitions_subset.get_partition_keys())
s = monthly.subset_with_partition_keys(["2026-08-01"])
print("mes->dias:", len(down.get_downstream_partitions_for_partitions(
    s, monthly, daily, current_time=now).get_partition_keys()))
EOF
```

**(b) Simular propagación con `AutomationCondition`** (no toca el repo; instancia efímera):
```bash
cd <REPO> && .venv/bin/python - <<'EOF'
import datetime as dt, dagster as dg
from dagster import AssetDep, AssetKey, AutomationCondition, DailyPartitionsDefinition, \
                   MonthlyPartitionsDefinition, TimeWindowPartitionMapping, asset
monthly = MonthlyPartitionsDefinition(start_date="2026-01-01", end_offset=1)
daily = DailyPartitionsDefinition(start_date="2026-01-01", end_offset=1)

@asset(name="padre", partitions_def=monthly, automation_condition=AutomationCondition.on_cron("0 6 * * *"))
def padre(): pass

@asset(name="hijo", partitions_def=daily,
       deps=[AssetDep(padre, partition_mapping=TimeWindowPartitionMapping())],
       automation_condition=AutomationCondition.eager())
def hijo(): pass

inst = dg.DagsterInstance.ephemeral()
def tick(when, cursor=None, label=""):
    r = dg.evaluate_automation_conditions(defs=[padre, hijo], instance=inst, evaluation_time=when, cursor=cursor)
    print(f'[{label}] padre={sorted(r.get_requested_partitions(AssetKey("padre")))} '
          f'hijo={sorted(r.get_requested_partitions(AssetKey("hijo")))}')
    return r
T = lambda h, d: dt.datetime(2026, 9, d, h, tzinfo=dt.timezone.utc)
a = tick(T(12, 15), label="dia 15 baseline")
dg.materialize([padre], instance=inst, partition_key="2026-09-01")
b = tick(T(13, 15), cursor=a.cursor, label="dia 15 tras el mes")
dg.materialize([hijo], instance=inst, partition_key="2026-09-15")
tick(T(12, 16), cursor=b.cursor, label="dia 16 DIA NUEVO")
EOF
```

**(c) Huérfanos en `db.sqlite`** (solo lectura, ~1 min; `python3` del sistema basta):
```bash
cd <REPO> && python3 -c "
import sqlite3
con = sqlite3.connect('file:db.sqlite?mode=ro', uri=True, timeout=120)
con.execute('PRAGMA query_only=1')
q = '''select 'sales_det', count(*), sum(case when s.id is null then 1 else 0 end), min(case when s.id is null then d.period end), max(case when s.id is null then d.period end) from sire_sales_details d left join sire_sales s on s.id=d.sire_sale_id
union all select 'purchs_det', count(*), sum(case when p.id is null then 1 else 0 end), min(case when p.id is null then d.period end), max(case when p.id is null then d.period end) from sire_purchs_details d left join sire_purchs p on p.id=d.sire_purch_id
union all select 'sales_files', count(*), sum(case when s.id is null then 1 else 0 end), min(case when s.id is null then f.period end), max(case when s.id is null then f.period end) from sire_sales_files f left join sire_sales s on s.id=f.sire_sale_id
union all select 'purchs_files', count(*), sum(case when p.id is null then 1 else 0 end), min(case when p.id is null then f.period end), max(case when p.id is null then f.period end) from sire_purchs_files f left join sire_purchs p on p.id=f.sire_purch_id'''
for r in con.execute(q):
    print('%-13s filas=%-7s huerfanos=%-6s rango=%s..%s' % r)
con.close()
"
```
(Salida de la corrida original: `/tmp/orphans.txt`.)

## 11. Caveats — qué NO se verificó

- **No se ejecutaron los assets reales ni `dbt run`**: solo `evaluate_automation_conditions` con
  instancias efímeras y consultas de solo lectura. Si se corre `dbt run`, cerrar DBeaver antes
  (DuckDB abre `analytics_poc.duckdb` con lock exclusivo).
- Ticks **simulados**, no webserver/daemon real; el **primer tick es línea base** (~60 s en prod).
- No se midió coste/duración real de las corridas ni concurrencia sobre SQLite.
- El fix de ids exige **decidir la clave natural** (SUNAT repite documentos entre periodos;
  `removedups` lo mitiga por `car_sunat`).
- El saneo de agosto implica **re-descargar** detalles + PDF/ZIP de 11 días contra SUNAT.
- La **cadena de correo quedó sin auditar** (sección 9): su mapa se leyó del código, no se verificó.

## 12. Estado del entorno al cerrar la sesión

- La terminal del agente murió (`The terminal's shell process has exited`) y `read_files` /
  `search_codebase` devolvieron **ENOENT/abort** para **todo** lo de
  `/home/josemi/Desktop/REPOAIMNUEVO`. `/tmp` sí respondía.
- El **editor pudo crear** archivos nuevos en `/home/josemi/Desktop/REPOAIMNUEVO/memory-bank/` pero
  **no editar los existentes** (`activeContext.md` ⇒ ENOENT) ⇒ el repo **no está** en esa ruta
  (probablemente se movió/renombró o el montaje cambió) y esos archivos nuevos quedaron en un árbol
  huérfano. **Este archivo de `/tmp` es la copia fiable.**
- Próxima tarea: `pwd; ls -la; git status`; localizar el repo real; copiar este archivo a
  `memory-bank/HANDOFF-propagacion-dagster-SIRE.md` y poner un puntero al inicio de
  `memory-bank/activeContext.md`; luego seguir con la sección 9 (cadena de correo) o con el
  arreglo de datos de la sección 8.1/8.2.


