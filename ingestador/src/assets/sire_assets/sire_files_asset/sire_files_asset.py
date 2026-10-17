
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
from assets.sire_assets.sire_files_asset.models.pydantic_model import SireFile
from assets.sire_assets.sire_files_asset.resources.api_resource.constants import (
    FILE_KIND_PDF,
    FILE_KIND_ZIP,
    ROLE_EMISOR,
    ROLE_RECEPTOR,
    map_tipo,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.files_resource import (
    CpeFilesMissing,
    CpeFilesResource,
    SireApiMissing,
)
from assets.sire_assets.sire_files_asset.resources.db_resource import (
    SireFilesSqliteResource,
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

_LOG_AVANCE_CADA = 25

_TIPOS_ARCHIVO = (FILE_KIND_PDF, FILE_KIND_ZIP)

# Modo verboso de la carga de archivos: ``SIRE_VERBOSE`` (común a details y files) o
# ``SIRE_FILES_VERBOSE`` (solo este asset). Con el modo activo cada documento del run
# se loguea uno a uno con su identidad, el rol, si trajo archivo y lo que tardó, y al
# cerrar cada (empresa, libro, tipo) sale un resumen de ritmo. Apagado por defecto: el
# log de una corrida normal queda igual que antes.
_VERBOSE_ASSET = "files"


def _verbose_habilitado() -> bool:
    """``True`` si el modo verboso de este asset está activo (ver ``verbose.py``)."""
    return verbose_habilitado(_VERBOSE_ASSET)


def _log_documento_verbose(
    context: AssetExecutionContext,
    *,
    habilitado: bool,
    period: str,
    empresa: str,
    libro: str,
    tipo_documento: str,
    indice: int,
    total: int,
    rol: int,
    senderruc: Any,
    tipo: Any,
    serie: Any,
    numero: Any,
    archivos_count: int,
    inicio: float,
    resultado: str,
) -> None:
    """Loguea un documento del run cuando el modo verboso está activo.

    ``inicio`` es el ``time.perf_counter()`` tomado justo antes de atender el
    documento, así la línea muestra cuánto tardó (consulta a la API + parseo). Con el
    modo apagado es un retorno inmediato, sin coste apreciable en la corrida normal.
    """
    if not habilitado:
        return
    context.log.info(
        "[%s] %s %s %s: %d/%d %s-%s-%s (emisor %s; rol %s) -> %s; %d archivos; %.0f ms",
        period, empresa, libro, tipo_documento, indice, total, tipo, serie, numero,
        senderruc, rol, resultado, archivos_count,
        (time.perf_counter() - inicio) * 1000,
    )


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
    tipo_documento: str,
    motivo: str,
) -> dict[str, Any]:
    """Registro de un documento sin archivo para la metadata ``missing_files``."""
    return {
        "emisor": senderruc,
        "tipo": tipo,
        "serie": serie,
        "numero": numero,
        "empresa": empresa,
        "period": period,
        "tipo_documento": tipo_documento,
        "motivo": motivo,
    }


def _registrar_missing(
    context: AssetExecutionContext,
    missing: list[dict[str, Any]],
    *,
    senderruc: Any,
    tipo: Any,
    serie: Any,
    numero: Any,
    empresa: str,
    period: str,
    libro: str,
    tipo_documento: str,
    motivo: str,
) -> None:
    """Agrega un documento a ``missing_files`` y loguea la falla.

    Solo se loguean las fallas (no los reintentos): cada documento que termina
    sin archivo queda visible en el log con su identidad y el motivo.
    """
    context.log.warning(
        "[%s] %s %s %s: documento %s-%s-%s sin archivo (emisor %s; motivo: %s)",
        period, empresa, libro, tipo_documento,
        tipo, serie, numero, senderruc, motivo,
    )
    missing.append(
        _missing(
            senderruc, tipo, serie, numero, empresa,
            period, tipo_documento, motivo,
        )
    )


def _procesar_mes(
    context: AssetExecutionContext,
    sire_files: CpeFilesResource,
    sire_files_db: SireFilesSqliteResource,
    month: str,
) -> tuple[dict[str, int], list[dict[str, Any]], int]:
    """Procesa un mes completo y devuelve (totales, missing, documentos pendientes).

    ``month`` es el mes de la partición (p. ej. ``"2026-07"``) y la ventana
    ``[start_date, end_date)`` es el mes completo. Por cada empresa y libro
    (compras/ventas) se procesan por tipo de documento (PDF y ZIP) los documentos
    que no tienen fila para ese tipo, etiquetando lo insertado con la clave de la
    partición (``"2026-07-01"``).

    El insert es **por lotes**: cada ``_LOG_AVANCE_CADA`` documentos procesados se
    persiste lo acumulado y al final el resto, así un run que muere a mitad de un
    lote no pierde el avance (el append-only lo respeta en el reintento). Cada
    documento que termina sin archivo se loguea (``warning``) con
    ``_registrar_missing``; con el modo verboso activo
    (``SIRE_VERBOSE``/``SIRE_FILES_VERBOSE``) **todos** los documentos (con y sin
    archivo) se loguean con su resultado y su tiempo con ``_log_documento_verbose``, y
    se cierra cada (empresa, libro, tipo) con un resumen de ritmo.
    """
    period = f"{month}-01"  # clave de la partición mensual
    window = monthly_partitions_def.time_window_for_partition_key(period)
    start_date = window.start.date()
    end_date = window.end.date()

    empresas = sire_files.companies()
    # Los documentos pendientes se seleccionan UNA sola vez por (empresa, libro, tipo)
    # y se reutilizan para el total y para el proceso. Antes se lanzaba la misma
    # consulta dos veces (una solo para contar) y el resultado del conteo se descartaba.
    seleccion: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for empresa in empresas:
        for bc in (BOOK_CODE_PURCHASES, BOOK_CODE_SALES):
            for tipo_documento in _TIPOS_ARCHIVO:
                seleccion[(empresa, bc, tipo_documento)] = _dedupe_documents(
                    sire_files_db.select_missing_files(
                        start_date, end_date, empresa, tipo_documento,
                        book_code=bc,
                    )
                )
    total_dia = sum(len(docs) for docs in seleccion.values())
    context.log.info(
        "Día %s [%s a %s]: %d archivos por procesar en total",
        period,
        start_date,
        end_date,
        total_dia,
    )

    totals: dict[str, int] = {}
    missing: list[dict[str, Any]] = []

    for empresa in empresas:
        ruc_empresa = sire_files.ruc(empresa)
        for book_code, libro, es_venta in (
            (BOOK_CODE_PURCHASES, "compras", False),
            (BOOK_CODE_SALES, "ventas", True),
        ):
            etiqueta = "sales" if es_venta else "purchs"
            rol = ROLE_EMISOR if es_venta else ROLE_RECEPTOR

            for tipo_documento in _TIPOS_ARCHIVO:
                documentos = seleccion[(empresa, book_code, tipo_documento)]
                total_lote = len(documentos)
                context.log.info(
                    "[%s] %s %s %s: %d documentos por procesar",
                    period, empresa, libro, tipo_documento, total_lote,
                )
                archivos: list[dict[str, Any]] = []
                insertados = 0
                verbose = _verbose_habilitado()
                inicio_lote = time.perf_counter()
                docs_con_archivo = 0
                docs_sin_archivo = 0
                archivos_lote = 0

                procesados = 0
                for doc in documentos:
                    procesados += 1
                    inicio_doc = time.perf_counter()
                    if procesados % _LOG_AVANCE_CADA == 0:
                        # Persiste lo acumulado antes de seguir: si el run muere a
                        # mitad del lote, el avance ya insertado no se pierde
                        # (append-only).
                        insertados += sire_files_db.insert_files(
                            period, empresa, rows=archivos, book_code=book_code
                        )
                        context.log.info(
                            "[%s] %s %s %s: %d/%d documentos procesados "
                            "(%d archivos insertados)",
                            period, empresa, libro, tipo_documento,
                            procesados, total_lote, insertados,
                        )
                        archivos = []

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
                        docs_sin_archivo += 1
                        _registrar_missing(
                            context, missing,
                            senderruc=senderruc, tipo=tipo_cp_doc, serie=serie,
                            numero=numero, empresa=empresa, period=period,
                            libro=libro, tipo_documento=tipo_documento,
                            motivo=motivo,
                        )
                        _log_documento_verbose(
                            context, habilitado=verbose, period=period,
                            empresa=empresa, libro=libro,
                            tipo_documento=tipo_documento, indice=procesados,
                            total=total_lote, rol=rol, senderruc=senderruc,
                            tipo=tipo_cp_doc, serie=serie, numero=numero,
                            archivos_count=0, inicio=inicio_doc, resultado=motivo,
                        )
                        continue
                    if (not serie or numero is None) or (not es_venta and not senderruc):
                        motivo = "sin datos completos"
                        docs_sin_archivo += 1
                        _registrar_missing(
                            context, missing,
                            senderruc=senderruc, tipo=tipo_cp_doc, serie=serie,
                            numero=numero, empresa=empresa, period=period,
                            libro=libro, tipo_documento=tipo_documento,
                            motivo=motivo,
                        )
                        _log_documento_verbose(
                            context, habilitado=verbose, period=period,
                            empresa=empresa, libro=libro,
                            tipo_documento=tipo_documento, indice=procesados,
                            total=total_lote, rol=rol, senderruc=senderruc,
                            tipo=tipo_cp_doc, serie=serie, numero=numero,
                            archivos_count=0, inicio=inicio_doc, resultado=motivo,
                        )
                        continue

                    # NC/ND con tipo_cp_modificado inesperado lanza ValueError -> cae el run.
                    tipo = map_tipo(tipo_cp_doc, doc.get("tipo_cp_modificado"))

                    try:
                        archivo = sire_files.get_file(
                            senderruc, tipo, serie, numero,
                            tipo_archivo=tipo_documento, empresa=empresa, rol=rol,
                        )
                    except SireApiMissing:
                        motivo = "sin respuesta de la API"
                        docs_sin_archivo += 1
                        _registrar_missing(
                            context, missing,
                            senderruc=senderruc, tipo=tipo, serie=serie,
                            numero=numero, empresa=empresa, period=period,
                            libro=libro, tipo_documento=tipo_documento,
                            motivo=motivo,
                        )
                        _log_documento_verbose(
                            context, habilitado=verbose, period=period,
                            empresa=empresa, libro=libro,
                            tipo_documento=tipo_documento, indice=procesados,
                            total=total_lote, rol=rol, senderruc=senderruc,
                            tipo=tipo, serie=serie, numero=numero,
                            archivos_count=0, inicio=inicio_doc, resultado=motivo,
                        )
                        continue

                    fila = SireFile.model_validate(
                        {**archivo, "tipo_documento": tipo_documento}
                    ).model_dump()
                    archivos.append(
                        {
                            **fila,
                            ("sire_sale" if es_venta else "sire_purch"): doc["id"],
                        }
                    )
                    docs_con_archivo += 1
                    archivos_lote += 1

                    # Modo verboso: cada documento procesado deja su línea con el
                    # resultado y lo que tardó (API + parseo + validación).
                    _log_documento_verbose(
                        context, habilitado=verbose, period=period, empresa=empresa,
                        libro=libro, tipo_documento=tipo_documento, indice=procesados,
                        total=total_lote, rol=rol, senderruc=senderruc, tipo=tipo,
                        serie=serie, numero=numero, archivos_count=1,
                        inicio=inicio_doc, resultado="con archivo",
                    )

                insertados += sire_files_db.insert_files(
                    period, empresa, rows=archivos, book_code=book_code
                )
                totals[f"{empresa}:{etiqueta}_{tipo_documento.lower()}"] = insertados
                context.log.info(
                    "Archivos %s empresa %s %s insertados: %d (%s; %d documentos)",
                    period, empresa, tipo_documento, insertados, libro, len(documentos),
                )
                if verbose:
                    transcurrido = time.perf_counter() - inicio_lote
                    context.log.info(
                        "[%s] %s %s %s: resumen verboso -> %d documentos (%d con "
                        "archivo, %d sin archivo), %d archivos en %.1f s "
                        "(%.0f ms/documento)",
                        period, empresa, libro, tipo_documento, len(documentos),
                        docs_con_archivo, docs_sin_archivo, archivos_lote, transcurrido,
                        (transcurrido * 1000 / len(documentos)) if documentos else 0.0,
                    )

    context.log.info(
        "Mes %s: %d archivos procesados, %d sin archivo",
        period, total_dia, len(missing),
    )
    return totals, missing, total_dia


@asset(
    group_name="from_sire",
    partitions_def=sire_monthly_partitions_def,
    deps=[AssetDep(sire_proposal_monthly)],
)
def sire_files_monthly(
    context: AssetExecutionContext,
    sire_files: CpeFilesResource,
    sire_files_db: SireFilesSqliteResource,
) -> MaterializeResult:
    """Alimenta los archivos (PDF/ZIP) de los comprobantes de los meses del run.

    ``partition_months(context)`` da el mes de la partición (el cron materializa
    **mes anterior + mes actual**, una partición = un run); cada mes se procesa con
    ``_procesar_mes`` y los totales se acumulan en la metadata. El insert es
    append-only y solo se piden los tipos que faltan, así que re-materializar el mes
    es barato y añade lo que entró después.
    """
    months = partition_months(context)
    totals: dict[str, int] = {}
    missing: list[dict[str, Any]] = []
    documentos_pendientes = 0

    for month in months:
        totales_mes, missing_mes, pendientes_mes = _procesar_mes(
            context, sire_files, sire_files_db, month
        )
        for key, value in totales_mes.items():
            totals[key] = totals.get(key, 0) + value
        missing.extend(missing_mes)
        documentos_pendientes += pendientes_mes

    metadata: dict[str, Any] = {
        "months": len(months),
        "documentos_pendientes": documentos_pendientes,
        "verbose": _verbose_habilitado(),
        "missing_files": MetadataValue.json(missing),
        "missing_files_count": len(missing),
    }
    for key, value in totals.items():
        metadata[key] = value

    # MaterializeResult **sin valor**: el resumen de filas viaja en la metadata del
    # materialization event (un ``Output`` con valor pasaría por el IO manager por
    # defecto, que no aporta nada aquí).
    return MaterializeResult(metadata=metadata)


