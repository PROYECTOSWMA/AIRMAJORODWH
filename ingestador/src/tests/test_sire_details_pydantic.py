"""Tests del modelo pydantic de ítems de detalle de comprobantes CPE."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from assets.sire_assets.sire_details_asset.models.pydantic_model import SireDetailsItem


def _item(**overrides):
    row = {
        "cnt_items": 1,
        "cod_unidad_medida": "ZZ",
        "des_unidad_medida": "UNIDAD",
        "des_codigo": "3300000106",
        "des_item": "RENDIMIENTO GANADO POR CXC",
        "mto_val_unitario": "30.96",
        "mto_icbper": "0.00",
        "mto_desc": "0.00",
        "mto_imp_total": "36.53",
    }
    row.update(overrides)
    return row


def test_valida_y_convierte_tipos():
    d = SireDetailsItem.model_validate(_item()).model_dump()
    assert d["cnt_items"] == Decimal("1.00")
    assert d["cod_unidad_medida"] == "ZZ"
    assert d["mto_val_unitario"] == Decimal("30.96")
    assert d["mto_imp_total"] == Decimal("36.53")


def test_floats_van_a_decimal_2dp_sin_ruido_binario():
    # json.loads devuelve floats; no debe arrastrar 36.529999999999994
    d = SireDetailsItem.model_validate(
        _item(mto_imp_total=36.53, mto_val_unitario=17.0, mto_icbper=0)
    ).model_dump()
    assert d["mto_imp_total"] == Decimal("36.53")
    assert d["mto_val_unitario"] == Decimal("17.00")
    assert d["mto_icbper"] == Decimal("0.00")


def test_cnt_items_acepta_fraccionarios():
    # Las cantidades pueden ser fraccionarias (p. ej. kilos): 17.568 -> 2 decimales.
    d = SireDetailsItem.model_validate(_item(cnt_items=17.568)).model_dump()
    assert d["cnt_items"] == Decimal("17.57")
    d = SireDetailsItem.model_validate(_item(cnt_items="1")).model_dump()
    assert d["cnt_items"] == Decimal("1.00")


def test_campo_faltante_levanta():
    with pytest.raises(ValidationError):
        SireDetailsItem.model_validate(
            {k: v for k, v in _item().items() if k != "des_item"}
        )


def test_monto_none_a_cero():
    # La API a veces manda montos None (p. ej. mto_imp_total): se registran 0.00.
    d = SireDetailsItem.model_validate(_item(mto_imp_total=None)).model_dump()
    assert d["mto_imp_total"] == Decimal("0.00")
    d = SireDetailsItem.model_validate(_item(mto_icbper=None)).model_dump()
    assert d["mto_icbper"] == Decimal("0.00")


def test_string_none_levanta():
    with pytest.raises(ValidationError):
        SireDetailsItem.model_validate(_item(des_item=None))


def test_claves_extra_se_ignoran():
    d = SireDetailsItem.model_validate(_item(otra_cosa=1)).model_dump()
    assert "otra_cosa" not in d
