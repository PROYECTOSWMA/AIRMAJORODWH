from __future__ import annotations

from assets._common.abstract_resource import AbstractDbResource
from assets.static_data_asset.models.static_ambulance_sales import StaticAmbulanceSales
from assets.static_data_asset.models.static_lap_aeronave import StaticLapReports
from assets.static_data_asset.models.static_payroll import StaticPayroll
from assets.static_data_asset.models.static_aux_accounts_assignment import (
    StaticAuxAccountsAssignment,
)
from assets.static_data_asset.models.static_aux_airports import StaticAuxAirports
from assets.static_data_asset.models.static_aux_cost_centers_override import (
    StaticAuxCostCentersOverride,
)
from assets.static_data_asset.models.static_dwh_airplanes import StaticDwhAirplanes
from assets.static_data_asset.models.static_dwh_cost_centers import (
    StaticDwhCostCenters,
)
from assets.static_data_asset.models.static_dwh_master_account_groups import (
    StaticDwhMasterAccountGroups,
)
from assets.static_data_asset.models.static_dwh_master_accounts import (
    StaticDwhMasterAccounts,
)
from assets.static_data_asset.models.static_invoice_fenix import (
    StaticInvoiceFenixDetails,
    StaticInvoiceFenixHeader,
)
from assets.static_data_asset.models.static_invoice_jetset import (
    StaticInvoiceJetsetDetails,
    StaticInvoiceJetsetHeader,
)
from assets.static_data_asset.models.static_invoice_kal import (
    StaticInvoiceKalDetails,
    StaticInvoiceKalHeader,
)
from assets.static_data_asset.models.static_invoice_peniel import (
    StaticInvoicePenielDetails,
    StaticInvoicePenielHeader,
)
from assets.static_data_asset.models.static_invoice_po import (
    StaticInvoicePoDetails,
    StaticInvoicePoHeader,
)
from assets.static_data_asset.models.static_invoice_precision import (
    StaticInvoicePrecisionDetails,
    StaticInvoicePrecisionHeader,
)
from assets.static_data_asset.models.static_invoice_textron import (
    StaticInvoiceTextronDetails,
    StaticInvoiceTextronHeader,
)
from assets.static_data_asset.models.sales_selva import SalesSelva


class StaticDataSqliteResource(AbstractDbResource):
    """Resource que hace el upsert de las tablas de las fuentes estáticas."""

    def _tables(self) -> tuple[type, ...]:
        return (
            # Operativos (snapshots).
            StaticAmbulanceSales,
            StaticLapReports,
            StaticPayroll,
            SalesSelva,
            # Facturas y órdenes de compra del exterior (2 tablas por subcarpeta).
            StaticInvoiceFenixHeader,
            StaticInvoiceFenixDetails,
            StaticInvoiceJetsetHeader,
            StaticInvoiceJetsetDetails,
            StaticInvoiceKalHeader,
            StaticInvoiceKalDetails,
            StaticInvoicePenielHeader,
            StaticInvoicePenielDetails,
            StaticInvoicePrecisionHeader,
            StaticInvoicePrecisionDetails,
            StaticInvoiceTextronHeader,
            StaticInvoiceTextronDetails,
            StaticInvoicePoHeader,
            StaticInvoicePoDetails,
            # CSV de referencia.
            StaticDwhMasterAccounts,
            StaticDwhMasterAccountGroups,
            StaticDwhAirplanes,
            StaticDwhCostCenters,
            StaticAuxAccountsAssignment,
            StaticAuxAirports,
            StaticAuxCostCentersOverride,
        )

    def replace_all(self, model: type, rows: list[dict]) -> int:
        """Reemplaza la tabla **completa** del ``model`` (snapshots y CSV).

        Ninguna de estas tablas tiene partición: cada materialización del asset las
        vuelca tal cual, borrando lo anterior (``_replace`` con ``where=None``).
        """
        return self._replace(model, None, rows)
