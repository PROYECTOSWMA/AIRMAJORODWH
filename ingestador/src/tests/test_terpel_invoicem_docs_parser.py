"""Tests del parser del PDF de factura Terpel (``Fact_*``) del remitente invoicem.

El parser extrae ``orden_de_compra`` y ``observaciones`` por regex y deriva
``agregado_o_entrega`` (el índice del ticket: el número tras 'DT', que antes
calculaba el CASE de dbt en ``cost_centers``). Se testean textos
sintéticos que reproducen el layout real y PDFs construidos en memoria con
``make_pdf``.
"""

from assets.from_email_assets.terpel_assets.terpel_invoicem_asset.parser_docs import (
    parse_fact_pdf,
    parse_fact_text,
    parse_o_entrega,
)


# --- parse_o_entrega -------------------------------------------------------


def test_parse_o_entrega_desde_orden_de_compra():
    assert (
        parse_o_entrega(
            "DT 2618104502 PEDIDO: 160127922 MONEDA: DOLAR AMERICANO", ""
        )
        == 2618104502
    )


def test_parse_o_entrega_fallback_a_observaciones():
    # Los casos reales en que la orden no trae 'DT' lo llevan en observaciones.
    assert parse_o_entrega("PEDIDO: 160127922", "DT 2622003503") == 2622003503


def test_parse_o_entrega_orden_de_compra_tiene_prioridad():
    assert parse_o_entrega("DT 111", "DT 222") == 111


def test_parse_o_entrega_es_case_insensitive_como_like():
    # El LIKE '%DT%' de SQLite no distingue mayúsculas/minúsculas.
    assert parse_o_entrega("dt 12042 PEDIDO: 1", "") == 12042


def test_parse_o_entrega_sin_dt_es_none():
    assert parse_o_entrega("PEDIDO: 160128177 MONEDA: DOLAR", "") is None
    assert parse_o_entrega("", "") is None


def test_parse_o_entrega_sin_digitos_tras_dt_es_cero():
    # Replica CAST(texto AS INTEGER) de SQLite: sin dígitos iniciales -> 0.
    assert parse_o_entrega("DT ABC", "") == 0


# --- parse_fact_text / parse_fact_pdf --------------------------------------


def test_parse_fact_text_incluye_agregado_o_entrega():
    texto = (
        "ORDEN DE COMPRA: DT 2618503502 PEDIDO: 160128177 "
        "MONEDA: DOLAR AMERICANO\n"
    )
    assert parse_fact_text(texto) == {
        "orden_de_compra": (
            "DT 2618503502 PEDIDO: 160128177 MONEDA: DOLAR AMERICANO"
        ),
        "observaciones": "",
        "agregado_o_entrega": 2618503502,
    }


def test_parse_fact_pdf_deriva_agregado_o_entrega(make_pdf):
    pdf = make_pdf(
        [
            "FACTURA ELECTRONICA",
            "ORDEN DE COMPRA: DT 2618503502 PEDIDO: 160128177 "
            "MONEDA: DOLAR AMERICANO",
        ]
    )
    assert parse_fact_pdf(pdf) == {
        "orden_de_compra": (
            "DT 2618503502 PEDIDO: 160128177 MONEDA: DOLAR AMERICANO"
        ),
        "observaciones": "",
        "agregado_o_entrega": 2618503502,
    }


def test_parse_fact_pdf_sin_dt_deja_agregado_en_none(make_pdf):
    pdf = make_pdf(["ORDEN DE COMPRA: PEDIDO: 160128177"])
    out = parse_fact_pdf(pdf)
    assert out["agregado_o_entrega"] is None
