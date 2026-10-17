
import base64
from typing import Any

from dagster import (
    AssetDep,
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    asset,
)

from assets._common.partitions import partition_months, sire_monthly_partitions_def
from assets.from_sire_files_assets._common.file_extractor import extract_xml
from assets.from_sire_files_assets.icaro_cost_centers_asset.models.pydantic_model import (
    AeronaveRow,
)
from assets.from_sire_files_assets.icaro_cost_centers_asset.parser import parse_ticket
from assets.from_sire_files_assets.icaro_cost_centers_asset.resources.db_resource import (
    IcaroCostCenterSqliteResource,
)
from assets.sire_assets.sire_files_asset.sire_files_asset import sire_files_monthly

_LOG_AVANCE_CADA = 50


@asset(
    group_name="from_sire",
    partitions_def=sire_monthly_partitions_def,
    deps=[AssetDep(sire_files_monthly)],
    backfill_policy=BackfillPolicy.single_run(),
)
def icaro_cost_centers_monthly(
    context: AssetExecutionContext,
    icaro_cost_centers_db: IcaroCostCenterSqliteResource,
) -> MaterializeResult:
    months = partition_months(context)
    zips = icaro_cost_centers_db.select_zip_files(months)
    context.log.info(
        "Meses %s: %d ZIPs SIRE de ICARO por procesar", months, len(zips)
    )

    filas: list[dict[str, Any]] = []

    for procesados, z in enumerate(zips, start=1):
        if procesados % _LOG_AVANCE_CADA == 0:
            context.log.info(
                "%d/%d ZIPs procesados", procesados, len(zips)
            )
        try:
            xml = extract_xml(base64.b64decode(z["val_archivo"]))
        except Exception as exc:
            context.log.warning(
                "ZIP %s (%s): no se pudo leer: %s",
                z["id"],
                z["nom_archivo"],
                exc,
            )
            continue

        # ``parse_ticket`` levanta ``IcaroParseError`` si el XML no trae el ticket
        # esperado en su ``cac:InvoiceLine``: el error se propaga y cae la partición
        # (no se omite en silencio).
        ticket = parse_ticket(xml)
        fila = AeronaveRow.model_validate(
            {
                "id_file": z["id"],
                "filename": xml.filename,
                "aeronave": ticket["matricula"],
                "nro_ticket": ticket["nro_ticket"],
                "texto_planta": ticket["texto_planta"],
                "texto_matricula": ticket["texto_matricula"],
                "matricula": ticket["matricula"],
                "schema_info": ticket["schema_info"],
            }
        ).model_dump()
        # ``period`` es el día del ZIP (fecha de emisión del comprobante).
        filas.append({**fila, "period": z["period"]})

    count = icaro_cost_centers_db.insert_aeronaves_new(filas)
    context.log.info(
        "Meses %s: %d aeronaves nuevas de %d ZIPs", months, count, len(zips)
    )

    metadata: dict[str, Any] = {
        "months": len(months),
        "aeronaves_inserted": count,
        "zips_procesados": len(zips),
    }

    return MaterializeResult(metadata=metadata)
