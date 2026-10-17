"""Tests de TerpelInvoicemSqliteResource (select del día y upsert de docs/tickets/reportes)."""

import pytest

from assets.mail_asset.model import Email, EmailAttachments, db
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.models.model import (
    InvoicemDoc,
    InvoicemReport,
    InvoicemTicket,
)
from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.resources.db_resource import (
    SENDER_INVOICE_LUBES,
    TerpelInvoicemSqliteResource,
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
    return TerpelInvoicemSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _email(eid, partition, sender=SENDER_INVOICE_LUBES, subject="facturas"):
    return Email.create(
        id=eid, partition_date=partition, sender=sender, subject=subject
    )


def _attachment(eid, filename, data="QUJD"):
    return EmailAttachments.create(email=eid, filename=filename, data=data)


def _doc(id_attachment, filename):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
        "orden_de_compra": "DT 2618503502 PEDIDO: 160128177",
        "observaciones": "",
        "agregado_o_entrega": 2618503502,
    }


def _ticket(id_attachment, filename, o_entrega="450001234"):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
        "o_entrega": o_entrega,
        "estacion": "LIM",
        "matricula": "ABC-123",
        "galones": "166",
    }


def _report(id_attachment, filename, ticket="2600603901"):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
        "fecha": "2026-01-06",
        "ticket": ticket,
        "producto": "JET",
        "aerolinea": "AIR MAJORO S.A.C",
        "vuelo": "2092",
        "galones": "67",
        "scop": "12636963345",
        "precio": "2.53",
        "monto": "169.51",
        "n_factura": "FV02-00031982",
    }


def test_select_invoicem_emails_filtra_dia_y_remitente(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    _email("e2", "2026-08-14", sender="otro@correo.com")
    _email("e3", "2026-08-01")   # otro día del mismo mes
    _email("e4", "2026-07-31")   # otro mes

    rows = res.select_invoicem_emails("2026-08-14")

    assert sorted(r["id"] for r in rows) == ["e1"]
    assert rows[0]["subject"] == "facturas"


def test_select_invoicem_emails_sin_correos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_invoicem_emails("2026-08-14") == []


def test_select_invoicem_attachments_solo_de_los_correos_dados(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    _email("e2", "2026-08-14")
    _attachment("e1", "FACTURA DEL 14.08.2026-MAJORO.zip")
    _attachment("e1", "Reporte abastecimiento 14.08.2026-MAJORO.xlsx")
    _attachment("e2", "otro.zip")

    rows = res.select_invoicem_attachments(["e1"])

    assert [r["filename"] for r in rows] == [
        "FACTURA DEL 14.08.2026-MAJORO.zip",
        "Reporte abastecimiento 14.08.2026-MAJORO.xlsx",
    ]
    assert all(r["email_id"] == "e1" for r in rows)
    assert all(isinstance(r["id_attachment"], int) for r in rows)


def test_select_invoicem_attachments_vacio_sin_ids(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_invoicem_attachments([]) == []


def test_upsert_docs_day_borra_el_dia_e_inserta(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "FACTURA DEL 14.08.2026-MAJORO.zip")
    a2 = _attachment("e1", "Fact_14-08-2026_FV02-00033000.pdf")

    n = res.upsert_docs_day(
        "2026-08-14", [_doc(a1.id, "Fact_1.pdf"), _doc(a2.id, "Fact_2.pdf")]
    )

    assert n == 2
    assert InvoicemDoc.select().count() == 2
    assert InvoicemDoc.get(InvoicemDoc.filename == "Fact_1.pdf").id_attachment == a1.id

    # Re-upsertar el día: borra TODO lo del día y deja solo lo nuevo.
    n2 = res.upsert_docs_day("2026-08-14", [_doc(a2.id, "Fact_9.pdf")])
    assert n2 == 1
    assert InvoicemDoc.select().count() == 1
    assert InvoicemDoc.get().filename == "Fact_9.pdf"


def test_upsert_tickets_day_borra_el_dia_e_inserta(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "ORDENES DE ENTREGA DEL 14.08.2026-MAJORO.zip")

    n = res.upsert_tickets_day(
        "2026-08-14", [_ticket(a1.id, "Reimpresion_2600803905.pdf")]
    )

    assert n == 1
    t = InvoicemTicket.get()
    assert t.o_entrega == "450001234"
    assert t.matricula == "ABC-123"
    assert t.partition_date == "2026-08-14"
    assert t.id_attachment == a1.id


def test_upsert_reports_day_borra_el_dia_e_inserta(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "Reporte abastecimiento 14.08.2026-MAJORO.xlsx")

    n = res.upsert_reports_day(
        "2026-08-14",
        [_report(a1.id, "Reporte abastecimiento 14.08.2026-MAJORO.xlsx")],
    )

    assert n == 1
    r = InvoicemReport.get()
    assert r.ticket == "2600603901"
    assert r.n_factura == "FV02-00031982"
    assert r.filename == "Reporte abastecimiento 14.08.2026-MAJORO.xlsx"
    assert r.partition_date == "2026-08-14"
    assert r.id_attachment == a1.id


def test_upsert_no_toca_otros_dias(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "a.zip")
    res.upsert_docs_day("2026-08-13", [_doc(a1.id, "Fact_1.pdf")])
    res.upsert_docs_day("2026-08-14", [_doc(a1.id, "Fact_2.pdf")])

    assert InvoicemDoc.select().count() == 2
    assert (
        InvoicemDoc.select()
        .where(InvoicemDoc.partition_date == "2026-08-13")
        .count()
        == 1
    )
