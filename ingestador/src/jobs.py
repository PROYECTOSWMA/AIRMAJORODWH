
import warnings

from dagster import AssetSelection, define_asset_job

# La cadena de correo tiene políticas de backfill mixtas **a propósito**: `ingest_emails` y
# `corpac_files_daily` con `BackfillPolicy.multi_run(max_partitions_per_run=30)` (el cron pide 1
# día por run; en un backfill del rango van en runs de hasta 30 días y su función los recorre día
# a día con `partition_days`), y `corpac_data_daily` + los 4 reportes con
# `BackfillPolicy.single_run()` (un único run para todo el rango, que su función recorre día a
# día). Dagster lo acepta y **se queda con la política mínima** (`multi_run(30)` = hasta 30
# particiones por run), que es lo que quiere un backfill del job; el cron diario sigue
# materializando 1 día por run (`--partition`), que no depende de la política. El aviso que emite
# al resolver el job es ruido fijo en cada comando, así que se silencia **solo ese mensaje** (el
# comportamiento lo fija `src/tests/test_jobs.py`).
warnings.filterwarnings(
    "ignore",
    message="Asset job correo_daily_job materializes assets with varying BackfillPolicies",
)

# Cadena de correo: los 7 assets diarios (1 día por run; el cron pide varios días).
correo_daily_job = define_asset_job(
    name="correo_daily_job",
    selection=AssetSelection.groups("from_email"),
    description="Los 7 assets de la cadena de correo (partición diaria).",
)

# SIRE: los 6 assets son mensuales (el cron pide mes anterior + mes actual). Ojo con las
# políticas: `sire_proposal_monthly` y los 3 `*_cost_centers_monthly` usan
# `BackfillPolicy.single_run()`, pero `sire_details_monthly` y `sire_files_monthly` NO declaran
# política **a propósito** (= `multi_run(1)`: 1 run por mes). Por eso el job resuelve
# `multi_run(1)` y el mes anterior + el actual se lanzan con 2 `--partition` (o con un backfill de
# la UI/daemon): `dagster asset materialize --partition-range` exige `single_run()` en TODOS los
# assets seleccionados y rechaza el rango si estos 2 entran en la selección.
sire_monthly_job = define_asset_job(
    name="sire_monthly_job",
    selection=AssetSelection.groups("from_sire"),
    description="Los 6 assets de SIRE (partición mensual; details/files sin política = 1 run/mes).",
)

# Reporte RH del SEE-SOL: asset independiente (mensual, single_run).
rh_monthly_job = define_asset_job(
    name="rh_monthly_job",
    selection=AssetSelection.assets("seesol_rh_monthly"),
    description="Reporte RH del SEE-SOL (partición mensual, single_run).",
)

# SISA: liquidaciones de ventas (partición mensual propia).
sisa_monthly_job = define_asset_job(
    name="sisa_monthly_job",
    selection=AssetSelection.assets("sisa_sales_monthly"),
    description="Liquidaciones de SISA (partición mensual).",
)

# Reporte de estadísticas de vuelos de SISA (partición mensual propia, single_run).
flight_reports_monthly_job = define_asset_job(
    name="flight_reports_monthly_job",
    selection=AssetSelection.assets("flight_reports_asset"),
    description="Reporte de estadísticas de vuelos de SISA (partición mensual).",
)

# Estáticos: snapshots + CSV de `static/` (sin particiones ni `period`: cada run deja la
# foto vigente de los archivos).
estaticos_job = define_asset_job(
    name="estaticos_job",
    selection=AssetSelection.assets("static_data_asset"),
    description="Snapshots y CSV de `static/` (sin particiones ni period).",
)

# Tipo de cambio (partición semanal, semana en curso incluida).
calendar_weekly_job = define_asset_job(
    name="calendar_weekly_job",
    selection=AssetSelection.assets("calendar_weekly"),
    description="Tipo de cambio SUNAT de la semana (partición semanal).",
)

# Capa analítica + publicación: los 2 assets SIN particiones. El orden lo dan las deps
# (`publish_dwh` depende de `dbt_run`).
dwh_publish_job = define_asset_job(
    name="dwh_publish_job",
    selection=AssetSelection.assets("dbt_run", "publish_dwh"),
    description="`dbt run` + publicación al schema `dwh` de PostgreSQL (sin particiones).",
)

JOBS = [
    correo_daily_job,
    sire_monthly_job,
    rh_monthly_job,
    sisa_monthly_job,
    flight_reports_monthly_job,
    estaticos_job,
    calendar_weekly_job,
    dwh_publish_job,
]
