"""Tests de CorpacSqliteResource (select de correos CORPAC pendientes del día y append-only de corpac_files)."""

import pytest

from assets.from_email_assets.corpac_assets.corpac_files_asset.models.model import CorpacFile
from assets.from_email_assets.corpac_assets.corpac_files_asset.resources.db_resource import (
    CORPAC_SENDER,
    CorpacSqliteResource,
)
from assets.mail_asset.model import Email, db


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
    return CorpacSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _email(id, sender=CORPAC_SENDER, partition="2026-08-11", body="body"):
    return Email.create(id=id, partition_date=partition, sender=sender, body=body)


def _fila(id_email, filename):
    return {"id_email": id_email, "filename": filename, "data": "QUJD"}


def test_select_corpac_emails_filtra_remitente_y_dia(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    _email("e2", partition="2026-08-10")
    _email("e3", sender="otro@correo.com")
    _email("e4", body="<html>...corpac link...</html>")

    rows = res.select_corpac_emails("2026-08-11")

    assert sorted(r["id"] for r in rows) == ["e1", "e4"]
    assert all(r["sender"] == CORPAC_SENDER for r in rows)
    by_id = {r["id"]: r for r in rows}
    assert by_id["e1"]["body"] == "body"


def test_select_corpac_emails_sin_correos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_corpac_emails("2026-08-11") == []


def test_select_corpac_emails_salta_los_correos_ya_procesados(tmp_path):
    """Con **al menos un** archivo ya insertado, el correo no vuelve a aparecer."""
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    _email("e2")
    res.upsert_files("2026-08-11", [_fila("e1", "a.pdf")])

    rows = res.select_corpac_emails("2026-08-11")

    assert [r["id"] for r in rows] == ["e2"]


def test_select_corpac_emails_ya_procesados_no_afecta_a_otros_dias(tmp_path):
    """El filtro es por correo (``id_email``), no por la partición de los archivos."""
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    _email("e2", partition="2026-08-12")
    res.upsert_files("2026-08-12", [_fila("e2", "b.pdf")])

    assert [r["id"] for r in res.select_corpac_emails("2026-08-11")] == ["e1"]
    assert res.select_corpac_emails("2026-08-12") == []


def test_upsert_files_es_append_only_y_mantiene_el_id(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    n = res.upsert_files("2026-08-11", [_fila("e1", "a.pdf"), _fila("e1", "a.xml")])
    assert n == 2
    ids = {f.filename: f.id for f in CorpacFile.select()}

    # Re-materializar los mismos archivos + uno nuevo: NO borra, solo agrega el nuevo.
    n = res.upsert_files("2026-08-11", [_fila("e1", "a.pdf"), _fila("e1", "b.pdf")])

    assert n == 1
    assert CorpacFile.select().count() == 3
    # El ``id`` de los archivos ya presentes no cambia (``corpac_header.file_id``).
    assert {f.filename: f.id for f in CorpacFile.select() if f.filename in ids} == ids
    fila = CorpacFile.get(CorpacFile.filename == "b.pdf")
    assert fila.id_email == "e1"
    assert fila.partition_date == "2026-08-11"


def test_upsert_files_no_guarda_dos_veces_el_mismo_documento(tmp_path):
    """El mismo ``filename`` en dos correos (2 buzones / respuestas del hilo) es UNA fila.

    Sin esto la tabla crecía ×16 con copias byte a byte del mismo PDF (~250 MB) y el
    asset de datos parseaba el PDF N veces.
    """
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    _email("e2")
    _email("e3", partition="2026-08-12")

    # Mismo documento en 2 correos del día y en un correo de otro día: una fila.
    n = res.upsert_files(
        "2026-08-11",
        [_fila("e1", "01-F02500029006.pdf"), _fila("e2", "01-F02500029006.pdf")],
    )
    n += res.upsert_files("2026-08-12", [_fila("e3", "01-F02500029006.pdf")])

    assert n == 1
    fila = CorpacFile.get(CorpacFile.filename == "01-F02500029006.pdf")
    assert fila.id_email == "e1"  # se queda la primera entrega
    assert fila.partition_date == "2026-08-11"


def test_upsert_files_todos_los_archivos_sin_duplicados(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    n = res.upsert_files(
        "2026-08-11",
        [_fila("e1", "a.pdf"), _fila("e1", "a.xml"), _fila("e1", "b.pdf")],
    )
    assert n == 3
    assert CorpacFile.select().count() == 3


def test_upsert_files_no_toca_otros_dias(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    res.upsert_files("2026-08-10", [_fila("e1", "a.pdf")])
    res.upsert_files("2026-08-11", [_fila("e2", "b.pdf")])
    assert CorpacFile.select().where(CorpacFile.partition_date == "2026-08-10").count() == 1
    assert CorpacFile.select().where(CorpacFile.partition_date == "2026-08-11").count() == 1


def test_upsert_files_vacio_no_borra(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1")
    res.upsert_files("2026-08-11", [_fila("e1", "a.pdf")])
    n = res.upsert_files("2026-08-11", [])
    assert n == 0
    assert CorpacFile.select().count() == 1


def test_upsert_files_muchas_filas_chunked(tmp_path, monkeypatch):
    """Muchas filas no deben superar el límite de variables SQL de SQLite."""
    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 10)
    res = _resource(tmp_path)
    res._ensure_db()
    rows = [_fila("e1", f"f{i:03d}.pdf") for i in range(50)]
    n = res.upsert_files("2026-08-11", rows)
    assert n == 50
    assert CorpacFile.select().count() == 50
