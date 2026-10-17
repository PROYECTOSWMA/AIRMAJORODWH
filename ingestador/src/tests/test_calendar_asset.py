"""Tests del asset calendar_weekly (partición semanal, tipos de cambio SUNAT).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD.

Con ``BackfillPolicy.single_run()`` un run de backfill invoca la función **una vez** con
todas las semanas del rango (``context.partition_keys``): la lógica de una semana vive en
``procesar_semana`` y aquí se prueba también que el asset la recorre para **todas** las
semanas del run (con la caché de meses de la API compartida) y que **no** devuelve ``Output``
con valor (en un run de rango el IO manager por defecto reventaría el run).
"""

from datetime import date
from decimal import Decimal

from dagster import MaterializeResult

from assets.calendar_asset.calendar_asset import calendar_weekly, procesar_semana
from assets.calendar_asset.resources.api_resource.calendar_resource import (
    CalendarApiError,
)

# ``calendar_weekly`` es un AssetsDefinition; ``op.compute_fn.decorated_fn`` es la
# función original (context, calendar_api, calendar_db).
_ASSET_FN = calendar_weekly.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class _Context:
    """Contexto mínimo: una semana (2023-01-02, lunes), o las de un run de rango."""

    def __init__(self, partition_key="2023-01-02", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys
        self.log = _Log()


class _Api:
    def __init__(self, dias_por_mes):
        self.dias_por_mes = dias_por_mes
        self.calls = []

    def get_month(self, year, month):
        self.calls.append((year, month))
        return self.dias_por_mes.get((year, month), {})


class _Db:
    def __init__(self):
        self.upserts = []

    def upsert_week(self, start_date, end_date, rows):
        self.upserts.append((start_date, end_date, rows))
        return len(rows)


def _mes(year, month, venta="3.77", compra="3.758"):
    """Dict {fecha: {compra, venta}} para todos los días de un mes."""
    from calendar import monthrange

    dias = monthrange(year, month)[1]
    return {
        f"{year}-{month:02d}-{d:02d}": {"compra": compra, "venta": venta}
        for d in range(1, dias + 1)
    }


def test_single_run():
    # El rango completo se materializa en un único run (``partition_keys`` trae todas las
    # semanas): planificar un run por semana solo añadiría overhead.
    politica = calendar_weekly.backfill_policy
    assert politica is not None and politica.max_partitions_per_run is None


def test_asset_carga_la_semana_completa():
    api = _Api({(2023, 1): _mes(2023, 1)})
    db = _Db()

    out = _ASSET_FN(_Context(), api, db)

    # Se consulta solo el mes de la ventana (enero 2023).
    assert api.calls == [(2023, 1)]

    # Un solo upsert de la ventana semanal [2023-01-02, 2023-01-09).
    assert len(db.upserts) == 1
    start, end, rows = db.upserts[0]
    assert start == date(2023, 1, 2)
    assert end == date(2023, 1, 9)
    assert len(rows) == 7

    primera = rows[0]
    assert primera["date"] == date(2023, 1, 2)
    assert primera["year"] == 2023
    assert primera["month"] == 1
    assert primera["month_name"] == "January"
    assert primera["day"] == 2
    assert primera["week_number"] == 1
    assert primera["exchange_rate_sale"] == Decimal("3.77")
    assert primera["exchange_rate_purchase"] == Decimal("3.758")

    # 2023-01-08 cae en la semana ISO 1 (domingo de la misma semana).
    assert rows[-1]["date"] == date(2023, 1, 8)
    assert rows[-1]["week_number"] == 1

    assert out.metadata["rows_upserted"] == 7
    assert out.metadata["weeks"].data == ["2023-01-02"]
    assert out.metadata["weeks_processed"] == 1
    assert out.metadata["rows_by_week"].data == {"2023-01-02": 7}
    assert out.metadata["missing_api_dates_count"] == 0


def test_asset_omite_dias_sin_dato_en_la_api():
    dias = _mes(2023, 1)
    # Falta el día 3 en la respuesta de la API.
    dias.pop("2023-01-03")
    api = _Api({(2023, 1): dias})
    db = _Db()

    out = _ASSET_FN(_Context(), api, db)

    start, end, rows = db.upserts[0]
    assert len(rows) == 6
    assert all(r["date"] != date(2023, 1, 3) for r in rows)
    assert out.metadata["missing_api_dates"].data == ["2023-01-03"]
    assert out.metadata["missing_api_dates_count"] == 1
    assert out.metadata["rows_upserted"] == 6


# --- Una semana por llamada (``procesar_semana``) y el rango de un ``single_run`` ---------


def test_procesar_semana_devuelve_el_resumen():
    api = _Api({(2023, 1): _mes(2023, 1)})
    db = _Db()

    resumen = procesar_semana(_Context(), api, db, "2023-01-02", {})

    assert resumen["period"] == "2023-01-02"
    assert resumen["rows_upserted"] == 7
    assert resumen["missing_api_dates"] == []
    assert resumen["missing_api_dates_count"] == 0
    assert db.upserts[0][:2] == (date(2023, 1, 2), date(2023, 1, 9))


def test_asset_recorre_todas_las_semanas_del_rango():
    # ``single_run()``: Dagster invoca la función UNA vez con el rango completo de semanas
    # (``partition_keys``), así que el asset las procesa una a una.
    api = _Api({(2023, 1): _mes(2023, 1)})
    db = _Db()
    semanas = ["2023-01-02", "2023-01-09"]
    context = _Context(partition_key=semanas[0], partition_keys=semanas)

    out = _ASSET_FN(context, api, db)

    # Los dos lunes son de enero: el mes se pide UNA sola vez para todo el run (caché compartida).
    assert api.calls == [(2023, 1)]

    # Un upsert por semana, en orden y con su propia ventana.
    assert [(start, end) for start, end, _ in db.upserts] == [
        (date(2023, 1, 2), date(2023, 1, 9)),
        (date(2023, 1, 9), date(2023, 1, 16)),
    ]
    assert [len(rows) for _, _, rows in db.upserts] == [7, 7]

    # La metadata es el agregado del run.
    assert out.metadata["rows_upserted"] == 14
    assert out.metadata["weeks_processed"] == 2
    assert out.metadata["weeks"].data == semanas
    assert out.metadata["rows_by_week"].data == {"2023-01-02": 7, "2023-01-09": 7}


def test_asset_comparte_la_cache_de_meses_entre_semanas():
    # Un rango que cruza de mes pide los 2 meses (una vez cada uno), no uno por semana.
    api = _Api({(2023, 1): _mes(2023, 1), (2023, 2): _mes(2023, 2)})
    db = _Db()
    semanas = ["2023-01-30", "2023-02-06"]
    context = _Context(partition_key=semanas[0], partition_keys=semanas)

    _ASSET_FN(context, api, db)

    assert api.calls == [(2023, 1), (2023, 2)]


def test_el_asset_no_devuelve_output_con_valor():
    # Con un rango de particiones, un ``Output`` con valor pasa por el IO manager por defecto,
    # que no sabe persistir un output asociado a varias particiones y tumbaría el run después
    # de escribir los datos. El resumen va en la metadata del materialization event.
    assert _ASSET_FN.__annotations__.get("return") is MaterializeResult


# --- Degradación ante fallos de la API (p. ej. 429 persistente) --------------------------


class _ApiQueFalla(_Api):
    """API que lanza ``CalendarApiError`` (simula el 429 agotado) para ciertos meses."""

    def __init__(self, dias_por_mes, meses_fallidos):
        super().__init__(dias_por_mes)
        self.meses_fallidos = set(meses_fallidos)

    def get_month(self, year, month):
        self.calls.append((year, month))
        if (year, month) in self.meses_fallidos:
            raise CalendarApiError(
                f"Status HTTP 429 (rate limit) en tipo-cambio-sunat?year={year}"
                f"&month={month:02d}"
            )
        return self.dias_por_mes.get((year, month), {})


def test_semana_sin_datos_de_la_api_no_tumba_el_run():
    # Un 429 persistente del mes de la semana NO debe propagarse: se omite la semana.
    api = _ApiQueFalla({(2023, 1): _mes(2023, 1)}, {(2023, 1)})
    db = _Db()

    resumen = procesar_semana(_Context(), api, db, "2023-01-02", {})

    assert resumen["skipped"] is True
    assert resumen["rows_upserted"] == 0
    assert resumen["missing_api_dates_count"] == 7
    assert "429" in resumen["skip_reason"]
    # Nada de upsert parcial: la ventana se reemplaza entera o no se toca.
    assert db.upserts == []


def test_asset_continua_con_las_demas_semanas_si_una_falla():
    # La semana de enero falla (429) y la de febrero va bien: el run sigue, no cae.
    api = _ApiQueFalla(
        {(2023, 1): _mes(2023, 1), (2023, 2): _mes(2023, 2)}, {(2023, 1)}
    )
    db = _Db()
    semanas = ["2023-01-30", "2023-02-06"]
    context = _Context(partition_key=semanas[0], partition_keys=semanas)

    out = _ASSET_FN(context, api, db)

    # Solo se upsertea la semana de febrero (la de enero se omite entera).
    assert len(db.upserts) == 1
    assert db.upserts[0][:2] == (date(2023, 2, 6), date(2023, 2, 13))
    assert out.metadata["rows_upserted"] == 7
    assert out.metadata["weeks_skipped"] == 1
    assert out.metadata["rows_by_week"].data["2023-01-30"] == 0
    assert "2023-01-30" in out.metadata["skipped_weeks"].data
    assert "429" in out.metadata["skipped_weeks"].data["2023-01-30"]


def test_asset_sin_fallos_no_reporta_semanas_omitidas():
    api = _Api({(2023, 1): _mes(2023, 1)})
    db = _Db()

    out = _ASSET_FN(_Context(), api, db)

    assert out.metadata["weeks_skipped"] == 0
    assert out.metadata["skipped_weeks"].data == {}
