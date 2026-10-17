"""Asset mensual de la liquidación contable de ventas (SISA).

Para el mes de la partición consulta ``SisaSalesResource.get_sales`` de **cada
sede** definida en ``constants.SEDES`` (las empresas y sedes del flujo SISA
viven en constantes, no en ``sire_credentials``), valida las filas contra el
modelo pydantic (réplica de la tabla) y hace un **upsert total** de la
partición vía ``SisaSalesSqliteResource.upsert_sales``: borra todas las filas
del mes e inserta las nuevas, con ``nombre_empresa`` y ``nombre_sede``
denormalizados en cada fila. El asset no tiene padre.

Declara ``BackfillPolicy.single_run()``: el rango completo de un backfill se materializa en
**un único run** (``context.partition_keys`` trae todos los meses) y la función lo recorre mes
a mes con ``partition_days``. Cada mes es barato (3 consultas serializadas + un upsert total) y
su upsert es todo-o-nada de ese mes, así que paralelizar solo añadiría overhead.
"""

from typing import Any

from dagster import (
    AssetExecutionContext,
    BackfillPolicy,
    MaterializeResult,
    MetadataValue,
    MonthlyPartitionsDefinition,
    asset,
)

from assets._common.partitions import partition_days
from assets.sisa_sales_asset.models.pydantic_model import (
    SisaCreditNoteRow,
    SisaSalesRow,
)
from assets.sisa_sales_asset.resources.api_resource.constants import (
    EMPRESAS,
    SEDES,
)
from assets.sisa_sales_asset.resources.api_resource.sisa_sales_resource import (
    SisaSalesResource,
)
from assets.sisa_sales_asset.resources.db_resource import (
    SisaSalesSqliteResource,
)

monthly_partitions_def = MonthlyPartitionsDefinition(
    start_date="2026-01-01",
    end_offset=1,  # incluye el mes en curso (p. ej. 2026-08-01 aunque no haya terminado)
    
)


def procesar_mes(
    context: AssetExecutionContext,
    sisa_sales: SisaSalesResource,
    sisa_sales_db: SisaSalesSqliteResource,
    period: str,
) -> dict[str, Any]:
    """Consulta las sedes de **un** mes y hace el upsert total de esa partición.

    ``period`` es la clave de la partición mensual (``"2026-08-01"``). Itera sobre todas las
    sedes de ``constants.SEDES``; por cada una consulta el endpoint y acumula sus filas. Las
    consultas se hacen de a una (el resource las serializa): cada sede espera a que termine la
    anterior. Como el upsert borra **toda** la partición, las filas de las sedes se juntan y se
    insertan en un solo ``upsert_sales`` al final. Devuelve el resumen del mes para la metadata
    del materialization event.
    """
    filas: list[dict[str, Any]] = []
    por_sede: dict[str, int] = {}
    for sede in SEDES:
        clave = f"{sede['cod_emp_doref']}:{sede['cod_sed_doref']}"
        rows = sisa_sales.get_sales(
            period,
            cod_emp_doref=sede["cod_emp_doref"],
            cod_sed_doref=sede["cod_sed_doref"],
        )
        por_sede[clave] = len(rows)
        context.log.info(
            "SISA %s empresa '%s' sede '%s' (%s): %d filas",
            period,
            sede["cod_emp_doref"],
            sede["cod_sed_doref"],
            sede["nombre"],
            len(rows),
        )
        for r in rows:
            fila = SisaSalesRow.model_validate(r).model_dump()
            filas.append(
                {
                    **fila,
                    "nombre_empresa": EMPRESAS[sede["cod_emp_doref"]],
                    "nombre_sede": sede["nombre"],
                }
            )

    count = sisa_sales_db.upsert_sales(period, filas)
    context.log.info("SISA %s upserted: %d filas", period, count)

    # Notas de crédito (se RESTAN de las ventas): mismo barrido de sedes, procedure
    # ``USP_UVW_LIQUIDACION_NOTACREDITO`` y upsert total en ``sisa_credit_notes``.
    filas_nc: list[dict[str, Any]] = []
    por_sede_nc: dict[str, int] = {}
    for sede in SEDES:
        clave = f"{sede['cod_emp_doref']}:{sede['cod_sed_doref']}"
        rows = sisa_sales.get_credit_notes(
            period,
            cod_emp_doref=sede["cod_emp_doref"],
            cod_sed_doref=sede["cod_sed_doref"],
        )
        por_sede_nc[clave] = len(rows)
        context.log.info(
            "SISA notas de crédito %s empresa '%s' sede '%s' (%s): %d filas",
            period,
            sede["cod_emp_doref"],
            sede["cod_sed_doref"],
            sede["nombre"],
            len(rows),
        )
        for r in rows:
            fila = SisaCreditNoteRow.model_validate(r).model_dump()
            filas_nc.append(
                {
                    **fila,
                    "nombre_empresa": EMPRESAS[sede["cod_emp_doref"]],
                    "nombre_sede": sede["nombre"],
                }
            )

    count_nc = sisa_sales_db.upsert_credit_notes(period, filas_nc)
    context.log.info("SISA %s notas de crédito upserted: %d filas", period, count_nc)

    resumen: dict[str, Any] = {
        "period": period,
        "rows_upserted": count,
        "nc_rows_upserted": count_nc,
    }
    for clave, n in por_sede.items():
        resumen[f"{clave}_filas"] = n
    for clave, n in por_sede_nc.items():
        resumen[f"{clave}_nc_filas"] = n
    return resumen


@asset(
    partitions_def=monthly_partitions_def,
    backfill_policy=BackfillPolicy.single_run(),
)
def sisa_sales_monthly(
    context: AssetExecutionContext,
    sisa_sales: SisaSalesResource,
    sisa_sales_db: SisaSalesSqliteResource,
) -> MaterializeResult:
    """Alimenta ``sisa_sales`` con la liquidación de ventas de los meses del run.

    Con ``BackfillPolicy.single_run()`` un backfill de un rango va en **un único run** y esta
    función se invoca **una vez** con todos los meses de ``partition_days(context)``; en una
    materialización normal el run trae un solo mes. Cada mes se consulta y se upsertea por
    separado (todo-o-nada por mes).

    Devuelve ``MaterializeResult`` **sin valor**: un ``Output`` con valor pasaría por el IO
    manager por defecto, que no sabe persistir un output asociado a varias particiones y tumbaría
    el run del backfill (después de escribir los datos).
    """
    meses = partition_days(context)

    resumenes = [procesar_mes(context, sisa_sales, sisa_sales_db, mes) for mes in meses]

    # Agregado del run: ``rows_upserted`` y las filas por sede (``"01:01_filas"``...).
    totales: dict[str, Any] = {}
    for resumen in resumenes:
        for clave, valor in resumen.items():
            if clave == "period":
                continue
            totales[clave] = totales.get(clave, 0) + valor

    context.log.info(
        "Listo: %d mes(es) (%s), %d filas upserteadas",
        len(meses),
        ", ".join(meses),
        totales["rows_upserted"],
    )

    return MaterializeResult(
        metadata={
            **totales,
            "months": MetadataValue.json(meses),
            "months_processed": len(meses),
            "rows_by_month": MetadataValue.json(
                {resumen["period"]: resumen["rows_upserted"] for resumen in resumenes}
            ),
        }
    )
