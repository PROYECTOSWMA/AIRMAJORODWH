"""Tests del asset sisa_sales_monthly (recorrido de sedes y upsert total por período).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la red ni la BD.

Con ``BackfillPolicy.single_run()`` un run de backfill invoca la función **una vez** con todos
los meses del rango (``context.partition_keys``): la lógica de un mes vive en ``procesar_mes`` y
aquí se prueba también que el asset la recorre para **todos** los meses del run y que **no**
devuelve ``Output`` con valor (en un run de rango el IO manager por defecto reventaría el run).
"""

from decimal import Decimal

from dagster import MaterializeResult

from assets.sisa_sales_asset.sisa_sales_asset import procesar_mes, sisa_sales_monthly

# ``sisa_sales_monthly`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, sisa_sales, sisa_sales_db).
_ASSET_FN = sisa_sales_monthly.op.compute_fn.decorated_fn


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


class _Sales:
    def __init__(self, filas_por_sede, por_mes=None, nc_por_sede=None):
        self.filas_por_sede = filas_por_sede
        # Filas por mes (para el rango de un backfill); si no hay entrada, ``filas_por_sede``.
        self.por_mes = por_mes or {}
        # Notas de crédito por (empresa, sede); por defecto, ninguna.
        self.nc_por_sede = nc_por_sede or {}
        self.calls = []
        self.nc_calls = []

    def get_sales(self, period, cod_emp_doref, cod_sed_doref):
        self.calls.append((period, cod_emp_doref, cod_sed_doref))
        fuente = self.por_mes.get(period, self.filas_por_sede)
        return fuente.get((cod_emp_doref, cod_sed_doref), [])

    def get_credit_notes(self, period, cod_emp_doref, cod_sed_doref):
        self.nc_calls.append((period, cod_emp_doref, cod_sed_doref))
        return self.nc_por_sede.get((cod_emp_doref, cod_sed_doref), [])


class _Db:
    def __init__(self):
        self.upserts = []
        self.nc_upserts = []

    def upsert_sales(self, period, rows):
        self.upserts.append((period, rows))
        return len(rows)

    def upsert_credit_notes(self, period, rows):
        self.nc_upserts.append((period, rows))
        return len(rows)


FILA = {
    "numerofila": 1,
    "codorgdoref": "01",
    "codperdoref": "2026",
    "codseddoref": "06",
    "codempdoref": "02",
    "nro_documento": "F006-24684",
    "fechaemisio": "01/08/2026",
    "fechavuelo": None,
    "razonsocial": "PENSION 65",
    "doreftotnum": "30.0000",
    "tipcammoned": "3.3910",
    "cantidad": "1.0000",
}


def test_single_run():
    # El rango completo se materializa en un único run (``partition_keys`` trae todos los
    # meses): cada mes es barato (3 consultas serializadas + su upsert) y planificar un run por
    # mes solo añadiría overhead.
    politica = sisa_sales_monthly.backfill_policy
    assert politica is not None and politica.max_partitions_per_run is None


def test_asset_recorre_todas_las_sedes_y_hace_un_solo_upsert():
    sales = _Sales(
        {
            ("01", "01"): [
                {
                    **FILA,
                    "codempdoref": "01",
                    "codseddoref": "01",
                    "razonsocial": "CLIENTE LIMA",
                }
            ],
            ("01", "02"): [],
            ("02", "06"): [{**FILA, "numerofila": 2}],
        }
    )
    db = _Db()

    out = _ASSET_FN(_Context(), sales, db)

    # Se consultan las 3 sedes con la partición del mes.
    assert sales.calls == [
        ("2026-08-01", "01", "01"),
        ("2026-08-01", "01", "02"),
        ("2026-08-01", "02", "06"),
    ]

    # Un único upsert con todas las filas del mes (upsert total de la partición).
    assert len(db.upserts) == 1
    period, rows = db.upserts[0]
    assert period == "2026-08-01"
    assert len(rows) == 2

    lima = rows[0]
    assert lima["nombre_empresa"] == "Air Majoro"
    assert lima["nombre_sede"] == "Lima"
    assert lima["codempdoref"] == "01"
    assert lima["codseddoref"] == "01"
    assert lima["fechaemisio"].isoformat() == "2026-08-01"
    assert lima["doreftotnum"] == Decimal("30.00")
    assert lima["tipcammoned"] == Decimal("3.3910")

    pucallpa = rows[1]
    assert pucallpa["nombre_empresa"] == "Air Majoro Selva"
    assert pucallpa["nombre_sede"] == "Pucallpa"
    assert pucallpa["numerofila"] == 2

    assert out.metadata["rows_upserted"] == 2
    assert out.metadata["months"].data == ["2026-08-01"]
    assert out.metadata["months_processed"] == 1
    assert out.metadata["rows_by_month"].data == {"2026-08-01": 2}
    assert out.metadata["01:01_filas"] == 1
    assert out.metadata["01:02_filas"] == 0
    assert out.metadata["02:06_filas"] == 1


def test_asset_upsert_vacio_cuando_no_hay_filas():
    sales = _Sales({})
    db = _Db()

    out = _ASSET_FN(_Context(), sales, db)

    assert sales.calls == [
        ("2026-08-01", "01", "01"),
        ("2026-08-01", "01", "02"),
        ("2026-08-01", "02", "06"),
    ]
    assert len(db.upserts) == 1
    period, rows = db.upserts[0]
    assert period == "2026-08-01"
    assert rows == []
    assert out.metadata["rows_upserted"] == 0
    assert out.metadata["01:01_filas"] == 0


def test_asset_tambien_ingiere_notas_de_credito():
    nc = {
        "numerofila": 1,
        "codempdoref": "02",
        "codseddoref": "06",
        "sunatnserie": "FC01",
        "sunatnforma": "123",
        "fechaemisio": "01/08/2026",
        "dorefsubtot": "10.0000",
        "dorefimpimp": "1.8000",
        "doreftotnum": "11.8000",
    }
    sales = _Sales({}, nc_por_sede={("02", "06"): [nc]})
    db = _Db()

    out = _ASSET_FN(_Context(), sales, db)

    # Las NC se consultan para las 3 sedes y se upsertean en su propia tabla.
    assert sales.nc_calls == [
        ("2026-08-01", "01", "01"),
        ("2026-08-01", "01", "02"),
        ("2026-08-01", "02", "06"),
    ]
    assert len(db.nc_upserts) == 1
    period, rows = db.nc_upserts[0]
    assert period == "2026-08-01"
    assert len(rows) == 1
    assert rows[0]["nombre_empresa"] == "Air Majoro Selva"
    assert rows[0]["nombre_sede"] == "Pucallpa"
    assert out.metadata["nc_rows_upserted"] == 1
    assert out.metadata["02:06_nc_filas"] == 1
    assert out.metadata["01:01_nc_filas"] == 0


# --- Un mes por llamada (``procesar_mes``) y el rango de un ``single_run`` -----------------


def test_procesar_mes_devuelve_el_resumen():
    sales = _Sales({("02", "06"): [{**FILA, "numerofila": 2}]})
    db = _Db()

    resumen = procesar_mes(_Context(), sales, db, "2026-08-01")

    assert resumen["period"] == "2026-08-01"
    assert resumen["rows_upserted"] == 1
    assert resumen["02:06_filas"] == 1
    assert resumen["01:01_filas"] == 0
    assert db.upserts[0][0] == "2026-08-01"


def test_asset_recorre_todos_los_meses_del_rango():
    # ``single_run()``: Dagster invoca la función UNA vez con el rango completo de meses
    # (``partition_keys``), así que el asset los procesa uno a uno con su propio upsert total.
    meses = ["2026-08-01", "2026-09-01"]
    sales = _Sales(
        {},
        por_mes={
            "2026-08-01": {("02", "06"): [{**FILA, "numerofila": 2}]},
            "2026-09-01": {("01", "01"): [{**FILA, "numerofila": 3}]},
        },
    )
    db = _Db()
    context = _Context(partition_key=meses[0], partition_keys=meses)

    out = _ASSET_FN(context, sales, db)

    # Las 3 sedes se consultan en cada uno de los 2 meses, en orden.
    assert sales.calls == [
        ("2026-08-01", "01", "01"),
        ("2026-08-01", "01", "02"),
        ("2026-08-01", "02", "06"),
        ("2026-09-01", "01", "01"),
        ("2026-09-01", "01", "02"),
        ("2026-09-01", "02", "06"),
    ]

    # Un upsert por mes, en orden y con su propia partición.
    assert [period for period, _ in db.upserts] == meses
    assert [len(rows) for _, rows in db.upserts] == [1, 1]

    # La metadata es el agregado del run (filas por sede sumadas de los 2 meses).
    assert out.metadata["rows_upserted"] == 2
    assert out.metadata["months_processed"] == 2
    assert out.metadata["months"].data == meses
    assert out.metadata["rows_by_month"].data == {"2026-08-01": 1, "2026-09-01": 1}
    assert out.metadata["01:01_filas"] == 1
    assert out.metadata["02:06_filas"] == 1


def test_el_asset_no_devuelve_output_con_valor():
    # Con un rango de particiones, un ``Output`` con valor pasa por el IO manager por defecto,
    # que no sabe persistir un output asociado a varias particiones y tumbaría el run después
    # de escribir los datos. El resumen va en la metadata del materialization event.
    assert _ASSET_FN.__annotations__.get("return") is MaterializeResult
