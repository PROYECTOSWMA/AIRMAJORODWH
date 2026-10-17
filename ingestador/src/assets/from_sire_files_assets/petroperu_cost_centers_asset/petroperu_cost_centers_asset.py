
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
from assets.from_sire_files_assets._common.parser import parse_aeronave, parse_aeropuerto
from assets.from_sire_files_assets.petroperu_cost_centers_asset.models.pydantic_model import (
    AeronaveRow,
)
from assets.from_sire_files_assets.petroperu_cost_centers_asset.resources.db_resource import (
    PetroperuCostCenterSqliteResource,
)
from assets.sire_assets.sire_files_asset.sire_files_asset import sire_files_monthly

_LOG_AVANCE_CADA = 50


@asset(
    group_name="from_sire",
    partitions_def=sire_monthly_partitions_def,
    # Depende SOLO de ``sire_files_monthly`` (los ZIP): el orden del run lo da el grafo
    # (propuesta -> files -> cost centers) y así los ZIP del mes ya están descargados al
    # extraer las aeronaves. La propuesta entra por transitividad, no como dep directa.
    # El asset **no** consulta ``sire_purchs``: identifica los ZIP del proveedor por el
    # RUC de su ``nom_archivo`` y la FK ``sire_purchs_files.sire_purch`` garantiza el
    # vínculo con la compra.
    deps=[AssetDep(sire_files_monthly)],
    backfill_policy=BackfillPolicy.single_run(),
)
def petroperu_cost_centers_monthly(
    context: AssetExecutionContext,
    petroperu_cost_centers_db: PetroperuCostCenterSqliteResource,
) -> MaterializeResult:
    """Alimenta ``from_sire_petroperu_cost_centers`` con las aeronaves de los ZIP SIRE de los meses.

    ``partition_months(context)`` da el mes de la partición o los meses del rango de
    un backfill ``single_run``. Por cada ZIP de compras del proveedor se extrae la
    aeronave del XML no-``R-``.
    """
    months = partition_months(context)
    zips = petroperu_cost_centers_db.select_zip_files(months)
    context.log.info(
        "Meses %s: %d ZIPs SIRE de PETROPERU por procesar", months, len(zips)
    )

    filas: list[dict[str, Any]] = []
    sin_aeronave = 0

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

        aeronave = parse_aeronave(xml)
        if aeronave is None:
            sin_aeronave += 1
            context.log.warning(
                "ZIP %s (%s): XML %s sin aeronave OB-####",
                z["id"],
                z["nom_archivo"],
                xml.filename,
            )
            continue

        # Aeropuerto del DatoAdicional de código 31 (None si el XML no lo trae).
        aeropuerto, aeropuerto_completo = parse_aeropuerto(xml)
        fila = AeronaveRow.model_validate(
            {
                "id_file": z["id"],
                "filename": xml.filename,
                "aeronave": aeronave,
                "aeropuerto": aeropuerto,
                "aeropuerto_completo": aeropuerto_completo,
            }
        ).model_dump()
        # ``period`` es el día del ZIP (fecha de emisión del comprobante).
        filas.append({**fila, "period": z["period"]})

    count = petroperu_cost_centers_db.insert_aeronaves_new(filas)
    context.log.info(
        "Meses %s: %d aeronaves nuevas de %d ZIPs", months, count, len(zips)
    )

    metadata: dict[str, Any] = {
        "months": len(months),
        "aeronaves_inserted": count,
        "zips_procesados": len(zips),
        "zips_sin_aeronave": sin_aeronave,
    }
    # MaterializeResult **sin valor**: un ``Output`` con valor pasa por el IO manager
    # por defecto, que no sabe persistir un output asociado a varias particiones y
    # revienta el run ``single_run`` del cron (mes anterior + mes actual). El resumen
    # viaja igual en la metadata del materialization event.
    return MaterializeResult(metadata=metadata)
