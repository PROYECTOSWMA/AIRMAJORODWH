"""Tests de SireDetailsSqliteResource (insert append-only de detalles por período)."""

from datetime import date

import pytest

from assets.sire_assets.sire_details_asset.models.model import (
    SirePurchsDetails,
    SireSalesDetails,
)
from assets.sire_assets.sire_details_asset.resources.db_resource import (
    SireDetailsSqliteResource,
)
from assets.sire_assets.sire_proposal_asset.models.model import SirePurchs, SireSales, db
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    BOOK_CODE_PURCHASES,
    BOOK_CODE_SALES,
)


@pytest.fixture(autouse=True)
def _clean_db():
    # db es un singleton global: cerrar la conexión entre tests para que cada uno
    # apunte al archivo SQLite temporal que le corresponde.
    yield
    if db.obj is not None:
        try:
            db.obj.close()
        except Exception:
            pass
        db.initialize(None)


def _item(sire_id, des_item="ITEM", mto="10.50", fk="sire_sale"):
    return {
        fk: sire_id,
        "cnt_items": 1,
        "cod_unidad_medida": "ZZ",
        "des_unidad_medida": "UNIDAD",
        "des_codigo": "3300000106",
        "des_item": des_item,
        "mto_val_unitario": "10.50",
        "mto_icbper": "0.00",
        "mto_desc": "0.00",
        "mto_imp_total": mto,
    }


def _resource(tmp_path):
    return SireDetailsSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _sales(period="202607", empresa="Air Majoro", serie="F001", numero=1, fecha=None):
    return SireSales.create(
        period=period,
        empresa=empresa,
        tipo_cp_doc=1,
        serie_del_cdp=serie,
        nro_cp_o_doc_nro_inicial_rango=numero,
        fecha_de_emision=fecha,
    )


def test_insert_details_inserta_y_respeta_lo_existente(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    parent = _sales()
    n = res.insert_details(
        "202607",
        "Air Majoro",
        rows=[_item(parent.id), _item(parent.id, "ITEM 2")],
        book_code=BOOK_CODE_SALES,
    )
    assert n == 2
    assert (
        SireSalesDetails.select()
        .where(
            (SireSalesDetails.period == "202607")
            & (SireSalesDetails.empresa == "Air Majoro")
        )
        .count()
        == 2
    )
    assert SireSalesDetails.get().sire_sale_id == parent.id
    assert SireSalesDetails.get().empresa == "Air Majoro"

    # Append-only: re-insertar NO borra, solo agrega.
    n2 = res.insert_details(
        "202607", "Air Majoro", rows=[_item(parent.id)], book_code=BOOK_CODE_SALES
    )
    assert n2 == 1
    assert SireSalesDetails.select().where(SireSalesDetails.period == "202607").count() == 3


def test_insert_details_no_toca_otros_periodos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    p1 = _sales()
    p2 = _sales(period="202608")
    res.insert_details(
        "202607", "Air Majoro", rows=[_item(p1.id)], book_code=BOOK_CODE_SALES
    )
    res.insert_details(
        "202608", "Air Majoro", rows=[_item(p2.id)], book_code=BOOK_CODE_SALES
    )
    assert SireSalesDetails.select().where(SireSalesDetails.period == "202607").count() == 1
    assert SireSalesDetails.select().where(SireSalesDetails.period == "202608").count() == 1


def test_insert_details_dos_empresas_no_se_pisan(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    p1 = _sales()
    p2 = _sales(empresa="Air Majoro Selva")
    res.insert_details(
        "202607", "Air Majoro", rows=[_item(p1.id, "MAJORO")], book_code=BOOK_CODE_SALES
    )
    res.insert_details(
        "202607",
        "Air Majoro Selva",
        rows=[_item(p2.id, "SELVA")],
        book_code=BOOK_CODE_SALES,
    )

    def count(empresa):
        return SireSalesDetails.select().where(
            (SireSalesDetails.period == "202607")
            & (SireSalesDetails.empresa == empresa)
        ).count()

    assert count("Air Majoro") == 1
    assert count("Air Majoro Selva") == 1
    # insertar de nuevo una empresa no toca las filas de la otra
    res.insert_details(
        "202607", "Air Majoro", rows=[_item(p1.id)], book_code=BOOK_CODE_SALES
    )
    assert count("Air Majoro") == 2
    assert count("Air Majoro Selva") == 1


def test_insert_details_muchos_items_particionados(tmp_path, monkeypatch):
    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 100)
    res = _resource(tmp_path)
    res._ensure_db()
    parent = _sales()
    rows = [_item(parent.id, f"ITEM {i}") for i in range(50)]
    n = res.insert_details(
        "202607", "Air Majoro", rows=rows, book_code=BOOK_CODE_SALES
    )
    assert n == 50
    assert SireSalesDetails.select().count() == 50


def test_insert_details_compras_usa_tabla_purchs(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    parent = SirePurchs.create(
        period="202607",
        empresa="Air Majoro",
        serie_del_cdp="E001",
        nro_cp_o_doc_nro_inicial_rango=5,
    )
    res.insert_details(
        "202607",
        "Air Majoro",
        rows=[_item(parent.id, fk="sire_purch")],
        book_code=BOOK_CODE_PURCHASES,
    )
    row = SirePurchsDetails.get()
    assert row.sire_purch_id == parent.id
    assert row.empresa == "Air Majoro"
    assert SireSalesDetails.select().count() == 0


def test_select_documents_filtra_por_fecha_de_emision(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    dentro = _sales(serie="F001", numero=42, fecha=date(2026, 7, 8))
    _sales(serie="F002", numero=43, fecha=date(2026, 7, 4))  # antes de la ventana
    _sales(serie="F003", numero=44, fecha=date(2026, 7, 13))  # después de la ventana
    _sales(serie="F004", numero=45, fecha=None)  # sin fecha -> queda fuera

    docs = res.select_documents(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", book_code=BOOK_CODE_SALES
    )
    assert [d["id"] for d in docs] == [dentro.id]
    assert docs[0]["tipo_cp_doc"] == 1
    assert docs[0]["serie"] == "F001"
    assert docs[0]["numero"] == 42

    assert (
        res.count_documents(
            date(2026, 7, 5), date(2026, 7, 12), "Air Majoro",
            book_code=BOOK_CODE_SALES,
        )
        == 1
    )
    # la ventana no toca filas de otra empresa
    _sales(empresa="Air Majoro Selva", serie="G001", numero=1, fecha=date(2026, 7, 8))
    assert (
        res.count_documents(
            date(2026, 7, 5), date(2026, 7, 12), "Air Majoro Selva",
            book_code=BOOK_CODE_SALES,
        )
        == 1
    )


def test_select_documents_primer_dia_del_mes_incluye_emitidos_antes_del_periodo(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    anterior = _sales(period="202607", serie="F001", numero=1, fecha=date(2026, 6, 30))
    del_dia = _sales(period="202607", serie="F002", numero=2, fecha=date(2026, 7, 1))
    # Mismo mes pero OTRO periodo: no debe entrar ni emitido antes ni el día 1.
    _sales(period="202606", serie="F003", numero=3, fecha=date(2026, 6, 30))
    _sales(period="202606", serie="F004", numero=4, fecha=date(2026, 7, 1))

    docs = res.select_documents(
        date(2026, 7, 1), date(2026, 7, 2), "Air Majoro", book_code=BOOK_CODE_SALES
    )
    assert sorted(d["id"] for d in docs) == [anterior.id, del_dia.id]


def test_select_documents_dia_no_primero_solo_del_mismo_periodo(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    del_mes = _sales(period="202607", serie="F001", numero=1, fecha=date(2026, 7, 8))
    _sales(period="202607", serie="F002", numero=2, fecha=date(2026, 6, 30))  # fuera de ventana
    _sales(period="202606", serie="F003", numero=3, fecha=date(2026, 7, 8))  # en ventana, otro periodo

    docs = res.select_documents(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", book_code=BOOK_CODE_SALES
    )
    assert [d["id"] for d in docs] == [del_mes.id]


def test_select_missing_documents_primer_dia_incluye_emitidos_antes_sin_detalle(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    anterior = _sales(period="202607", serie="F001", numero=1, fecha=date(2026, 6, 30))
    con_detalle = _sales(period="202607", serie="F002", numero=2, fecha=date(2026, 6, 30))
    res.insert_details(
        "2026-07-01",
        "Air Majoro",
        rows=[_item(con_detalle.id)],
        book_code=BOOK_CODE_SALES,
    )

    docs = res.select_missing_documents(
        date(2026, 7, 1), date(2026, 7, 2), "Air Majoro", book_code=BOOK_CODE_SALES
    )
    assert [d["id"] for d in docs] == [anterior.id]


def test_select_missing_documents_solo_los_sin_detalle(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    venta_con_detalle = _sales(serie="F001", numero=1, fecha=date(2026, 7, 8))
    venta_sin_detalle = _sales(serie="F002", numero=2, fecha=date(2026, 7, 8))
    res.insert_details(
        "2026-07-05",
        "Air Majoro",
        rows=[_item(venta_con_detalle.id)],
        book_code=BOOK_CODE_SALES,
    )

    ventas = res.select_missing_documents(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", book_code=BOOK_CODE_SALES
    )
    assert [d["id"] for d in ventas] == [venta_sin_detalle.id]
    assert ventas[0]["serie"] == "F002"
    assert ventas[0]["numero"] == 2

    compra = SirePurchs.create(
        period="202607",
        empresa="Air Majoro",
        serie_del_cdp="E001",
        nro_cp_o_doc_nro_inicial_rango=5,
        fecha_de_emision=date(2026, 7, 8),
    )
    compras = res.select_missing_documents(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", book_code=BOOK_CODE_PURCHASES
    )
    assert [d["id"] for d in compras] == [compra.id]


def test_insert_details_no_borra_lo_existente(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    parent = _sales()
    res.insert_details(
        "202607", "Air Majoro", rows=[_item(parent.id, "ITEM 1")], book_code=BOOK_CODE_SALES
    )

    n = res.insert_details(
        "202607", "Air Majoro", rows=[_item(parent.id, "ITEM 2")], book_code=BOOK_CODE_SALES
    )
    assert n == 1
    assert SireSalesDetails.select().count() == 2
    items = sorted(
        SireSalesDetails.select().where(SireSalesDetails.period == "202607"),
        key=lambda r: r.des_item,
    )
    assert [r.des_item for r in items] == ["ITEM 1", "ITEM 2"]


def test_delete_orphan_details_limpia_detalles_sin_padre(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    padre = _sales()  # id 1
    # otra fila de otro período mantiene alto el contador de rowid de SQLite
    _sales(period="202608", serie="F002")  # id 2
    res.insert_details(
        "202607", "Air Majoro", rows=[_item(padre.id)], book_code=BOOK_CODE_SALES
    )
    # Simula el re-upsert de la propuesta: el padre se borra e inserta con id nuevo.
    SireSales.delete().where(
        (SireSales.period == "202607") & (SireSales.empresa == "Air Majoro")
    ).execute()
    nuevo = _sales(serie="F003")  # id 3: el id 2 sigue ocupado por el otro período
    assert nuevo.id != padre.id
    res.insert_details(
        "202608", "Air Majoro", rows=[_item(nuevo.id)], book_code=BOOK_CODE_SALES
    )

    n = res.delete_orphan_details("202607", "Air Majoro", book_code=BOOK_CODE_SALES)
    assert n == 1
    # El detalle del padre borrado se fue; el del padre existente se mantiene.
    assert SireSalesDetails.select().count() == 1
    assert SireSalesDetails.get().sire_sale_id == nuevo.id

