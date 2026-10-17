import os
import sys


def _nul_stream():
    return os.fdopen(os.open(os.devnull, os.O_WRONLY), "w", encoding="utf8", buffering=1)


if os.name == "nt":
    # Windows: sys.stdout/stderr pueden tener un handle de OS inválido (WinError 6)
    # cuando dagster dev corre sin consola y los compute-logs intentan flush().
    # Los reemplazamos por un fd válido (NUL). El output de las ops igual queda en
    # los compute-logs (dagster redirige a archivo durante la captura).
    sys.stdout = _nul_stream()
    sys.stderr = _nul_stream()

# El entry point `definitions.py` vive en la RAÍZ del repo, pero el paquete `assets/` y
# `jobs.py` viven en `src/`: se añade `src/` al sys.path para que `import assets...` /
# `import jobs` funcione sin depender del CWD ni de quién cargue el módulo (dagster dev,
# `-m definitions`, pytest o `scripts/`).
_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from dagster import Definitions

from assets.from_email_assets.corpac_assets.corpac_data_asset.corpac_data_asset import (
    corpac_data_daily,
)
from assets.from_email_assets.corpac_assets.corpac_data_asset.resources.db_resource import (
    CorpacDataSqliteResource,
)
from assets.from_email_assets.corpac_assets.corpac_files_asset.corpac_files_asset import (
    corpac_files_daily,
)
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.api_resource import CorpacResource
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.db_resource import CorpacSqliteResource
from assets.mail_asset.mail_asset import ingest_emails
from assets.mail_asset.resources.api_resource import GmailResource
from assets.mail_asset.resources.db_resource import DbResource
from assets.sire_assets.resources.token_resource import SireTokenResource
from assets.sire_assets.sire_details_asset.resources.api_resource.details_resource import (
    CpeDetailsResource,
)
from assets.sire_assets.sire_details_asset.resources.db_resource import (
    SireDetailsSqliteResource,
)
from assets.sire_assets.sire_details_asset.sire_details_asset import (
    sire_details_monthly,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.files_resource import (
    CpeFilesResource,
)
from assets.sire_assets.sire_files_asset.resources.db_resource import (
    SireFilesSqliteResource,
)
from assets.sire_assets.sire_files_asset.sire_files_asset import (
    sire_files_monthly,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.proposal_resource import (
    ProposalResource,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.ticket_resource import (
    TicketResource,
)
from assets.sire_assets.sire_proposal_asset.resources.db_resource import SireSqliteResource
from assets.sire_assets.sire_proposal_asset.sire_proposal_asset import (
    sire_proposal_monthly,
)
from assets.seesol_rh_asset.resources.api_resource import RhResource
from assets.seesol_rh_asset.resources.db_resource import SeesolRhSqliteResource
from assets.seesol_rh_asset.seesol_rh_asset import seesol_rh_monthly
from assets.from_sire_files_assets.cep_cost_centers_asset.cep_cost_centers_asset import (
    cep_cost_centers_monthly,
)
from assets.from_sire_files_assets.cep_cost_centers_asset.resources.db_resource import (
    CepCostCenterSqliteResource,
)
from assets.from_sire_files_assets.icaro_cost_centers_asset.icaro_cost_centers_asset import (
    icaro_cost_centers_monthly,
)
from assets.from_sire_files_assets.icaro_cost_centers_asset.resources.db_resource import (
    IcaroCostCenterSqliteResource,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.petroperu_cost_centers_asset import (
    petroperu_cost_centers_monthly,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.resources.db_resource import (
    PetroperuCostCenterSqliteResource,
)
from assets.sisa_sales_asset.resources.api_resource.sisa_sales_resource import (
    SisaSalesResource,
)
from assets.sisa_sales_asset.resources.db_resource import SisaSalesSqliteResource
from assets.sisa_sales_asset.sisa_sales_asset import sisa_sales_monthly
from assets.from_sql_majoro_assets.flight_reports_asset.flight_reports_asset import (
    flight_reports_asset,
)
from assets.from_sql_majoro_assets.flight_reports_asset.resources.api_resource.flight_reports_resource import (
    FlightReportsResource,
)
from assets.from_sql_majoro_assets.flight_reports_asset.resources.db_resource import (
    FlightReportsSqliteResource,
)
from assets.calendar_asset.calendar_asset import calendar_weekly
from assets.calendar_asset.resources.api_resource.calendar_resource import (
    CalendarApiResource,
)
from assets.calendar_asset.resources.db_resource import CalendarSqliteResource
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.resources.db_resource import (
    TerpelInvoicemSqliteResource,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.terpel_invoicem_asset import (
    terpel_invoicem_daily,
)
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.resources.db_resource import (
    TerpelSqliteResource,
)
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.terpel_tickets_asset import (
    terpel_tickets_daily,
)
from assets.from_email_assets.adp_reports_asset.adp_reports_asset import (
    adp_reports_daily,
)
from assets.from_email_assets.adp_reports_asset.resources.db_resource import (
    AdpReportSqliteResource,
)
from assets.from_email_assets.talma_reports_asset.talma_reports_asset import (
    talma_reports_daily,
)
from assets.from_email_assets.talma_reports_asset.resources.db_resource import (
    TalmaReportSqliteResource,
)
from assets.from_email_assets.cep_docs_asset.cep_docs_asset import cep_docs_daily
from assets.from_email_assets.cep_docs_asset.resources.db_resource import (
    CepDocsSqliteResource,
)
from assets.static_data_asset.resources.db_resource import (
    StaticDataSqliteResource,
)
from assets.static_data_asset.static_data_asset import (
    static_data_asset,
)
from assets.dwh_assets.dbt_run_asset.dbt_run_asset import dbt_run
from assets.dwh_assets.dbt_run_asset.resources.dbt_resource import DbtResource
from assets.dwh_assets.dwh_publish_asset.dwh_publish_asset import publish_dwh
from assets.dwh_assets.dwh_publish_asset.resources.publish_resource import (
    DwhPublishResource,
)
from jobs import JOBS

_sire_token = SireTokenResource()
_sire_ticket = TicketResource(token_resource=_sire_token)
_sire_proposal = ProposalResource(
    ticket_resource=_sire_ticket, token_resource=_sire_token
)
_sire_details = CpeDetailsResource(token_resource=_sire_token)
_sire_files = CpeFilesResource(token_resource=_sire_token)

defs = Definitions(
    assets=[
        ingest_emails,
        corpac_files_daily,
        corpac_data_daily,
        sire_proposal_monthly,
        sire_details_monthly,
        sire_files_monthly,
        sisa_sales_monthly,
        flight_reports_asset,
        terpel_tickets_daily,
        terpel_invoicem_daily,
        adp_reports_daily,
        talma_reports_daily,
        cep_docs_daily,
        cep_cost_centers_monthly,
        icaro_cost_centers_monthly,
        petroperu_cost_centers_monthly,
        static_data_asset,
        calendar_weekly,
        seesol_rh_monthly,
        # Capa analítica y publicación (sin particiones; `publish_dwh` depende de `dbt_run`).
        dbt_run,
        publish_dwh,
    ],
    jobs=JOBS,
    resources={
        "gmail": GmailResource(
            accounts=[
                "jorge.paredes@airmajoro.com",
                "contabilidad@airmajoro.com",
            ]
        ),
        "db": DbResource(),
        "corpac": CorpacResource(),
        "corpac_db": CorpacSqliteResource(),
        "corpac_data_db": CorpacDataSqliteResource(),
        "sire_token": _sire_token,
        "sire_ticket": _sire_ticket,
        "sire_proposal": _sire_proposal,
        "sire_db": SireSqliteResource(),
        "sire_details": _sire_details,
        "sire_details_db": SireDetailsSqliteResource(),
        "sire_files": _sire_files,
        "sire_files_db": SireFilesSqliteResource(),
        "sisa_sales": SisaSalesResource(),
        "sisa_sales_db": SisaSalesSqliteResource(),
        "flight_reports": FlightReportsResource(),
        "flight_reports_db": FlightReportsSqliteResource(),
        "terpel_db": TerpelSqliteResource(),
        "terpel_invoicem_db": TerpelInvoicemSqliteResource(),
        "adp_reports_db": AdpReportSqliteResource(),
        "talma_reports_db": TalmaReportSqliteResource(),
        "cep_docs_db": CepDocsSqliteResource(),
        "cep_cost_centers_db": CepCostCenterSqliteResource(),
        "icaro_cost_centers_db": IcaroCostCenterSqliteResource(),
        "petroperu_cost_centers_db": PetroperuCostCenterSqliteResource(),
        "rh": RhResource(),
        "seesol_rh_db": SeesolRhSqliteResource(),
        "static_data_db": StaticDataSqliteResource(),
        "calendar_api": CalendarApiResource(),
        "calendar_db": CalendarSqliteResource(),
        "dbt": DbtResource(),
        "dwh_publish": DwhPublishResource(),
    },
)
