"""Tests del asset terpel_invoicem_daily (routing docs/tickets/reportes por adjunto).

El asset se invoca a través de su función de cómputo subyacente (la que envuelve
``@asset``) con recursos stub para no tocar la BD. Los PDFs se generan en memoria con
``make_pdf``, los ZIPs con ``zipfile`` y los Excel con ``openpyxl``. No es fail-fast: un
adjunto/ZIP/Excel ilegible se registra como warning y se continúa.
"""

import base64
import datetime as dt
import io
import zipfile

import openpyxl

from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.terpel_invoicem_asset import (
    clasificar_pdf,
    terpel_invoicem_daily,
)

# ``terpel_invoicem_daily`` es un AssetsDefinition; ``op.compute_fn.decorated_fn``
# es la función original (context, terpel_invoicem_db).
_ASSET_FN = terpel_invoicem_daily.op.compute_fn.decorated_fn


class _Log:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class _Context:
    partition_key = "2026-08-14"
    log = _Log()


class _Db:
    def __init__(self, emails, attachments):
        self.emails = emails
        self.attachments = attachments
        self.docs_upserts = []
        self.tickets_upserts = []
        self.reports_upserts = []

    def select_invoicem_emails(self, period):
        return self.emails

    def select_invoicem_attachments(self, email_ids):
        return self.attachments

    def upsert_docs_day(self, period, rows):
        self.docs_upserts.append((period, list(rows)))
        return len(rows)

    def upsert_tickets_day(self, period, rows):
        self.tickets_upserts.append((period, list(rows)))
        return len(rows)

    def upsert_reports_day(self, period, rows):
        self.reports_upserts.append((period, list(rows)))
        return len(rows)


def _email(eid):
    return {"id": eid, "subject": "facturas", "header_date": ""}


def _zip_b64(make_pdf, pdfs):
    """ZIP en memoria (base64) con los PDFs ``(nombre, lineas)`` dados."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for nombre, lineas in pdfs:
            zf.writestr(nombre, make_pdf(lineas))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _xlsx_b64():
    """Excel en memoria (base64) con la cabecera real del reporte en la fila 3."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, "VENTA DEL 06.01.2026 - AIR MAJORO S.A.C"])
    ws.append([])
    ws.append(
        [None, "FECHA", "TICKET", "PRODUCTO", "AEROLINEA", "VUELO", "GALONES",
         "SCOP", "PRECIO", "MONTO", "N°FACTURA"]
    )
    ws.append([1, dt.datetime(2026, 1, 6), 2600603901, "JET", "AIR MAJORO S.A.C",
               2092, 67, 12636963345, 2.53, 169.51, "FV02-00031982"])
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _attachment(id_attachment, filename, data, email_id="e1"):
    return {
        "email_id": email_id,
        "id_attachment": id_attachment,
        "filename": filename,
        "data": data,
    }


_FACT = [
    "FACTURA ELECTRONICA",
    "ORDEN DE COMPRA: DT 2618503502 PEDIDO: 160128177 MONEDA: DOLAR AMERICANO",
]

_TICKET = [
    "O.Entrega 450001234",
    "Estacion: LIM Fecha: 01/01/2026 10:56",
    "Matricula: ABC-123 Aeronave: B 200",
    "GALONES: 166",
]


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_clasificar_pdf():
    assert clasificar_pdf("Fact_04-07-2026_FV02-00032959.pdf") == "docs"
    assert clasificar_pdf("fact_minuscula.pdf") == "docs"
    assert clasificar_pdf("Reimpresion_2600603905.pdf") == "tickets"
    assert clasificar_pdf("ORDEN DE ENTREGA DEL 29.12.2025-MAJORO.pdf") == "tickets"
    assert clasificar_pdf("ORDEN DE ENTRGEA DEL 04.03.2026-MAJORO.pdf") == "tickets"
    assert clasificar_pdf("NoCr_07-01-2026_FC02-00001149.pdf") is None
    assert clasificar_pdf("Fact_05-01-2026_FV02-00031976.xml") is None
    assert clasificar_pdf("image001.png") is None


def test_asset_reparte_docs_tickets_y_reportes(make_pdf):
    db = _Db(
        [_email("e1")],
        [
            _attachment(
                1,
                "FACTURA DEL 14.08.2026-MAJORO.zip",
                _zip_b64(make_pdf, [("Fact_14-08-2026_FV02-00033000.pdf", _FACT)]),
            ),
            _attachment(
                2,
                "ORDENES DE ENTREGA DEL 14.08.2026-MAJORO.zip",
                _zip_b64(
                    make_pdf,
                    [
                        ("Reimpresion_2600803905.pdf", _TICKET),
                        ("Fact_dentro_de_ordenes.pdf", _FACT),
                    ],
                ),
            ),
            _attachment(
                3, "Reporte abastecimiento 14.08.2026-MAJORO.xlsx", _xlsx_b64()
            ),
        ],
    )

    assert _ASSET_FN(_Context(), db) is None  # el asset ya no devuelve Output

    # ZIP de facturas -> docs; ZIP de órdenes -> tickets; el routing es por el nombre
    # de cada entrada, así que un ``Fact_*`` dentro del ZIP de órdenes también va a docs.
    assert len(db.docs_upserts) == 1
    period, docs = db.docs_upserts[0]
    assert period == "2026-08-14"
    assert [d["filename"] for d in docs] == [
        "Fact_14-08-2026_FV02-00033000.pdf",
        "Fact_dentro_de_ordenes.pdf",
    ]
    assert docs[0]["orden_de_compra"] == (
        "DT 2618503502 PEDIDO: 160128177 MONEDA: DOLAR AMERICANO"
    )
    assert docs[0]["agregado_o_entrega"] == 2618503502
    assert docs[0]["id_attachment"] == 1
    assert "partition_date" not in docs[0]  # lo inyecta la BD

    _, tickets = db.tickets_upserts[0]
    assert [t["filename"] for t in tickets] == ["Reimpresion_2600803905.pdf"]
    assert tickets[0]["o_entrega"] == "450001234"
    assert tickets[0]["id_attachment"] == 2

    _, reports = db.reports_upserts[0]
    assert len(reports) == 1
    assert reports[0]["ticket"] == "2600603901"
    assert reports[0]["n_factura"] == "FV02-00031982"
    assert reports[0]["fecha"] == "2026-01-06"
    assert reports[0]["id_attachment"] == 3


def test_asset_adjuntos_sueltos_y_ruido(make_pdf):
    db = _Db(
        [_email("e1")],
        [
            _attachment(1, "Fact_05-01-2026_FV02-00031976.pdf", _b64(make_pdf(_FACT))),
            _attachment(
                2,
                "ORDEN DE ENTREGA DEL 29.12.2025-MAJORO.pdf",
                _b64(make_pdf(_TICKET)),
            ),
            _attachment(3, "Fact_05-01-2026_FV02-00031976.xml", _b64(b"<xml/>")),
            _attachment(4, "image001.png", _b64(b"png")),
            _attachment(5, "NoCr_07-01-2026_FC02-00001149.pdf", _b64(make_pdf(_FACT))),
        ],
    )

    _ASSET_FN(_Context(), db)

    _, docs = db.docs_upserts[0]
    _, tickets = db.tickets_upserts[0]
    _, reports = db.reports_upserts[0]
    assert [d["filename"] for d in docs] == ["Fact_05-01-2026_FV02-00031976.pdf"]
    assert [t["filename"] for t in tickets] == ["ORDEN DE ENTREGA DEL 29.12.2025-MAJORO.pdf"]
    assert reports == []


def test_asset_zip_ilegible_y_xlsx_ilegible_no_derriban(make_pdf):
    db = _Db(
        [_email("e1")],
        [
            _attachment(1, "FACTURA ROTA-MAJORO.zip", _b64(b"no soy un zip")),
            _attachment(2, "Reporte abastecimiento roto.xlsx", _b64(b"no soy xlsx")),
            _attachment(3, "Fact_ok.pdf", _b64(make_pdf(_FACT))),
        ],
    )

    _ASSET_FN(_Context(), db)

    _, docs = db.docs_upserts[0]
    assert [d["filename"] for d in docs] == ["Fact_ok.pdf"]  # el resto se ignora
    assert db.reports_upserts == [("2026-08-14", [])]


def test_asset_sin_correos_del_dia():
    db = _Db([], [])

    _ASSET_FN(_Context(), db)

    assert db.docs_upserts == [("2026-08-14", [])]
    assert db.tickets_upserts == [("2026-08-14", [])]
    assert db.reports_upserts == [("2026-08-14", [])]
