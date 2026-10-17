"""Asset diario de archivos CORPAC (documentos de comunicaciones de facturación).

Para la partición diaria lee los correos del remitente CORPAC de ``emails`` (tabla que
alimenta ``ingest_emails``) **que aún no tengan archivos** en ``from_email_corpac_files``
(append-only: si el correo ya tiene al menos uno, se salta y ni se descarga), extrae del
body el enlace de comunicaciones (``parser.extract_corpac_url``), descarga el ZIP del
portal con ``CorpacResource`` y desempaqueta sus 2-3 documentos (factura, XML, OC...) en
``from_email_corpac_files`` como hijos del correo (``id_email`` = id del email).

Es **fail-fast**: si un correo pendiente falla (sin enlace, descarga fallida o ZIP
inválido) se lanza ``CorpacProcessingError`` y **cae la partición** con un error. Al ser
append-only, un re-run solo procesa los correos que siguen sin archivos: lo ya insertado
no se borra ni se re-descarga y los archivos viejos conservan su ``id`` (``file_id`` que
referencia ``corpac_header``).

Declara ``BackfillPolicy.multi_run(max_partitions_per_run=30)``, igual que ``ingest_emails``: al
lanzar un backfill de un rango, Dagster **no** invoca la función una vez por día, sino **una vez
por run** con el trozo de rango que le toque (hasta 30 particiones, que el contexto expone en
``context.partition_keys``). Además, en un run de rango ``context.partition_key`` lanza
``DagsterInvariantViolationError``.

Por eso todo el trabajo de **un** día vive en ``procesar_dia`` y el asset se limita a recorrer
``partition_days(context)``, que devuelve un solo día en una materialización normal (el cron
diario) y los N días del trozo en un run de backfill, cada uno con su carga append-only (un
insert por día).
"""

import zipfile
from typing import Any

from dagster import (
    AssetDep,
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets._common.partitions import correos_daily_partitions_def, partition_days
from assets.from_email_assets.corpac_assets.corpac_files_asset.parser import extract_corpac_url, extract_zip_files
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.api_resource import (
    CorpacResource,
    CorpacZipError,
)
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.db_resource import CorpacSqliteResource
from assets.mail_asset.mail_asset import ingest_emails

# Misma definición diaria que ``ingest_emails`` (mismo objeto = mismo espacio de
# particiones), requisito para poder materializarse en el mismo run.
daily_partitions_def = correos_daily_partitions_def

_LOG_AVANCE_CADA = 50


class CorpacProcessingError(Exception):
    """Falla al procesar un correo CORPAC: derrumba la materialización de la partición."""


def procesar_dia(
    context: AssetExecutionContext,
    corpac: CorpacResource,
    corpac_db: CorpacSqliteResource,
    period: str,
) -> dict[str, Any]:
    """Descarga y agrega los archivos de los correos CORPAC pendientes de **un** día.

    ``period`` es la clave de la partición diaria (p. ej. ``"2026-08-11"``). Por cada correo del
    remitente CORPAC **sin archivos** en ``from_email_corpac_files`` se extrae el enlace del body,
    se descarga el ZIP y se desempaquetan sus archivos (append-only: los correos que ya tienen al
    menos un archivo se saltan y no se vuelven a descargar). Si un correo pendiente falla se lanza
    ``CorpacProcessingError``: ese día cae y lo ya insertado en corridas anteriores queda intacto.
    Devuelve el resumen del día para la metadata del materialization event.
    """
    emails = corpac_db.select_corpac_emails(period)
    context.log.info(
        "Día %s: %d correos CORPAC por procesar",
        period,
        len(emails),
    )

    filas: list[dict[str, Any]] = []

    for procesados, email in enumerate(emails, start=1):
        if procesados % _LOG_AVANCE_CADA == 0:
            context.log.info(
                "[%s] %d/%d correos procesados",
                period,
                procesados,
                len(emails),
            )

        url = extract_corpac_url(email.get("body") or "")
        if not url:
            raise CorpacProcessingError(
                f"Correo {email['id']}: sin enlace CORPAC en el body"
            )

        try:
            zip_bytes = corpac.download_zip(url)
        except CorpacZipError as exc:
            raise CorpacProcessingError(
                f"Correo {email['id']}: descarga fallida: {exc}"
            ) from exc

        try:
            archivos = extract_zip_files(zip_bytes)
        except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
            raise CorpacProcessingError(
                f"Correo {email['id']}: zip inválido: {exc}"
            ) from exc

        for archivo in archivos:
            filas.append(
                {
                    "id_email": email["id"],
                    "filename": archivo["filename"],
                    "data": archivo["data"],
                }
            )

    count = corpac_db.upsert_files(period, filas)
    context.log.info(
        "Día %s: %d archivos insertados de %d correos",
        period,
        count,
        len(emails),
    )

    return {
        "period": period,
        "files_inserted": count,
        "emails_procesados": len(emails),
    }


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    deps=[AssetDep(ingest_emails)],
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=30),
)
def corpac_files_daily(
    context: AssetExecutionContext,
    corpac: CorpacResource,
    corpac_db: CorpacSqliteResource,
) -> MaterializeResult:
    """Alimenta ``from_email_corpac_files`` con los documentos de los correos CORPAC del día.

    Con ``BackfillPolicy.multi_run(max_partitions_per_run=30)``, igual que ``ingest_emails``, un
    backfill de un rango va en runs de hasta 30 días y esta función se invoca **una vez por run**
    con el trozo de días de ``partition_days(context)``; en la materialización diaria del cron el
    run trae un solo día. Cada día se descarga y se agrega por separado (append-only: los correos
    que ya tienen archivos se saltan), así que re-lanzar el run no duplica nada y un correo roto
    solo tumba el run, no los días que ya se insertaron.

    Devuelve ``MaterializeResult`` **sin valor**: un ``Output`` con valor pasaría por el IO
    manager por defecto, que no sabe persistir un output asociado a varias particiones y tumbaría
    el run del backfill (después de escribir los datos). El resumen agregado viaja en la metadata
    del materialization event.
    """

    dias = partition_days(context)

    resumenes = [procesar_dia(context, corpac, corpac_db, dia) for dia in dias]

    totales = {
        clave: sum(resumen[clave] for resumen in resumenes)
        for clave in ("files_inserted", "emails_procesados")
    }
    context.log.info(
        "Listo: %d día(s) (%s), %d archivos insertados de %d correos",
        len(dias),
        ", ".join(dias),
        totales["files_inserted"],
        totales["emails_procesados"],
    )

    return MaterializeResult(
        metadata={
            **totales,
            "days": MetadataValue.json(dias),
            "days_processed": len(dias),
            "files_by_day": MetadataValue.json(
                {r["period"]: r["files_inserted"] for r in resumenes}
            ),
        }
    )
