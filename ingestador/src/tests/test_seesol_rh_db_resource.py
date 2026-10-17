"""Tests de ``SeesolRhSqliteResource`` (tabla ``seesol_rh`` por mes y empresa).

Se comprueba que el resource crea la tabla y que el upsert reemplaza **solo** la
pareja (period, empresa) pedida: los otros meses y la otra empresa se conservan.
"""

import pytest

import assets._common.db as db_mod
from assets.seesol_rh_asset.models.rh import Rh
from assets.seesol_rh_asset.resources.db_resource import SeesolRhSqliteResource


@pytest.fixture(autouse=True)
def _clean_db():
    # ``db`` es un DatabaseProxy global compartido: se desenlaza entre tests para
    # que cada recurso lo apunte al archivo SQLite temporal que le corresponde.
    yield
    if db_mod.db.obj is not None:
        try:
            db_mod.db.obj.close()
        except Exception:
            pass
        db_mod.db.initialize(None)


def _fila(nro: str, period: str, empresa: str) -> dict:
    return {
        "period": period,
        "empresa": empresa,
        "fecha_de_emision": "01/08/2026",
        "tipo_doc_emitido": "RH",
        "nro_doc_emitido": nro,
        "renta_bruta": "100.00",
    }


def test_crea_la_tabla_seesol_rh(tmp_path):
    res = SeesolRhSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res._ensure_db()
    assert "seesol_rh" in db_mod.db.get_tables()


def test_upsert_month_reemplaza_solo_su_mes_y_empresa(tmp_path):
    res = SeesolRhSqliteResource(database_path=str(tmp_path / "db.sqlite"))

    assert res.upsert_month("2026-08-01", "Air Majoro", [_fila("E001-1", "2026-08-01", "Air Majoro")]) == 1
    assert res.upsert_month("2026-08-01", "Air Majoro Selva", [_fila("E002-1", "2026-08-01", "Air Majoro Selva")]) == 1
    assert res.upsert_month("2026-07-01", "Air Majoro", [_fila("E001-9", "2026-07-01", "Air Majoro")]) == 1

    # Re-upsert del mismo mes+empresa: sustituye, no acumula.
    assert res.upsert_month("2026-08-01", "Air Majoro", [_fila("E001-2", "2026-08-01", "Air Majoro")]) == 1

    assert res.count_month("2026-08-01", "Air Majoro") == 1
    assert sorted(
        f.nro_doc_emitido for f in Rh.select().where(Rh.empresa == "Air Majoro")
    ) == ["E001-2", "E001-9"]
    # La otra empresa y el otro mes siguen intactos.
    assert res.count_month("2026-08-01", "Air Majoro Selva") == 1
    assert Rh.select().count() == 3


def test_upsert_month_con_lista_vacia_limpia_ese_mes(tmp_path):
    res = SeesolRhSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.upsert_month("2026-08-01", "Air Majoro", [_fila("E001-1", "2026-08-01", "Air Majoro")])

    assert res.upsert_month("2026-08-01", "Air Majoro", []) == 0
    assert res.count_month("2026-08-01", "Air Majoro") == 0
