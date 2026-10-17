"""Asset mensual de aeronaves (``OB-####``) de los XML de compras SIRE de
CONSORCIO ENERGÉTICO DEL PERÚ (RUC 20613566881).

Para los meses de la materialización lee de ``sire_purchs_files`` los ZIP
(``tipo_documento = ZIP``) **del proveedor** — se filtran por el RUC que SUNAT pone
al principio del nombre del ZIP (``nom_archivo``), **sin** consultar
``sire_purchs`` — y cuya ``period`` (fecha de emisión del comprobante) cae en esos
meses. Su única dep es ``sire_files_monthly`` (los ZIP; la propuesta entra por
transitividad). De cada ZIP se extrae el XML del comprobante (``file_extractor``)
y su aeronave ``OB-####`` (``parser``; el ``R-*.XML`` es la respuesta de SUNAT) y
se inserta una fila por aeronave en ``from_sire_cep_cost_centers``.

Es **append-only por ``(id_file, aeronave)``** y solo se miran los ZIP que aún no
tienen filas: re-materializar el mes (o el rango de dos meses) solo añade lo nuevo
y el insert ocurre una sola vez al final. Un ZIP que no se puede leer o que no trae
aeronave se omite (se loguea) sin derrumbar la partición.
"""

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
from assets.from_sire_files_assets._common.parser import parse_aeronave
from assets.from_sire_files_assets.cep_cost_centers_asset.models.pydantic_model import (
    AeronaveRow,
)
from assets.from_sire_files_assets.cep_cost_centers_asset.resources.db_resource import (
    CepCostCenterSqliteResource,
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
def cep_cost_centers_monthly(
    context: AssetExecutionContext,
    cep_cost_centers_db: CepCostCenterSqliteResource,
) -> MaterializeResult:
    """Alimenta ``from_sire_cep_cost_centers`` con las aeronaves de los ZIP SIRE de los meses.

    ``partition_months(context)`` da el mes de la partición o los meses del rango de
    un backfill ``single_run``. Por cada ZIP de compras del proveedor se extrae la
    aeronave del XML no-``R-``.
    """
    months = partition_months(context)
    zips = cep_cost_centers_db.select_zip_files(months)
    context.log.info(
        "Meses %s: %d ZIPs SIRE de CEP por procesar", months, len(zips)
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

        fila = AeronaveRow.model_validate(
            {"id_file": z["id"], "filename": xml.filename, "aeronave": aeronave}
        ).model_dump()
        # ``period`` es el día del ZIP (fecha de emisión del comprobante).
        filas.append({**fila, "period": z["period"]})

    count = cep_cost_centers_db.insert_aeronaves_new(filas)
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
