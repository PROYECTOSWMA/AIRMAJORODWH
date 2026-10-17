"""Tests de AdpReportSqliteResource: ``get_adp_attachments`` (lista aplanada de
adjuntos Excel del día de la remitente ADP) y upsert total del día."""

import pytest

from assets.from_email_assets.adp_reports_asset.models.model import AdpReport
from assets.from_email_assets.adp_reports_asset.resources.db_resource import (
    ADP_SENDER,
    AdpReportSqliteResource,
)
from assets.mail_asset.model import Email, EmailAttachments, db


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
    return AdpReportSqliteResource(database_path=str(tmp_path / "db.sqlite"))


def _email(eid, partition, sender=ADP_SENDER, subject="servicios"):
    return Email.create(
        id=eid, partition_date=partition, sender=sender, subject=subject
    )


def _attachment(eid, filename, data="QUJD"):
    return EmailAttachments.create(email=eid, filename=filename, data=data)


def test_get_adp_attachments_filtra_dia_y_remitente(tmp_path):
    """Solo los correos de la remitente ADP del día, sin distinguir case/espacios."""
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14", sender=ADP_SENDER)
    _email("e2", "2026-08-14", sender="  Ladyliz.Moreno@ADP.com.pe  ")
    _email("e3", "2026-08-14", sender="otro@correo.com")  # otro remitente
    _email("e4", "2026-08-15", sender=ADP_SENDER)  # otro día del mismo mes
    _email("e5", "2026-07-31", sender=ADP_SENDER)  # otro mes
    _attachment("e1", "a.xlsx")
    _attachment("e2", "b.xls")
    _attachment("e3", "c.xlsx")
    _attachment("e4", "d.xlsx")

    rows = res.get_adp_attachments("2026-08-14")

    assert sorted(r["email_id"] for r in rows) == ["e1", "e2"]
    assert sorted(r["filename"] for r in rows) == ["a.xlsx", "b.xls"]


def test_get_adp_attachments_solo_excel_y_omite_correos_sin_adjuntos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    _email("e2", "2026-08-14")  # sin adjuntos: no aporta filas
    a1 = _attachment("e1", "reporte.xlsx")
    a2 = _attachment("e1", "reporte.xlsm")
    _attachment("e1", "documento.pdf")  # se ignora

    rows = res.get_adp_attachments("2026-08-14")

    assert rows == [
        {
            "email_id": "e1",
            "id_attachment": a1.id,
            "filename": "reporte.xlsx",
            "data": "QUJD",
        },
        {
            "email_id": "e1",
            "id_attachment": a2.id,
            "filename": "reporte.xlsm",
            "data": "QUJD",
        },
    ]


def test_get_adp_attachments_vacio_sin_correos(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    assert res.get_adp_attachments("2026-08-14") == []


def _report(id_attachment, filename):
    return {
        "id_attachment": id_attachment,
        "filename": filename,
    }


def test_upsert_day_reemplaza_el_dia(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "reporte-1.xlsx")
    a2 = _attachment("e1", "reporte-2.xlsx")
    a9 = _attachment("e1", "reporte-9.xlsx")

    n = res.upsert_day(
        "2026-08-14",
        [_report(a1.id, "reporte-1.xlsx"), _report(a2.id, "reporte-2.xlsx")],
    )

    assert n == 2
    assert AdpReport.select().count() == 2

    # Re-upsertar el día: borra TODO lo del día y deja solo lo nuevo.
    n2 = res.upsert_day("2026-08-14", [_report(a9.id, "reporte-9.xlsx")])
    assert n2 == 1
    assert AdpReport.select().count() == 1
    fila = AdpReport.get()
    assert fila.filename == "reporte-9.xlsx"
    assert fila.id_attachment == a9.id


def test_upsert_day_no_toca_otros_dias(tmp_path):
    res = _resource(tmp_path)
    res._ensure_db()
    _email("e1", "2026-08-14")
    a1 = _attachment("e1", "reporte-1.xlsx")
    a2 = _attachment("e1", "reporte-2.xlsx")
    res.upsert_day("2026-08-13", [_report(a1.id, "reporte-1.xlsx")])
    res.upsert_day("2026-08-14", [_report(a2.id, "reporte-2.xlsx")])

    assert AdpReport.select().count() == 2
    assert (
        AdpReport.select()
        .where(AdpReport.partition_date == "2026-08-13")
        .count()
        == 1
    )
