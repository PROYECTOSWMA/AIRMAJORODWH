"""Asset mensual de propuestas SIRE (RCE compras y RVIE ventas).

La partición es **mensual** (clave = primer día del mes) y el cron materializa el
**mes anterior + el mes actual** en un único run: el libro de SUNAT del mes en
curso crece a diario, así que re-pasarlo cada día es lo que recoge los documentos
que entran más tarde. Se consulta ``ProposalResource.get_proposal`` **una sola vez
por mes, empresa y libro** (``per_tributario=yyyymm``).

Las filas se validan contra los modelos pydantic (réplica de las tablas) y se
insertan con ``SireSqliteResource.insert_proposal_new`` (append-only por clave
natural), de modo que los ids del padre son estables y sus hijos (detalles y
archivos) nunca quedan huérfanos: re-materializar el mismo mes solo añade lo nuevo.
"""

from typing import Any

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets._common.partitions import partition_months, sire_monthly_partitions_def

from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.proposal_resource import (
    ProposalResource,
)
from assets.sire_assets.sire_proposal_asset.resources.db_resource import (
    SireSqliteResource,
)
from assets.sire_assets.sire_proposal_asset.models.pydantic_model import (
    SirePurchsRow,
    SireSalesRow,
)

@asset(
    group_name="from_sire",
    partitions_def=sire_monthly_partitions_def,
    backfill_policy=BackfillPolicy.single_run(),
)
def sire_proposal_monthly(
    context: AssetExecutionContext,
    sire_proposal: ProposalResource,
    sire_db: SireSqliteResource,
) -> MaterializeResult:
    """Alimenta las tablas de compras y ventas de la propuesta SIRE de los meses del run.

    ``partition_months(context)`` da el mes de la partición (``"2026-09"``) o los
    meses del rango cuando es un backfill ``single_run`` (p. ej. el mes anterior y
    el actual). Itera sobre todas las empresas de ``sire_credentials.json``; por
    cada mes y empresa descarga y guarda ambos libros (compras RCE y ventas RVIE).
    El insert es append-only: nunca borra, así que los ids de los comprobantes son
    estables entre corridas.
    """
    months = partition_months(context)

    totals: dict[str, int] = {}
    for month in months:
        period = month.replace("-", "")  # "2026-08" -> "202608"
        for empresa in sire_proposal.companies():
            purchs_rows = sire_proposal.get_proposal(
                period, book_code=BOOK_CODE_PURCHASES, empresa=empresa
            )
            sales_rows = sire_proposal.get_proposal(
                period, book_code=BOOK_CODE_SALES, empresa=empresa
            )

            purchs_count = sire_db.insert_proposal_new(
                period,
                [
                    SirePurchsRow.model_validate({**r, "empresa": empresa}).model_dump()
                    for r in purchs_rows
                ],
                book_code=BOOK_CODE_PURCHASES,
                empresa=empresa,
            )
            sales_count = sire_db.insert_proposal_new(
                period,
                [
                    SireSalesRow.model_validate({**r, "empresa": empresa}).model_dump()
                    for r in sales_rows
                ],
                book_code=BOOK_CODE_SALES,
                empresa=empresa,
            )

            for key, count in (
                (f"{empresa}:purchases", purchs_count),
                (f"{empresa}:sales", sales_count),
            ):
                totals[key] = totals.get(key, 0) + count
            context.log.info(
                "Propuesta %s empresa %s: %d compras (RCE) y %d ventas (RVIE) nuevas",
                period,
                empresa,
                purchs_count,
                sales_count,
            )

    metadata: dict[str, Any] = {
        "months": MetadataValue.json(months),
        "periods": MetadataValue.json([m.replace("-", "") for m in months]),
    }
    for key, value in totals.items():
        metadata[key] = value

    # MaterializeResult **sin valor**: un ``Output`` con valor pasa por el IO manager
    # por defecto, que no sabe persistir un output asociado a varias particiones y
    # revienta el run ``single_run`` del cron (mes anterior + mes actual). El resumen
    # de filas viaja igual en la metadata del materialization event.
    return MaterializeResult(metadata=metadata)

