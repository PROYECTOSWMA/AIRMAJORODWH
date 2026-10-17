"""Tests del asset corpac_data_daily (iteración de PDFs, upsert y fail-fast).

El asset se invoca a través de su función de cómputo subyacente (la que
envuelve ``@asset``) con recursos stub para no tocar la red ni la BD. Se usan
PDFs reales de los fixtures: si un PDF falla al parsear, el asset lanza
``CorpacDataProcessingError`` y nunca llega al upsert del día.

Con ``BackfillPolicy.single_run()`` un run de backfill invoca la función **una vez** con los
N días del rango completo (``context.partition_keys``): la lógica de un día vive en
``procesar_dia`` y aquí se prueba también que el asset la recorre para **todos** los días del
run y que **no** devuelve ``Output`` con valor (en un run de rango el IO manager por defecto
reventaría el run).
"""

import base64
from pathlib import Path

import pytest

from dagster import MaterializeResult

from assets.from_email_assets.corpac_assets.corpac_data_asset.corpac_data_asset import (
    CorpacDataProcessingError,
    corpac_data_daily,
    procesar_dia,
)

# ``corpac_data_daily`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, corpac_data_db).
_ASSET_FN = corpac_data_daily.op.compute_fn.decorated_fn

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "corpac"


def _pdf_b64(nombre):
    with open(_FIXTURES / f"{nombre}.pdf.b64", encoding="ascii") as f:
        return f.read()


# PDFs reales de 3 series distintas (1 fila, 2 filas US$, ruta+km pegados).
_F1 = {"id": 10, "filename": "01-F02500029006.pdf", "data": _pdf_b64("f025_29006")}
_F2 = {"id": 20, "filename": "01-F05600003893.pdf", "data": _pdf_b64("f056_3893")}
_F3 = {"id": 30, "filename": "01-F05100002816.pdf", "data": _pdf_b64("f051_2816")}


class _Log:
    def info(self, *args, **kwargs):
        pass


class _Context:
    """Contexto mínimo: un día, o el rango completo de un run ``single_run``."""

    def __init__(self, partition_key="2026-08-12", partition_keys=None):
        self.partition_key = partition_key
        if partition_keys is not None:
            self.partition_keys = partition_keys
        self.log = _Log()


class _Db:
    def __init__(self, files=(), por_dia=None):
        self.files = list(files)
        # PDFs por día (para el rango de un backfill); si no hay entrada, ``files``.
        self.por_dia = por_dia or {}
        self.upserts = []

    def select_corpac_pdfs(self, partition_date):
        return self.por_dia.get(partition_date, self.files)

    def upsert_day(self, partition_date, headers, details):
        self.upserts.append((partition_date, list(headers), list(details)))
        return len(headers), len(details)


def test_asset_parsea_e_inserta_cabeceras_y_detalles():
    db = _Db([_F1, _F2])
    out = _ASSET_FN(_Context(), db)

    assert len(db.upserts) == 1
    particion, headers, details = db.upserts[0]
    assert particion == "2026-08-12"

    assert [h["filename"] for h in headers] == [
        "01-F02500029006.pdf",
        "01-F05600003893.pdf",
    ]
    assert [h["factura"] for h in headers] == ["F0250029006", "F0560003893"]
    assert all("partition_date" not in h for h in headers)  # lo inyecta la BD
    assert headers[0]["file_id"] == 10

    # F025: 1 detalle (S/); F056: 2 detalles (US$).
    assert len(details) == 3
    assert [d["filename"] for d in details] == [
        "01-F02500029006.pdf",
        "01-F05600003893.pdf",
        "01-F05600003893.pdf",
    ]
    assert details[0]["moneda"] == "S/"
    assert details[1]["moneda"] == "US$"

    assert out.metadata["pdfs_procesados"] == 2
    assert out.metadata["headers_inserted"] == 2
    assert out.metadata["details_inserted"] == 3


def test_asset_ruta_pegada_al_km_parte_bien():
    from decimal import Decimal

    db = _Db([_F3])
    out = _ASSET_FN(_Context(), db)

    _, _, details = db.upserts[0]
    snar = details[1]
    assert snar["ruta_aerea"] == "AYA DCT UDENI UT332/UT32"
    assert snar["total_km"] == Decimal("3123.32")


def test_asset_sin_pdfs_del_dia():
    db = _Db([])
    out = _ASSET_FN(_Context(), db)

    assert db.upserts == [("2026-08-12", [], [])]
    assert out.metadata["pdfs_procesados"] == 0
    assert out.metadata["headers_inserted"] == 0


def test_asset_pdf_invalido_cae_la_particion():
    db = _Db(
        [
            _F1,
            {"id": 99, "filename": "01-ROTO.pdf", "data": base64.b64encode(b"no pdf").decode()},
        ]
    )

    with pytest.raises(CorpacDataProcessingError, match="01-ROTO.pdf"):
        _ASSET_FN(_Context(), db)

    assert db.upserts == []  # nunca llega al upsert


def test_asset_sin_clave_factura_cae_la_particion():
    # Un PDF que abre pero no trae cabecera de factura también falla.
    db = _Db(
        [
            {
                "id": 99,
                "filename": "01-VACIO.pdf",
                "data": base64.b64encode(b"%PDF-1.4").decode(),
            }
        ]
    )

    with pytest.raises(CorpacDataProcessingError):
        _ASSET_FN(_Context(), db)

    assert db.upserts == []


# --- Un día por llamada (``procesar_dia``) y el rango de un ``single_run`` --------


def test_procesar_dia_devuelve_el_resumen_del_dia():
    db = _Db([_F1])

    resumen = procesar_dia(_Context(), db, "2026-08-12")

    assert resumen["period"] == "2026-08-12"
    assert resumen["pdfs_procesados"] == 1
    assert resumen["headers_inserted"] == 1
    assert resumen["details_inserted"] == 1
    assert db.upserts[0][0] == "2026-08-12"


def test_procesar_dia_cuenta_las_copias_omitidas_del_mismo_documento():
    # ``select_corpac_pdfs`` entrega una copia por documento y anota cuántas había
    # (``copies``): el resumen del día reporta las omitidas para que la materialización
    # muestre cuánta repetición de correo está absorbiendo.
    db = _Db([{**_F1, "copies": 4}, {**_F2, "copies": 1}])

    resumen = procesar_dia(_Context(), db, "2026-08-12")

    assert resumen["pdfs_procesados"] == 2
    assert resumen["pdfs_duplicados_omitidos"] == 3
    assert len(db.upserts[0][1]) == 2  # una cabecera por documento, no por copia


def test_asset_recorre_todos_los_dias_del_rango():
    # ``single_run()``: Dagster invoca la función UNA vez por run con el rango completo de días
    # de la materialización (``partition_keys``), así que el asset los procesa uno a uno.
    dias = ["2026-08-12", "2026-08-13", "2026-08-14"]
    db = _Db(
        por_dia={
            "2026-08-12": [_F1],
            "2026-08-13": [_F2],
            "2026-08-14": [_F3],
        }
    )
    context = _Context(partition_key=dias[0], partition_keys=dias)

    out = _ASSET_FN(context, db)

    # Un upsert por día, en orden y con su propia partición.
    assert [period for period, _, _ in db.upserts] == dias
    assert [len(headers) for _, headers, _ in db.upserts] == [1, 1, 1]
    # La metadata es el agregado del run.
    assert out.metadata["pdfs_procesados"] == 3
    assert out.metadata["headers_inserted"] == 3
    assert out.metadata["details_inserted"] == 5  # 1 (F025) + 2 (F056) + 2 (F051)
    assert out.metadata["days_processed"] == 3
    assert out.metadata["days"].data == dias
    assert out.metadata["pdfs_by_day"].data == {dia: 1 for dia in dias}


def test_el_fail_fast_es_por_dia():
    # El upsert del día es todo-o-nada y los días anteriores ya están insertados: un PDF
    # roto tumba el run, pero no re-hace los días ya upserteados (idempotente por día).
    dias = ["2026-08-12", "2026-08-13"]
    db = _Db(
        por_dia={
            "2026-08-12": [_F1],
            "2026-08-13": [
                {"id": 99, "filename": "01-ROTO.pdf", "data": base64.b64encode(b"no pdf").decode()}
            ],
        }
    )
    context = _Context(partition_key=dias[0], partition_keys=dias)

    with pytest.raises(CorpacDataProcessingError, match="01-ROTO.pdf"):
        _ASSET_FN(context, db)

    assert [period for period, _, _ in db.upserts] == ["2026-08-12"]


def test_el_asset_no_devuelve_output_con_valor():
    # Con un rango de particiones, un ``Output`` con valor pasa por el IO manager por
    # defecto, que no sabe persistir un output asociado a varias particiones y tumbaría
    # el run después de escribir los datos. El resumen va en la metadata del
    # materialization event (``MaterializeResult``), no en un valor.
    assert _ASSET_FN.__annotations__.get("return") is MaterializeResult


def test_el_asset_declara_single_run():
    # El rango completo se materializa en un único run (``partition_keys`` trae todos los días).
    politica = corpac_data_daily.backfill_policy
    assert politica is not None and politica.max_partitions_per_run is None
