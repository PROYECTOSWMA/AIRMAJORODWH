"""Tests de SireFilesSqliteResource (archivos PDF/ZIP por período en SQLite temporal)."""

from datetime import date

import pytest

from assets.sire_assets.sire_files_asset.models.model import (
    SirePurchsFiles,
    SireSalesFiles,
)
from assets.sire_assets.sire_files_asset.resources.api_resource.constants import (
    FILE_KIND_PDF,
    FILE_KIND_ZIP,
)
from assets.sire_assets.sire_files_asset.resources.db_resource import (
    SireFilesSqliteResource,
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


def _file(sire_id, tipo_documento=FILE_KIND_PDF, nom="a.pdf", val="QUJD", fk="sire_sale"):
    return {
        fk: sire_id,
        "tipo_documento": tipo_documento,
        "nom_archivo": nom,
        "val_archivo": val,
    }


def _resource(tmp_path):
    return SireFilesSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _sales(period="202607", empresa="Air Majoro", serie="F001", numero=1, fecha=None):
    return SireSales.create(
        period=period,
        empresa=empresa,
        tipo_cp_doc=1,
        serie_del_cdp=serie,
        nro_cp_o_doc_nro_inicial_rango=numero,
        fecha_de_emision=fecha,
    )


def test_insert_files_inserta_y_respeta_lo_existente(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    parent = _sales()
    n = res.insert_files(
        "202607",
        "Air Majoro",
        rows=[_file(parent.id), _file(parent.id, FILE_KIND_ZIP, "b.zip")],
        book_code=BOOK_CODE_SALES,
    )
    assert n == 2
    assert SireSalesFiles.select().count() == 2
    assert SireSalesFiles.get().sire_sale_id == parent.id
    assert SireSalesFiles.get().empresa == "Air Majoro"

    n2 = res.insert_files(
        "202607",
        "Air Majoro",
        rows=[_file(parent.id, FILE_KIND_ZIP, "b2.zip")],
        book_code=BOOK_CODE_SALES,
    )
    assert n2 == 1
    assert SireSalesFiles.select().count() == 3


def test_select_missing_files_solo_los_que_faltan_por_tipo(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    con_pdf = _sales(serie="F001", numero=1, fecha=date(2026, 7, 8))
    con_zip = _sales(serie="F002", numero=2, fecha=date(2026, 7, 8))
    sin_nada = _sales(serie="F003", numero=3, fecha=date(2026, 7, 8))
    res.insert_files(
        "2026-07-05", "Air Majoro",
        rows=[_file(con_pdf.id, FILE_KIND_PDF)], book_code=BOOK_CODE_SALES,
    )
    res.insert_files(
        "2026-07-05", "Air Majoro",
        rows=[_file(con_zip.id, FILE_KIND_ZIP)], book_code=BOOK_CODE_SALES,
    )

    pdfs = res.select_missing_files(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", FILE_KIND_PDF,
        book_code=BOOK_CODE_SALES,
    )
    assert sorted(d["id"] for d in pdfs) == [con_zip.id, sin_nada.id]

    zips = res.select_missing_files(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", FILE_KIND_ZIP,
        book_code=BOOK_CODE_SALES,
    )
    assert sorted(d["id"] for d in zips) == [con_pdf.id, sin_nada.id]


def test_select_missing_files_compras_usa_tabla_de_compras(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    compra = SirePurchs.create(
        period="202607",
        empresa="Air Majoro",
        tipo_cp_doc=3,
        serie_del_cdp="B100",
        nro_cp_o_doc_nro_inicial_rango=7,
        fecha_de_emision=date(2026, 7, 8),
        nro_doc_identidad="20100047218",
    )
    faltan = res.select_missing_files(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", FILE_KIND_PDF,
        book_code=BOOK_CODE_PURCHASES,
    )
    assert [d["id"] for d in faltan] == [compra.id]
    assert faltan[0]["nro_doc_identidad"] == "20100047218"


def test_select_missing_files_primer_dia_del_mes_incluye_emitidos_antes_del_periodo(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    anterior = _sales(period="202607", serie="F001", numero=1, fecha=date(2026, 6, 30))
    del_dia = _sales(period="202607", serie="F002", numero=2, fecha=date(2026, 7, 1))
    # Mismo mes pero OTRO periodo: no debe entrar ni emitido antes ni el día 1.
    _sales(period="202606", serie="F003", numero=3, fecha=date(2026, 6, 30))
    _sales(period="202606", serie="F004", numero=4, fecha=date(2026, 7, 1))

    faltan = res.select_missing_files(
        date(2026, 7, 1), date(2026, 7, 2), "Air Majoro", FILE_KIND_PDF,
        book_code=BOOK_CODE_SALES,
    )
    assert sorted(d["id"] for d in faltan) == [anterior.id, del_dia.id]


def test_select_missing_files_dia_no_primero_solo_del_mismo_periodo(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    del_mes = _sales(period="202607", serie="F001", numero=1, fecha=date(2026, 7, 8))
    _sales(period="202607", serie="F002", numero=2, fecha=date(2026, 6, 30))  # fuera de ventana
    _sales(period="202606", serie="F003", numero=3, fecha=date(2026, 7, 8))  # en ventana, otro periodo

    faltan = res.select_missing_files(
        date(2026, 7, 5), date(2026, 7, 12), "Air Majoro", FILE_KIND_PDF,
        book_code=BOOK_CODE_SALES,
    )
    assert [d["id"] for d in faltan] == [del_mes.id]


def test_delete_orphan_files_limpia_archivos_sin_padre(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    padre = _sales()  # id 1
    # otra fila de otro período mantiene alto el contador de rowid de SQLite
    _sales(period="202608", serie="F002")  # id 2
    res.insert_files(
        "202607", "Air Majoro",
        rows=[_file(padre.id), _file(padre.id, FILE_KIND_ZIP, "b.zip")],
        book_code=BOOK_CODE_SALES,
    )
    # Simula el re-upsert de la propuesta: el padre se borra e inserta con id nuevo.
    SireSales.delete().where(
        (SireSales.period == "202607") & (SireSales.empresa == "Air Majoro")
    ).execute()
    nuevo = _sales(serie="F003")  # id 3: el id 2 sigue ocupado por el otro período
    assert nuevo.id != padre.id
    res.insert_files(
        "202608", "Air Majoro",
        rows=[_file(nuevo.id, FILE_KIND_PDF)], book_code=BOOK_CODE_SALES,
    )

    n = res.delete_orphan_files("202607", "Air Majoro", book_code=BOOK_CODE_SALES)
    assert n == 2
    # Los archivos del padre borrado se fueron; el del padre existente se mantiene.
    assert SireSalesFiles.select().count() == 1
    assert SireSalesFiles.get().sire_sale_id == nuevo.id
