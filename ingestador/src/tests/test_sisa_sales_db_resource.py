"""Tests de SisaSalesSqliteResource (upsert total por período)."""

import pytest

from assets.sisa_sales_asset.models.model import SisaCreditNote, SisaSales, db
from assets.sisa_sales_asset.resources.db_resource import SisaSalesSqliteResource


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un DatabaseProxy global compartido: se desenlaza entre tests para
    # que cada recurso lo apunte al archivo SQLite temporal que le corresponde.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)


def _row(
    cod_sed_doref: str = "06",
    nro: str = "F006-24684",
    nombre_empresa: str = "Air Majoro Selva",
    nombre_sede: str = "Pucallpa",
    total: str = "30.00",
) -> dict:
    return {
        "numerofila": 1,
        "codempdoref": "02",
        "codseddoref": cod_sed_doref,
        "nro_documento": nro,
        "razonsocial": "PENSION 65",
        "fechaemisio": "2026-08-01",
        "doreftotnum": total,
        "tipcammoned": "3.3910",
        "cantidad": "1.0000",
        "nombre_empresa": nombre_empresa,
        "nombre_sede": nombre_sede,
    }


def test_upsert_inserts_and_replaces_same_period(tmp_path):
    res = SisaSalesSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    n = res.upsert_sales("2026-08-01", [_row(), _row(nro="F006-24685")])
    assert n == 2
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 2

    n2 = res.upsert_sales("2026-08-01", [_row(nro="F006-24686")])
    assert n2 == 1
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 1
    assert SisaSales.get(SisaSales.period == "2026-08-01").nro_documento == "F006-24686"


def test_upsert_total_borra_todas_las_sedes_del_mes(tmp_path):
    res = SisaSalesSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.upsert_sales(
        "2026-08-01",
        [
            _row(nombre_sede="Pucallpa"),
            _row(nro="F001-1", cod_sed_doref="01", nombre_sede="Lima"),
        ],
    )
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 2

    # Re-upsertar el mes borra TODAS las filas del mes (upsert total de la partición).
    res.upsert_sales("2026-08-01", [_row(nro="F006-24690")])
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 1
    assert {f.nombre_sede for f in SisaSales.select()} == {"Pucallpa"}


def test_upsert_does_not_touch_other_periods(tmp_path):
    res = SisaSalesSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.upsert_sales("2026-07-01", [_row()])
    res.upsert_sales("2026-08-01", [_row()])
    assert SisaSales.select().where(SisaSales.period == "2026-07-01").count() == 1
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 1


def test_upsert_empty_rows_clears_period(tmp_path):
    res = SisaSalesSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.upsert_sales("2026-08-01", [_row()])
    n = res.upsert_sales("2026-08-01", [])
    assert n == 0
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 0


def test_upsert_credit_notes_total_por_periodo(tmp_path):
    res = SisaSalesSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    filas = [
        {
            "numerofila": 1,
            "codempdoref": "02",
            "codseddoref": "06",
            "sunatnserie": "FC01",
            "sunatnforma": "123",
            "fechaemisio": "2026-08-01",
            "dorefsubtot": "10.0000",
            "dorefimpimp": "1.8000",
            "doreftotnum": "11.8000",
            "nombre_empresa": "Air Majoro Selva",
            "nombre_sede": "Pucallpa",
        }
    ]
    assert res.upsert_credit_notes("2026-08-01", filas) == 1
    assert SisaCreditNote.select().where(SisaCreditNote.period == "2026-08-01").count() == 1

    # Upsert total: reemplaza el período (acepta vacío).
    assert res.upsert_credit_notes("2026-08-01", []) == 0
    assert SisaCreditNote.select().where(SisaCreditNote.period == "2026-08-01").count() == 0


def test_upsert_many_rows_chunked(tmp_path, monkeypatch):
    """Muchas filas no deben superar el límite de variables SQL de SQLite."""

    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = SisaSalesSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [_row(nro=f"F{i:06d}") for i in range(50)]
    n = res.upsert_sales("2026-08-01", rows)
    assert n == 50
    assert SisaSales.select().where(SisaSales.period == "2026-08-01").count() == 50
    assert SisaSales.get(SisaSales.nro_documento == "F000049") is not None
