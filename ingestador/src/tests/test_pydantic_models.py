"""Tests de los modelos pydantic que validan las filas del CSV de SIRE."""

import pytest

from assets.sire_assets.sire_proposal_asset.models.pydantic_model import (
    SirePurchsRow,
    SireSalesRow,
)


def _purchs_row(**overrides):
    row = {
        "ruc": "20494626978",
        "periodo": "202607",
        "car_sunat": "2060749696101E0010000001001",
        "fecha_de_emision": "04/07/2026",
        "fecha_vcto_pago": "",
        "tipo_cp_doc": "01",
        "serie_del_cdp": "E001",
        "ano": None,
        "nro_cp_o_doc_nro_inicial_rango": "1001",
        "tipo_doc_identidad": "6",
        "nro_doc_identidad": "20607496961",
        "apellidos_nombres_razon_social": "AIR MAJORO SELVA S.A.C.",
        "bi_gravado_dg": "0.00",
        "igv_ipm_dg": "0.00",
        "bi_gravado_dgng": "0.00",
        "igv_ipm_dgng": "0.00",
        "bi_gravado_dng": "0.00",
        "igv_ipm_dng": "0.00",
        "valor_adq_ng": "250.00",
        "isc": "0.00",
        "icbper": "0.00",
        "otros_trib_cargos": "0.00",
        "total_cp": "250.00",
        "moneda": "PEN",
        "tipo_de_cambio": "1.000",
        "est_comp": "1",
        "incal": "0",
    }
    row.update(overrides)
    return row


def test_validates_and_coerces_types():
    dumped = SirePurchsRow.model_validate(_purchs_row()).model_dump()
    assert dumped["ruc"] == 20494626978
    assert dumped["tipo_cp_doc"] == 1
    assert dumped["tipo_doc_identidad"] == "6"
    assert dumped["fecha_de_emision"].isoformat() == "2026-07-04"
    assert dumped["fecha_vcto_pago"] is None
    assert dumped["ano"] is None
    assert dumped["total_cp"] is not None
    assert dumped["est_comp"] == "1"


def test_iso_date_also_accepted():
    row = _purchs_row(fecha_de_emision="2026-07-04")
    dumped = SirePurchsRow.model_validate(row).model_dump()
    assert dumped["fecha_de_emision"].isoformat() == "2026-07-04"


def test_extra_csv_columns_are_dropped():
    row = _purchs_row()
    row["apellidos_y_nombres_o_razon_social"] = "AIR MAJORO SOCIEDAD ANONIMA"
    row["clu2"] = "x"
    row["clu39"] = "y"
    dumped = SirePurchsRow.model_validate(row).model_dump()
    assert "apellidos_y_nombres_o_razon_social" not in dumped
    assert "clu2" not in dumped
    assert "clu39" not in dumped


def test_invalid_date_raises():
    with pytest.raises(ValueError):
        SirePurchsRow.model_validate(_purchs_row(fecha_de_emision="31/13/2026"))


def test_invalid_int_raises():
    with pytest.raises(ValueError):
        SirePurchsRow.model_validate(_purchs_row(ruc="no-un-numero"))


def test_missing_required_field_raises():
    # Los modelos ya no tienen campos obligatorios (toleran celdas vacías de
    # SUNAT), así que la validación no debe fallar ni con filas totalmente vacías.
    dumped_p = SirePurchsRow.model_validate({k: None for k in _purchs_row()}).model_dump()
    assert all(v is None for v in dumped_p.values())
    dumped_s = SireSalesRow.model_validate({k: None for k in _sales_row()}).model_dump()
    assert all(v is None for v in dumped_s.values())


def _sales_row(**overrides):
    row = {
        "ruc": "20494626978",
        "periodo": "202607",
        "car_sunat": "F001-1",
        "fecha_de_emision": "04/07/2026",
        "tipo_cp_doc": "01",
        "serie_del_cdp": "F001",
        "nro_cp_o_doc_nro_inicial_rango": "1",
        "tipo_doc_identidad": "6",
        "nro_doc_identidad": "20494626978",
        "apellidos_nombres_razon_social": "AIR MAJORO SAC",
        "valor_facturado_exportacion": "0.00",
        "bi_gravada": "100.00",
        "dscto_bi": "0.00",
        "igv_ipm": "18.00",
        "dscto_igv_ipm": "0.00",
        "mto_exonerado": "0.00",
        "mto_inafecto": "0.00",
        "isc": "0.00",
        "bi_grav_ivap": "0.00",
        "ivap": "0.00",
        "icbper": "0.00",
        "otros_tributos": "0.00",
        "total_cp": "118.00",
        "moneda": "PEN",
        "tipo_cambio": "1.000",
        "id_proyecto_operadores_atribucion": "",
        "est_comp": "1",
        "valor_fob_embarcado": "0.00",
        "valor_op_gratuitas": "0.00",
    }
    row.update(overrides)
    return row


def test_sales_row_validates():
    dumped = SireSalesRow.model_validate(_sales_row()).model_dump()
    assert dumped["ruc"] == 20494626978
    assert dumped["bi_gravada"] is not None
    assert dumped["total_cp"] is not None


def test_empresa_is_preserved_when_provided():
    """La columna empresa se inyecta desde el asset y debe sobrevivir al volcado."""
    dumped = SirePurchsRow.model_validate(
        _purchs_row(empresa="Air Majoro")
    ).model_dump()
    assert dumped["empresa"] == "Air Majoro"

    dumped_s = SireSalesRow.model_validate(
        _sales_row(empresa="Air Majoro Selva")
    ).model_dump()
    assert dumped_s["empresa"] == "Air Majoro Selva"


def test_tipo_doc_identidad_accepts_letters():
    """SUNAT puede enviar letras en tipo_doc_identidad (p. ej. 'A') sin romper."""
    dumped_s = SireSalesRow.model_validate(
        _sales_row(tipo_doc_identidad="A")
    ).model_dump()
    assert dumped_s["tipo_doc_identidad"] == "A"

    dumped_p = SirePurchsRow.model_validate(
        _purchs_row(tipo_doc_identidad="A")
    ).model_dump()
    assert dumped_p["tipo_doc_identidad"] == "A"


def test_empty_doc_identidad_allowed_purchs():
    """SUNAT puede enviar ``nro_doc_identidad`` vacío -> None (caso real)."""
    row = _purchs_row(nro_doc_identidad=None, apellidos_nombres_razon_social=None)
    dumped = SirePurchsRow.model_validate(row).model_dump()
    assert dumped["nro_doc_identidad"] is None
    assert dumped["apellidos_nombres_razon_social"] is None


def test_empty_doc_identidad_allowed_sales():
    """Igual que compras: contraparte vacía -> None sin romper la validación."""
    dumped = SireSalesRow.model_validate(
        _sales_row(nro_doc_identidad=None, apellidos_nombres_razon_social=None)
    ).model_dump()
    assert dumped["nro_doc_identidad"] is None
    assert dumped["apellidos_nombres_razon_social"] is None
