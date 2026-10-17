"""Tests de DbResource de mail_asset: append-only de correos/adjuntos (no borra
lo ya insertado, solo inserta lo que tenga un id nuevo) con varias cuentas
(bandejas)."""

import pytest

from assets.mail_asset.model import Email, EmailAttachments, db
from assets.mail_asset.resources.db_resource import DbResource


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


def _resource(tmp_path):
    return DbResource(database_path=str(tmp_path / "db.sqlite"))


def _email(id, mailbox="", partition="2026-08-11", attachments=None):
    return {
        "id": id,
        "sender": "remitente@x.com",
        "subject": "asunto",
        "body": "cuerpo",
        "thread_id": "t1",
        "header_date": "2026-08-11T10:00:00-05:00",
        "received_date": "2026-08-11T15:00:00Z",
        "mailbox": mailbox,
        "attachments": attachments or [],
    }


def test_upsert_y_read_guardan_mailbox(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_emails("2026-08-11", [_email("e1", mailbox="jorge.paredes@airmajoro.com")])

    rows = res.read_emails("2026-08-11")
    assert len(rows) == 1
    assert rows[0]["mailbox"] == "jorge.paredes@airmajoro.com"


def test_upsert_mezcla_varias_cuentas_en_la_misma_particion(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_emails(
        "2026-08-11",
        [
            _email("e1", mailbox="jorge.paredes@airmajoro.com"),
            _email("e2", mailbox="contabilidad@airmajoro.com"),
        ],
    )

    rows = res.read_emails("2026-08-11")
    assert {r["mailbox"] for r in rows} == {
        "jorge.paredes@airmajoro.com",
        "contabilidad@airmajoro.com",
    }
    assert Email.select().count() == 2


def test_upsert_no_borra_lo_ya_insertado(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_emails("2026-08-11", [_email("e1", mailbox="jorge.paredes@airmajoro.com")])
    # Re-materialización con otro correo y otra cuenta: NO borra el anterior.
    n = res.append_emails("2026-08-11", [_email("e2", mailbox="contabilidad@airmajoro.com")])

    assert n == 1
    rows = res.read_emails("2026-08-11")
    assert sorted(r["id"] for r in rows) == ["e1", "e2"]
    assert {r["mailbox"] for r in rows} == {
        "jorge.paredes@airmajoro.com",
        "contabilidad@airmajoro.com",
    }


def test_upsert_es_idempotente_con_los_mismos_ids(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_emails("2026-08-11", [_email("e1"), _email("e2")])
    n = res.append_emails("2026-08-11", [_email("e1"), _email("e2")])

    assert n == 0
    assert Email.select().count() == 2


def test_upsert_conserva_la_particion_original_del_correo(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_emails("2026-08-11", [_email("e1")])
    # El mismo id en otra partición no se reinserta ni se mueve de día.
    n = res.append_emails("2026-08-12", [_email("e1")])

    assert n == 0
    assert [r["id"] for r in res.read_emails("2026-08-11")] == ["e1"]
    assert res.read_emails("2026-08-12") == []


def test_append_email_attachments_solo_inserta_los_nuevos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()

    n = res.append_email_attachments(
        "2026-08-11",
        [
            _email(
                "e1",
                attachments=[
                    {"filename": "a.pdf", "data": "x"},
                    {"filename": "b.pdf", "data": "y"},
                ],
            )
        ],
    )
    assert n == 2
    assert EmailAttachments.select().count() == 2

    # Re-materializar con un adjunto ya presente y uno nuevo: solo entra el nuevo.
    n = res.append_email_attachments(
        "2026-08-11",
        [
            _email(
                "e1",
                attachments=[
                    {"filename": "a.pdf", "data": "x"},
                    {"filename": "c.pdf", "data": "z"},
                ],
            )
        ],
    )

    assert n == 1
    assert {a.filename for a in EmailAttachments.select()} == {
        "a.pdf",
        "b.pdf",
        "c.pdf",
    }


def test_append_email_attachments_mantiene_el_id_estable(tmp_path):
    """El ``id`` autoincremental no cambia al re-materializar (habilita el FK)."""
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_email_attachments(
        "2026-08-11",
        [_email("e1", attachments=[{"filename": "zip.zip", "data": "x"}])],
    )
    first_id = EmailAttachments.get().id

    res.append_email_attachments(
        "2026-08-11",
        [_email("e1", attachments=[{"filename": "zip.zip", "data": "x"}])],
    )

    assert EmailAttachments.select().count() == 1
    assert EmailAttachments.get().id == first_id


def test_existing_email_ids_devuelve_solo_los_guardados(tmp_path):
    """Es lo que usa el asset para no volver a descargar de Gmail lo ya guardado."""
    res = _resource(tmp_path)
    res._ensure_db()

    res.append_emails("2026-08-11", [_email("e1"), _email("e2")])

    assert res.existing_email_ids(["e1", "e2", "e3"]) == {"e1", "e2"}
    assert res.existing_email_ids([]) == set()


def test_existing_email_ids_trocea_la_consulta_por_lotes(tmp_path):
    """Con más ids que variables por sentencia del motor, consulta por lotes."""
    res = _resource(tmp_path)
    res._ensure_db()

    ids = [f"e{i}" for i in range(2000)]
    res.append_emails("2026-08-11", [_email(i) for i in ids])

    assert res.existing_email_ids(ids) == set(ids)
    assert res.existing_email_ids(ids + ["no-existe"]) == set(ids)


def test_ensure_db_crea_el_indice_de_la_particion(tmp_path):
    """El índice ``emails_partition_date`` lo crea ``create_tables`` (viene del modelo)."""
    res = _resource(tmp_path)
    res._ensure_db()

    indices = {i.name for i in db.get_indexes("emails")}
    assert "emails_partition_date" in indices

