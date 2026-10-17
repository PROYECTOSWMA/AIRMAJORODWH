import time
from typing import Any

from dagster import (
    AssetDep,
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
)

from assets._common.partitions import partition_months, sire_monthly_partitions_def

from assets.sire_assets.resources.verbose import verbose_habilitado
from assets.sire_assets.sire_details_asset.models.pydantic_model import SireDetailsItem
from assets.sire_assets.sire_details_asset.resources.api_resource.constants import (
    ROLE_EMISOR,
    ROLE_RECEPTOR,
    map_tipo,
)
from assets.sire_assets.sire_details_asset.resources.api_resource.details_resource import (
    CpeDetailsMissing,
    CpeDetailsResource,
)
from assets.sire_assets.sire_details_asset.resources.db_resource import (
    SireDetailsSqliteResource,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)
from assets.sire_assets.sire_proposal_asset.sire_proposal_asset import (
    sire_proposal_monthly,
)

_DOC_TIPOS_VALIDOS = (1, 3, 7, 8)

# Misma definición mensual que el resto de la cadena SIRE.
monthly_partitions_def = sire_monthly_partitions_def

_LOG_AVANCE_CADA = 50

# Modo verboso de la carga de detalles: ``SIRE_VERBOSE`` (común a details y files) o
# ``SIRE_DETAILS_VERBOSE`` (solo este asset). Con el modo activo cada documento del run
# se loguea uno a uno con su identidad, el rol, los ítems devueltos y lo que tardó, y
# al cerrar cada (empresa, libro) sale un resumen de ritmo. Apagado por defecto: el log
# de una corrida normal queda igual que antes.
_VERBOSE_ASSET = "details"


def _verbose_habilitado() -> bool:
    """``True`` si el modo verboso de este asset está activo (ver ``verbose.py``)."""
    return verbose_habilitado(_VERBOSE_ASSET)


def _dedupe_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita documentos repetidos (mismo tipo, serie y número) dentro del scope."""
    vistos: set[tuple[Any, ...]] = set()
    resultado = []
    for doc in documents:
        clave = (doc.get("tipo_cp_doc"), doc.get("serie"), doc.get("numero"))
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(doc)
    return resultado


def _missing(
    senderruc: Any,
    tipo: Any,
    serie: Any,
    numero: Any,
    empresa: str,
    period: str,
    motivo: str,
) -> dict[str, Any]:
    """Registro de un documento sin detalle para la metadata ``missing_documents``."""
    return {
        "emisor": senderruc,
        "tipo": tipo,
        "serie": serie,
        "numero": numero,
        "empresa": empresa,
        "period": period,
        "motivo": motivo,
    }


def _registrar_sin_detalle(
    context: AssetExecutionContext,
    *,
    senderruc: Any,
    tipo: Any,
    serie: Any,
    numero: Any,
    empresa: str,
    period: str,
    motivo: str,
) -> None:
    """Loguea (``info``) un documento que termina sin detalle.

    Igual que ``sire_files`` loguea cada documento sin archivo, aquí cada documento
    que queda sin detalle se loguea uno a uno con su identidad y el motivo, para no
    depender solo del conteo agregado de ``missing_documents``.
    """
    context.log.info(
        "[%s] %s: documento %s-%s-%s sin detalle (emisor %s; motivo: %s)",
        period, empresa, tipo, serie, numero, senderruc, motivo,
    )


def _log_documento_verbose(
    context: AssetExecutionContext,
    *,
    habilitado: bool,
    period: str,
    empresa: str,
    libro: str,
    indice: int,
    total: int,
    rol: int,
    senderruc: Any,
    tipo: Any,
    serie: Any,
    numero: Any,
    items_count: int | None,
    inicio: float,
    resultado: str,
) -> None:
    """Loguea un documento del run cuando ``SIRE_DETAILS_VERBOSE`` está activo.

    ``inicio`` es el ``time.perf_counter()`` tomado justo antes de atender el
    documento, así la línea muestra cuánto tardó (consulta a la API + parseo). Con el
    modo apagado es un retorno inmediato, sin coste apreciable en la corrida normal.
    """
    if not habilitado:
        return
    context.log.info(
        "[%s] %s %s: %d/%d %s-%s-%s (emisor %s; rol %s) -> %s; %d ítems; %.0f ms",
        period, empresa, libro, indice, total, tipo, serie, numero, senderruc, rol,
        resultado, items_count or 0, (time.perf_counter() - inicio) * 1000,
    )


def _procesar_mes(
    context: AssetExecutionContext,
    sire_details: CpeDetailsResource,
    sire_details_db: SireDetailsSqliteResource,
    month: str,
) -> tuple[dict[str, int], list[dict[str, Any]], int]:
    """Procesa un mes completo y devuelve (totales, missing, documentos pendientes).

    ``month`` es el mes de la partición (p. ej. ``"2026-07"``) y la ventana
    ``[start_date, end_date)`` es el mes completo. Se seleccionan los documentos de
    ``sire_sales``/``sire_purchs`` del libro de ese periodo (``period``) que aún no
    tienen detalle, **una sola vez** por (empresa, libro) — se reutiliza la misma
    lista para el total y para el proceso —, para cada empresa de
    ``sire_credentials.json``; sus ítems se insertan sin borrar lo existente
    (append-only), etiquetados con la clave de la partición (``"2026-07-01"``).

    El filtro ``_rango_documentos`` incluye además los emitidos **antes** del mes
    (la propuesta mensual puede traerlos), que es lo que antes hacía el caso
    especial del día 1.

    El insert es **por lotes**: cada ``_LOG_AVANCE_CADA`` documentos procesados se
    persiste lo acumulado y al final el resto, así un run que muere a mitad de un
    lote no pierde el avance (el append-only lo respeta en el reintento). Cada
    documento que queda sin detalle (falla de la API, tipo no manejado o respuesta
    sin ítems) se loguea uno a uno con ``_registrar_sin_detalle``; con el modo
    verboso activo (``SIRE_VERBOSE``/``SIRE_DETAILS_VERBOSE``) **todos** los documentos
    (con y sin detalle) se loguean con su resultado y su tiempo con
    ``_log_documento_verbose``, y se cierra cada (empresa, libro) con un resumen de
    ritmo.
    """
    period = f"{month}-01"  # clave de la partición mensual
    window = monthly_partitions_def.time_window_for_partition_key(period)
    start_date = window.start.date()
    end_date = window.end.date()

    empresas = sire_details.companies()
    # Los documentos pendientes se seleccionan UNA sola vez por (empresa, libro) y se
    # reutilizan para el total y para el proceso. Antes se lanzaba la misma consulta
    # dos veces (una solo para contar) y el resultado del conteo se descartaba.
    seleccion: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for empresa in empresas:
        for bc in (BOOK_CODE_PURCHASES, BOOK_CODE_SALES):
            seleccion[(empresa, bc)] = _dedupe_documents(
                sire_details_db.select_missing_documents(
                    start_date, end_date, empresa, book_code=bc
                )
            )
    total_dia = sum(len(docs) for docs in seleccion.values())
    context.log.info(
        "Día %s [%s a %s]: %d documentos por procesar en total",
        period,
        start_date,
        end_date,
        total_dia,
    )

    totals: dict[str, int] = {}
    missing: list[dict[str, Any]] = []

    for empresa in empresas:
        ruc_empresa = sire_details.ruc(empresa)
        for book_code, libro, es_venta in (
            (BOOK_CODE_PURCHASES, "compras", False),
            (BOOK_CODE_SALES, "ventas", True),
        ):
            etiqueta = "sales" if es_venta else "purchs"
            rol = ROLE_EMISOR if es_venta else ROLE_RECEPTOR
            documentos = seleccion[(empresa, book_code)]
            total_lote = len(documentos)
            context.log.info(
                "[%s] %s %s: %d documentos por procesar",
                period,
                empresa,
                libro,
                total_lote,
            )
            detalles: list[dict[str, Any]] = []
            insertados = 0
            verbose = _verbose_habilitado()
            inicio_libro = time.perf_counter()
            docs_con_detalle = 0
            docs_sin_detalle = 0
            items_libro = 0

            procesados = 0
            for doc in documentos:
                procesados += 1
                inicio_doc = time.perf_counter()
                if procesados % _LOG_AVANCE_CADA == 0:
                    # Persiste lo acumulado antes de seguir: si el run muere a mitad
                    # del lote, el avance ya insertado no se pierde (append-only).
                    insertados += sire_details_db.insert_details(
                        period, empresa, rows=detalles, book_code=book_code
                    )
                    context.log.info(
                        "[%s] %s %s: %d/%d documentos procesados (%d ítems insertados)",
                        period, empresa, libro, procesados, total_lote, insertados,
                    )
                    detalles = []

                tipo_cp_doc = doc.get("tipo_cp_doc")
                serie = doc.get("serie").strip()
                numero = doc.get("numero")

                if es_venta:
                    if not ruc_empresa:
                        raise ValueError(
                            f"No hay RUC configurado para la empresa '{empresa}' "
                            f"en sire_credentials.json"
                        )
                    senderruc = ruc_empresa
                else:
                    senderruc = (doc.get("nro_doc_identidad") or "").strip()

                if tipo_cp_doc not in _DOC_TIPOS_VALIDOS:
                    motivo = "tipo_cp_doc no manejado"
                    docs_sin_detalle += 1
                    _registrar_sin_detalle(
                        context, senderruc=senderruc, tipo=tipo_cp_doc, serie=serie,
                        numero=numero, empresa=empresa, period=period, motivo=motivo,
                    )
                    _log_documento_verbose(
                        context, habilitado=verbose, period=period, empresa=empresa,
                        libro=libro, indice=procesados, total=total_lote, rol=rol,
                        senderruc=senderruc, tipo=tipo_cp_doc, serie=serie,
                        numero=numero, items_count=None, inicio=inicio_doc,
                        resultado=motivo,
                    )
                    missing.append(
                        _missing(
                            senderruc, tipo_cp_doc, serie, numero, empresa, period,
                            motivo,
                        )
                    )
                    continue
                if (not serie or numero is None) or (not es_venta and not senderruc):
                    motivo = "sin datos completos"
                    docs_sin_detalle += 1
                    _registrar_sin_detalle(
                        context, senderruc=senderruc, tipo=tipo_cp_doc, serie=serie,
                        numero=numero, empresa=empresa, period=period, motivo=motivo,
                    )
                    _log_documento_verbose(
                        context, habilitado=verbose, period=period, empresa=empresa,
                        libro=libro, indice=procesados, total=total_lote, rol=rol,
                        senderruc=senderruc, tipo=tipo_cp_doc, serie=serie,
                        numero=numero, items_count=None, inicio=inicio_doc,
                        resultado=motivo,
                    )
                    missing.append(
                        _missing(
                            senderruc, tipo_cp_doc, serie, numero, empresa, period,
                            motivo,
                        )
                    )
                    continue

                # NC/ND con tipo_cp_modificado inesperado lanza ValueError -> cae el run.
                tipo = map_tipo(tipo_cp_doc, doc.get("tipo_cp_modificado"))

                try:
                    items = sire_details.get_items(
                        senderruc, tipo, serie, numero, rol, empresa=empresa
                    )
                except CpeDetailsMissing:
                    motivo = "sin respuesta de la API"
                    docs_sin_detalle += 1
                    _registrar_sin_detalle(
                        context, senderruc=senderruc, tipo=tipo, serie=serie,
                        numero=numero, empresa=empresa, period=period, motivo=motivo,
                    )
                    _log_documento_verbose(
                        context, habilitado=verbose, period=period, empresa=empresa,
                        libro=libro, indice=procesados, total=total_lote, rol=rol,
                        senderruc=senderruc, tipo=tipo, serie=serie, numero=numero,
                        items_count=None, inicio=inicio_doc, resultado=motivo,
                    )
                    missing.append(
                        _missing(
                            senderruc, tipo, serie, numero, empresa, period, motivo,
                        )
                    )
                    continue

                if not items:
                    # La API respondió sin ítems: el documento no trae detalle. No es
                    # una falla, así que solo se loguea (no va a ``missing_documents``).
                    docs_sin_detalle += 1
                    _registrar_sin_detalle(
                        context, senderruc=senderruc, tipo=tipo, serie=serie,
                        numero=numero, empresa=empresa, period=period,
                        motivo="la API no devolvió ítems",
                    )
                else:
                    docs_con_detalle += 1
                    items_libro += len(items)

                for item in items:
                    fila = SireDetailsItem.model_validate(item).model_dump()
                    detalles.append(
                        {
                            **fila,
                            ("sire_sale" if es_venta else "sire_purch"): doc["id"],
                        }
                    )

                # Modo verboso: cada documento procesado deja su línea con el resultado
                # y lo que tardó (consulta a la API + parseo + validación).
                _log_documento_verbose(
                    context, habilitado=verbose, period=period, empresa=empresa,
                    libro=libro, indice=procesados, total=total_lote, rol=rol,
                    senderruc=senderruc, tipo=tipo, serie=serie, numero=numero,
                    items_count=len(items), inicio=inicio_doc,
                    resultado=(
                        "con detalle"
                        if items
                        else "sin detalle (la API no devolvió ítems)"
                    ),
                )

            insertados += sire_details_db.insert_details(
                period, empresa, rows=detalles, book_code=book_code
            )
            totals[f"{empresa}:{etiqueta}_details"] = insertados
            context.log.info(
                "Detalles %s empresa %s insertados: %d (%s; %d documentos, "
                "%d sin detalle acumulados)",
                period, empresa, insertados, libro, len(documentos), len(missing),
            )
            if verbose:
                transcurrido = time.perf_counter() - inicio_libro
                context.log.info(
                    "[%s] %s %s: resumen verboso -> %d documentos (%d con detalle, "
                    "%d sin detalle), %d ítems en %.1f s (%.0f ms/documento)",
                    period, empresa, libro, len(documentos), docs_con_detalle,
                    docs_sin_detalle, items_libro, transcurrido,
                    (transcurrido * 1000 / len(documentos)) if documentos else 0.0,
                )

    context.log.info(
        "Mes %s: %d documentos procesados, %d sin detalle",
        period, total_dia, len(missing),
    )
    return totals, missing, total_dia


@asset(
    group_name="from_sire",
    partitions_def=sire_monthly_partitions_def,
    deps=[AssetDep(sire_proposal_monthly)],
)
def sire_details_monthly(
    context: AssetExecutionContext,
    sire_details: CpeDetailsResource,
    sire_details_db: SireDetailsSqliteResource,
) -> MaterializeResult:
    """Alimenta los detalles de comprobantes (ítems de línea) de los meses del run.

    ``partition_months(context)`` da el mes de la partición (el cron materializa
    **mes anterior + mes actual**, una partición = un run); cada mes se procesa con
    ``_procesar_mes`` y los totales se acumulan en la metadata. El insert es
    append-only y solo se piden los documentos sin detalle, así que re-materializar
    el mes es barato y añade lo que entró después.
    """
    months = partition_months(context)
    totals: dict[str, int] = {}
    missing: list[dict[str, Any]] = []
    documentos_pendientes = 0

    for month in months:
        totales_mes, missing_mes, pendientes_mes = _procesar_mes(
            context, sire_details, sire_details_db, month
        )
        for key, value in totales_mes.items():
            totals[key] = totals.get(key, 0) + value
        missing.extend(missing_mes)
        documentos_pendientes += pendientes_mes

    metadata: dict[str, Any] = {
        "months": len(months),
        "documentos_pendientes": documentos_pendientes,
        "verbose": _verbose_habilitado(),
        "missing_documents": MetadataValue.json(missing),
        "missing_documents_count": len(missing),
    }
    for key, value in totals.items():
        metadata[key] = value

    # MaterializeResult **sin valor**: el resumen de filas viaja en la metadata del
    # materialization event (un ``Output`` con valor pasaría por el IO manager por
    # defecto, que no aporta nada aquí).
    return MaterializeResult(metadata=metadata)


