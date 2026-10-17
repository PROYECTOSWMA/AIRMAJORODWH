"""Tests del modelo pydantic de archivos de comprobantes CPE."""

import pytest
from pydantic import ValidationError

from assets.sire_assets.sire_files_asset.models.pydantic_model import SireFile


def _file(**overrides):
    row = {
        "tipo_documento": "PDF",
        "nom_archivo": "20514513172-08-F040-399-XML.zip",
        "val_archivo": "UEsDBBQAAAAI",
    }
    row.update(overrides)
    return row


def test_valida_campos():
    d = SireFile.model_validate(_file()).model_dump()
    assert d == _file()


def test_tipo_documento_acepta_pdf_y_zip():
    assert SireFile.model_validate(_file(tipo_documento="ZIP")).tipo_documento == "ZIP"


def test_tipo_documento_solo_pdf_o_zip():
    with pytest.raises(ValidationError):
        SireFile.model_validate(_file(tipo_documento="XML"))


def test_campo_faltante_levanta():
    with pytest.raises(ValidationError):
        SireFile.model_validate(
            {k: v for k, v in _file().items() if k != "val_archivo"}
        )


def test_campo_none_levanta():
    with pytest.raises(ValidationError):
        SireFile.model_validate(_file(nom_archivo=None))
