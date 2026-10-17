"""Tests del asset terpel_tickets_daily (parseo, upsert por día y fail-fast).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la BD. Los PDFs se generan en
memoria con ``make_pdf``: si un adjunto no permite identificar el ticket, el
asset lanza ``TerpelProcessingError`` y nunca llega al upsert.
"""

import base64

import pytest

from assets.from_email_assets.terpel_assets.terpel_tickets_asset.terpel_tickets_asset import (
    TerpelProcessingError,
    terpel_tickets_daily,
)

# ``terpel_tickets_daily`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, terpel_db).
_ASSET_FN = terpel_tickets_daily.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass


class _Context:
    partition_key = "2026-08-14"
    log = _Log()


class _Db:
    def __init__(self, emails, attachments):
        self.emails = emails
        self.attachments = attachments
        self.upserts = []

    def select_terpel_emails(self, partition_date):
        return self.emails

    def select_terpel_attachments(self, email_ids):
        return self.attachments

    def upsert_day(self, partition_date, rows):
        self.upserts.append((partition_date, list(rows)))
        return len(rows)


def _email(eid):
    return {"id": eid, "subject": "ticket", "header_date": ""}


def _attachment(id_attachment, filename, make_pdf, campos=None, email_id="e1"):
    # Layout real del tiquete (labels sin acento); el parser acepta además
    # ESTACIÓN/ESTACION y MATRÍCULA/MATRICULA.
    lineas = campos or [
        "O.Entrega 450001234",
        "Estacion: LIM Fecha: 01/01/2026 10:56",
        "Operacion: SUMINISTRO Producto: JET A-1",
        "Cliente: - AIR MAJORO S.A.C",
        "No. Vuelo: 2221 Destino: AYP",
        "Matricula: ABC-123 Aeronave: B 200",
        "GALONES: 166",
        "Final: 11:04 29,783,940",
        "Inicial: 10:56 29,783,774",
    ]
    pdf = make_pdf(lineas)
    return {
        "email_id": email_id,
        "id_attachment": id_attachment,
        "filename": filename,
        "data": base64.b64encode(pdf).decode("ascii"),
    }


def _fixture_attachment(email_id, filename, fixture_name):
    from pathlib import Path

    _FIX = Path(__file__).resolve().parent / "fixtures" / "terpel"
    with open(_FIX / f"{fixture_name}.pdf.b64", encoding="ascii") as f:
        return {
            "email_id": email_id,
            "id_attachment": 1,
            "filename": filename,
            "data": f.read(),
        }


def test_asset_parsea_e_inserta_un_ticket_por_adjunto(make_pdf):
    db = _Db(
        [_email("e1"), _email("e2")],
        [
            _attachment(1, "ticket-1.pdf", make_pdf),
            _attachment(
                2,
                "ticket-2.pdf",
                make_pdf,
                ["O.Entrega 777", "ESTACION: LIMA", "MATRICULA: QWE-456"],
                email_id="e2",
            ),
        ],
    )

    assert _ASSET_FN(_Context(), db) is None  # el asset ya no devuelve Output

    assert len(db.upserts) == 1
    particion, filas = db.upserts[0]
    assert particion == "2026-08-14"
    assert [f["filename"] for f in filas] == ["ticket-1.pdf", "ticket-2.pdf"]
    assert [f["id_attachment"] for f in filas] == [1, 2]
    assert filas[0]["o_entrega"] == "450001234"
    assert filas[0]["estacion"] == "LIM"
    assert filas[0]["matricula"] == "ABC-123"
    assert filas[0]["galones"] == "166"
    assert filas[0]["cliente"] == "AIR MAJORO S.A.C"
    assert filas[1]["o_entrega"] == "777"
    assert all("partition_date" not in f for f in filas)  # lo inyecta la BD


def test_asset_parsea_ticket_real_de_fixture():
    db = _Db(
        [_email("e1")],
        [_fixture_attachment("e1", "tiquete-4503.pdf", "tiquete_2600104503")],
    )

    _ASSET_FN(_Context(), db)

    _, filas = db.upserts[0]
    assert len(filas) == 1
    assert filas[0]["id_attachment"] == 1
    assert filas[0]["filename"] == "tiquete-4503.pdf"
    assert filas[0]["o_entrega"] == "2600104503"
    assert filas[0]["estacion"] == "LIM"
    assert filas[0]["matricula"] == "OB2221P"
    assert filas[0]["galones"] == "166"
    assert filas[0]["destino"] == "AYP"


def test_asset_pdf_sin_campo_requerido_cae_la_particion(make_pdf):
    db = _Db(
        [_email("e1")],
        [
            _attachment(1, "ticket-1.pdf", make_pdf),
            # Sin MATRÍCULA: no se identifica el ticket.
            _attachment(
                2,
                "ticket-2.pdf",
                make_pdf,
                ["O.Entrega 1", "ESTACION: LIMA"],
            ),
        ],
    )

    with pytest.raises(TerpelProcessingError, match="ticket-2.pdf"):
        _ASSET_FN(_Context(), db)

    assert db.upserts == []  # nunca llega al upsert


def test_asset_adjunto_invalido_cae_la_particion():
    db = _Db(
        [_email("e1")],
        [
            {
                "email_id": "e1",
                "id_attachment": 1,
                "filename": "ticket-roto.pdf",
                "data": base64.b64encode(b"no soy un pdf").decode("ascii"),
            }
        ],
    )

    with pytest.raises(TerpelProcessingError, match="ticket-roto.pdf"):
        _ASSET_FN(_Context(), db)

    assert db.upserts == []


def test_asset_sin_correos_del_dia():
    db = _Db([], [])

    _ASSET_FN(_Context(), db)

    assert db.upserts == [("2026-08-14", [])]
