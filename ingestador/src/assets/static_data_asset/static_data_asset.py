
import glob
import os
from pathlib import Path
from typing import Any

from dagster import (
    AssetExecutionContext,
    Output,
    asset,
)

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
from assets.static_data_asset.models.sales_selva import SalesSelva
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
from assets.static_data_asset.parsers.ambulance_sales.ambulance_sales_parser import parse_ambulancia_ventas
from assets.static_data_asset.parsers.csv_static import parse_csv
from assets.static_data_asset.parsers.invoices import (
    fenix,
    jetset,
    kal,
    peniel,
    precision,
    purchase_order,
    textron,
)
from assets.static_data_asset.parsers.lap_reports import parse_lap_aeronave
from assets.static_data_asset.parsers.payroll import parse_planilla
from assets.static_data_asset.parsers.sales_selva import parse_sales_selva
from assets.static_data_asset.resources.db_resource import (
    StaticDataSqliteResource,
)

# Raíz del repo (parents[3] = .../src/assets/static_data_asset/../../..).
PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_DIR = PROJECT_ROOT / "static"

# Carpeta de las facturas de proveedores del exterior y sus subcarpetas.
INVOICE_DIR = "INVOICE INTERNACIONALES"

# Facturas del exterior: una subcarpeta por proveedor, cada una con su parser y sus
# DOS tablas (``header`` = una fila por factura, ``details`` = una fila por línea).
INVOICE_SPECS: list[dict[str, Any]] = [
    {
        "carpeta": f"{INVOICE_DIR}/FENIX AEROSPACE",
        "parser": fenix.parse,
        "tablas": (
            ("static_invoice_fenix_header", StaticInvoiceFenixHeader, "header"),
            ("static_invoice_fenix_details", StaticInvoiceFenixDetails, "details"),
        ),
    },
    {
        "carpeta": f"{INVOICE_DIR}/JETSET",
        "parser": jetset.parse,
        "tablas": (
            ("static_invoice_jetset_header", StaticInvoiceJetsetHeader, "header"),
            ("static_invoice_jetset_details", StaticInvoiceJetsetDetails, "details"),
        ),
    },
    {
        "carpeta": f"{INVOICE_DIR}/KAL AIRPARTS",
        "parser": kal.parse,
        "tablas": (
            ("static_invoice_kal_header", StaticInvoiceKalHeader, "header"),
            ("static_invoice_kal_details", StaticInvoiceKalDetails, "details"),
        ),
    },
    {
        "carpeta": f"{INVOICE_DIR}/PENIEL",
        "parser": peniel.parse,
        "tablas": (
            ("static_invoice_peniel_header", StaticInvoicePenielHeader, "header"),
            ("static_invoice_peniel_details", StaticInvoicePenielDetails, "details"),
        ),
    },
    {
        "carpeta": f"{INVOICE_DIR}/PRECISION HELIPARTS",
        "parser": precision.parse,
        "tablas": (
            ("static_invoice_precision_header", StaticInvoicePrecisionHeader, "header"),
            ("static_invoice_precision_details", StaticInvoicePrecisionDetails, "details"),
        ),
    },
    {
        "carpeta": f"{INVOICE_DIR}/TEXTRON",
        "parser": textron.parse,
        "tablas": (
            ("static_invoice_textron_header", StaticInvoiceTextronHeader, "header"),
            ("static_invoice_textron_details", StaticInvoiceTextronDetails, "details"),
        ),
    },
    {
        # Órdenes de compra: las seis subcarpetas de proveedor comparten formato,
        # así que las procesa **un solo parser** (recursivo).
        "carpeta": f"{INVOICE_DIR}/ORDEN DE COMPRA",
        "parser": purchase_order.parse,
        "tablas": (
            ("static_invoice_po_header", StaticInvoicePoHeader, "header"),
            ("static_invoice_po_details", StaticInvoicePoDetails, "details"),
        ),
    },
]




STATIC_SPECS: list[dict[str, Any]] = [
    {
        "tabla": "ambulancia_ventas_reports",
        "patron": "VENTAS*",
        "parser": parse_ambulancia_ventas,
        "model": StaticAmbulanceSales,
    },
    {
        "tabla": "lap_reports",
        "patron": "LAP*",
        "parser": parse_lap_aeronave,
        "model": StaticLapReports,
    },
    {
        "tabla": "planilla",
        "patron": "Planilla*",
        "parser": parse_planilla,
        "model": StaticPayroll,
    },
    {
        # Reporte de ventas Air Majoro: una hoja por mes y empresa; cada fila queda
        # etiquetada con `sheet_name` (y `row_number`) en la tabla `sales_selva`.
        "tabla": "sales_selva",
        "patron": "1.- REPORTE DE VENTAS*.xlsx",
        "parser": parse_sales_selva,
        "model": SalesSelva,
    },
]

CSV_SPECS: list[dict[str, Any]] = [
    {
        "tabla": "dwh_static_master_accounts",
        "model": StaticDwhMasterAccounts,
    },
    {
        "tabla": "dwh_static_master_account_groups",
        "model": StaticDwhMasterAccountGroups
    },
    {
        "tabla": "dwh_static_airplanes",
        "model": StaticDwhAirplanes,
    },
    {
        "tabla": "dwh_static_cost_centers",
        "model": StaticDwhCostCenters,
    },
    {
        "tabla": "static_aux_accounts_assignment",
        "model": StaticAuxAccountsAssignment,
    },
    {
        "tabla": "static_aux_airports",
        "model": StaticAuxAirports,
    },
    {
        "tabla": "static_aux_cost_centers_override",
        "model": StaticAuxCostCentersOverride,
    },
]


def _procesar_facturas(spec: dict[str, Any], db: Any, context: AssetExecutionContext) -> dict[str, int]:
    """Procesa una subcarpeta de facturas/POs y reemplaza sus **dos** tablas.

    El parser recibe la carpeta y devuelve ``{"header": [...], "details": [...]}``:
    la cabecera (una fila por documento) y los detalles (una fila por línea).
    """
    carpeta = STATIC_DIR / spec["carpeta"]
    if not carpeta.is_dir():
        raise ValueError(f"No se encontró la carpeta '{spec['carpeta']}' en {STATIC_DIR}")
    if not any(carpeta.rglob("*.pdf")):
        raise ValueError(f"La carpeta '{spec['carpeta']}' no contiene PDFs")
    resultado = spec["parser"](carpeta)
    filas_por_tabla: dict[str, int] = {}
    for tabla, modelo, clave in spec["tablas"]:
        filas = resultado.get(clave, [])
        filas_por_tabla[tabla] = db.replace_all(modelo, filas)
        context.log.info(
            "%s reemplazada: %d filas desde '%s/'",
            tabla,
            filas_por_tabla[tabla],
            spec["carpeta"],
        )
    return filas_por_tabla


def _procesar_spec(spec: dict[str, Any], db: Any, context: AssetExecutionContext) -> tuple[int, str]:
    """Maquinaria común de un snapshot: localiza, parsea y reemplaza su tabla.

    Devuelve ``(filas_insertadas, nombre_del_archivo)`` para el resumen.
    """
    tabla = spec["tabla"]

    archivos = sorted(
        p for p in glob.glob(str(STATIC_DIR / spec["patron"])) if os.path.isfile(p)
    )
    if not archivos:
        raise ValueError(
            f"No se encontró archivo que cumpla '{spec['patron']}' en {STATIC_DIR}"
        )
    path = Path(archivos[0])

    filas = spec["parser"](path)
    count = db.replace_all(spec["model"], filas)
    context.log.info(
        "%s reemplazada: %d filas desde '%s'",
        tabla,
        count,
        path.name,
    )
    return count, path.name


@asset()
def static_data_asset(
    context: AssetExecutionContext,
    static_data_db: StaticDataSqliteResource,
) -> Output[dict[str, Any]]:

    # 1) Snapshots estáticos: cada spec localiza su archivo, lo parsea y reemplaza su tabla.
    resumen: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    for spec in STATIC_SPECS:
        count, archivo = _procesar_spec(spec, static_data_db, context)
        resumen[spec["tabla"]] = count
        metadata[f"{spec['tabla']}_archivo"] = archivo
        metadata[f"{spec['tabla']}_rows_upserted"] = count

    # 2) Facturas y órdenes de compra del exterior: una subcarpeta por proveedor
    #    (con su parser) y una carpeta de POs; cada una llena DOS tablas.
    for spec in INVOICE_SPECS:
        filas_por_tabla = _procesar_facturas(spec, static_data_db, context)
        for tabla, filas in filas_por_tabla.items():
            resumen[tabla] = filas
            metadata[f"{tabla}_archivo"] = spec["carpeta"]
            metadata[f"{tabla}_rows_upserted"] = filas

    # 3) CSV de referencia: se parsea cada `<tabla>.csv` completo y se reemplaza su
    #    tabla homónima en la BD (dbt los lee de ahí con `FROM <tabla>`).
    for spec in CSV_SPECS:
        tabla = spec["tabla"]
        archivo_csv = STATIC_DIR / f"{tabla}.csv"
        if not archivo_csv.is_file():
            raise FileNotFoundError(
                f"No se encontró el CSV '{archivo_csv.name}' en {STATIC_DIR}"
            )
        filas_csv = parse_csv(archivo_csv)
        count_csv = static_data_db.replace_all(spec["model"], filas_csv)
        resumen[tabla] = count_csv
        metadata[f"{tabla}_archivo"] = archivo_csv.name
        metadata[f"{tabla}_rows_upserted"] = count_csv
        context.log.info(
            "%s reemplazada: %d filas desde '%s'", tabla, count_csv, archivo_csv.name
        )

    context.log.info("static_data_asset re-materializado: %r", resumen)
    return Output(value=resumen, metadata=metadata)
