"""Tests de ``CepDocsSqliteResource`` (select de PDFs del día y upsert total).

Cubre el filtro por día/remitente, la deduplicación por nombre de archivo (el mismo
PDF llega a las dos bandejas), y el upsert total de cabecera + detalle con la FK.
"""

import pytest

from assets.mail_asset.model import Email, EmailAttachments, db
from assets.from_email_assets.cep_docs_asset.models.model import (
    CepDocDetail,
    CepDocHeader,
)
from assets.from_email_assets.cep_docs_asset.resources.db_resource import (
    CEP_SENDER,
    CepDocsSqliteResource,
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


def _resource(tmp_path):
    return CepDocsSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _email(eid, partition, sender=CEP_SENDER, subject="factura"):
    return Email.create(
        id=eid, partition_date=partition, sender=sender, subject=subject
    )


def _attachment(eid, filename, data="QUJD"):
    return EmailAttachments.create(email=eid, filename=filename, data=data)


def _header(id_attachment, filename, factura="F002-009674", placa="OB-1919"):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
        "factura": factura,
        "tipo_documento": "FACTURA",
        "fecha_emision": "31/12/2025",
        "cliente": "AIR MAJORO S.A.",
        "ruc_cliente": "20494626978",
        "direccion": "AV ARGENTINA NRO 4065 ZI CALLAO",
        "cod_del_cliente": "NZA/SPZA",
        "n_de_guia": "2",
        "cod_vendedor": "115984",
        "cond_pago": "Contado",
        "moneda": "DOLARES",
        "o_c": "2009689",
        "transportista": "AIR MAJORO S.A.",
        "chofer": "PILMER D. CESPEDES LOZANO",
        "son": "DOSCIENTOS SESENTA Y CUATRO Y 79/100 DOLARES AMERICANOS",
        "placa": placa,
        "op_gravadas": "224.40",
        "op_exoneradas": "0.00",
        "igv": "40.39",
        "importe_total": "264.79",
        "codigo_scop": "12634330075",
    }


def _detail(filename):
    return {
        "filename": filename,
        "codigo": "AV",
        "cant": "20.00",
        "descripcion": "AV GAS 100LL",
        "u_m": "GLL",
        "valor_unit": "11.2200",
        "precio_unit": "13.2396",
        "valor_venta": "224.40",
    }


def test_select_cep_pdf_attachments_filtra_dia_remitente_y_pdf(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-01-02")
    _email("e2", "2026-01-02", sender="  FE.Corporacion.Energetico@Gmail.com  ")
    _email("e3", "2026-01-02", sender="otro@correo.com")  # no es el remitente
    _email("e4", "2026-01-03")  # otro día
    _attachment("e1", "20613566881-01-F002-009674.PDF")
    _attachment("e1", "20613566881-01-F002-009674.XML")  # se ignora
    _attachment("e3", "otro.pdf")

    rows = res.select_cep_pdf_attachments("2026-01-02")

    assert [r["filename"] for r in rows] == ["20613566881-01-F002-009674.PDF"]


def test_select_cep_pdf_attachments_dedupe_por_nombre(tmp_path):
    """El mismo PDF llega a las dos bandejas: se procesa una sola vez."""
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-01-02")
    _email("e2", "2026-01-02")
    _attachment("e1", "20613566881-01-F002-009674.PDF", data="QQ==")
    _attachment("e2", "20613566881-01-F002-009674.PDF", data="Qg==")

    rows = res.select_cep_pdf_attachments("2026-01-02")

    assert len(rows) == 1
    assert rows[0]["data"] == "QQ=="  # gana el primero (por id de email/adjunto)


def test_upsert_day_inserta_cabecera_y_detalles(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-01-02")
    a1 = _attachment("e1", "20613566881-01-F002-009674.PDF")
    headers = [_header(a1.id, "20613566881-01-F002-009674.PDF")]
    details = [_detail("20613566881-01-F002-009674.PDF")]

    n_headers, n_details = res.upsert_day("2026-01-02", headers, details)

    assert (n_headers, n_details) == (1, 1)
    h = CepDocHeader.get()
    assert h.factura == "F002-009674"
    assert h.placa == "OB-1919"
    assert h.cod_vendedor == "115984"
    assert h.partition_date == "2026-01-02"
    assert h.id_attachment == a1.id
    d = CepDocDetail.get()
    assert d.header_id == h.id
    assert d.codigo == "AV"
    assert d.descripcion == "AV GAS 100LL"
    assert d.partition_date == "2026-01-02"


def test_upsert_day_reemplaza_el_dia_y_limpia_detalles(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-01-02")
    a1 = _attachment("e1", "a.PDF")
    a2 = _attachment("e1", "b.PDF")
    res.upsert_day(
        "2026-01-02",
        [_header(a1.id, "a.PDF", factura="F001-1")],
        [_detail("a.PDF")],
    )
    assert CepDocHeader.select().count() == 1
    assert CepDocDetail.select().count() == 1

    # Re-upsertar el día: borra cabeceras y detalles del día y deja solo lo nuevo.
    res.upsert_day(
        "2026-01-02",
        [_header(a2.id, "b.PDF", factura="F001-2")],
        [_detail("b.PDF"), _detail("b.PDF")],
    )
    assert CepDocHeader.select().count() == 1
    assert CepDocHeader.get().factura == "F001-2"
    assert CepDocDetail.select().count() == 2
    assert {d.header_id for d in CepDocDetail.select()} == {CepDocHeader.get().id}
