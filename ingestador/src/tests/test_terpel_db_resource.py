"""Tests de TerpelSqliteResource (select de correos/adjuntos del día y upsert total)."""

import pytest

from assets.mail_asset.model import Email, EmailAttachments, db
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.models.model import TerpelTicket
from assets.from_email_assets.terpel_assets.terpel_tickets_asset.resources.db_resource import (
    TICKETS_SENDER,
    TerpelSqliteResource,
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
    return TerpelSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _email(eid, partition, sender=TICKETS_SENDER, subject="ticket"):
    return Email.create(
        id=eid, partition_date=partition, sender=sender, subject=subject
    )


def _attachment(eid, filename, data="QUJD"):
    return EmailAttachments.create(email=eid, filename=filename, data=data)


def _ticket(id_attachment, filename, o_entrega="450001234", matricula="ABC-123"):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
        "o_entrega": o_entrega,
        "estacion": "LIM",
        "matricula": matricula,
        "fecha": "01/01/2026 10:56",
        "equipo": "RF11 - Refueller",
        "operacion": "SUMINISTRO",
        "producto": "JET A-1",
        "p_abastecimiento": "13",
        "operador": "43675718-BAZALAR NINAMEZA LUIS ALFREDO",
        "cliente": "AIR MAJORO S.A.C",
        "comercializador": "TER/TERPEL COMERCIAL",
        "forma_pago": "CREDITO",
        "nro_vuelo": "2221",
        "destino": "AYP",
        "aeronave": "B 200",
        "hora_llegada": "10:55",
        "hora_conexion": "10:55",
        "hora_final": "11:04",
        "hora_inicial": "10:56",
        "lectura_final": "29,783,940",
        "lectura_inicial": "29,783,774",
        "galones": "166",
        "temperatura": "80.2",
        "flow_rate": "34",
        "api_corregido": "43,0",
        "densidad": "3,035",
        "presion_dif": "17,417",
        "prueba_apariencia": "Cumple",
        "prueba_agua": "Cumple",
    }


def test_select_terpel_emails_filtra_dia_y_remitente(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    _email("e2", "2026-08-14", sender="otro@correo.com")
    _email("e3", "2026-08-01")   # otro día del mismo mes
    _email("e4", "2026-08-31")
    _email("e5", "2026-07-31")   # otro mes
    _email("e6", "2026-09-01")   # otro mes

    rows = res.select_terpel_emails("2026-08-14")

    assert sorted(r["id"] for r in rows) == ["e1"]
    assert rows[0]["subject"] == "ticket"


def test_select_terpel_emails_sin_correos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_terpel_emails("2026-08-14") == []


def test_select_terpel_attachments_solo_de_los_correos_dados(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    _email("e2", "2026-08-14")
    _attachment("e1", "ticket-1.pdf")
    _attachment("e1", "ticket-2.pdf")
    _attachment("e2", "ticket-3.pdf")

    rows = res.select_terpel_attachments(["e1"])

    assert [r["filename"] for r in rows] == ["ticket-1.pdf", "ticket-2.pdf"]
    assert all(r["email_id"] == "e1" for r in rows)
    assert all(isinstance(r["id_attachment"], int) for r in rows)


def test_select_terpel_attachments_vacio_sin_ids(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_terpel_attachments([]) == []


def test_upsert_day_borra_el_dia_e_inserta(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "ticket-1.pdf")
    a2 = _attachment("e1", "ticket-2.pdf")
    a9 = _attachment("e1", "ticket-9.pdf")
    rows = [_ticket(a1.id, "ticket-1.pdf"), _ticket(a2.id, "ticket-2.pdf")]

    n = res.upsert_day("2026-08-14", rows)

    assert n == 2
    assert TerpelTicket.select().count() == 2
    t = TerpelTicket.get(TerpelTicket.filename == "ticket-1.pdf")
    assert t.o_entrega == "450001234"
    assert t.estacion == "LIM"
    assert t.matricula == "ABC-123"
    assert t.galones == "166"
    assert t.cliente == "AIR MAJORO S.A.C"
    assert t.partition_date == "2026-08-14"
    assert t.id_attachment == a1.id

    # Re-upsertar el día: borra TODO lo del día y deja solo lo nuevo.
    n2 = res.upsert_day("2026-08-14", [_ticket(a9.id, "ticket-9.pdf")])
    assert n2 == 1
    assert TerpelTicket.select().count() == 1
    assert TerpelTicket.get().filename == "ticket-9.pdf"


def test_upsert_day_no_toca_otros_dias(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "ticket-1.pdf")
    a2 = _attachment("e1", "ticket-2.pdf")
    res.upsert_day("2026-08-13", [_ticket(a1.id, "ticket-1.pdf")])
    res.upsert_day("2026-08-14", [_ticket(a2.id, "ticket-2.pdf")])

    assert TerpelTicket.select().count() == 2
    assert (
        TerpelTicket.select()
        .where(TerpelTicket.partition_date == "2026-08-13")
        .count()
        == 1
    )


def test_upsert_day_vacio_limpia_el_dia(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "ticket-1.pdf")
    res.upsert_day("2026-08-14", [_ticket(a1.id, "ticket-1.pdf")])

    n = res.upsert_day("2026-08-14", [])

    assert n == 0
    assert TerpelTicket.select().count() == 0


def test_upsert_day_muchas_filas_chunked(tmp_path, monkeypatch):
    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 10)
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "ticket.pdf")
    rows = [_ticket(a1.id, f"ticket-{i}.pdf") for i in range(50)]

    n = res.upsert_day("2026-08-14", rows)

    assert n == 50
    assert TerpelTicket.select().count() == 50
