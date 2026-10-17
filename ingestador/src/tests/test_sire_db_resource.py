"""Tests de SireSqliteResource (insert append-only por período en SQLite temporal).

El resource solo **añade** comprobantes nuevos (``insert_proposal_new``): nunca
borra ni actualiza, para que los ids del padre sean estables entre corridas y sus
hijos (``sire_*_details`` / ``sire_*_files``) no queden huérfanos. La clave natural
es ``(empresa, tipo_cp_doc, serie, número, nro_doc_identidad)``: **la primera
versión gana**.
"""

import pytest

from assets.sire_assets.sire_proposal_asset.models.model import SirePurchs, SireSales, db
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_SALES,
)
from assets.sire_assets.sire_proposal_asset.resources.db_resource import (
    SireSqliteResource,
)


@pytest.fixture(autouse=True)
def _clean_db():
    # db es un singleton global: cerrar la conexión entre tests para que cada
    # uno apunte al archivo SQLite temporal que le corresponde.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)


def _row(
    serie: str = "E001",
    numero: int = 1,
    contraparte: str = "20607496961",
    car_sunat: str = "F001",
    total: str = "100.50",
) -> dict:
    return {
        "ruc": 20494626978,
        "periodo": "202607",
        "car_sunat": car_sunat,
        "fecha_de_emision": "2026-07-04",
        "tipo_cp_doc": 1,
        "serie_del_cdp": serie,
        "nro_cp_o_doc_nro_inicial_rango": numero,
        "tipo_doc_identidad": 6,
        "nro_doc_identidad": contraparte,
        "apellidos_nombres_razon_social": "AIR MAJORO SELVA S.A.C.",
        "bi_gravado_dg": "0.00",
        "igv_ipm_dg": "0.00",
        "bi_gravado_dgng": "0.00",
        "igv_ipm_dgng": "0.00",
        "bi_gravado_dng": "0.00",
        "igv_ipm_dng": "0.00",
        "valor_adq_ng": "250.00",
        "isc": "0.00",
        "icbper": "0.00",
        "otros_trib_cargos": "0.00",
        "total_cp": total,
        "moneda": "PEN",
        "tipo_de_cambio": "1.000",
        "est_comp": 1,
        "incal": 0,
    }


def test_inserta_las_filas_nuevas(tmp_path):
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    n = res.insert_proposal_new(
        "202607",
        [_row("E001", 1), _row("E002", 2)],
        empresa="Air Majoro",
    )
    assert n == 2
    assert SirePurchs.select().where(SirePurchs.period == "202607").count() == 2


def test_segunda_corrida_no_duplica_ni_borra(tmp_path):
    """Re-materializar el mismo mes es idempotente (append-only)."""
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    filas = [_row("E001", 1), _row("E002", 2)]
    assert res.insert_proposal_new("202607", filas, empresa="Air Majoro") == 2

    assert res.insert_proposal_new("202607", filas, empresa="Air Majoro") == 0
    assert SirePurchs.select().where(SirePurchs.period == "202607").count() == 2


def test_rectificatoria_no_actualiza_la_primera_version(tmp_path):
    """La primera versión gana: mismo comprobante con otros montos no se toca."""
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.insert_proposal_new(
        "202607",
        [_row("E001", 1, car_sunat="F001", total="100.50")],
        empresa="Air Majoro",
    )

    # Misma clave natural (mismo emisor, tipo, serie y número) pero corregido.
    assert (
        res.insert_proposal_new(
            "202607",
            [_row("E001", 1, car_sunat="F999", total="999.99")],
            empresa="Air Majoro",
        )
        == 0
    )
    assert SirePurchs.select().count() == 1
    fila = SirePurchs.get()
    assert fila.car_sunat == "F001"
    assert float(fila.total_cp) == 100.50


def test_duplicados_dentro_de_la_misma_corrida(tmp_path):
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    n = res.insert_proposal_new(
        "202607",
        [_row("E001", 1), _row("E001", 1), _row("E002", 2)],
        empresa="Air Majoro",
    )
    assert n == 2


def test_inserta_ventas_en_su_tabla(tmp_path):
    """``book_code=SALES`` inserta en ``sire_sales`` (columnas propias de ventas)."""
    libre_venta = {
        "car_sunat": "F001",
        "fecha_de_emision": "2026-07-04",
        "tipo_cp_doc": 1,
        "serie_del_cdp": "F001",
        "nro_cp_o_doc_nro_inicial_rango": 100,
        "nro_doc_identidad": "20607496961",
        "total_cp": "100.50",
        "moneda": "PEN",
    }
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    n = res.insert_proposal_new(
        "202607",
        [libre_venta],
        book_code=BOOK_CODE_SALES,
        empresa="Air Majoro",
    )
    assert n == 1
    assert SireSales.select().count() == 1
    assert SirePurchs.select().count() == 0
    # Segunda corrida: la misma clave natural no vuelve a entrar.
    assert (
        res.insert_proposal_new(
            "202607", [libre_venta], book_code=BOOK_CODE_SALES, empresa="Air Majoro"
        )
        == 0
    )


def test_misma_clave_en_otra_empresa_se_inserta(tmp_path):
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.insert_proposal_new("202607", [_row("E001", 1)], empresa="Air Majoro")
    n = res.insert_proposal_new("202607", [_row("E001", 1)], empresa="Air Majoro Selva")

    assert n == 1

    def count(empresa):
        return (
            SirePurchs.select()
            .where((SirePurchs.period == "202607") & (SirePurchs.empresa == empresa))
            .count()
        )

    assert count("Air Majoro") == 1
    assert count("Air Majoro Selva") == 1


def test_mismo_numero_de_otro_emisor_se_inserta(tmp_path):
    """Dos proveedores pueden usar la misma serie/número: la contraparte está en la clave."""
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.insert_proposal_new(
        "202607", [_row("E001", 1, contraparte="20100047218")], empresa="Air Majoro"
    )
    n = res.insert_proposal_new(
        "202607", [_row("E001", 1, contraparte="20602542115")], empresa="Air Majoro"
    )

    assert n == 1
    assert SirePurchs.select().count() == 2


def test_no_toca_otros_periodos(tmp_path):
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    res.insert_proposal_new("202607", [_row("E001", 1)], empresa="Air Majoro")
    res.insert_proposal_new("202608", [_row("G001", 1)], empresa="Air Majoro")

    assert SirePurchs.select().where(SirePurchs.period == "202607").count() == 1
    assert SirePurchs.select().where(SirePurchs.period == "202608").count() == 1


def test_sin_filas_no_hace_nada(tmp_path):
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    assert res.insert_proposal_new("202607", [], empresa="Air Majoro") == 0
    assert SirePurchs.select().count() == 0


def test_muchas_filas_chunked(tmp_path, monkeypatch):
    """Muchas filas no deben superar el límite de variables SQL de SQLite.

    Se baja ``_SQLITE_MAX_VARIABLES`` para forzar varios lotes y comprobar el
    insert particionado (batch_size = 100 // nº de columnas).
    """
    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = SireSqliteResource(database_path=str(tmp_path / "db.sqlite"))
    rows = [_row(f"E{i:04d}", i) for i in range(1, 51)]
    n = res.insert_proposal_new("202607", rows, empresa="Air Majoro")

    assert n == 50
    assert SirePurchs.select().where(SirePurchs.period == "202607").count() == 50
    assert SirePurchs.get(SirePurchs.serie_del_cdp == "E0050") is not None
