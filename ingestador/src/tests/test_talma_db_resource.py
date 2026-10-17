"""Tests de TalmaReportSqliteResource (select de correos/adjuntos del día y upsert total)."""

import pytest

from assets.mail_asset.model import Email, EmailAttachments, db
from assets.from_email_assets.talma_reports_asset.models.model import TalmaReport
from assets.from_email_assets.talma_reports_asset.resources.db_resource import (
    TALMA_SENDERS,
    TalmaReportSqliteResource,
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
    return TalmaReportSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _email(eid, partition, sender=TALMA_SENDERS[0], subject="reporte"):
    return Email.create(
        id=eid, partition_date=partition, sender=sender, subject=subject
    )


def _attachment(eid, filename, data="QUJD"):
    return EmailAttachments.create(email=eid, filename=filename, data=data)


def _report(id_attachment, filename, rsir="0000048910"):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
        "fecha": "01/12/2025",
        "estacion": "CHICLAYO",
        "aerolinea": "AIR MAJORO SA",
        "rsir": rsir,
        "aeronave": "BEECHCRAFT B-200",
        "matricula": "OB-2092P",
        "vuelo_l": "2092",
        "vuelo_s": "2092",
        "hora_l": "22:08",
        "hora_s": "00:03",
        "diferencia": "",
        "pea_origen": "--",
        "pea_destino": "--",
        "cantidad": "1",
        "equipo": "1",
        "peso_kg": "",
        "servicio": "PAQUETE",
        "tarifa": "70",
        "moneda": "DOL",
        "estado": "Activo",
        "tipo_rsir": "",
    }


def test_select_talma_emails_filtra_dia_y_ambos_remitentes(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14", sender=TALMA_SENDERS[0])
    _email("e2", "2026-08-14", sender=TALMA_SENDERS[1])
    _email("e3", "2026-08-14", sender="  Facturacion.Centralizada@Talma.com.pe  ")
    _email("e4", "2026-08-14", sender="otro@correo.com")
    _email("e5", "2026-08-15", sender=TALMA_SENDERS[0])  # otro día del mismo mes
    _email("e6", "2026-07-31", sender=TALMA_SENDERS[0])  # otro mes

    rows = res.select_talma_emails("2026-08-14")

    assert sorted(r["id"] for r in rows) == ["e1", "e2", "e3"]
    assert rows[0]["subject"] == "reporte"


def test_select_talma_emails_sin_correos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_talma_emails("2026-08-14") == []


def test_select_talma_attachments_solo_excel(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    _attachment("e1", "reporte.xlsx")
    _attachment("e1", "otro.xls")
    _attachment("e1", "documento.pdf")  # se ignora

    rows = res.select_talma_attachments(["e1"])

    assert [r["filename"] for r in rows] == ["reporte.xlsx", "otro.xls"]
    assert all(isinstance(r["id_attachment"], int) for r in rows)


def test_select_talma_attachments_vacio_sin_ids(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.select_talma_attachments([]) == []


def test_upsert_day_borra_el_dia_e_inserta(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "reporte-1.xlsx")
    a2 = _attachment("e1", "reporte-2.xlsx")
    a9 = _attachment("e1", "reporte-9.xlsx")
    rows = [_report(a1.id, "reporte-1.xlsx"), _report(a2.id, "reporte-2.xlsx")]

    n = res.upsert_day("2026-08-14", rows)

    assert n == 2
    assert TalmaReport.select().count() == 2
    t = TalmaReport.get(TalmaReport.filename == "reporte-1.xlsx")
    assert t.rsir == "0000048910"
    assert t.estacion == "CHICLAYO"
    assert t.tarifa == "70"
    assert t.partition_date == "2026-08-14"
    assert t.id_attachment == a1.id

    # Re-upsertar el día: borra TODO lo del día y deja solo lo nuevo.
    n2 = res.upsert_day("2026-08-14", [_report(a9.id, "reporte-9.xlsx")])
    assert n2 == 1
    assert TalmaReport.select().count() == 1
    assert TalmaReport.get().filename == "reporte-9.xlsx"


def test_upsert_day_no_toca_otros_dias(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "reporte-1.xlsx")
    a2 = _attachment("e1", "reporte-2.xlsx")
    res.upsert_day("2026-08-13", [_report(a1.id, "reporte-1.xlsx")])
    res.upsert_day("2026-08-14", [_report(a2.id, "reporte-2.xlsx")])

    assert TalmaReport.select().count() == 2
    assert (
        TalmaReport.select()
        .where(TalmaReport.partition_date == "2026-08-13")
        .count()
        == 1
    )


def test_upsert_day_vacio_limpia_el_dia(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "reporte-1.xlsx")
    res.upsert_day("2026-08-14", [_report(a1.id, "reporte-1.xlsx")])

    n = res.upsert_day("2026-08-14", [])

    assert n == 0
    assert TalmaReport.select().count() == 0


def test_upsert_day_muchas_filas_chunked(tmp_path, monkeypatch):
    import assets._common.db as db_mod

    monkeypatch.setattr(db_mod, "_SQLITE_MAX_VARIABLES", 10)
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "reporte.xlsx")
    rows = [_report(a1.id, f"reporte-{i}.xlsx") for i in range(50)]

    n = res.upsert_day("2026-08-14", rows)

    assert n == 50
    assert TalmaReport.select().count() == 50
