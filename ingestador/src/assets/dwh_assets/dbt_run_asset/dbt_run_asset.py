
from typing import Any

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets.calendar_asset.calendar_asset import calendar_weekly
from assets.dwh_assets.dbt_run_asset.resources.dbt_resource import DbtResource
from assets.from_email_assets.adp_reports_asset.adp_reports_asset import (
    adp_reports_daily,
)
from assets.from_email_assets.cep_docs_asset.cep_docs_asset import cep_docs_daily
from assets.from_email_assets.corpac_assets.corpac_data_asset.corpac_data_asset import (
    corpac_data_daily,
)
from assets.from_email_assets.talma_reports_asset.talma_reports_asset import (
    talma_reports_daily,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.terpel_invoicem_asset import (
    terpel_invoicem_daily,
)
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.terpel_tickets_asset import (
    terpel_tickets_daily,
)
from assets.from_sire_files_assets.cep_cost_centers_asset.cep_cost_centers_asset import (
    cep_cost_centers_monthly,
)
from assets.from_sire_files_assets.icaro_cost_centers_asset.icaro_cost_centers_asset import (
    icaro_cost_centers_monthly,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.petroperu_cost_centers_asset import (
    petroperu_cost_centers_monthly,
)
from assets.seesol_rh_asset.seesol_rh_asset import seesol_rh_monthly
from assets.sire_assets.sire_details_asset.sire_details_asset import (
    sire_details_monthly,
)
from assets.sire_assets.sire_proposal_asset.sire_proposal_asset import (
    sire_proposal_monthly,
)
from assets.sisa_sales_asset.sisa_sales_asset import sisa_sales_monthly
from assets.from_sql_majoro_assets.flight_reports_asset.flight_reports_asset import (
    flight_reports_asset,
)
from assets.static_data_asset.static_data_asset import static_data_asset


FUENTES_DBT = [
    corpac_data_daily,
    cep_docs_daily,
    sire_proposal_monthly,
    sire_details_monthly,
    sisa_sales_monthly,
    flight_reports_asset,
    terpel_tickets_daily,
    terpel_invoicem_daily,
    adp_reports_daily,
    talma_reports_daily,
    cep_cost_centers_monthly,
    icaro_cost_centers_monthly,
    petroperu_cost_centers_monthly,
    static_data_asset,
    calendar_weekly,
    seesol_rh_monthly,
]


@asset(
    name="dbt_run",
    group_name="dwh",
    deps=FUENTES_DBT,
    description=(
        "Materializa `analytics_poc.duckdb` (`dbt run`, target `dev`) leyendo `db.sqlite`. "
        "Sin particiones: dbt rehace todas las tablas en cada corrida."
    ),
)
def dbt_run(context: AssetExecutionContext, dbt: DbtResource) -> MaterializeResult:
    """Ejecuta ``dbt run`` sobre ``src/dbt`` y deja el resumen en la metadata."""
    resumen: dict[str, Any] = dbt.run()
    context.log.info(
        "dbt run OK: %d modelos en %.2fs (estados: %s) [%s]",
        resumen["models_run"],
        resumen["elapsed_seconds"],
        resumen["statuses"],
        " ".join(resumen["args"]),
    )
    return MaterializeResult(
        metadata={
            "dbt_project_dir": dbt.project_dir,
            "dbt_target": dbt.target,
            "models_run": resumen["models_run"],
            "statuses": MetadataValue.json(resumen["statuses"]),
            "elapsed_seconds": resumen["elapsed_seconds"],
            "dbt_args": " ".join(resumen["args"]),
        }
    )
