"""Tests de CorpacDataSqliteResource (select de PDFs 01-* del día y upsert total de cabeceras/detalles)."""

import pytest

from assets.from_email_assets.corpac_assets.corpac_data_asset.models.model import CorpacDetail, CorpacHeader
from assets.from_email_assets.corpac_assets.corpac_data_asset.resources.db_resource import CorpacDataSqliteResource
from assets.from_email_assets.corpac_assets.corpac_files_asset.models.model import CorpacFile
from assets.mail_asset.model import Email, db


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


def _resource(tmp_path):
    return CorpacDataSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _file(id_email, partition, filename, data="QUJD"):
    return CorpacFile.create(
        id_email=id_email, partition_date=partition, filename=filename, data=data
    )


def _header(filename, factura="F0250001", section=0):
    return {
        "file_id": 1,
        "filename": filename,
        "_section": section,
        "factura": factura,
        "fecha_doc": "11/08/2026",
        "fch_impresion": "12/08/2026",
        "hora": "00:19:46",
        "pagina": "1 de 1",
        "cliente": "306390 AIR MAJORO SOCIEDAD ANONIMA",
        "matricula": "OB-2200",
        "tipo_aeronave": "CESSNA C-208",
        "pmd": "3.10",
    }


def _detail(filename, section=0):
    return {
        "filename": filename,
        "_section": section,
        "servicio": "SNAR NACIONAL SOLES",
        "aeropuerto_origen": "SPCL",
        "aeropuerto_destino": "SPAY",
        "vuelo_llegada": "",
        "vuelo_salida": "ESP01",
        "ruta_aerea": "SPCL DCT SPAY",
        "total_km": "274.72",
        "fecha_llegada": "11/08/2026 15:12",
        "fecha_salida": "11/08/2026 14:12",
        "total_min": "",
        "moneda": "S/",
        "precio_unitario": "35.66",
    }


def test_select_corpac_pdfs_filtra_dia_prefijo_y_extension(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _file("e1", "2026-08-12", "01-F02500029006.pdf")
    _file("e1", "2026-08-12", "20100004675-01-F025-00029006.pdf")  # no 01-
    _file("e1", "2026-08-12", "01-F02500029006.xml")  # no pdf
    _file("e1", "2026-08-11", "01-F02500028997.pdf")  # otro día

    rows = res.select_corpac_pdfs("2026-08-12")

    assert [r["filename"] for r in rows] == ["01-F02500029006.pdf"]
    assert rows[0]["id"] == CorpacFile.select().where(
        CorpacFile.filename == "01-F02500029006.pdf"
    ).get().id


def test_select_corpac_pdfs_sin_archivos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_corpac_pdfs("2026-08-12") == []


def test_select_corpac_pdfs_una_copia_por_documento(tmp_path):
    """El mismo PDF ingerido N veces (2 buzones + respuestas del hilo) es UN documento.

    Se devuelve la copia de menor ``id`` y ``copies`` con el nº de copias, para que el
    asset no vuelva a parsearlo (era lo que multiplicaba las cabeceras y ``moves``).
    """
    res = _resource(tmp_path)
    res._ensure_db()
    primera = _file("e1", "2026-08-12", "01-F02500029006.pdf")
    _file("e1", "2026-08-12", "01-F02500029006.pdf")
    _file("e2", "2026-08-12", "01-F02500029006.pdf")
    _file("e2", "2026-08-12", "01-F02500028997.pdf")

    rows = res.select_corpac_pdfs("2026-08-12")

    assert [r["filename"] for r in rows] == [
        "01-F02500029006.pdf",
        "01-F02500028997.pdf",
    ]
    assert rows[0]["id"] == primera.id  # la copia canónica es la de menor ``id``
    assert rows[0]["copies"] == 3
    assert rows[1]["copies"] == 1
    assert rows[0]["data"] == "QUJD"


def test_select_corpac_pdfs_copia_canonica_es_global(tmp_path):
    """La copia canónica se busca en toda la tabla: si el documento se ingirió en otro
    día, no se vuelve a crear su cabecera (``corpac_purchs_std`` cruza por ``factura`` y
    duplicaría ``moves``)."""
    res = _resource(tmp_path)
    res._ensure_db()
    primera = _file("e1", "2026-08-11", "01-F02500029006.pdf")
    _file("e1", "2026-08-12", "01-F02500029006.pdf")

    assert res.select_corpac_pdfs("2026-08-11")[0]["id"] == primera.id
    assert res.select_corpac_pdfs("2026-08-12") == []


def test_upsert_day_borra_el_dia_e_inserta_con_fk(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    headers = [_header("01-A.pdf", "F0250001"), _header("01-B.pdf", "F0250002")]
    details = [_detail("01-A.pdf"), _detail("01-A.pdf"), _detail("01-B.pdf")]

    n_h, n_d = res.upsert_day("2026-08-12", headers, details)

    assert (n_h, n_d) == (2, 3)
    assert CorpacHeader.select().count() == 2
    assert CorpacDetail.select().count() == 3

    # Cada detalle apunta a la cabecera de su PDF (mismo filename).
    a = CorpacHeader.get(CorpacHeader.filename == "01-A.pdf")
    b = CorpacHeader.get(CorpacHeader.filename == "01-B.pdf")
    assert CorpacDetail.select().where(CorpacDetail.header == a).count() == 2
    assert CorpacDetail.select().where(CorpacDetail.header == b).count() == 1
    det = CorpacDetail.select().where(CorpacDetail.header == a).get()
    assert det.servicio == "SNAR NACIONAL SOLES"
    assert det.partition_date == "2026-08-12"

    # Re-upsertar el día: borra TODO lo del día y deja solo lo nuevo.
    n_h, n_d = res.upsert_day("2026-08-12", [_header("01-C.pdf")], [_detail("01-C.pdf")])
    assert (n_h, n_d) == (1, 1)
    assert CorpacHeader.select().count() == 1
    assert CorpacDetail.select().count() == 1
    assert CorpacHeader.get().filename == "01-C.pdf"


def test_upsert_day_varias_secciones_de_la_misma_factura(tmp_path):
    """Una factura con varias aeronaves genera una cabecera por sección."""
    res = _resource(tmp_path)
    res._ensure_db()
    # 3 secciones del mismo PDF (3 aeronaves), con matrícula distinta.
    matricula_por_seccion = {0: "OB-2092P", 1: "OB-2209", 2: "OB-2221P"}
    headers = [
        {**_header("01-F00100150472.pdf", "F0010150472", section=i),
         "matricula": matricula_por_seccion[i]}
        for i in range(3)
    ]
    details = [_detail("01-F00100150472.pdf", section=i) for i in range(3)]

    n_h, n_d = res.upsert_day("2026-08-12", headers, details)

    assert (n_h, n_d) == (3, 3)
    assert CorpacHeader.select().count() == 3
    assert CorpacDetail.select().count() == 3

    # Cada detalle apunta a la cabecera de su sección (matrícula correcta).
    # Los detalles se insertan en orden: el i-ésimo pertenece a la sección i.
    for i, det in enumerate(CorpacDetail.select().order_by(CorpacDetail.id)):
        assert det.header.matricula == matricula_por_seccion[i]
        assert det.header.filename == "01-F00100150472.pdf"


def test_upsert_day_no_crea_cabecera_repetida_del_mismo_pdf(tmp_path):
    """Dos copias del mismo PDF (``filename``) no crean dos cabeceras de la factura.

    La tabla ``from_email_corpac_headers`` es 1:1 con el documento; el guardado del
    upsert mantiene ese contrato aunque le llegue el PDF repetido.
    """
    res = _resource(tmp_path)
    res._ensure_db()
    headers = [_header("01-A.pdf", "F0250001"), _header("01-A.pdf", "F0250001")]

    n_h, _n_d = res.upsert_day("2026-08-12", headers, [_detail("01-A.pdf")])

    assert n_h == 1
    assert CorpacHeader.select().count() == 1
    assert CorpacHeader.get().filename == "01-A.pdf"


def test_upsert_day_no_toca_otros_dias(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    res.upsert_day("2026-08-11", [_header("01-A.pdf")], [_detail("01-A.pdf")])
    res.upsert_day("2026-08-12", [_header("01-B.pdf")], [_detail("01-B.pdf")])

    assert CorpacHeader.select().count() == 2
    assert CorpacDetail.select().count() == 2
    assert (
        CorpacDetail.select()
        .join(CorpacHeader)
        .where(CorpacHeader.filename == "01-A.pdf")
        .count()
        == 1
    )


def test_upsert_day_vacio_limpia_el_dia(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    res.upsert_day("2026-08-12", [_header("01-A.pdf")], [_detail("01-A.pdf")])

    n_h, n_d = res.upsert_day("2026-08-12", [], [])

    assert (n_h, n_d) == (0, 0)
    assert CorpacHeader.select().count() == 0
    assert CorpacDetail.select().count() == 0


def test_upsert_day_muchas_filas_chunked(tmp_path, monkeypatch):
    """Muchos detalles no deben superar el límite de variables SQL de SQLite."""
    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 10)
    res = _resource(tmp_path)
    res._ensure_db()
    headers = [_header(f"01-F{i:05d}.pdf") for i in range(50)]
    details = [_detail(f"01-F{i:05d}.pdf") for i in range(50)]

    n_h, n_d = res.upsert_day("2026-08-12", headers, details)

    assert (n_h, n_d) == (50, 50)
    assert CorpacDetail.select().count() == 50
