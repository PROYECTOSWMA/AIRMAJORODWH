"""Tests del asset flight_reports_asset (consulta y upsert total por período).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD. Con
``BackfillPolicy.single_run()`` un run de backfill invoca la función **una vez**
con todos los meses del rango (``context.partition_keys``): la lógica de un mes vive
en ``procesar_mes`` y aquí se prueba también que el asset la recorre para **todos**
los meses del run.
"""

from dagster import MaterializeResult

from assets.from_sql_majoro_assets.flight_reports_asset.flight_reports_asset import (
    flight_reports_asset,
    procesar_mes,
)

# ``flight_reports_asset`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, flight_reports, flight_reports_db).
_ASSET_FN = flight_reports_asset.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass


class _Context:
    """Contexto mínimo: un mes, o los meses del rango de un run ``single_run``."""

    def __init__(self, partition_key="2026-08-01", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys
        self.log = _Log()


class _Reports:
    def __init__(self, filas=None, por_mes=None):
        self.filas = filas if filas is not None else []
        self.por_mes = por_mes or {}
        self.calls = []

    def get_report(self, period):
        self.calls.append(period)
        return self.por_mes.get(period, self.filas)


class _Db:
    def __init__(self):
        self.upserts = []

    def upsert_report(self, period, rows):
        self.upserts.append((period, rows))
        return len(rows)


FILA = {
    "fecha_vuelo": "2026-08-01T00:00:00.0000000",
    "sede_operacion": "MEDEVAC",
    "matricula": "OB2092",
    "horas_vuelo": "3.50",
    "total_pasajeros": 8,
}


def test_single_run():
    # El rango completo se materializa en un único run (``partition_keys`` trae todos
    # los meses): cada mes es una consulta + su upsert total.
    politica = flight_reports_asset.backfill_policy
    assert politica is not None and politica.max_partitions_per_run is None


def test_asset_consulta_y_hace_upsert():
    reports = _Reports([FILA, {**FILA, "matricula": "OB2200"}])
    db = _Db()

    out = _ASSET_FN(_Context(), reports, db)

    assert reports.calls == ["2026-08-01"]
    assert db.upserts[0][0] == "2026-08-01"
    assert len(db.upserts[0][1]) == 2
    assert out.metadata["rows_upserted"] == 2
    assert out.metadata["months"].data == ["2026-08-01"]
    assert out.metadata["months_processed"] == 1
    assert out.metadata["rows_by_month"].data == {"2026-08-01": 2}


def test_asset_upsert_vacio_cuando_no_hay_filas():
    reports = _Reports([])
    db = _Db()

    out = _ASSET_FN(_Context(), reports, db)

    assert len(db.upserts) == 1
    period, rows = db.upserts[0]
    assert period == "2026-08-01"
    assert rows == []
    assert out.metadata["rows_upserted"] == 0


def test_procesar_mes_devuelve_el_resumen():
    reports = _Reports([FILA])
    db = _Db()

    resumen = procesar_mes(_Context(), reports, db, "2026-08-01")

    assert resumen["period"] == "2026-08-01"
    assert resumen["rows_upserted"] == 1
    assert db.upserts[0][0] == "2026-08-01"


def test_asset_recorre_todos_los_meses_del_rango():
    meses = ["2026-07-01", "2026-08-01"]
    reports = _Reports(
        por_mes={
            "2026-07-01": [FILA],
            "2026-08-01": [FILA, {**FILA, "matricula": "OB2200"}],
        }
    )
    db = _Db()
    context = _Context(partition_key=meses[0], partition_keys=meses)

    out = _ASSET_FN(context, reports, db)

    assert reports.calls == meses
    assert [period for period, _ in db.upserts] == meses
    assert [len(rows) for _, rows in db.upserts] == [1, 2]
    assert out.metadata["rows_upserted"] == 3
    assert out.metadata["months_processed"] == 2
    assert out.metadata["rows_by_month"].data == {"2026-07-01": 1, "2026-08-01": 2}


def test_el_asset_no_devuelve_output_con_valor():
    # Con un rango de particiones, un ``Output`` con valor pasa por el IO manager por
    # defecto, que no sabe persistir un output asociado a varias particiones.
    assert _ASSET_FN.__annotations__.get("return") is MaterializeResult
