from .constants import _MAX_RESULTS
from datetime import datetime, timedelta
from typing import Any

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets._common.partitions import correos_daily_partitions_def, \
    partition_days

from .resources.api_resource import GmailResource
from .resources.db_resource import DbResource

daily_partitions_def = correos_daily_partitions_def


def procesar_dia(
    context: AssetExecutionContext,
    gmail: GmailResource,
    db: DbResource,
    partition_date: str,
) -> dict[str, Any]:
    # Gmail query usa formato YYYY/MM/DD para after/before.
    # after: es INCLUSIVO de la fecha; before: es EXCLUSIVO de la fecha.
    # Para capturar exactamente un día (p. ej. 08/08) hay que usar
    # after:08/08 before:08/09 (desde el inicio del día
    # hasta antes del día siguiente).
    day = datetime.strptime(partition_date, "%Y-%m-%d").date()
    after = day.strftime("%Y/%m/%d")
    before = (day + timedelta(days=1)).strftime("%Y/%m/%d")
    query = f"after:{after} before:{before}"

    ids_by_account = gmail.list_message_ids(
        query=query, max_results=_MAX_RESULTS)
    ids_del_dia = [mid for mids in ids_by_account.values() for mid in mids]

    ya_guardados = db.existing_email_ids(ids_del_dia)
    context.log.info(
        "Día %s: %d correos en Gmail (%s), %d ya en `emails`, %d por descargar",
        partition_date,
        len(ids_del_dia),
        ", ".join(f"{cuenta}: {len(ids)}" for cuenta,
                  ids in ids_by_account.items()),
        len(ya_guardados),
        len(ids_del_dia) - len(ya_guardados),
    )
    for cuenta, ids in ids_by_account.items():
        if len(ids) >= _MAX_RESULTS:
            context.log.warning(
                "Día %s: la cuenta %s devolvió %d ids (el tope):puede haber correos"
                "del día sin listar",
                partition_date,
                cuenta,
                _MAX_RESULTS,
            )

    # Fase 3: solo se descarga el cuerpo/adjuntos de lo nuevo.
    emails = gmail.fetch_emails(
        query=query,
        max_results=_MAX_RESULTS,
        ids_by_account=ids_by_account,
        skip_ids=ya_guardados,
    )

    db.append_emails(partition_date, emails)

    db.append_email_attachments(partition_date, emails)

    return {
        "partition_date": partition_date,
        "emails_ingested": len(emails),
        "emails_skipped": len(ya_guardados),
        "emails_in_window": len(ids_del_dia),
        "mailboxes": list(dict.fromkeys(e.get("mailbox", "") for e in emails)),
    }


@asset(
    group_name="from_email",
    partitions_def=correos_daily_partitions_def,
    backfill_policy=BackfillPolicy.multi_run(max_partitions_per_run=30),
)
def ingest_emails(
    context: AssetExecutionContext,
    gmail: GmailResource,
    db: DbResource,
) -> MaterializeResult:

    dias = partition_days(context)

    resumenes = [procesar_dia(context, gmail, db, dia) for dia in dias]
    totales = {
        clave: sum(resumen[clave] for resumen in resumenes)
        for clave in ("emails_ingested", "emails_skipped", "emails_in_window")
    }
    mailboxes = list(
        dict.fromkeys(cuenta for r in resumenes for cuenta in r["mailboxes"])
    )
    context.log.info(
        "Listo: %d día(s) (%s), %d correos nuevos, %d ya guardados de %d en la ventana",
        len(dias),
        ", ".join(dias),
        totales["emails_ingested"],
        totales["emails_skipped"],
        totales["emails_in_window"],
    )

    return MaterializeResult(
        metadata={
            **totales,
            "days": MetadataValue.json(dias),
            "days_processed": len(dias),
            "emails_by_day": MetadataValue.json(
                {r["partition_date"]: r["emails_ingested"] for r in resumenes}
            ),
            "mailboxes": MetadataValue.json(mailboxes),
        }
    )
