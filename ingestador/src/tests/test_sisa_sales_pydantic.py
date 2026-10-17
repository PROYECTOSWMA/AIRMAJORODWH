"""Tests del modelo pydantic de sisa_sales (fechas dd/mm/yyyy, decimales y nulls)."""

from decimal import Decimal

from assets.sisa_sales_asset.models.pydantic_model import (
    SisaCreditNoteRow,
    SisaSalesRow,
)


def test_valida_fila_del_ejemplo():
    fila = SisaSalesRow.model_validate(
        {
            "numerofila": 1,
            "codorgdoref": "01",
            "codperdoref": "2026",
            "codseddoref": "06",
            "codempdoref": "02",
            "codregdoref": "001882",
            "codnvedoref": "00",
            "nomtipmoned": "MN",
            "t01tipdoref": "FT",
            "nro_documento": "F006-24684",
            "fechaemisio": "01/08/2026",
            "fechavuelo": "01/08/2026",
            "numeroderuc": "20547960051",
            "ruc_cliente20": "943815211",
            "razonsocial": "PROGRAMA NACIONAL DE ASISTENCIA SOLIDARIA PENSION 65",
            "dorefsubtot": "30.0000",
            "dorefimpimp": "0.0000",
            "doreftotnum": "30.0000",
            "cuenta_contable": "704104",
            "nomtipopago": "TARJETA CREDITO",
            "aenavmatric": "OB2200",
            "nomsitdoref": "106",
            "t01lugorige": "001",
            "desorigen": "PUCALLPA",
            "t01lugdesti": "011",
            "desdestino": "ATALAYA",
            "tipcammoned": "3.3910",
            "cantidad": "1.0000",
            "observacion": "PASAJE AEREO EN LA RUTA PUCALLPA ATALAYA*\nPAX:ANDY ERICK SAAVEDRA RIOS*",
        }
    ).model_dump()

    assert fila["numerofila"] == 1
    assert fila["fechaemisio"].isoformat() == "2026-08-01"
    assert fila["fechavuelo"].isoformat() == "2026-08-01"
    assert fila["numeroderuc"] == "20547960051"
    assert fila["razonsocial"] == "PROGRAMA NACIONAL DE ASISTENCIA SOLIDARIA PENSION 65"
    assert fila["dorefsubtot"] == Decimal("30.00")
    assert fila["dorefimpimp"] == Decimal("0.00")
    assert fila["doreftotnum"] == Decimal("30.00")
    assert fila["tipcammoned"] == Decimal("3.3910")
    assert fila["cantidad"] == Decimal("1.0000")


def test_tolera_nulls():
    fila = SisaSalesRow.model_validate(
        {
            "numerofila": 2,
            "nro_documento": "F006-24685",
            "fechaemisio": "01/08/2026",
            "fechavuelo": None,
            "aenavmatric": None,
            "desorigen": None,
            "desdestino": None,
            "tipcammoned": None,
            "dorefsubtot": None,
        }
    ).model_dump()

    assert fila["fechavuelo"] is None
    assert fila["aenavmatric"] is None
    assert fila["desorigen"] is None
    assert fila["tipcammoned"] is None
    assert fila["dorefsubtot"] is None


def test_fecha_iso_tambien_valida():
    fila = SisaSalesRow.model_validate({"fechaemisio": "2026-08-01"})
    assert fila.fechaemisio.isoformat() == "2026-08-01"


def test_nota_de_credito_valida_y_parsea():
    fila = SisaCreditNoteRow.model_validate(
        {
            "numerofila": 1,
            "codempdoref": "02",
            "codseddoref": "06",
            "sunatnserie": "FC01",
            "sunatnforma": "123",
            "fechaemisio": "01/08/2026",
            "fechavuelo": None,
            "numeroderuc": "20547960051",
            "dorefsubtot": "10.0000",
            "dorefimpimp": "1.8000",
            "doreftotnum": "11.8000",
        }
    ).model_dump()

    assert fila["fechaemisio"].isoformat() == "2026-08-01"
    assert fila["fechavuelo"] is None
    assert fila["dorefsubtot"] == Decimal("10.00")
    assert fila["dorefimpimp"] == Decimal("1.80")
    assert fila["doreftotnum"] == Decimal("11.80")
