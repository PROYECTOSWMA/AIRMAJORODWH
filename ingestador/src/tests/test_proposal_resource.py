"""Tests de ProposalResource y del parseo del CSV de la propuesta."""

import io
import json
import zipfile

import pytest

from assets.sire_assets.resources.token_resource import SireTokenResource
from assets.sire_assets.sire_proposal_asset.resources.api_resource.constants import (
    TICKET_POLL_SECONDS,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.proposal_resource import (
    ProposalResource,
    read_zip,
)
from assets.sire_assets.sire_proposal_asset.resources.api_resource.ticket_resource import (
    PropuestaRceError,
)

CSV_TEXT = (
    "CAR SUNAT,FECHA DE EMISION,TOTAL CP\r\n"
    "F001,2026-07-01,100.50\r\n"
    "B002,2026-07-02, 200.00 \r\n"
)

# Formato mixto real de la propuesta RCE de compras: la mayoría de comprobantes
# vienen en una sola línea, pero SUNAT a veces parte alguno en dos (cabecera +
# línea de montos que empieza con una celda vacía que repite la contraparte).
MIXED_TEXT = (
    "RUC,CAR SUNAT,Fecha de emision,Total CP,Moneda,Est. Comp.\r\n"
    "20494626978,F001,12/03/2026,40.00,PEN,1\r\n"
    "20494626978,F002,13/03/2026\r\n"
    ",50.00,PEN,1\r\n"
    "20494626978,F003,14/03/2026\r\n"
    ",60.00,PEN,1\r\n"
)


def make_zip(csv_text: str = CSV_TEXT) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("propuesta.csv", csv_text.encode("utf-8-sig"))
    return buf.getvalue()


class StubTicket:
    """Sustituto mínimo de TicketResource para aislar ProposalResource."""

    def __init__(self, zip_bytes):
        self.zip_bytes = zip_bytes

    def get_zip(self, per_tributario, book_code, poll_seconds, *, empresa):
        self.called_with = (per_tributario, book_code, poll_seconds, empresa)
        return self.zip_bytes


def test_read_zip_parses_rows_and_strips():
    rows = read_zip(make_zip())
    assert rows == [
        {
            "car_sunat": "F001",
            "fecha_de_emision": "2026-07-01",
            "total_cp": "100.50",
        },
        {
            "car_sunat": "B002",
            "fecha_de_emision": "2026-07-02",
            "total_cp": "200.00",
        },
    ]


def test_read_zip_empty_cells_become_none():
    rows = read_zip(make_zip("A,B\r\n1,\r\n"))
    assert rows == [{"a": "1", "b": None}]


def test_read_zip_reassembles_split_purchase_records():
    """SUNAT parte a veces un comprobante en 2 líneas (cabecera + montos).

    La línea de montos empieza con una celda vacía (placeholder de la contraparte)
    y debe unirse a la cabecera para que los montos queden en sus columnas.
    """
    rows = read_zip(make_zip(MIXED_TEXT))
    assert rows == [
        {
            "ruc": "20494626978",
            "car_sunat": "F001",
            "fecha_de_emision": "12/03/2026",
            "total_cp": "40.00",
            "moneda": "PEN",
            "est_comp": "1",
        },
        {
            "ruc": "20494626978",
            "car_sunat": "F002",
            "fecha_de_emision": "13/03/2026",
            "total_cp": "50.00",
            "moneda": "PEN",
            "est_comp": "1",
        },
        {
            "ruc": "20494626978",
            "car_sunat": "F003",
            "fecha_de_emision": "14/03/2026",
            "total_cp": "60.00",
            "moneda": "PEN",
            "est_comp": "1",
        },
    ]


def test_read_zip_without_csv_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "hola")
    with pytest.raises(PropuestaRceError, match="does not contain"):
        read_zip(buf.getvalue())


def test_read_zip_empty_csv_raises():
    with pytest.raises(PropuestaRceError, match="no data rows"):
        read_zip(make_zip("A,B\r\n"))


def test_download_delegates_to_ticket_get_zip(tmp_path):
    zip_bytes = make_zip()
    stub = StubTicket(zip_bytes)
    creds = tmp_path / "sire_credentials.json"
    creds.write_text(
        json.dumps([{"name": "Air Majoro", "ruc": "20494626978", "token": "tok-1"}]),
        encoding="utf-8",
    )
    token = SireTokenResource(credentials_path=str(creds))
    proposal = ProposalResource.__new__(ProposalResource)
    object.__setattr__(proposal, "ticket_resource", stub)
    object.__setattr__(proposal, "token_resource", token)

    rows = proposal.get_proposal("202607", empresa="Air Majoro")
    assert rows == [
        {
            "car_sunat": "F001",
            "fecha_de_emision": "2026-07-01",
            "total_cp": "100.50",
        },
        {
            "car_sunat": "B002",
            "fecha_de_emision": "2026-07-02",
            "total_cp": "200.00",
        },
    ]
    # El sondeo por defecto es el de la constante (2 s), no un valor suelto.
    assert stub.called_with == ("202607", "080000", TICKET_POLL_SECONDS, "Air Majoro")


def test_get_proposal_con_periodo_sin_comprobantes_devuelve_vacio(tmp_path):
    """``get_zip`` -> None (SUNAT 422 / cod 1070) significa 0 filas, no un error."""
    stub = StubTicket(None)
    creds = tmp_path / "sire_credentials.json"
    creds.write_text(
        json.dumps([{"name": "Air Majoro", "ruc": "20494626978", "token": "tok-1"}]),
        encoding="utf-8",
    )
    token = SireTokenResource(credentials_path=str(creds))
    proposal = ProposalResource.__new__(ProposalResource)
    object.__setattr__(proposal, "ticket_resource", stub)
    object.__setattr__(proposal, "token_resource", token)

    assert proposal.get_proposal("202608", empresa="Air Majoro") == []
