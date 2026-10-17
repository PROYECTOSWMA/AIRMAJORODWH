"""Tests de los parsers de facturas del exterior que NO son de PDF real.

Cubren las dos piezas que más se rompen sin avisar:

* **Quantum Control** (JetSet/Peniel): su tabla de ítems se lee del **texto**, con una
  línea por ítem. El caso de la factura **54402** es el que obliga a las reglas: el
  número de línea viene pegado a la **descripción** (el P/N real va rotulado en un
  renglón de abajo, ``P/N: 3049291-01``) y las cantidades ``Shipped/BackOrd/CD``
  caen en su propio renglón.
* **Precision/PAG**: imprime el ``:`` en su **propia celda** cuando el hueco es ancho
  (``['Customer P.O.', ':PO 717-2026']``); sin pegarla, la etiqueta se queda sin dos
  puntos y el nº de PO, la fecha y el vencimiento salían en blanco.
* **Fechas**: ``iso_from_slash`` tenía el **día y el mes invertidos** en su modo US
  (``'03/26/26'`` daba el 3 de junio y ``'1/22/2026'`` quedaba en NULL), así que el
  ``doc_date`` de compras del exterior caía en el mes equivocado o no existía; y
  ``iso_from_text`` no reconocía el formato ``'Feb-04-2026'``.

Los PDF reales se prueban al final (se saltan si no está la carpeta).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from assets.static_data_asset.parsers.invoices import _quantum, precision
from assets.static_data_asset.parsers.invoices._common import iso_from_slash, iso_from_text

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CARPETA = _REPO_ROOT / "static" / "INVOICE INTERNACIONALES"

# Cabecera + un ítem normal (el P/N y el alternativo van en la misma celda).
_JETSET = """\
Item Part Number/Description Shipped BackOrd CD Unit Price UOM Total Amt
1 101-381015-9 // 4712-6 BLEED SOLENOID VALVE 1 0 OH 2,500.00 EA 2,500.00
Serial #: 2187 OH
(EXCHANGE)
2 FREIGHT _ 1 0 175.00 EA 175.00
SubTotal: 2,675.00
"""

# El caso de la 54402: descripción arriba, P/N rotulado y cantidades en otro renglón.
_54402 = """\
Item Part Number/Description Shipped BackOrd CD Unit Price UOM Total Amt
1 C.T. DISC BALANCING ASSEMBLY C.T DISC 1 0 OH 2,800.00 EA 2,800.00
ASSY.
Serial: A001LP4L
P/N: 3049291-01
BALANCING AND OVERHAULED
2 C.T. DISC BALANCING ASSEMBLY C.T DISC 1 0 OH 2,230.00 EA 2,230.00
P/N: 3027411
3 BLADCT 20.00 EA 1,160.00
58 0 NE
P/N: 3123131-02
Special Instructions:
1. Material is subject to inspection at destination.
"""


def test_quantum_lee_el_item_y_su_continuacion():
    filas = _quantum.detalles([_JETSET], "jetset.pdf")

    assert [f["item"] for f in filas] == ["1", "2"]
    primero = filas[0]
    assert primero["part_number"] == "101-381015-9"
    assert primero["alt_part"] == "4712-6"
    assert primero["description"] == "BLEED SOLENOID VALVE"
    assert (primero["shipped"], primero["backord_cd"]) == ("1", "0 OH")
    assert (primero["unit_price"], primero["uom"], primero["amount"]) == (
        "2500.00", "EA", "2500.00",
    )
    # Los renglones sin número de línea son continuación (van a `extras`).
    assert "Serial #: 2187 OH" in primero["extras"]
    # El '_' de las celdas vacías no es una descripción.
    assert filas[1]["part_number"] == "FREIGHT"
    assert filas[1]["description"] is None


def test_quantum_lee_la_factura_54402():
    filas = _quantum.detalles([_54402], "54402.pdf")

    assert len(filas) == 3
    # El P/N sale del renglón rotulado y la primera línea queda como descripción.
    assert filas[0]["part_number"] == "3049291-01"
    assert filas[0]["description"] == "C.T. DISC BALANCING ASSEMBLY C.T DISC"
    assert filas[0]["shipped"] == "1"
    assert filas[0]["backord_cd"] == "0 OH"
    # Las cantidades del ítem 3 caen en su propio renglón ('58 0 NE').
    tercero = filas[2]
    assert (tercero["item"], tercero["part_number"]) == ("3", "3123131-02")
    assert (tercero["shipped"], tercero["backord_cd"]) == ("58", "0 NE")
    assert (tercero["unit_price"], tercero["amount"]) == ("20.00", "1160.00")
    # Y la suma de las líneas es el subtotal de la factura.
    assert sum(float(f["amount"]) for f in filas) == 6190.00


def test_quantum_no_toma_el_pie_numerado_como_items():
    """'1. Material is subject…' empieza con dígito pero no es una línea de ítem."""
    assert len(_quantum.detalles([_54402], "54402.pdf")) == 3


def test_iso_from_slash_es_mes_dia_ano_como_eeuu():
    """Por defecto el orden es el de EE.UU. (mes/día/año), no día/mes/año."""
    assert iso_from_slash("03/26/26") == "2026-03-26"
    assert iso_from_slash("1/6/2026") == "2026-01-06"      # Jetset 54402
    assert iso_from_slash("1/22/2026") == "2026-01-22"     # día > 12: antes era None
    assert iso_from_slash("26/03/2026", day_first=True) == "2026-03-26"
    assert iso_from_slash("13/13/2026") is None


def test_iso_from_text_acepta_el_mes_primero_con_guion():
    """``'Feb-04-2026'`` (Precision/PAG) y ``'02 Feb 2026'`` (Fenix)."""
    assert iso_from_text("Feb-04-2026") == "2026-02-04"
    assert iso_from_text("Mar-06-2026") == "2026-03-06"
    assert iso_from_text("02 Feb 2026") == "2026-02-02"
    assert iso_from_text("15-Ene-26") == "2026-01-15"


def _celda(texto: str) -> dict[str, object]:
    return {"texto": texto, "x0": 0.0, "x1": 1.0}


def test_precision_pega_la_celda_de_los_dos_puntos():
    """``['Customer P.O.', ':PO 717-2026']`` -> etiqueta y valor, no dos celdas mudas."""
    filas = [
        [_celda("Customer P.O."), _celda(":PO 717-2026"), _celda("Your Ref")],
        [_celda("Invoice Date"), _celda(":Feb-04-2026")],
    ]

    pares = precision._campos(filas)

    assert pares["CUSTOMER P.O."] == "PO 717-2026"
    assert pares["INVOICE DATE"] == "Feb-04-2026"


@pytest.mark.skipif(not _CARPETA.is_dir(), reason="falta la carpeta de facturas")
def test_54402_del_pdf_real():
    from assets.static_data_asset.parsers.invoices import jetset, peniel

    jetset_datos = jetset.parse(_CARPETA / "JETSET")
    lineas = [d for d in jetset_datos["details"] if d["source_file"].endswith("54402 PO 069-2025.pdf")]
    assert len(lineas) == 3
    assert round(sum(float(d["amount"]) for d in lineas), 2) == 6190.00
    assert {d["part_number"] for d in lineas} == {"3049291-01", "3027411", "3123131-02"}

    # Peniel no se toca con estos cambios: 5 líneas y 459,30.
    peniel_datos = peniel.parse(_CARPETA / "PENIEL")
    assert len(peniel_datos["details"]) == 5
    assert round(sum(float(d["amount"]) for d in peniel_datos["details"]), 2) == 459.30
